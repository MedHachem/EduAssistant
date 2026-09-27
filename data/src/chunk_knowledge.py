"""
Phase 10 - Knowledge chunking v1 (chapter-generic, deterministic only).

Reads a chapter's NORMALIZED knowledge JSON (Phase 7), ENRICHMENT file
(Phase 8), and optionally the RELATIONS file (Phase 9) and the final
figures index (Phase 5a), and produces chunks -- see
knowledge_chunk.schema.json / knowledge_chunking.md for the full design
this implements. Purely additive: reads all of the above, modifies none
of them, and writes to a SEPARATE per-chapter output directory
(data/output/<chapter_id>/chunks/knowledge_chunks.json).

100% deterministic/rule-based. NO Claude/LLM call anywhere in this
module. No text is summarized, paraphrased, or invented -- every chunk's
`text` is assembled ONLY from substrings/joins of already-existing
normalized fields (see _statement_text_whole/_statement_text_for_part
below).

A NON-OBVIOUS FACT THIS MODULE DEPENDS ON, confirmed against real data
before writing this (see knowledge_chunking.md §0 for the merge/split
evidence; this specific point is new, found while implementing):
`exercise_details.statement`/`questions[]`/`qcm_choices` are NOT
additional text alongside `content` -- they are a STRUCTURED RE-PARSE of
the exact same source text `content` already holds verbatim (confirmed:
a QCM item's `content` already contains its choice lines rendered as
"- $\\square$ ..."; an exercise's `correction.content` is a literal
substring of its own `content`, immediately following a "### Solution"
heading). Concatenating `content` AND `exercise_details`' own text would
therefore DUPLICATE information. This module's rule:
  - Whole-item (no split) statement text = `content` with any correction
    suffix removed (found via substring search, not re-parsed) + `proof`.
  - A split part's text is instead assembled FROM the already-computed
    `exercise_details.questions[i]` node (label + text, recursively) --
    the only reliable source of "where does part I end and part II
    begin" once a corpus has compound one-line markers ("I. 1. ...") or
    a mismatched delimiter ("I/" not recognized as a marker at all,
    confirmed on a real Chapter 1 item) that make re-deriving character
    offsets from raw `content` fragile. This still introduces nothing
    new: every word rendered comes verbatim from an existing `label`/
    `text` field.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("chunk_knowledge")

APPLICATION_TYPES = {"activity", "exercise", "example"}


# --------------------------------------------------------------------
# Text assembly (see module docstring)
# --------------------------------------------------------------------

def _find_correction_split(item: dict) -> tuple[str, str | None]:
    """Returns (statement_only_content, correction_text_or_None).
    correction_text is located as a literal substring of `content`
    (confirmed present that way on the one real Chapter 1 exercise that
    has a correction) -- never invented, never re-derived from
    `exercise_details.correction.content` alone without confirming the
    substring relationship holds."""
    content = item["content"]
    details = item.get("exercise_details")
    if not details:
        return content, None
    correction = details.get("correction") or {}
    if not correction.get("present_in_source"):
        return content, None
    correction_text = correction.get("content")
    if not correction_text:
        return content, None
    idx = content.find(correction_text)
    if idx == -1:
        # Correction text isn't a literal substring of content in this
        # source (should not happen given how the converter builds it,
        # but fail closed rather than guess): keep content whole, still
        # emit the correction chunk from correction_text on its own.
        return content, correction_text
    return content[:idx].rstrip(), correction_text


def _statement_text_whole(item: dict, statement_only_content: str) -> str:
    text = statement_only_content
    if item.get("proof"):
        text = f"{text}\n\n{item['proof']}"
    return text


def _render_question_node(question: dict) -> str:
    """label + text (verbatim, never reworded) + recursively each
    sub_question, joined as separate paragraphs -- reconstructs a
    top-level question's own text from the already-computed structured
    fields, never from a re-derived slice of `content` (see module
    docstring)."""
    label = question["label"]
    text = question.get("text")
    line = f"{label}. {text}" if text else f"{label}."
    parts = [line]
    for sub in question.get("sub_questions") or []:
        parts.append(_render_question_node(sub))
    return "\n\n".join(parts)


def _statement_text_for_part(item: dict, question: dict) -> str:
    details = item["exercise_details"]
    parts = []
    if details.get("statement"):
        parts.append(details["statement"])
    parts.append(_render_question_node(question))
    return "\n\n".join(parts)


# --------------------------------------------------------------------
# Chunk id
# --------------------------------------------------------------------

def _chunk_id(chapter_id: str, source_item_ids: list[str], content_role: str, part_index: int | None) -> str:
    base = f"chunk-{chapter_id}-{'+'.join(source_item_ids)}"
    if content_role == "correction":
        return f"{base}-correction"
    if part_index is not None:
        return f"{base}-part{part_index}"
    return base


# --------------------------------------------------------------------
# Split / merge decisions
# --------------------------------------------------------------------

def _is_split_candidate(item: dict, statement_only_content: str) -> bool:
    """See knowledge_chunking.md §4 and config.CHUNK_SPLIT_MIN_CHARS's
    own comment: size is only ever a TRIGGER, never the boundary --
    splitting still requires >=2 real top-level questions to split
    along; a long item with no such structure is never force-split."""
    details = item.get("exercise_details")
    if not details or len(details.get("questions") or []) < 2:
        return False
    length = len(statement_only_content) + len(item.get("proof") or "")
    return length > config.CHUNK_SPLIT_MIN_CHARS


def _find_fragmentation_merges(items: list[dict]) -> dict[str, str]:
    """Returns {item_id: partner_item_id} for every item involved in a
    confirmed fragmentation-repair merge -- see knowledge_chunking.md
    §3: same type + same section_id + same bloc_numero + immediately
    consecutive `order` (difference of exactly 1). Tested against
    Chapter 1's real data to exclude ordinary bloc_numero reuse across
    different subsections (which never has an order difference of 1)."""
    merges: dict[str, str] = {}
    for i in range(len(items) - 1):
        a, b = items[i], items[i + 1]
        if b["order"] - a["order"] != 1:
            continue
        if a["type"] != b["type"]:
            continue
        if a["section_id"] != b["section_id"]:
            continue
        numero_a = a["provenance"].get("bloc_numero")
        numero_b = b["provenance"].get("bloc_numero")
        if not numero_a or numero_a != numero_b:
            continue
        merges[a["id"]] = b["id"]
        merges[b["id"]] = a["id"]
    return merges


# --------------------------------------------------------------------
# Figure references (see knowledge_chunking.md §6)
# --------------------------------------------------------------------

def _links_figure_refs(item: dict) -> list[dict]:
    return [
        {
            "source": "links.figures",
            "reconstructed_figure_id": fig.get("reconstructed_figure_id"),
            "figure_id": None,
            "confidence": None,
        }
        for fig in item.get("links", {}).get("figures", [])
    ]


def _illustrates_figure_refs(item_id: str, relations: list[dict]) -> list[dict]:
    return [
        {
            "source": "relation:illustrates",
            "reconstructed_figure_id": None,
            "figure_id": rel["source_id"],
            "confidence": rel["confidence"],
        }
        for rel in relations
        if rel["type"] == "illustrates" and rel["target_id"] == item_id and rel["target_kind"] == "knowledge_item"
    ]


# --------------------------------------------------------------------
# Main build
# --------------------------------------------------------------------

def _section_lookup(normalized: dict) -> tuple[dict, dict]:
    sections = {s["id"]: s for s in normalized.get("sections", [])}
    subsections = {s["id"]: s for s in normalized.get("subsections", [])}
    return sections, subsections


def _base_chunk(chapter_id: str, source_items: list[dict], sections: dict, subsections: dict,
                 enrichment_by_id: dict) -> dict:
    """Fields common to every chunk produced from this item group,
    before content_role/part-specific fields are filled in."""
    first = source_items[0]
    section = sections.get(first["section_id"])
    subsection = subsections.get(first["subsection_id"])

    pdf_pages: list[int] = []
    for it in source_items:
        for p in it["provenance"]["pdf_pages"]:
            if p not in pdf_pages:
                pdf_pages.append(p)
    pdf_pages.sort()

    topics: list[str] = []
    concepts: list[str] = []
    for it in source_items:
        record = enrichment_by_id.get(it["id"])
        if not record:
            continue
        for t in record["topics"]:
            if t not in topics:
                topics.append(t)
        for c in record["concepts"]:
            if c not in concepts:
                concepts.append(c)

    has_uncertain = any(
        it["uncertainty"]["has_uncertain_markers"] or it["uncertainty"]["has_gap_markers"]
        for it in source_items
    )

    is_group = len(source_items) > 1
    base = {
        "chapter_id": chapter_id,
        "order": min(it["order"] for it in source_items),
        "source_item_ids": [it["id"] for it in source_items],
        "item_types": [it["type"] for it in source_items],
        "section_id": first["section_id"],
        "section_title": section["title"] if section else None,
        "subsection_id": first["subsection_id"],
        "subsection_title": subsection["title"] if subsection else None,
        "pdf_pages": pdf_pages,
        "topics": topics,
        "concepts": concepts,
        "has_uncertain_content": has_uncertain,
    }
    methods = {
        "topics": "deterministic" if not is_group else "rule_based",
        "concepts": "deterministic" if not is_group else "rule_based",
    }
    return base, methods


def chunk(normalized: dict, enrichment: dict, relations: dict | None = None,
          figures_index: dict | None = None) -> dict:
    """Pure, deterministic transform. No chapter_id/page/item-id
    branching -- every identifier comes from the input."""
    chapter_id = normalized["chapter"]["id"]
    items = normalized["items"]
    items_by_id = {it["id"]: it for it in items}
    enrichment_by_id = {r["item_id"]: r for r in enrichment["items"]}
    sections, subsections = _section_lookup(normalized)
    relation_list = relations["relations"] if relations else []
    valid_figure_ids = {f["figure_id"] for f in figures_index["figures"]} if figures_index else None

    merge_partner = _find_fragmentation_merges(items)
    handled: set[str] = set()
    chunks: list[dict] = []

    for item in items:
        item_id = item["id"]
        if item_id in handled:
            continue

        partner_id = merge_partner.get(item_id)
        if partner_id and partner_id not in handled:
            # Merge: always take both items in `order`, regardless of
            # which one we happened to visit first.
            pair = sorted([item, items_by_id[partner_id]], key=lambda i: i["order"])
            handled.update(i["id"] for i in pair)
            base, methods = _base_chunk(chapter_id, pair, sections, subsections, enrichment_by_id)

            # Statement text: concatenate each item's own statement-only
            # content (+ its own proof, if any) in order -- a merge
            # never invents a transition, it just restores the original
            # adjacency.
            texts = []
            correction_texts = []
            for it in pair:
                stmt, corr = _find_correction_split(it)
                texts.append(_statement_text_whole(it, stmt))
                if corr:
                    correction_texts.append((it["id"], corr))
            text = "\n\n".join(texts)

            figure_refs = []
            for it in pair:
                figure_refs.extend(_links_figure_refs(it))
                figure_refs.extend(_illustrates_figure_refs(it["id"], relation_list))

            chunks.append({
                **base,
                "chunk_id": _chunk_id(chapter_id, base["source_item_ids"], "statement", None),
                "content_role": "statement",
                "part_index": None,
                "part_count": None,
                "text": text,
                "figure_refs": figure_refs,
                "related_chunk_ids": [],  # resolved in a second pass
                "generation_methods": {
                    "boundaries": "rule_based",
                    "text_assembly": "deterministic",
                    "figure_refs": "deterministic",
                    "related_chunk_ids": "rule_based",
                    **methods,
                },
                "review_status": "REVIEW_REQUIRED",
            })

            for source_item_id, corr in correction_texts:
                chunks.append(_correction_chunk(chapter_id, [items_by_id[source_item_id]], sections, subsections,
                                                  enrichment_by_id, corr))
            continue

        # Not part of a merge -- normal 1:1, possibly split.
        handled.add(item_id)
        statement_only, correction_text = _find_correction_split(item)

        if _is_split_candidate(item, statement_only):
            questions = item["exercise_details"]["questions"]
            part_count = len(questions)
            for part_index, question in enumerate(questions):
                base, methods = _base_chunk(chapter_id, [item], sections, subsections, enrichment_by_id)
                figure_refs = []
                if part_index == 0:
                    # A figure belongs to the item as a whole; attach it
                    # only to the first part to avoid repeating the same
                    # reference across every part (see knowledge_chunking.md §6/§12).
                    figure_refs = _links_figure_refs(item) + _illustrates_figure_refs(item_id, relation_list)
                chunks.append({
                    **base,
                    "chunk_id": _chunk_id(chapter_id, [item_id], "statement", part_index),
                    "content_role": "statement",
                    "part_index": part_index,
                    "part_count": part_count,
                    "text": _statement_text_for_part(item, question),
                    "figure_refs": figure_refs,
                    "related_chunk_ids": [],
                    "generation_methods": {
                        "boundaries": "rule_based",
                        "text_assembly": "deterministic",
                        "figure_refs": "deterministic",
                        "related_chunk_ids": "rule_based",
                        **methods,
                    },
                    "review_status": "REVIEW_REQUIRED",
                })
        else:
            base, methods = _base_chunk(chapter_id, [item], sections, subsections, enrichment_by_id)
            figure_refs = _links_figure_refs(item) + _illustrates_figure_refs(item_id, relation_list)
            chunks.append({
                **base,
                "chunk_id": _chunk_id(chapter_id, [item_id], "statement", None),
                "content_role": "statement",
                "part_index": None,
                "part_count": None,
                "text": _statement_text_whole(item, statement_only),
                "figure_refs": figure_refs,
                "related_chunk_ids": [],
                "generation_methods": {
                    "boundaries": "deterministic",
                    "text_assembly": "deterministic",
                    "figure_refs": "deterministic",
                    "related_chunk_ids": "rule_based",
                    **methods,
                },
                "review_status": "NOT_REQUIRED",
            })

        if correction_text:
            chunks.append(_correction_chunk(chapter_id, [item], sections, subsections, enrichment_by_id, correction_text))

    _resolve_related_chunk_ids(chunks, relation_list)
    _apply_figure_confidence_review(chunks)

    chunks.sort(key=lambda c: (c["order"], c["chunk_id"]))

    if valid_figure_ids is not None:
        for c in chunks:
            for ref in c["figure_refs"]:
                if ref["figure_id"] is not None and ref["figure_id"] not in valid_figure_ids:
                    ref["figure_id"] = None  # never reference a figure that doesn't exist

    return {
        "schema_version": "chunking-1.0",
        "algorithm_version": config.CHUNKING_ALGORITHM_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chapter_id": chapter_id,
        "chunks": chunks,
    }


def _correction_chunk(chapter_id: str, source_items: list[dict], sections: dict, subsections: dict,
                       enrichment_by_id: dict, correction_text: str) -> dict:
    base, methods = _base_chunk(chapter_id, source_items, sections, subsections, enrichment_by_id)
    return {
        **base,
        "chunk_id": _chunk_id(chapter_id, base["source_item_ids"], "correction", None),
        "content_role": "correction",
        "part_index": None,
        "part_count": None,
        "text": correction_text,
        "figure_refs": [],
        "related_chunk_ids": [],
        "generation_methods": {
            "boundaries": "deterministic",
            "text_assembly": "deterministic",
            "figure_refs": "deterministic",
            "related_chunk_ids": "rule_based",
            **methods,
        },
        "review_status": "NOT_REQUIRED",
    }


def _resolve_related_chunk_ids(chunks: list[dict], relation_list: list[dict]) -> None:
    """Only `applies_concept` relations produce related_chunk_ids: both
    of its endpoints are knowledge items, so both resolve to a chunk.
    `illustrates`' source is a figure (not a chunk) -- it is fully
    represented via figure_refs instead (see knowledge_chunking.md §7
    and this module's docstring)."""
    item_to_statement_chunks: dict[str, list[str]] = {}
    for c in chunks:
        if c["content_role"] != "statement":
            continue
        for item_id in c["source_item_ids"]:
            item_to_statement_chunks.setdefault(item_id, []).append(c["chunk_id"])

    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    for rel in relation_list:
        if rel["type"] != "applies_concept":
            continue
        source_chunks = item_to_statement_chunks.get(rel["source_id"], [])
        target_chunks = item_to_statement_chunks.get(rel["target_id"], [])
        for sc in source_chunks:
            for tc in target_chunks:
                if tc == sc:
                    continue
                if tc not in chunk_by_id[sc]["related_chunk_ids"]:
                    chunk_by_id[sc]["related_chunk_ids"].append(tc)
                if sc not in chunk_by_id[tc]["related_chunk_ids"]:
                    chunk_by_id[tc]["related_chunk_ids"].append(sc)

    # Statement <-> its own correction, both directions.
    by_source_key: dict[tuple, dict[str, str]] = {}
    for c in chunks:
        key = tuple(c["source_item_ids"])
        by_source_key.setdefault(key, {})[c["content_role"]] = c["chunk_id"]
    for roles in by_source_key.values():
        stmt_ids = [v for k, v in roles.items() if k == "statement"]
        corr_id = roles.get("correction")
        if corr_id and stmt_ids:
            for stmt_id in stmt_ids:
                if corr_id not in chunk_by_id[stmt_id]["related_chunk_ids"]:
                    chunk_by_id[stmt_id]["related_chunk_ids"].append(corr_id)
                if stmt_id not in chunk_by_id[corr_id]["related_chunk_ids"]:
                    chunk_by_id[corr_id]["related_chunk_ids"].append(stmt_id)

    for c in chunks:
        c["related_chunk_ids"].sort()


def _apply_figure_confidence_review(chunks: list[dict]) -> None:
    for c in chunks:
        if any(ref["confidence"] in ("low", "medium") for ref in c["figure_refs"]):
            c["review_status"] = "REVIEW_REQUIRED"


# --------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------

def _load(path: Path | None) -> dict | None:
    if path is None or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(normalized_path: Path, enrichment_path: Path, relations_path: Path | None,
        figures_index_path: Path | None, output_path: Path | None = None) -> dict:
    normalized = json.loads(Path(normalized_path).read_text(encoding="utf-8"))
    enrichment = json.loads(Path(enrichment_path).read_text(encoding="utf-8"))
    relations = _load(relations_path)
    figures_index = _load(figures_index_path)

    result = chunk(normalized, enrichment, relations, figures_index)

    out_path = output_path or config.chunks_json(result["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return result


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge chunking v1 (Phase 10)")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--enrichment", type=Path, default=config.enrichment_json(config.CHAPTER_01_ID))
    parser.add_argument("--relations", type=Path, default=config.relations_json(config.CHAPTER_01_ID))
    parser.add_argument("--figures-index", type=Path, default=config.FINAL_FIGURES_INDEX_JSON)
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/chunks/knowledge_chunks.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.normalized, args.enrichment, args.relations, args.figures_index, args.output)
        by_role = {}
        for c in result["chunks"]:
            by_role[c["content_role"]] = by_role.get(c["content_role"], 0) + 1
        logger.info("Chapter %s: %d chunks (%s).", result["chapter_id"], len(result["chunks"]), by_role)
    except Exception:
        logger.exception("chunk_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
