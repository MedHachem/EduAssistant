"""
Phase 4i - Human-review preparation for V3 (third verification round).

Same idea as prepare_review.py (a read-only join, no re-detection/
re-classification), but sourced from the V3 completeness-refined report
and its own crop index instead of V1's. Produces a review file in the
same schema the Angular Figure Review UI already reads, so the existing
frontend component can serve this round without inventing a new page.

Inputs:
  - visual_elements_report_v3.json (refine_completeness_for_v3.py):
    every candidate that reached the V2 queue, with V3's completeness-
    refined bbox and V2's classification/reason carried through.
  - figure_candidates_v3/index.json (extract_figure_candidates.py, run
    against the V3 report): the actual candidate_id + cropped PNG path
    for each candidate -- this is the authoritative id, since
    extract_figure_candidates.py enumerates fresh per page and V3's
    report-internal element order alone can't be trusted to match it.

Matched by (pdf_page, bbox) -- index.json's bbox is exactly the V3
report element's bbox (same value, both come from the same run).

Usage:
    python prepare_review_v3.py
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("prepare_review_v3")

# Same confidence heuristic as prepare_review.py, expressed over V2's
# 5-way classification instead of the 3-way soft hint -- only FIGURE/
# AMBIGUOUS ever reach this file (everything else was excluded from the
# queue upstream and has no crop to review).
_CONFIDENCE_BASE = {"FIGURE": 0.8, "AMBIGUOUS": 0.5}


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def load(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Required input not found: {path}. Run refine_completeness_for_v3.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def compute_confidence(category: str, bbox_grew: bool) -> float:
    score = _CONFIDENCE_BASE.get(category, 0.5)
    # Growing the bbox is inherently a bit less certain than an
    # untouched, already-tight box -- same spirit as V1's
    # refinement_uncertain discount in prepare_review.py.
    if bbox_grew:
        score = max(0.0, score - 0.1)
    return round(score, 2)


def build_rows(v3_report: dict, crops_index: dict) -> list:
    crop_by_key = {}
    for c in crops_index["candidates"]:
        crop_by_key[(c["pdf_page"], tuple(c["bbox"]))] = c

    rows = []
    for page_entry in v3_report["pages"]:
        pdf_page_number = page_entry["pdf_page"]
        for element in page_entry["visual_elements"]:
            category = element.get("v2_classification")
            if category not in ("FIGURE", "AMBIGUOUS"):
                continue  # not in the queue -- no crop exists for it

            key = (pdf_page_number, tuple(element["bbox"]))
            crop = crop_by_key.get(key)
            if crop is None:
                logger.warning("page %s bbox %s: no matching crop in index.json, skipping", pdf_page_number, element["bbox"])
                continue

            bbox_grew = bool(element.get("v3_completeness_changed", False))
            rows.append({
                "candidate_id": crop["id"],
                "pdf_page": pdf_page_number,
                "type": "candidate",
                "classification_hint": category.lower(),
                "hint_meaning": (
                    "Likely a graphical figure (curve/diagram/geometry). NOT confirmed -- verify against the image."
                    if category == "FIGURE" else
                    "Classifier signals disagreed or were inconclusive. Needs a closer look."
                ),
                "hint_explanation": element.get("v2_reason"),
                "confidence": compute_confidence(category, bbox_grew),
                "refinement_uncertain": bool(element.get("refinement_uncertain", False)),
                "likely_text_box": bool(element.get("likely_text_box", False)),
                "seed_bbox": element.get("seed_bbox", element["bbox"]),
                "refined_bbox": element["bbox"],
                "bbox": element["bbox"],
                "pre_trim_bbox": element.get("pre_trim_bbox"),
                "v2_bbox": element.get("v2_bbox"),
                "bbox_grew_in_v3": bbox_grew,
                "image_path": crop["image"],
                "needs_review": True,
            })
    return rows


def run(v3_report_path: Path, crops_index_path: Path, output_json: Path, output_txt: Path) -> dict:
    v3_report = load(v3_report_path)
    crops_index = load(crops_index_path)

    rows = build_rows(v3_report, crops_index)
    counts = {"figure": 0, "ambiguous": 0}
    for r in rows:
        counts[r["classification_hint"]] += 1

    output = {
        "note": (
            "Third human verification round (V3): candidates are the same 39 that reached the "
            "review queue in V2, with bboxes further refined for completeness (small labels/axes/"
            "curve fragments recovered where V2's trim cut them off). classification_hint is a SOFT "
            "TRIAGE HINT, not a verified label -- needs_review is unconditionally true for every "
            "candidate here; nothing is auto-excluded."
        ),
        "round": "v3",
        "total_candidates": len(rows),
        "counts_by_hint": counts,
        "candidates": rows,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "VISUAL ELEMENT REVIEW -- ROUND 3 (V3, completeness-refined)",
        "=" * 60,
        "",
        output["note"],
        "",
        f"Total candidates: {len(rows)}",
        f"  figure    : {counts['figure']}",
        f"  ambiguous : {counts['ambiguous']}",
        "",
    ]
    for r in rows:
        lines.append(f"{r['candidate_id']} (page {r['pdf_page']}) -- {r['classification_hint']}, confidence={r['confidence']}")
        lines.append(f"  bbox={r['bbox']}  grew_in_v3={r['bbox_grew_in_v3']}")
        lines.append(f"  image={r['image_path']}")
    output_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human-review preparation for V3 (Phase 4i)")
    parser.add_argument("--v3-report", type=Path, default=config.VISUAL_ELEMENTS_REPORT_V3_JSON)
    parser.add_argument("--crops-index", type=Path, default=config.FIGURE_CANDIDATES_V3_INDEX_JSON)
    parser.add_argument("--output-json", type=Path, default=config.VISUAL_ELEMENTS_REVIEW_V3_JSON)
    parser.add_argument("--output-txt", type=Path, default=config.VISUAL_ELEMENTS_REVIEW_V3_TXT)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.v3_report, args.crops_index, args.output_json, args.output_txt)
        logger.info("Counts by hint: %s", result["counts_by_hint"])
        logger.info("Review reports written to %s and %s", args.output_json, args.output_txt)
    except Exception:
        logger.exception("V3 review preparation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
