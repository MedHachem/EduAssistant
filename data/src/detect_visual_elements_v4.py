"""
Phase 4j - V4 classification orchestration.

Reads visual_elements_report_v3.json (V3 -- completeness-refined bboxes,
UNCHANGED, never re-run or overwritten here) and, for every element
still in the review queue (type=="candidate", i.e. the 39 real V3
candidates), applies classify_visual_elements_v4's FIGURE / NOT_FIGURE /
FIGURE_REVIEW classification. Writes visual_elements_report_v4.json in
the same schema, then reuses extract_figure_candidates.py UNCHANGED
against it into a NEW figure_candidates_v4/ directory.

Only FIGURE and FIGURE_REVIEW keep type="candidate" (crop generated,
enters the reviewable queue); NOT_FIGURE is re-tagged so
extract_figure_candidates.py's existing type=="candidate" filter skips
it automatically -- no change needed to that script.

Elements V2 already excluded (TEXT_BLOCK/TABLE/DECORATIVE, i.e. not in
the 39) pass through completely untouched.

Usage:
    python detect_visual_elements_v4.py
    python detect_visual_elements_v4.py --force
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import classify_visual_elements_v4 as v4
import config

logger = logging.getLogger("detect_visual_elements_v4")

QUEUE_CLASSIFICATIONS = {"FIGURE", "FIGURE_REVIEW"}


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_report(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"V3 report not found: {path}. Run refine_completeness_for_v3.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def classify_page_elements(page_array: np.ndarray, elements: list) -> tuple[list, list]:
    out = []
    feature_rows = []
    for element in elements:
        if element.get("type") != "candidate":
            out.append(element)
            continue

        bbox = element["bbox"]
        features = v4.extract_features(page_array, bbox)
        classification, confidence, reasons = v4.classify(features)

        updated = dict(element)
        updated["v4_classification"] = classification
        updated["v4_confidence"] = confidence
        updated["v4_reason_codes"] = reasons
        updated["v4_features"] = vars(features)
        updated["type"] = "candidate" if classification in QUEUE_CLASSIFICATIONS else "rejected_not_figure_v4"
        out.append(updated)

        feature_rows.append({
            "bbox": bbox,
            "classification": classification,
            "confidence": confidence,
            "reason_codes": reasons,
            "features": vars(features),
        })
    return out, feature_rows


def run(input_path: Path, output_path: Path, page_images_dir: Path, force: bool) -> dict:
    report = load_report(input_path)
    input_fingerprint = {"size": input_path.stat().st_size, "mtime": input_path.stat().st_mtime}

    if output_path.exists() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("source_report_fingerprint") == input_fingerprint:
                logger.info("V4 report already up to date, skipping (use --force to redo): %s", output_path)
                return existing
        except (json.JSONDecodeError, KeyError):
            pass

    pages_out = []
    counts = {}
    for page_entry in report.get("pages", []):
        pdf_page_number = page_entry["pdf_page"]
        image_path = page_images_dir / f"page_{pdf_page_number:03d}.png"
        page_array = np.array(Image.open(image_path).convert("RGB"))
        elements, _ = classify_page_elements(page_array, page_entry.get("visual_elements", []))
        pages_out.append({"pdf_page": pdf_page_number, "visual_elements": elements})
        for e in elements:
            cat = e.get("v4_classification")
            if cat:
                counts[cat] = counts.get(cat, 0) + 1

    output_report = dict(report)
    output_report["pages"] = pages_out
    output_report["source_report"] = str(input_path)
    output_report["source_report_fingerprint"] = input_fingerprint
    output_report["v4_classification_counts"] = counts
    output_report["v4_queue_count"] = sum(counts.get(c, 0) for c in QUEUE_CLASSIFICATIONS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_report


def run_v4_pipeline(force: bool) -> None:
    report = run(config.VISUAL_ELEMENTS_REPORT_V3_JSON, config.VISUAL_ELEMENTS_REPORT_V4_JSON, config.PAGE_IMAGES_DIR, force)
    logger.info("V4 classification counts: %s", report.get("v4_classification_counts"))
    logger.info("Candidates entering the review queue (FIGURE+FIGURE_REVIEW): %s", report.get("v4_queue_count"))

    cmd = [
        sys.executable, "extract_figure_candidates.py",
        "--report", str(config.VISUAL_ELEMENTS_REPORT_V4_JSON),
        "--output", str(config.FIGURE_CANDIDATES_V4_DIR),
        "--index", str(config.FIGURE_CANDIDATES_V4_INDEX_JSON),
    ]
    if force:
        cmd.append("--force")
    logger.info("Running extract_figure_candidates.py against the V4 report (unchanged script, new output dir)...")
    subprocess.run(cmd, check=True, cwd=Path(__file__).parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V4 figure/not-figure classification (Phase 4j)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-extract", action="store_true", help="Only write the V4 report, skip crop generation")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        if args.no_extract:
            report = run(config.VISUAL_ELEMENTS_REPORT_V3_JSON, config.VISUAL_ELEMENTS_REPORT_V4_JSON, config.PAGE_IMAGES_DIR, args.force)
            logger.info("Done. V4 classification counts: %s", report.get("v4_classification_counts"))
        else:
            run_v4_pipeline(args.force)
    except Exception:
        logger.exception("V4 classification failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
