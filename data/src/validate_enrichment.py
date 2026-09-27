"""
Phase 8 - structural validation for knowledge enrichment output.

Checks the output of enrich_knowledge.py against
knowledge_enrichment.schema.json (structural/required-field/enum
validation) plus cross-referential and controlled-vocabulary checks a
JSON Schema alone cannot express: every item_id traces back to a real
normalized item (no orphans), every normalized item has exactly one
enrichment record (no loss, no duplicates), and every controlled-
vocabulary field (topics/keywords/concepts) only ever contains values
that trace back to the chapter's own sections/subsections or the
explicit glossary file -- never silent vocabulary drift.

Chapter-generic: takes the enrichment file, the normalized file, and
the glossary file as arguments; never assumes a chapter_id.

Usage:
    python validate_enrichment.py
    python validate_enrichment.py --enrichment <path> --normalized <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("validate_enrichment")


def _schema_errors(enrichment: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed -- skipped schema validation (pip install jsonschema)"]

    schema = json.loads(config.ENRICHMENT_SCHEMA_JSON.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{e.message} (at {list(e.path)})" for e in validator.iter_errors(enrichment)]


def _duplicate_item_ids(enrichment: dict) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for record in enrichment["items"]:
        item_id = record["item_id"]
        if item_id in seen:
            duplicates.append(item_id)
        seen.add(item_id)
    return duplicates


def _no_loss_errors(enrichment: dict, normalized: dict | None) -> list[str]:
    if normalized is None:
        return []
    normalized_ids = {i["id"] for i in normalized["items"]}
    enriched_ids = {r["item_id"] for r in enrichment["items"]}
    missing = normalized_ids - enriched_ids
    if missing:
        return [f"{len(missing)} normalized item(s) have no enrichment record: {sorted(missing)}"]
    orphans = enriched_ids - normalized_ids
    if orphans:
        return [f"{len(orphans)} enrichment record(s) reference a non-existent normalized item: {sorted(orphans)}"]
    return []


def _controlled_vocabulary_errors(enrichment: dict, normalized: dict | None, glossary: dict | None) -> list[str]:
    if normalized is None or glossary is None:
        return []
    errors = []
    valid_topics = {s["title"] for s in normalized.get("sections", [])} | {
        s["title"] for s in normalized.get("subsections", [])
    }
    valid_keywords = {e["term"] for e in glossary["keywords"]}
    valid_concepts = valid_topics | {e["concept"] for e in glossary["keywords"] if e.get("concept")}

    for record in enrichment["items"]:
        for topic in record["topics"]:
            if topic not in valid_topics:
                errors.append(f"item {record['item_id']}: topic {topic!r} is not a real section/subsection title")
        for keyword in record["keywords"]:
            if keyword not in valid_keywords:
                errors.append(f"item {record['item_id']}: keyword {keyword!r} is not in the glossary")
        for concept in record["concepts"]:
            if concept not in {c.lower() for c in valid_concepts}:
                errors.append(f"item {record['item_id']}: concept {concept!r} traces to neither a topic nor the glossary")
    return errors


def _generation_method_consistency_errors(enrichment: dict) -> list[str]:
    """If any field was LLM-produced, review_status must not be
    NOT_REQUIRED -- a hard rule now, even though v1 never sets 'llm'."""
    errors = []
    for record in enrichment["items"]:
        used_llm = any(m == "llm" for m in record["generation_methods"].values())
        if used_llm and record["review_status"] == "NOT_REQUIRED":
            errors.append(
                f"item {record['item_id']}: an LLM-generated field exists but review_status is NOT_REQUIRED"
            )
    return errors


def validate(enrichment: dict, normalized: dict | None = None, glossary: dict | None = None) -> dict:
    checks = {
        "schema": _schema_errors(enrichment),
        "duplicate_item_ids": _duplicate_item_ids(enrichment),
        "no_lost_items": _no_loss_errors(enrichment, normalized),
        "controlled_vocabulary": _controlled_vocabulary_errors(enrichment, normalized, glossary),
        "generation_method_consistency": _generation_method_consistency_errors(enrichment),
    }
    total_errors = sum(len(v) for v in checks.values())

    from collections import Counter
    field_method_counts = {
        field: dict(Counter(r["generation_methods"][field] for r in enrichment["items"]))
        for field in ("topics", "keywords", "mathematical_entities", "exercise_type", "reasoning_types", "concepts")
    }
    unclassified_reasoning = sum(1 for r in enrichment["items"] if r["reasoning_types"] == ["unclassified"])
    exercise_type_counts = dict(Counter(r["exercise_type"] for r in enrichment["items"]))

    return {
        "chapter_id": enrichment["chapter_id"],
        "algorithm_version": enrichment.get("algorithm_version"),
        "counts": {
            "items": len(enrichment["items"]),
            "unclassified_reasoning_types": unclassified_reasoning,
            "exercise_type_distribution": exercise_type_counts,
        },
        "generation_method_counts_per_field": field_method_counts,
        "passed": total_errors == 0,
        "total_errors": total_errors,
        "checks": checks,
    }


def run(enrichment_path: Path, normalized_path: Path | None, glossary_path: Path | None,
        output_path: Path | None = None) -> dict:
    enrichment = json.loads(Path(enrichment_path).read_text(encoding="utf-8"))
    normalized = (
        json.loads(Path(normalized_path).read_text(encoding="utf-8"))
        if normalized_path and Path(normalized_path).exists() else None
    )
    glossary = (
        json.loads(Path(glossary_path).read_text(encoding="utf-8"))
        if glossary_path and Path(glossary_path).exists() else None
    )

    report = validate(enrichment, normalized, glossary)

    out_path = output_path or config.enrichment_validation_report_json(report["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return report


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate knowledge enrichment output (Phase 8)")
    parser.add_argument("--enrichment", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/enrichment/knowledge_enrichment.json for Chapter 1")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--glossary", type=Path, default=config.MATH_GLOSSARY_FR_JSON)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        enrichment_path = args.enrichment or config.enrichment_json(config.CHAPTER_01_ID)
        report = run(enrichment_path, args.normalized, args.glossary, args.output)
        logger.info("Validation %s: %d error(s) across %d check group(s)",
                     "PASSED" if report["passed"] else "FAILED", report["total_errors"], len(report["checks"]))
        if not report["passed"]:
            for name, errors in report["checks"].items():
                for e in errors:
                    logger.error("[%s] %s", name, e)
            sys.exit(1)
    except Exception:
        logger.exception("validate_enrichment failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
