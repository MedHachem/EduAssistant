"""
Phase 4f - V2 evaluation against the Chapter 1 human review ground truth.

GROUND TRUTH SOURCE -- read this before trusting the numbers below:
the actual per-candidate VALIDATED/REJECTED/NEEDS_CORRECTION browser
review state (frontend/.../figure-review, localStorage) was not
exportable into this session. Ground truth here was instead built by
directly, visually inspecting every one of the 68 real Chapter 1 refined
crops (figure_candidates_refined/) one by one against the human-provided
summary counts and the 6 explicitly-named NEEDS_CORRECTION candidate
IDs. Cross-check: 13 VALIDATED + 6 NEEDS_CORRECTION + 49 REJECTED = 68,
which balances exactly -- the human summary's "14 VALIDATED" does not
(14+49+6=69 for a 68-candidate set), so 13 is treated as the correct
figure here (documented explicitly in the final report, not silently
substituted).

This script is Chapter-1-specific (the GROUND_TRUTH table below is not
reusable for a future chapter) -- it exists to measure THIS chapter's
V1-vs-V2 improvement, not as a pipeline stage. The pipeline stages
themselves (detect/refine/classify_v2/extract) contain no chapter- or
candidate-specific logic.

Usage:
    python evaluate_v2_against_ground_truth.py
"""

import json
import logging
import sys

import config

logger = logging.getLogger("evaluate_v2")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


# See module docstring: built by direct visual inspection of every refined
# crop, cross-validated against the human-given aggregate counts and the
# 6 explicitly-named NEEDS_CORRECTION IDs.
GROUND_TRUTH = {
    "page_011_candidate_02": "VALIDATED", "page_011_candidate_06": "VALIDATED",
    "page_013_candidate_02": "VALIDATED", "page_013_candidate_04": "VALIDATED",
    "page_014_candidate_03": "VALIDATED", "page_015_candidate_03": "VALIDATED",
    "page_015_candidate_04": "VALIDATED", "page_017_candidate_02": "VALIDATED",
    "page_018_candidate_02": "VALIDATED", "page_019_candidate_04": "VALIDATED",
    "page_024_candidate_02": "VALIDATED", "page_025_candidate_02": "VALIDATED",
    "page_027_candidate_02": "VALIDATED",
    "page_009_candidate_02": "NEEDS_CORRECTION", "page_015_candidate_02": "NEEDS_CORRECTION",
    "page_016_candidate_01": "NEEDS_CORRECTION", "page_018_candidate_01": "NEEDS_CORRECTION",
    "page_027_candidate_03": "NEEDS_CORRECTION", "page_027_candidate_04": "NEEDS_CORRECTION",
}
# every other candidate_id -> REJECTED (49 candidates, sub-typed by
# direct visual inspection: not needed for the headline metrics, but
# included for the per-category breakdown)
GROUND_TRUTH_SUBTYPE = {
    "page_008_candidate_03": "TABLE", "page_008_candidate_04": "TABLE", "page_020_candidate_01": "TABLE",
    "page_006_candidate_04": "DECORATIVE", "page_006_candidate_05": "DECORATIVE", "page_006_candidate_06": "DECORATIVE",
    "page_011_candidate_03": "DECORATIVE", "page_011_candidate_04": "DECORATIVE", "page_012_candidate_01": "DECORATIVE",
    "page_013_candidate_03": "DECORATIVE", "page_015_candidate_01": "DECORATIVE", "page_015_candidate_05": "DECORATIVE",
    "page_018_candidate_03": "DECORATIVE", "page_019_candidate_03": "DECORATIVE", "page_019_candidate_05": "DECORATIVE",
    "page_023_candidate_01": "DECORATIVE", "page_024_candidate_01": "DECORATIVE", "page_024_candidate_03": "DECORATIVE",
    "page_025_candidate_01": "DECORATIVE", "page_025_candidate_03": "DECORATIVE", "page_027_candidate_01": "DECORATIVE",
}


