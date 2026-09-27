"""
Phase 4e - V2 visual-element classification + bbox trimming.

Reads the EXISTING Phase 4b refined report (detect_visual_elements.py +
refine_visual_elements.py -- seed detection and pixel-based bbox growth
are UNCHANGED, kept as-is per design brief) and, for every "candidate"
element, applies classify_visual_elements_v2.py's multi-signal
classification and text-margin bbox trimming. Writes a SEPARATE report
(visual_elements_report_v2.json) in the same schema as V1, so
extract_figure_candidates.py works UNCHANGED against it -- just point
--report at it (see run_v2_pipeline() below, which does exactly that
into a NEW figure_candidates_v2/ directory; V1's outputs are never
touched).

Only FIGURE and AMBIGUOUS candidates keep type="candidate" (so they are
extracted as crops and reach the human review queue); TABLE,
TEXT_BLOCK and DECORATIVE are re-tagged type="rejected_<category>" so
extract_figure_candidates.py's existing `type == "candidate"` filter
skips them automatically -- no change needed to that script at all.

Usage:
    python detect_visual_elements_v2.py
    python detect_visual_elements_v2.py --force
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import classify_visual_elements_v2 as v2
import config

logger = logging.getLogger("detect_visual_elements_v2")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_report(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Refined report not found: {path}. Run refine_visual_elements.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


# Only FIGURE/AMBIGUOUS enter the human figure review queue (kept as
# type="candidate" for extract_figure_candidates.py); everything else is
# re-tagged so that script's existing filter skips it.
QUEUE_CATEGORIES = {"FIGURE", "AMBIGUOUS"}


def classify_page_candidates(page_array: np.ndarray, elements: list) -> list:
    out = []
    for element in elements:
        if element.get("type") != "candidate":
            out.append(element)
            continue

        pre_trim_bbox = list(element["bbox"])
        trimmed_bbox, trimmed = v2.trim_text_margins(page_array, pre_trim_bbox)
        features = v2.extract_features(page_array, trimmed_bbox, element.get("likely_text_box", False))
        category, reason = v2.classify(features)

        updated = dict(element)
        updated["pre_trim_bbox"] = pre_trim_bbox
        updated["bbox"] = trimmed_bbox
        updated["bbox_trimmed"] = trimmed
        updated["v2_classification"] = category
        updated["v2_reason"] = reason
        updated["type"] = "candidate" if category in QUEUE_CATEGORIES else f"rejected_{category.lower()}"
        # needs_review stays True unconditionally -- V2 narrows what reaches
        # the queue, but never claims certainty for what does.
        out.append(updated)
    return out


def run(input_path: Path, output_path: Path, page_images_dir: Path, force: bool) -> dict:
    report = load_report(input_path)
    input_fingerprint = {"size": input_path.stat().st_size, "mtime": input_path.stat().st_mtime}

    if output_path.exists() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("source_report_fingerprint") == input_fingerprint:
                logger.info("V2 report already up to date, skipping (use --force to redo): %s", output_path)
                return existing
        except (json.JSONDecodeError, KeyError):
            pass

    pages_out = []
    counts = {}
    for page_entry in report.get("pages", []):
        pdf_page_number = page_entry["pdf_page"]
        image_path = page_images_dir / f"page_{pdf_page_number:03d}.png"
        page_array = np.array(Image.open(image_path).convert("RGB"))
        elements = classify_page_candidates(page_array, page_entry.get("visual_elements", []))
        pages_out.append({"pdf_page": pdf_page_number, "visual_elements": elements})
        for e in elements:
            cat = e.get("v2_classification")
            if cat:
                counts[cat] = counts.get(cat, 0) + 1

    output_report = dict(report)
    output_report["pages"] = pages_out
    output_report["source_report"] = str(input_path)
    output_report["source_report_fingerprint"] = input_fingerprint
    output_report["v2_classification_counts"] = counts
    output_report["v2_queue_count"] = sum(counts.get(c, 0) for c in QUEUE_CATEGORIES)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_report


def run_v2_pipeline(force: bool) -> None:
    """Full V2 leg: classify+trim, then reuse extract_figure_candidates.py
    UNCHANGED against the new report/output dir (per design brief)."""
    report = run(
        config.VISUAL_ELEMENTS_REFINED_REPORT_JSON,
        config.VISUAL_ELEMENTS_REPORT_V2_JSON,
        config.PAGE_IMAGES_DIR,
        force,
    )
    logger.info("V2 classification counts: %s", report.get("v2_classification_counts"))
    logger.info("Candidates entering the review queue (FIGURE+AMBIGUOUS): %s", report.get("v2_queue_count"))

    cmd = [
        sys.executable, "extract_figure_candidates.py",
        "--report", str(config.VISUAL_ELEMENTS_REPORT_V2_JSON),
        "--output", str(config.FIGURE_CANDIDATES_V2_DIR),
        "--index", str(config.FIGURE_CANDIDATES_V2_INDEX_JSON),
    ]
    if force:
        cmd.append("--force")
    logger.info("Running extract_figure_candidates.py against the V2 report (unchanged script, new output dir)...")
    subprocess.run(cmd, check=True, cwd=Path(__file__).parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V2 visual-element classification + bbox trimming (Phase 4e)")
    parser.add_argument("--input", type=Path, default=config.VISUAL_ELEMENTS_REFINED_REPORT_JSON)
    parser.add_argument("--output", type=Path, default=config.VISUAL_ELEMENTS_REPORT_V2_JSON)
    parser.add_argument("--page-images", type=Path, default=config.PAGE_IMAGES_DIR)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-extract", action="store_true", help="Only write the V2 report, skip crop generation")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        if args.no_extract:
            report = run(args.input, args.output, args.page_images, args.force)
            logger.info("Done. V2 classification counts: %s", report.get("v2_classification_counts"))
        else:
            run_v2_pipeline(args.force)
    except Exception:
        logger.exception("V2 visual element detection failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
