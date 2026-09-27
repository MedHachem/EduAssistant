"""
Phase 4k - V4 evaluation against the new, corrected human ground truth.

GROUND TRUTH SOURCE: the 39 candidate_ids given by the user for this
task, verified in this session by directly opening every one of the 39
real crops in data/output/figure_candidates_v3/ (matched against the
actual figure_candidates_v3/index.json filenames, NOT any earlier,
differently-numbered internal assumption) and confirming each one
visually matches its assigned REJECTED/VALIDATED/NEEDS_CORRECTION label.

Generates:
  - visual_detection_v4_evaluation.json / .txt (metrics, confusion matrix)
  - visual_detection_v4_features.json (per-candidate feature dump)
  - figure_candidates_v4/contact_sheet_all.png (every one of the 39,
    labeled with V4 classification + confidence -- built from the
    EXISTING V3 crops, no second crop pipeline)
  - figure_candidates_v4/contact_sheet_figures.png (FIGURE-only)

Usage:
    python evaluate_v4_against_ground_truth.py
"""

import json
import logging
import sys

import numpy as np
from PIL import Image, ImageDraw

import config

logger = logging.getLogger("evaluate_v4")

GT_REJECTED = """page_006_candidate_01 page_006_candidate_02 page_008_candidate_01 page_008_candidate_02
page_011_candidate_02 page_011_candidate_03 page_012_candidate_01 page_012_candidate_02
page_013_candidate_02 page_015_candidate_01 page_015_candidate_05 page_017_candidate_01
page_017_candidate_03 page_018_candidate_03 page_019_candidate_01 page_019_candidate_02
page_019_candidate_04 page_023_candidate_01 page_024_candidate_01 page_027_candidate_01""".split()

GT_VALIDATED = """page_011_candidate_01 page_011_candidate_04 page_013_candidate_01 page_013_candidate_03
page_014_candidate_01 page_015_candidate_03 page_015_candidate_04 page_017_candidate_02
page_018_candidate_02 page_019_candidate_03 page_024_candidate_02 page_027_candidate_02
page_027_candidate_03""".split()

GT_NEEDS_CORRECTION = """page_009_candidate_01 page_015_candidate_02 page_016_candidate_01
page_018_candidate_01 page_025_candidate_01 page_027_candidate_04""".split()

GROUND_TRUTH = {c: "REJECTED" for c in GT_REJECTED}
GROUND_TRUTH.update({c: "VALIDATED" for c in GT_VALIDATED})
GROUND_TRUTH.update({c: "NEEDS_CORRECTION" for c in GT_NEEDS_CORRECTION})

QUEUE_CLASSIFICATIONS = {"FIGURE", "FIGURE_REVIEW"}


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def build_rows() -> list:
    v4_report = json.loads(config.VISUAL_ELEMENTS_REPORT_V4_JSON.read_text(encoding="utf-8"))
    v3_index = json.loads(config.FIGURE_CANDIDATES_V3_INDEX_JSON.read_text(encoding="utf-8"))

    # Real, stable candidate_id per (page, bbox) -- from the actual V3
    # extraction (same bbox space the V4 report also uses, since V4
    # only re-classifies, never moves, a V3 bbox).
    id_by_key = {(c["pdf_page"], tuple(c["bbox"])): c["id"] for c in v3_index["candidates"]}

    rows = []
    for page in v4_report["pages"]:
        for e in page["visual_elements"]:
            if "v4_classification" not in e:
                continue
            key = (page["pdf_page"], tuple(e["bbox"]))
            candidate_id = id_by_key.get(key)
            if candidate_id is None:
                logger.warning("page %s bbox %s: no matching V3 candidate_id, skipping", page["pdf_page"], e["bbox"])
                continue
            rows.append({
                "candidate_id": candidate_id,
                "page": page["pdf_page"],
                "bbox": e["bbox"],
                "classification": e["v4_classification"],
                "confidence": e["v4_confidence"],
                "reason_codes": e["v4_reason_codes"],
                "features": e["v4_features"],
                "ground_truth": GROUND_TRUTH.get(candidate_id, "UNKNOWN"),
            })
    return rows