def run() -> dict:
    v1 = json.loads(config.VISUAL_ELEMENTS_REVIEW_JSON.read_text(encoding="utf-8"))
    v2_report = json.loads(config.VISUAL_ELEMENTS_REPORT_V2_JSON.read_text(encoding="utf-8"))

    v1_by_id = {c["candidate_id"]: c for c in v1["candidates"]}
    v2_by_id = {}
    for page in v2_report["pages"]:
        # Match V1's numbering exactly: extract_figure_candidates.py (which
        # produced visual_elements_review.json's candidate_ids) filters to
        # type=="candidate" FIRST, then enumerates -- so only elements that
        # WERE a V1 candidate (i.e. have a v2_classification at all, kept or
        # rejected) count towards the index; full_page_scan entries don't.
        former_candidates = [e for e in page["visual_elements"] if "v2_classification" in e]
        for i, e in enumerate(former_candidates, start=1):
            v2_by_id[f"page_{page['pdf_page']:03d}_candidate_{i:02d}"] = e

    candidates = []
    tp = fn_lost = fn_ambiguous = fp = 0
    needs_correction_in_queue = 0
    queue_categories = {"FIGURE", "AMBIGUOUS"}

    for cid, v1c in v1_by_id.items():
        truth = GROUND_TRUTH.get(cid, "REJECTED")
        subtype = GROUND_TRUTH_SUBTYPE.get(cid)
        v2c = v2_by_id.get(cid)
        v2_category = v2c.get("v2_classification") if v2c else None
        in_queue = v2_category in queue_categories

        if truth == "VALIDATED":
            if v2_category == "FIGURE":
                tp += 1
            elif in_queue:
                fn_ambiguous += 1
            else:
                fn_lost += 1
        elif truth == "REJECTED":
            if in_queue:
                fp += 1
        elif truth == "NEEDS_CORRECTION" and in_queue:
            needs_correction_in_queue += 1

        candidates.append({
            "candidate_id": cid,
            "pdf_page": v1c["pdf_page"],
            "ground_truth": truth,
            "ground_truth_subtype": subtype,
            "v1_classification_hint": v1c["classification_hint"],
            "v1_confidence": v1c["confidence"],
            "v2_classification": v2_category,
            "v2_reason": v2c.get("v2_reason") if v2c else None,
            "v2_enters_queue": in_queue,
            "seed_bbox": v1c.get("seed_bbox"),
            "v1_bbox": v1c.get("bbox"),
            "v2_pre_trim_bbox": v2c.get("pre_trim_bbox") if v2c else None,
            "v2_bbox": v2c.get("bbox") if v2c else None,
            "bbox_trimmed": v2c.get("bbox_trimmed") if v2c else False,
        })

    total_validated = sum(1 for c in candidates if c["ground_truth"] == "VALIDATED")
    total_rejected = sum(1 for c in candidates if c["ground_truth"] == "REJECTED")
    total_needs_correction = sum(1 for c in candidates if c["ground_truth"] == "NEEDS_CORRECTION")
    total_real_figures = total_validated + total_needs_correction

    queue_total = sum(1 for c in candidates if c["v2_enters_queue"])
    precision = tp / queue_total if queue_total else 0.0
    recall = tp / total_validated if total_validated else 0.0
    figure_recall_incl_needs_correction = (tp + needs_correction_in_queue) / total_real_figures if total_real_figures else 0.0
    needs_correction_candidates = [c for c in candidates if c["ground_truth"] == "NEEDS_CORRECTION"]
    bbox_tightened = sum(1 for c in needs_correction_candidates if c["bbox_trimmed"])

    result = {
        "ground_truth_note": (
            "Built by direct visual inspection of all 68 real Chapter 1 crops in this "
            "session (browser review-state export was not available); 13 VALIDATED is used "
            "(not the human summary's 14) because 13+49+6=68 balances and 14+49+6=69 does not."
        ),
        "total_candidates": len(candidates),
        "ground_truth_counts": {
            "VALIDATED": total_validated, "REJECTED": total_rejected, "NEEDS_CORRECTION": total_needs_correction,
        },
        "v1_classification_counts": v1.get("counts_by_hint"),
        "v2_classification_counts": v2_report.get("v2_classification_counts"),
        "v2_queue_count": queue_total,
        "figure_detection": {
            "TP_validated_correctly_kept_as_figure": tp,
            "FN_validated_lost_entirely": fn_lost,
            "FN_validated_only_reaches_queue_as_ambiguous": fn_ambiguous,
            "FP_rejected_leaking_into_queue": fp,
            "precision": round(precision, 4),
            "recall_validated_only": round(recall, 4),
            "recall_including_needs_correction": round(figure_recall_incl_needs_correction, 4),
        },
        "needs_correction": {
            "total": total_needs_correction,
            "reaching_queue": needs_correction_in_queue,
            "lost_entirely": total_needs_correction - needs_correction_in_queue,
        },
        "bbox_quality": {
            "needs_correction_bboxes_tightened": bbox_tightened,
            "needs_correction_bboxes_unchanged": total_needs_correction - bbox_tightened,
        },
        "v1_false_positives_no_longer_confident_figure": [
            c["candidate_id"] for c in candidates
            if c["ground_truth"] == "REJECTED" and c["v1_classification_hint"] == "figure" and c["v2_classification"] != "FIGURE"
        ],
        "v1_false_positives_fully_excluded_from_queue": [
            c["candidate_id"] for c in candidates
            if c["ground_truth"] == "REJECTED" and c["v1_classification_hint"] == "figure" and not c["v2_enters_queue"]
        ],
        "v1_false_positives_downgraded_to_ambiguous": [
            c["candidate_id"] for c in candidates
            if c["ground_truth"] == "REJECTED" and c["v1_classification_hint"] == "figure"
            and c["v2_classification"] != "FIGURE" and c["v2_enters_queue"]
        ],
        "v1_false_positives_still_confident_figure": [
            c["candidate_id"] for c in candidates
            if c["ground_truth"] == "REJECTED" and c["v1_classification_hint"] == "figure" and c["v2_classification"] == "FIGURE"
        ],
        "candidates": candidates,
    }
    return result


