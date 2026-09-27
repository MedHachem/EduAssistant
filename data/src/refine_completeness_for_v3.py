"""
Phase 4g - V3 figure-completeness refinement orchestration.

Reads visual_elements_report_v2.json (V2 -- classification + bbox
trimming, UNCHANGED, never re-run or overwritten here) and, for every
element that reached the review queue (v2_classification FIGURE or
AMBIGUOUS), applies figure_completeness_v3.refine_completeness() to
recover any small label/fragment V2's trimming may have cut from inside
the figure's own extent. Writes visual_elements_report_v3.json in the
same schema, then reuses extract_figure_candidates.py UNCHANGED against
it into a NEW figure_candidates_v3/ directory.

Elements V2 already excluded (TABLE/TEXT_BLOCK/DECORATIVE) are passed
through untouched -- this stage only ever adjusts the bbox of something
already judged to be a figure/ambiguous candidate, it never changes
classification.

Usage:
    python refine_completeness_for_v3.py
    python refine_completeness_for_v3.py --force
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import config
import figure_completeness_v3 as v3

logger = logging.getLogger("refine_completeness_for_v3")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_report(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"V2 report not found: {path}. Run detect_visual_elements_v2.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


QUEUE_CATEGORIES = {"FIGURE", "AMBIGUOUS"}


def refine_page_elements(page_array: np.ndarray, elements: list) -> tuple[list, int]:
    out = []
    changed_count = 0
    for element in elements:
        if element.get("v2_classification") not in QUEUE_CATEGORIES:
            out.append(element)
            continue

        v2_bbox = list(element["bbox"])
        search_bbox = element.get("pre_trim_bbox")
        v3_bbox, changed = v3.refine_completeness(page_array, v2_bbox, search_bbox)

        updated = dict(element)
        updated["v2_bbox"] = v2_bbox
        updated["bbox"] = v3_bbox
        updated["v3_completeness_changed"] = changed
        out.append(updated)
        changed_count += int(changed)
    return out, changed_count


def run(input_path: Path, output_path: Path, page_images_dir: Path, force: bool) -> dict:
    report = load_report(input_path)
    input_fingerprint = {"size": input_path.stat().st_size, "mtime": input_path.stat().st_mtime}

    if output_path.exists() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("source_report_fingerprint") == input_fingerprint:
                logger.info("V3 report already up to date, skipping (use --force to redo): %s", output_path)
                return existing
        except (json.JSONDecodeError, KeyError):
            pass

    pages_out = []
    total_changed = 0
    for page_entry in report.get("pages", []):
        pdf_page_number = page_entry["pdf_page"]
        image_path = page_images_dir / f"page_{pdf_page_number:03d}.png"
        page_array = np.array(Image.open(image_path).convert("RGB"))
        elements, changed_count = refine_page_elements(page_array, page_entry.get("visual_elements", []))
        pages_out.append({"pdf_page": pdf_page_number, "visual_elements": elements})
        total_changed += changed_count

    output_report = dict(report)
    output_report["pages"] = pages_out
    output_report["source_report"] = str(input_path)
    output_report["source_report_fingerprint"] = input_fingerprint
    output_report["v3_bboxes_changed"] = total_changed

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_report


def run_v3_pipeline(force: bool) -> None:
    report = run(config.VISUAL_ELEMENTS_REPORT_V2_JSON, config.VISUAL_ELEMENTS_REPORT_V3_JSON, config.PAGE_IMAGES_DIR, force)
    logger.info("V3 bboxes changed (grown to recover a missing fragment): %s", report.get("v3_bboxes_changed"))

    cmd = [
        sys.executable, "extract_figure_candidates.py",
        "--report", str(config.VISUAL_ELEMENTS_REPORT_V3_JSON),
        "--output", str(config.FIGURE_CANDIDATES_V3_DIR),
        "--index", str(config.FIGURE_CANDIDATES_V3_INDEX_JSON),
    ]
    if force:
        cmd.append("--force")
    logger.info("Running extract_figure_candidates.py against the V3 report (unchanged script, new output dir)...")
    subprocess.run(cmd, check=True, cwd=Path(__file__).parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V3 figure-completeness refinement (Phase 4g)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-extract", action="store_true", help="Only write the V3 report, skip crop generation")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        if args.no_extract:
            report = run(config.VISUAL_ELEMENTS_REPORT_V2_JSON, config.VISUAL_ELEMENTS_REPORT_V3_JSON, config.PAGE_IMAGES_DIR, args.force)
            logger.info("Done. V3 bboxes changed: %s", report.get("v3_bboxes_changed"))
        else:
            run_v3_pipeline(args.force)
    except Exception:
        logger.exception("V3 completeness refinement failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
