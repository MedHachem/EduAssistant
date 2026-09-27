"""
Phase 7 - structural validation for normalized knowledge output.

Checks the output of normalize_knowledge.py against
normalized_knowledge.schema.json (structural/required-field validation)
plus a set of cross-referential and content checks a JSON Schema alone
cannot express: unique IDs, valid hierarchy (no orphan section/
subsection references), valid/complete ordering, valid source/page
references, LaTeX balance (reusing validate_reconstruction.py's own
check_latex_balance -- no new math-validation logic invented here),
and no source item silently lost relative to the original knowledge
JSON it was normalized from.

Chapter-generic: takes the normalized file and the original source file
as arguments; never assumes a chapter_id.

Usage:
    python validate_normalized_knowledge.py
    python validate_normalized_knowledge.py --normalized <path> --source-knowledge <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config
from validate_reconstruction import check_latex_balance

logger = logging.getLogger("validate_normalized_knowledge")


def _schema_errors(normalized: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed -- skipped schema validation (pip install jsonschema)"]

    schema = json.loads(config.NORMALIZED_SCHEMA_JSON.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{e.message} (at {list(e.path)})" for e in validator.iter_errors(normalized)]


def _duplicate_ids(normalized: dict) -> list[str]:
    all_ids = (
        [normalized["chapter"]["id"]]
        + [s["id"] for s in normalized["sections"]]
        + [s["id"] for s in normalized["subsections"]]
        + [i["id"] for i in normalized["items"]]
    )
    seen: set[str] = set()
    duplicates: list[str] = []
    for id_ in all_ids:
        if id_ in seen:
            duplicates.append(id_)
        seen.add(id_)
    return duplicates


def _orphan_hierarchy_errors(normalized: dict) -> list[str]:
    errors = []
    section_ids = {s["id"] for s in normalized["sections"]}
    subsection_ids = {s["id"]: s for s in normalized["subsections"]}

    for sub in normalized["subsections"]:
        if sub["section_id"] not in section_ids:
            errors.append(f"subsection {sub['id']} references unknown section_id {sub['section_id']!r}")

    for item in normalized["items"]:
        if item["section_id"] is not None and item["section_id"] not in section_ids:
            errors.append(f"item {item['id']} references unknown section_id {item['section_id']!r}")
        if item["subsection_id"] is not None:
            sub = subsection_ids.get(item["subsection_id"])
            if sub is None:
                errors.append(f"item {item['id']} references unknown subsection_id {item['subsection_id']!r}")
            elif item["section_id"] is not None and sub["section_id"] != item["section_id"]:
                errors.append(
                    f"item {item['id']}'s subsection_id {item['subsection_id']!r} belongs to a "
                    f"different section ({sub['section_id']!r}) than the item's own section_id ({item['section_id']!r})"
                )
    return errors


def _ordering_errors(entries: list[dict], label: str) -> list[str]:
    orders = [e["order"] for e in entries]
    expected = list(range(len(entries)))
    if orders != expected:
        return [f"{label} 'order' values are not exactly 0..N-1 in array order: got {orders}"]
    return []


def _page_reference_errors(normalized: dict) -> list[str]:
    errors = []
    chapter = normalized["chapter"]
    lo, hi = chapter["pdf_page_start"], chapter["pdf_page_end"]
    for item in normalized["items"]:
        for page in item["provenance"]["pdf_pages"]:
            if not (lo <= page <= hi):
                errors.append(
                    f"item {item['id']} references page {page}, outside chapter page range [{lo}, {hi}]"
                )
    return errors


def _source_reference_errors(normalized: dict) -> list[str]:
    errors = []
    for item in normalized["items"]:
        prov = item["provenance"]
        if len(prov["pdf_pages"]) != len(prov["reconstructed_sources"]):
            errors.append(
                f"item {item['id']}: pdf_pages ({len(prov['pdf_pages'])}) and reconstructed_sources "
                f"({len(prov['reconstructed_sources'])}) length mismatch"
            )
        if not prov["bloc_type"]:
            errors.append(f"item {item['id']}: missing bloc_type")
    return errors


def _latex_errors(normalized: dict) -> list[str]:
    """Reuses validate_reconstruction.check_latex_balance -- no new
    LaTeX validation logic is written here."""
    errors = []

    def check(item_id: str, field: str, text: str | None):
        if not text:
            return
        issues: list[str] = []
        check_latex_balance(text, issues)
        for issue in issues:
            errors.append(f"item {item_id} field {field}: {issue}")

    for item in normalized["items"]:
        check(item["id"], "content", item["content"])
        check(item["id"], "proof", item.get("proof"))
        details = item.get("exercise_details")
        if details:
            check(item["id"], "exercise_details.statement", details.get("statement"))
            correction = details.get("correction") or {}
            check(item["id"], "exercise_details.correction.content", correction.get("content"))
            for choice in details.get("qcm_choices") or []:
                check(item["id"], "exercise_details.qcm_choices[].text", choice.get("text"))

            def check_questions(questions):
                for q in questions:
                    check(item["id"], "exercise_details.questions[].text", q.get("text"))
                    check_questions(q.get("sub_questions") or [])

            check_questions(details.get("questions") or [])
    return errors


def _no_lost_items_errors(normalized: dict, source: dict | None) -> list[str]:
    if source is None:
        return []
    source_ids = {i["id"] for i in source["items"]}
    normalized_ids = {i["id"] for i in normalized["items"]}
    missing = source_ids - normalized_ids
    if missing:
        return [f"{len(missing)} source item(s) missing from normalized output: {sorted(missing)}"]
    extra = normalized_ids - source_ids
    if extra:
        return [f"{len(extra)} normalized item(s) not present in the source: {sorted(extra)}"]
    return []


def validate(normalized: dict, source: dict | None = None) -> dict:
    checks = {
        "schema": _schema_errors(normalized),
        "duplicate_ids": _duplicate_ids(normalized),
        "hierarchy": _orphan_hierarchy_errors(normalized),
        "section_ordering": _ordering_errors(normalized["sections"], "sections"),
        "subsection_ordering": _ordering_errors(normalized["subsections"], "subsections"),
        "item_ordering": _ordering_errors(normalized["items"], "items"),
        "page_references": _page_reference_errors(normalized),
        "source_references": _source_reference_errors(normalized),
        "latex_balance": _latex_errors(normalized),
        "no_lost_items": _no_lost_items_errors(normalized, source),
    }
    total_errors = sum(len(v) for v in checks.values())
    return {
        "chapter_id": normalized["chapter"]["id"],
        "algorithm_version": normalized.get("algorithm_version"),
        "counts": {
            "sections": len(normalized["sections"]),
            "subsections": len(normalized["subsections"]),
            "items": len(normalized["items"]),
        },
        "passed": total_errors == 0,
        "total_errors": total_errors,
        "checks": checks,
    }


def run(normalized_path: Path, source_path: Path | None, output_path: Path | None = None) -> dict:
    normalized = json.loads(Path(normalized_path).read_text(encoding="utf-8"))
    source = json.loads(Path(source_path).read_text(encoding="utf-8")) if source_path and Path(source_path).exists() else None

    report = validate(normalized, source)

    out_path = output_path or config.normalized_validation_report_json(report["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return report


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate normalized knowledge output (Phase 7)")
    parser.add_argument("--normalized", type=Path, default=None,
                         help="Defaults to data/output/<chapter from --source-knowledge>/normalized/knowledge.json")
    parser.add_argument("--source-knowledge", type=Path, default=config.KNOWLEDGE_CHAPTER_01_JSON)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        source = json.loads(args.source_knowledge.read_text(encoding="utf-8")) if args.source_knowledge.exists() else None
        normalized_path = args.normalized or config.normalized_json(source["chapter"]["id"]) if source else args.normalized
        report = run(normalized_path, args.source_knowledge, args.output)
        logger.info("Validation %s: %d error(s) across %d check group(s)",
                     "PASSED" if report["passed"] else "FAILED", report["total_errors"], len(report["checks"]))
        if not report["passed"]:
            for name, errors in report["checks"].items():
                for e in errors:
                    logger.error("[%s] %s", name, e)
            sys.exit(1)
    except Exception:
        logger.exception("validate_normalized_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
