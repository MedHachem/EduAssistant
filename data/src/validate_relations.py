"""
Phase 9 - structural validation for knowledge relations output.

Checks the output of relate_knowledge.py against
knowledge_relations.schema.json (structural/required-field/enum
validation) plus cross-referential and consistency checks a JSON
Schema alone cannot express: every knowledge_item-kind endpoint traces
back to a real normalized item, every figure-kind endpoint traces back
to a real final figure, no duplicate relation_id, and the
confidence/generation_method/review_status consistency rules from
knowledge_relations.md §9.

Chapter-generic: takes the relations file, the normalized file, and the
final figures index as arguments; never assumes a chapter_id.

Usage:
    python validate_relations.py
    python validate_relations.py --relations <path> --normalized <path> --figures-index <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("validate_relations")


def _schema_errors(relations: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed -- skipped schema validation (pip install jsonschema)"]

    schema = json.loads(config.RELATIONS_SCHEMA_JSON.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{e.message} (at {list(e.path)})" for e in validator.iter_errors(relations)]


def _duplicate_relation_ids(relations: dict) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for r in relations["relations"]:
        rid = r["relation_id"]
        if rid in seen:
            duplicates.append(rid)
        seen.add(rid)
    return duplicates


def _referential_errors(relations: dict, normalized: dict | None, figures_index: dict | None) -> list[str]:
    errors = []
    valid_item_ids = {i["id"] for i in normalized["items"]} if normalized else None
    valid_figure_ids = {f["figure_id"] for f in figures_index["figures"]} if figures_index else None

    for r in relations["relations"]:
        for id_, kind, end in ((r["source_id"], r["source_kind"], "source"), (r["target_id"], r["target_kind"], "target")):
            if kind == "knowledge_item" and valid_item_ids is not None and id_ not in valid_item_ids:
                errors.append(f"relation {r['relation_id']}: {end} {id_!r} is not a real normalized item")
            if kind == "figure" and valid_figure_ids is not None and id_ not in valid_figure_ids:
                errors.append(f"relation {r['relation_id']}: {end} {id_!r} is not a real final figure")
    return errors


def _consistency_errors(relations: dict) -> list[str]:
    errors = []
    for r in relations["relations"]:
        if r["generation_method"] == "llm" and r["review_status"] == "NOT_REQUIRED":
            errors.append(f"relation {r['relation_id']}: llm-generated but review_status is NOT_REQUIRED")
        if r["generation_method"] == "human_confirmed" and r["review_status"] not in ("HUMAN_APPROVED", "REVIEW_REQUIRED"):
            errors.append(f"relation {r['relation_id']}: human_confirmed but review_status is {r['review_status']!r}")
        if r["confidence"] == "low" and r["review_status"] == "NOT_REQUIRED":
            errors.append(f"relation {r['relation_id']}: low confidence but review_status is NOT_REQUIRED")
    return errors


def validate(relations: dict, normalized: dict | None = None, figures_index: dict | None = None) -> dict:
    checks = {
        "schema": _schema_errors(relations),
        "duplicate_relation_ids": _duplicate_relation_ids(relations),
        "referential_integrity": _referential_errors(relations, normalized, figures_index),
        "consistency": _consistency_errors(relations),
    }
    total_errors = sum(len(v) for v in checks.values())

    from collections import Counter
    by_type = Counter(r["type"] for r in relations["relations"])
    by_confidence = Counter(r["confidence"] for r in relations["relations"])

    return {
        "chapter_id": relations["chapter_id"],
        "algorithm_version": relations.get("algorithm_version"),
        "counts": {
            "relations": len(relations["relations"]),
            "by_type": dict(by_type),
            "by_confidence": dict(by_confidence),
        },
        "passed": total_errors == 0,
        "total_errors": total_errors,
        "checks": checks,
    }


def run(relations_path: Path, normalized_path: Path | None, figures_index_path: Path | None,
        output_path: Path | None = None) -> dict:
    relations = json.loads(Path(relations_path).read_text(encoding="utf-8"))
    normalized = (
        json.loads(Path(normalized_path).read_text(encoding="utf-8"))
        if normalized_path and Path(normalized_path).exists() else None
    )
    figures_index = (
        json.loads(Path(figures_index_path).read_text(encoding="utf-8"))
        if figures_index_path and Path(figures_index_path).exists() else None
    )

    report = validate(relations, normalized, figures_index)

    out_path = output_path or config.relations_validation_report_json(report["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return report


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate knowledge relations output (Phase 9)")
    parser.add_argument("--relations", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/relations/knowledge_relations.json for Chapter 1")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--figures-index", type=Path, default=config.FINAL_FIGURES_INDEX_JSON)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        relations_path = args.relations or config.relations_json(config.CHAPTER_01_ID)
        report = run(relations_path, args.normalized, args.figures_index, args.output)
        logger.info("Validation %s: %d error(s) across %d check group(s)",
                     "PASSED" if report["passed"] else "FAILED", report["total_errors"], len(report["checks"]))
        if not report["passed"]:
            for name, errors in report["checks"].items():
                for e in errors:
                    logger.error("[%s] %s", name, e)
            sys.exit(1)
    except Exception:
        logger.exception("validate_relations failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
