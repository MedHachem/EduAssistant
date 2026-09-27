"""
Phase 7 - Knowledge normalization (chapter-generic).

Transforms a chapter's reconstructed KnowledgeItem JSON (Phase 6 output,
see knowledge_item.schema.json) into a clean, consistent, machine-readable
NORMALIZED representation (see normalized_knowledge.schema.json). Purely
additive: reads the source knowledge JSON, never modifies or regenerates
it, and writes to a SEPARATE per-chapter output directory.

WHAT "NORMALIZATION" MEANS HERE (see knowledge_normalization.md for the
full design rationale from inspecting the real Chapter 1 data):
  - Every item's `content` is `original_content` with inline
    reconstruction markup (<figure>/<uncertain>/<gap>) removed -- that
    data is not lost, it already lives structurally in `links.figures`
    and `uncertainty`. The full untouched original stays available
    under `provenance.original_content`.
  - Explicit `order` fields record original reading order, independent
    of array position.
  - `display_label` is mechanically recombined from two ALREADY-PRESENT
    source fields (item type + bloc_numero) -- never invented text.
  - A generic structural check flags subsection labels that look like a
    numbering-convention slip (e.g. "1.2" among roman-numeral siblings
    "<Section>.N") as an explicit `irregularities` note -- the label
    itself is preserved verbatim, never silently corrected.
  - Every other field (links, exercise_details, uncertainty, titles,
    proof) is copied through unchanged: there is no other inconsistency
    to fix in a single-converter, uniformly-shaped source.

100% deterministic, no LLM call. If a chapter needs this normalizer to
handle a genuinely new inconsistency shape, extend the transform
functions here -- never special-case a chapter_id or item_id.

Usage:
    python normalize_knowledge.py
    python normalize_knowledge.py --knowledge-json <path> --output <path>
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import logging
import re
import sys
from pathlib import Path

import config
from convert_to_knowledge import strip_tags_for_parsing

logger = logging.getLogger("normalize_knowledge")

# Collapses whitespace left behind where an inline tag used to sit
# (e.g. a <figure> tag that was the last paragraph of an item) into a
# single paragraph break, never touching intentional single blank
# lines that were already there between real paragraphs.
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

ITEM_TYPE_DISPLAY_LABEL = {
    "definition": "Définition",
    "theorem": "Théorème",
    "property": "Propriété",
    "formula": "Formule",
    "method": "Méthode",
    "example": "Exemple",
    "activity": "Activité",
    "exercise": "Exercice",
    "remark": "Remarque",
}

# A subsection label that looks like "<Section-label>.N" (e.g. "III.2")
# is the expected convention once ANY sibling subsection under the same
# section follows it. A sibling using the digit form instead ("1.2")
# is flagged, never rewritten -- see module docstring.
_ROMAN_DOT_DIGIT_RE = re.compile(r"^[IVXLCDM]+\.\s*\d+")
_DIGIT_DOT_DIGIT_RE = re.compile(r"^\d+\.\s*\d+")


def _clean_content(original_content: str) -> str:
    """original_content -> content: strip inline reconstruction markup
    (reusing the converter's own strip_tags_for_parsing, so tag
    handling stays identical to how the converter itself already treats
    these tags) and collapse the whitespace gap that removal leaves
    behind. Never touches LaTeX/Markdown otherwise."""
    cleaned = strip_tags_for_parsing(original_content)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def _clean_recursive_text_fields(node):
    """Applies _clean_content to every string-valued 'text'/'content'/
    'statement' field inside an exercise_details-shaped structure
    (SubQuestion trees, Correction, QcmChoice), in case a future
    chapter's source ever embeds inline markup at those levels too --
    Chapter 1's own never does, but this must stay chapter-generic."""
    if node is None:
        return None
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in ("text", "content", "statement") and isinstance(value, str):
                result[key] = _clean_content(value)
            else:
                result[key] = _clean_recursive_text_fields(value)
        return result
    if isinstance(node, list):
        return [_clean_recursive_text_fields(v) for v in node]
    return node


def _display_label(item_type: str, bloc_numero: str | None) -> str | None:
    if not bloc_numero:
        return None
    label = ITEM_TYPE_DISPLAY_LABEL.get(item_type)
    if not label:
        return None
    return f"{label} {bloc_numero}"


