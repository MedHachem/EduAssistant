"""
Phase 10 - structural validation for knowledge chunking output.

Checks the output of chunk_knowledge.py against
knowledge_chunk.schema.json (structural/required-field/enum validation)
plus cross-referential and consistency checks a JSON Schema alone cannot
express: unique chunk_ids, every source_item_id is a real normalized
item, every normalized item is covered exactly once (no loss, no
double-ownership across independent chunks), valid section/subsection/
page references, valid related_chunk_ids, valid figure references,
statement/correction consistency, deterministic ordering, stable
(recomputable) chunk_ids, and split part_index/part_count consistency.

Chapter-generic: takes the chunks file, the normalized file, and the
final figures index as arguments; never assumes a chapter_id.

Usage:
    python validate_chunks.py
    python validate_chunks.py --chunks <path> --normalized <path> --figures-index <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config
from chunk_knowledge import _chunk_id

logger = logging.getLogger("validate_chunks")


def _schema_errors(chunks_doc: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed -- skipped schema validation (pip install jsonschema)"]

    schema = json.loads(config.CHUNK_SCHEMA_JSON.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{e.message} (at {list(e.path)})" for e in validator.iter_errors(chunks_doc)]


def _duplicate_chunk_ids(chunks_doc: dict) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for c in chunks_doc["chunks"]:
        if c["chunk_id"] in seen:
            duplicates.append(c["chunk_id"])
        seen.add(c["chunk_id"])
    return duplicates


def _stable_id_errors(chunks_doc: dict) -> list[str]:
    """Recomputes each chunk_id from its own (source_item_ids,
    content_role, part_index) and checks it matches -- a chunk_id must
    always be reproducible from its own content, never drift from the
    deterministic template."""
    errors = []
    for c in chunks_doc["chunks"]:
        expected = _chunk_id(c["chapter_id"], c["source_item_ids"], c["content_role"], c["part_index"])
        if c["chunk_id"] != expected:
            errors.append(f"chunk_id {c['chunk_id']!r} does not match its own deterministic template {expected!r}")
    return errors


def _item_coverage_errors(chunks_doc: dict, normalized: dict | None) -> list[str]:
    """Every normalized item must be covered by EXACTLY one logical
    'statement ownership' unit: a whole chunk, one merge pair, or one
    split's set of parts -- never split across two unrelated chunks,
    never absent, never present in two different merge/split groups."""
    if normalized is None:
        return []
    errors = []
    valid_item_ids = {i["id"] for i in normalized["items"]}

    statement_chunks = [c for c in chunks_doc["chunks"] if c["content_role"] == "statement"]
    owner_group: dict[str, tuple] = {}
    for c in statement_chunks:
        key = tuple(c["source_item_ids"])
        for item_id in c["source_item_ids"]:
            if item_id in owner_group and owner_group[item_id] != key:
                errors.append(
                    f"item {item_id} appears in two different statement groups: "
                    f"{owner_group[item_id]} and {key}"
                )
            owner_group[item_id] = key

    covered = set(owner_group.keys())
    missing = valid_item_ids - covered
    if missing:
        errors.append(f"{len(missing)} normalized item(s) have no statement chunk at all: {sorted(missing)}")
    orphans = covered - valid_item_ids
    if orphans:
        errors.append(f"{len(orphans)} chunk(s) reference a non-existent normalized item: {sorted(orphans)}")
    return errors


def _section_reference_errors(chunks_doc: dict, normalized: dict | None) -> list[str]:
    if normalized is None:
        return []
    errors = []
    valid_sections = {s["id"] for s in normalized.get("sections", [])}
    valid_subsections = {s["id"] for s in normalized.get("subsections", [])}
    for c in chunks_doc["chunks"]:
        if c["section_id"] is not None and c["section_id"] not in valid_sections:
            errors.append(f"chunk {c['chunk_id']}: unknown section_id {c['section_id']!r}")
        if c["subsection_id"] is not None and c["subsection_id"] not in valid_subsections:
            errors.append(f"chunk {c['chunk_id']}: unknown subsection_id {c['subsection_id']!r}")
    return errors


def _page_reference_errors(chunks_doc: dict, normalized: dict | None) -> list[str]:
    if normalized is None:
        return []
    errors = []
    items_by_id = {i["id"]: i for i in normalized["items"]}
    for c in chunks_doc["chunks"]:
        expected_pages: set[int] = set()
        for item_id in c["source_item_ids"]:
            item = items_by_id.get(item_id)
            if item:
                expected_pages.update(item["provenance"]["pdf_pages"])
        if set(c["pdf_pages"]) != expected_pages:
            errors.append(
                f"chunk {c['chunk_id']}: pdf_pages {c['pdf_pages']} does not match the union of its "
                f"source items' own pages {sorted(expected_pages)}"
            )
        if c["pdf_pages"] != sorted(c["pdf_pages"]):
            errors.append(f"chunk {c['chunk_id']}: pdf_pages is not sorted ascending")
    return errors


def _related_chunk_id_errors(chunks_doc: dict) -> list[str]:
    errors = []
    valid_ids = {c["chunk_id"] for c in chunks_doc["chunks"]}
    for c in chunks_doc["chunks"]:
        for rid in c["related_chunk_ids"]:
            if rid not in valid_ids:
                errors.append(f"chunk {c['chunk_id']}: related_chunk_ids references unknown chunk {rid!r}")
            if rid == c["chunk_id"]:
                errors.append(f"chunk {c['chunk_id']}: related_chunk_ids references itself")
    return errors


def _figure_reference_errors(chunks_doc: dict, figures_index: dict | None) -> list[str]:
    errors = []
    valid_figure_ids = {f["figure_id"] for f in figures_index["figures"]} if figures_index else None
    for c in chunks_doc["chunks"]:
        for ref in c["figure_refs"]:
            if ref["source"] == "relation:illustrates" and ref["figure_id"] is None:
                errors.append(f"chunk {c['chunk_id']}: a relation:illustrates figure_ref must carry a figure_id")
            if valid_figure_ids is not None and ref["figure_id"] is not None and ref["figure_id"] not in valid_figure_ids:
                errors.append(f"chunk {c['chunk_id']}: figure_ref {ref['figure_id']!r} is not a real final figure")
    return errors


def _statement_correction_errors(chunks_doc: dict, normalized: dict | None) -> list[str]:
    errors = []
    by_source_key: dict[tuple, dict[str, list[str]]] = {}
    for c in chunks_doc["chunks"]:
        key = tuple(c["source_item_ids"])
        by_source_key.setdefault(key, {}).setdefault(c["content_role"], []).append(c["chunk_id"])

    for key, roles in by_source_key.items():
        if len(roles.get("correction", [])) > 1:
            errors.append(f"source items {key}: more than one correction chunk ({roles['correction']})")

    if normalized is not None:
        items_by_id = {i["id"]: i for i in normalized["items"]}
        for key, roles in by_source_key.items():
            has_correction_chunk = bool(roles.get("correction"))
            expects_correction = any(
                (items_by_id[iid].get("exercise_details") or {}).get("correction", {}).get("present_in_source")
                for iid in key if iid in items_by_id
            )
            if expects_correction and not has_correction_chunk:
                errors.append(f"source items {key}: source has a correction but no correction chunk was produced")
            if has_correction_chunk and not expects_correction:
                errors.append(f"source items {key}: a correction chunk exists but no source item has one")
    return errors


def _split_consistency_errors(chunks_doc: dict) -> list[str]:
    errors = []
    groups: dict[tuple, list[dict]] = {}
    for c in chunks_doc["chunks"]:
        if c["content_role"] != "statement" or c["part_index"] is None:
            continue
        groups.setdefault(tuple(c["source_item_ids"]), []).append(c)

    for key, parts in groups.items():
        part_counts = {p["part_count"] for p in parts}
        if len(part_counts) != 1:
            errors.append(f"source items {key}: inconsistent part_count values {part_counts}")
            continue
        expected_count = part_counts.pop()
        indices = sorted(p["part_index"] for p in parts)
        if indices != list(range(expected_count)):
            errors.append(f"source items {key}: part_index values {indices} are not exactly 0..{expected_count - 1}")
        if len(parts) != expected_count:
            errors.append(f"source items {key}: {len(parts)} part chunk(s) found but part_count is {expected_count}")
    return errors


def _ordering_errors(chunks_doc: dict) -> list[str]:
    chunks = chunks_doc["chunks"]
    keys = [(c["order"], c["chunk_id"]) for c in chunks]
    if keys != sorted(keys):
        return ["chunks are not sorted by (order, chunk_id) ascending"]
    return []


def validate(chunks_doc: dict, normalized: dict | None = None, figures_index: dict | None = None) -> dict:
    checks = {
        "schema": _schema_errors(chunks_doc),
        "duplicate_chunk_ids": _duplicate_chunk_ids(chunks_doc),
        "stable_ids": _stable_id_errors(chunks_doc),
        "item_coverage": _item_coverage_errors(chunks_doc, normalized),
        "section_references": _section_reference_errors(chunks_doc, normalized),
        "page_references": _page_reference_errors(chunks_doc, normalized),
        "related_chunk_ids": _related_chunk_id_errors(chunks_doc),
        "figure_references": _figure_reference_errors(chunks_doc, figures_index),
        "statement_correction_consistency": _statement_correction_errors(chunks_doc, normalized),
        "split_consistency": _split_consistency_errors(chunks_doc),
        "ordering": _ordering_errors(chunks_doc),
    }
    total_errors = sum(len(v) for v in checks.values())

    from collections import Counter
    chunks = chunks_doc["chunks"]
    by_role = Counter(c["content_role"] for c in chunks)
    by_review = Counter(c["review_status"] for c in chunks)
    merges = sum(1 for c in chunks if c["content_role"] == "statement" and len(c["source_item_ids"]) > 1)
    splits = sum(1 for c in chunks if c["part_index"] is not None)
    whole = sum(1 for c in chunks if c["content_role"] == "statement" and len(c["source_item_ids"]) == 1 and c["part_index"] is None)

    return {
        "chapter_id": chunks_doc["chapter_id"],
        "algorithm_version": chunks_doc.get("algorithm_version"),
        "counts": {
            "total_chunks": len(chunks),
            "by_content_role": dict(by_role),
            "by_review_status": dict(by_review),
            "whole_item_chunks": whole,
            "merge_chunks": merges,
            "split_chunks": splits,
            "figure_refs_total": sum(len(c["figure_refs"]) for c in chunks),
            "chunks_with_related_chunk_ids": sum(1 for c in chunks if c["related_chunk_ids"]),
        },
        "passed": total_errors == 0,
        "total_errors": total_errors,
        "checks": checks,
    }


def run(chunks_path: Path, normalized_path: Path | None, figures_index_path: Path | None,
        output_path: Path | None = None) -> dict:
    chunks_doc = json.loads(Path(chunks_path).read_text(encoding="utf-8"))
    normalized = (
        json.loads(Path(normalized_path).read_text(encoding="utf-8"))
        if normalized_path and Path(normalized_path).exists() else None
    )
    figures_index = (
        json.loads(Path(figures_index_path).read_text(encoding="utf-8"))
        if figures_index_path and Path(figures_index_path).exists() else None
    )

    report = validate(chunks_doc, normalized, figures_index)

    out_path = output_path or config.chunks_validation_report_json(report["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return report


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate knowledge chunking output (Phase 10)")
    parser.add_argument("--chunks", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/chunks/knowledge_chunks.json for Chapter 1")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--figures-index", type=Path, default=config.FINAL_FIGURES_INDEX_JSON)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        chunks_path = args.chunks or config.chunks_json(config.CHAPTER_01_ID)
        report = run(chunks_path, args.normalized, args.figures_index, args.output)
        logger.info("Validation %s: %d error(s) across %d check group(s)",
                     "PASSED" if report["passed"] else "FAILED", report["total_errors"], len(report["checks"]))
        if not report["passed"]:
            for name, errors in report["checks"].items():
                for e in errors:
                    logger.error("[%s] %s", name, e)
            sys.exit(1)
    except Exception:
        logger.exception("validate_chunks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