def compute_metrics(rows: list) -> dict:
    validated = [r for r in rows if r["ground_truth"] == "VALIDATED"]
    needs_correction = [r for r in rows if r["ground_truth"] == "NEEDS_CORRECTION"]
    rejected = [r for r in rows if r["ground_truth"] == "REJECTED"]

    validated_retained = sum(1 for r in validated if r["classification"] in QUEUE_CLASSIFICATIONS)
    needs_correction_retained = sum(1 for r in needs_correction if r["classification"] in QUEUE_CLASSIFICATIONS)
    real_figures_retained = validated_retained + needs_correction_retained
    total_real_figures = len(validated) + len(needs_correction)

    fp_retained = [r for r in rejected if r["classification"] in QUEUE_CLASSIFICATIONS]
    fp_excluded = [r for r in rejected if r["classification"] == "NOT_FIGURE"]

    queue_size = sum(1 for r in rows if r["classification"] in QUEUE_CLASSIFICATIONS)
    figure_only = sum(1 for r in rows if r["classification"] == "FIGURE")
    precision_queue = real_figures_retained / queue_size if queue_size else 0.0
    precision_figure_bucket = sum(1 for r in rows if r["classification"] == "FIGURE" and r["ground_truth"] != "REJECTED") / figure_only if figure_only else 0.0

    confusion = {}
    for r in rows:
        key = (r["ground_truth"], r["classification"])
        confusion.setdefault(key, []).append(r["candidate_id"])

    false_negatives = [
        r["candidate_id"] for r in (validated + needs_correction)
        if r["classification"] not in QUEUE_CLASSIFICATIONS
    ]

    return {
        "total_candidates": len(rows),
        "ground_truth_counts": {"VALIDATED": len(validated), "NEEDS_CORRECTION": len(needs_correction), "REJECTED": len(rejected)},
        "classification_counts": {
            c: sum(1 for r in rows if r["classification"] == c) for c in ("FIGURE", "FIGURE_REVIEW", "NOT_FIGURE")
        },
        "recall": {
            "validated": f"{validated_retained}/{len(validated)}",
            "needs_correction": f"{needs_correction_retained}/{len(needs_correction)}",
            "overall_real_figures": f"{real_figures_retained}/{total_real_figures}",
            "overall_real_figures_pct": round(100 * real_figures_retained / total_real_figures, 1) if total_real_figures else None,
        },
        "false_negatives_real_figures_lost": false_negatives,
        "false_positives": {
            "rejected_still_in_queue": [r["candidate_id"] for r in fp_retained],
            "rejected_still_in_queue_count": len(fp_retained),
            "rejected_confidently_excluded_count": len(fp_excluded),
            "rejected_confidently_excluded": [r["candidate_id"] for r in fp_excluded],
        },
        "queue_size": queue_size,
        "precision_queue_real_figures_over_queue": round(precision_queue, 3),
        "precision_figure_bucket_only": round(precision_figure_bucket, 3),
        "confusion_matrix": {f"{gt}->{pred}": ids for (gt, pred), ids in sorted(confusion.items())},
    }


def render_text_report(metrics: dict, rows: list) -> str:
    lines = [
        "VISUAL DETECTION V4 -- EVALUATION AGAINST NEW GROUND TRUTH",
        "=" * 60,
        "",
        f"Total candidates (V3 queue): {metrics['total_candidates']}",
        f"Ground truth: {metrics['ground_truth_counts']}",
        f"V4 classification counts: {metrics['classification_counts']}",
        f"Queue size (FIGURE + FIGURE_REVIEW): {metrics['queue_size']} / {metrics['total_candidates']}",
        "",
        "--- Recall (the critical metric) ---",
        f"VALIDATED retained       : {metrics['recall']['validated']}",
        f"NEEDS_CORRECTION retained: {metrics['recall']['needs_correction']}",
        f"Overall real-figure recall: {metrics['recall']['overall_real_figures']} ({metrics['recall']['overall_real_figures_pct']}%)",
        f"Real figures LOST (must be empty): {metrics['false_negatives_real_figures_lost']}",
        "",
        "--- Precision ---",
        f"REJECTED still in queue (FIGURE/FIGURE_REVIEW): {metrics['false_positives']['rejected_still_in_queue_count']} / {metrics['ground_truth_counts']['REJECTED']}",
        f"  ids: {metrics['false_positives']['rejected_still_in_queue']}",
        f"REJECTED confidently excluded (NOT_FIGURE): {metrics['false_positives']['rejected_confidently_excluded_count']} / {metrics['ground_truth_counts']['REJECTED']}",
        f"Precision (real figures / queue size): {metrics['precision_queue_real_figures_over_queue']:.1%}",
        f"Precision (FIGURE bucket only): {metrics['precision_figure_bucket_only']:.1%}",
        "",
        "--- Confusion matrix (ground_truth -> V4 classification) ---",
    ]
    for k, ids in metrics["confusion_matrix"].items():
        lines.append(f"{k}: {len(ids)}  {ids}")
    lines.append("")
    lines.append("--- Per-candidate detail ---")
    for r in sorted(rows, key=lambda r: (r["ground_truth"], r["candidate_id"])):
        lines.append(
            f"{r['ground_truth']:18s} {r['candidate_id']:26s} -> {r['classification']:14s} "
            f"conf={r['confidence']:.2f} reasons={r['reason_codes']}"
        )
    return "\n".join(lines) + "\n"