def render_text_report(result: dict) -> str:
    fd = result["figure_detection"]
    nc = result["needs_correction"]
    bq = result["bbox_quality"]
    lines = [
        "VISUAL DETECTION V2 -- CHAPTER 1 EVALUATION",
        "=" * 44,
        "",
        result["ground_truth_note"],
        "",
        f"Total candidates            : {result['total_candidates']}",
        f"Ground truth (VALIDATED/REJECTED/NEEDS_CORRECTION): {result['ground_truth_counts']}",
        "",
        f"V1 classification counts (evaluate_visual_elements.py hints): {result['v1_classification_counts']}",
        f"V2 classification counts (classify_visual_elements_v2.py)   : {result['v2_classification_counts']}",
        f"V2 candidates entering the human review queue (FIGURE+AMBIGUOUS): {result['v2_queue_count']} / {result['total_candidates']}",
        "",
        "--- Figure detection (against the 13 confirmed VALIDATED figures) ---",
        f"TP (validated, correctly FIGURE)      : {fd['TP_validated_correctly_kept_as_figure']}",
        f"FN (validated, lost entirely)         : {fd['FN_validated_lost_entirely']}",
        f"FN (validated, only reaches queue as AMBIGUOUS): {fd['FN_validated_only_reaches_queue_as_ambiguous']}",
        f"FP (rejected candidate leaking into queue as FIGURE/AMBIGUOUS): {fd['FP_rejected_leaking_into_queue']}",
        f"Precision (TP / queue size)           : {fd['precision']:.1%}",
        f"Recall (TP / 13 validated)             : {fd['recall_validated_only']:.1%}",
        f"Recall incl. needs_correction (TP+NC_in_queue / 19 real figures): {fd['recall_including_needs_correction']:.1%}",
        "",
        "--- NEEDS_CORRECTION (6 real figures with an oversized V1 crop) ---",
        f"Reaching the review queue : {nc['reaching_queue']} / {nc['total']}",
        f"Lost entirely             : {nc['lost_entirely']} / {nc['total']}",
        "",
        "--- Bbox quality ---",
        f"NEEDS_CORRECTION bboxes tightened by V2 trimming : {bq['needs_correction_bboxes_tightened']} / 6",
        f"NEEDS_CORRECTION bboxes unchanged (known limitation, documented): {bq['needs_correction_bboxes_unchanged']} / 6",
        "",
        "--- V1's 4 confident false positives (hinted 'figure', ground truth REJECTED) ---",
        f"No longer a confident FIGURE in V2  : {result['v1_false_positives_no_longer_confident_figure']}",
        f"  - fully excluded from the queue   : {result['v1_false_positives_fully_excluded_from_queue']}",
        f"  - downgraded to AMBIGUOUS (still reviewed, just not confidently wrong): {result['v1_false_positives_downgraded_to_ambiguous']}",
        f"Still a confident FIGURE in V2 (none expected): {result['v1_false_positives_still_confident_figure']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    setup_logging()
    result = run()
    config.VISUAL_DETECTION_V2_EVALUATION_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    config.VISUAL_DETECTION_V2_REPORT_TXT.write_text(render_text_report(result), encoding="utf-8")
    logger.info("Wrote %s and %s", config.VISUAL_DETECTION_V2_EVALUATION_JSON, config.VISUAL_DETECTION_V2_REPORT_TXT)
    print(render_text_report(result))


if __name__ == "__main__":
    main()