def _normalize_item(item: dict, order: int) -> dict:
    source = item["source"]
    return {
        "id": item["id"],
        "type": item["type"],
        "order": order,
        "chapter_id": item["chapter_id"],
        "document_id": item["document_id"],
        "section_id": item.get("section_id"),
        "subsection_id": item.get("subsection_id"),
        "title": item.get("title"),
        "display_label": _display_label(item["type"], source.get("bloc_numero")),
        "content": _clean_content(item["original_content"]),
        "proof": _clean_content(item["proof"]) if item.get("proof") else None,
        "links": copy.deepcopy(item["links"]),
        "exercise_details": _clean_recursive_text_fields(item.get("exercise_details")),
        "uncertainty": copy.deepcopy(item["uncertainty"]),
        "provenance": {
            "source_item_id": item["id"],
            "document_id": source["document_id"],
            "pdf_pages": list(source["pdf_pages"]),
            "reconstructed_sources": list(source["reconstructed_sources"]),
            "bloc_type": source["bloc_type"],
            "bloc_numero": source.get("bloc_numero"),
            "continues_from_previous_page": source.get("continues_from_previous_page", False),
            "continues_on_next_page": source.get("continues_on_next_page", False),
            "original_content": item["original_content"],
        },
    }


def _label_irregularities(subsections: list[dict]) -> dict[str, list[str]]:
    """Maps subsection id -> list of irregularity notes. See module
    docstring / _ROMAN_DOT_DIGIT_RE above."""
    by_section: dict[str, list[dict]] = {}
    for sub in subsections:
        by_section.setdefault(sub["section_id"], []).append(sub)

    notes: dict[str, list[str]] = {}
    for siblings in by_section.values():
        has_roman_convention = any(_ROMAN_DOT_DIGIT_RE.match(s["label"]) for s in siblings)
        if not has_roman_convention:
            continue
        for sub in siblings:
            label = sub["label"]
            if _DIGIT_DOT_DIGIT_RE.match(label) and not _ROMAN_DOT_DIGIT_RE.match(label):
                notes.setdefault(sub["id"], []).append(
                    f"label {label!r} uses digit numbering while sibling subsections under the same "
                    "section use roman-numeral numbering (e.g. 'III.2') -- preserved verbatim, not corrected"
                )
    return notes


def _normalize_section(section: dict, order: int) -> dict:
    return {
        "id": section["id"],
        "chapter_id": section["chapter_id"],
        "label": section["label"],
        "title": section["title"],
        "pdf_page_start": section["pdf_page_start"],
        "pdf_page_end": section["pdf_page_end"],
        "order": order,
        "irregularities": [],
    }


def _normalize_subsection(subsection: dict, order: int, irregularities: list[str]) -> dict:
    return {
        "id": subsection["id"],
        "section_id": subsection["section_id"],
        "label": subsection["label"],
        "title": subsection["title"],
        "pdf_page_start": subsection["pdf_page_start"],
        "pdf_page_end": subsection["pdf_page_end"],
        "order": order,
        "irregularities": irregularities,
    }


def normalize(knowledge: dict) -> dict:
    """Pure, deterministic transform: source KnowledgeItem JSON (already
    parsed) -> normalized representation (already a plain dict, not yet
    written to disk). No chapter_id/page/item-id branching -- every
    identifier comes from the input."""
    irregularities_by_id = _label_irregularities(knowledge.get("subsections", []))

    return {
        "schema_version": "normalized-1.0",
        "algorithm_version": config.NORMALIZATION_ALGORITHM_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "document": copy.deepcopy(knowledge["document"]),
        "chapter": copy.deepcopy(knowledge["chapter"]),
        "sections": [
            _normalize_section(s, order=i) for i, s in enumerate(knowledge.get("sections", []))
        ],
        "subsections": [
            _normalize_subsection(s, order=i, irregularities=irregularities_by_id.get(s["id"], []))
            for i, s in enumerate(knowledge.get("subsections", []))
        ],
        "items": [
            _normalize_item(item, order=i) for i, item in enumerate(knowledge["items"])
        ],
    }


def load_knowledge(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(knowledge_path: Path, output_path: Path | None = None) -> dict:
    knowledge = load_knowledge(knowledge_path)
    result = normalize(knowledge)

    out_path = output_path or config.normalized_json(result["chapter"]["id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return result


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge normalization (Phase 7)")
    parser.add_argument("--knowledge-json", type=Path, default=config.KNOWLEDGE_CHAPTER_01_JSON)
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/normalized/knowledge.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.knowledge_json, args.output)
        logger.info("Chapter %s: %d sections, %d subsections, %d items normalized.",
                     result["chapter"]["id"], len(result["sections"]), len(result["subsections"]), len(result["items"]))
    except Exception:
        logger.exception("normalize_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