LABEL_COLORS = {"FIGURE": (30, 140, 60), "FIGURE_REVIEW": (180, 130, 20), "NOT_FIGURE": (170, 30, 30)}


def build_contact_sheet(rows: list, output_path, only_classifications=None) -> None:
    entries = [r for r in rows if only_classifications is None or r["classification"] in only_classifications]
    if not entries:
        return
    entries = sorted(entries, key=lambda r: r["candidate_id"])

    thumb_size = 260
    label_height = 50
    cell_size_w = thumb_size + 10
    cell_size_h = thumb_size + label_height
    columns = max(1, int(len(entries) ** 0.5))
    rows_n = -(-len(entries) // columns)

    sheet = Image.new("RGB", (columns * cell_size_w, rows_n * cell_size_h), "white")
    draw = ImageDraw.Draw(sheet)

    for i, entry in enumerate(entries):
        page = entry["page"]
        image_path = config.FIGURE_CANDIDATES_V3_DIR / f"page_{page:03d}" / f"{entry['candidate_id']}.png"
        col, row = i % columns, i // columns
        x0 = col * cell_size_w
        y0 = row * cell_size_h
        if image_path.exists():
            try:
                with Image.open(image_path) as im:
                    thumb = im.copy()
                thumb.thumbnail((thumb_size, thumb_size))
                px = x0 + 5 + (thumb_size - thumb.width) // 2
                py = y0 + (thumb_size - thumb.height) // 2
                sheet.paste(thumb, (px, py))
            except Exception:
                pass
        color = LABEL_COLORS.get(entry["classification"], (0, 0, 0))
        draw.rectangle([x0, y0 + thumb_size, x0 + cell_size_w, y0 + cell_size_h], fill=(245, 245, 245))
        draw.text((x0 + 5, y0 + thumb_size + 2), entry["candidate_id"], fill="black")
        draw.text((x0 + 5, y0 + thumb_size + 18), entry["classification"], fill=color)
        draw.text((x0 + 5, y0 + thumb_size + 34), f"conf={entry['confidence']:.2f}", fill=(80, 80, 80))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def main() -> None:
    setup_logging()
    rows = build_rows()
    metrics = compute_metrics(rows)

    config.VISUAL_DETECTION_V4_EVALUATION_JSON.write_text(
        json.dumps({**metrics, "candidates": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config.VISUAL_DETECTION_V4_EVALUATION_TXT.write_text(render_text_report(metrics, rows), encoding="utf-8")

    features_dump = [
        {
            "candidate_id": r["candidate_id"],
            "page": r["page"],
            "bbox": r["bbox"],
            "classification": r["classification"],
            "confidence": r["confidence"],
            "features": r["features"],
            "reason_codes": r["reason_codes"],
        }
        for r in sorted(rows, key=lambda r: r["candidate_id"])
    ]
    config.VISUAL_DETECTION_V4_FEATURES_JSON.write_text(json.dumps(features_dump, ensure_ascii=False, indent=2), encoding="utf-8")

    build_contact_sheet(rows, config.FIGURE_CANDIDATES_V4_DIR / "contact_sheet_all.png")
    build_contact_sheet(rows, config.FIGURE_CANDIDATES_V4_DIR / "contact_sheet_figures.png", only_classifications={"FIGURE"})

    logger.info("Wrote evaluation JSON/TXT, features JSON, and 2 contact sheets.")
    print(render_text_report(metrics, rows))


if __name__ == "__main__":
    main()
