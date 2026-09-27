"""
Phase 5a - build the final Chapter 1 figure dataset.

Finalizes the 19 real figures already confirmed by human review (see
visual_detection_v4_evaluation.json's "ground_truth" field, produced by
the completed V4 task): 13 VALIDATED (kept as-is, V4's own bbox is
already an acceptable crop) + 6 NEEDS_CORRECTION (real figure, but the
V4 bbox includes attached non-figure text -- corrected here via
crop_correction.correct_crop, see that module for the algorithm).

This script only READS visual_detection_v4_evaluation.json and the
rendered page images (data/output/page_images/); it never modifies V3,
V4, or the Chapter 1 knowledge JSON. It WRITES a new, separate
directory: data/output/final_figures/ (figure_001.png..figure_019.png,
index.json, review.json, contact_sheet.png, validation_report.json).

The ground-truth list of which 19 candidates are real, and which of
those 6 need correction, is NOT hardcoded here as page/candidate IDs
picked out of thin air -- it is the exact, already-established human
review verdict recorded in visual_detection_v4_evaluation.json's
"ground_truth" field for every one of the 39 V3 candidates. This
script only filters for ground_truth in {VALIDATED, NEEDS_CORRECTION}
and reads each entry's own (page, bbox); it does not special-case any
individual page or candidate.

Usage:
    python build_final_figures.py
    python build_final_figures.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config
from crop_correction import correct_crop

logger = logging.getLogger("build_final_figures")

REAL_GROUND_TRUTH_STATUSES = {"VALIDATED", "NEEDS_CORRECTION"}
CONTACT_SHEET_COLUMNS = 4
CONTACT_SHEET_CELL_WIDTH = 420
CONTACT_SHEET_CELL_HEIGHT = 340
CONTACT_SHEET_IMAGE_HEIGHT = 260
CONTACT_SHEET_PADDING = 12


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_real_figures() -> list[dict]:
    """Read the 19 human-confirmed-real candidates, ordered by
    (page, candidate_id) for a stable, reproducible figure_NNN numbering."""
    if not config.VISUAL_DETECTION_V4_EVALUATION_JSON.exists():
        raise FileNotFoundError(
            f"{config.VISUAL_DETECTION_V4_EVALUATION_JSON} not found -- run the V4 pipeline first"
        )
    data = json.loads(config.VISUAL_DETECTION_V4_EVALUATION_JSON.read_text(encoding="utf-8"))
    real = [c for c in data["candidates"] if c.get("ground_truth") in REAL_GROUND_TRUTH_STATUSES]
    real.sort(key=lambda c: (c["page"], c["candidate_id"]))
    return real


def load_page_image(page: int, cache: dict) -> np.ndarray:
    if page not in cache:
        path = config.PAGE_IMAGES_DIR / f"page_{page:03d}.png"
        cache[page] = np.array(Image.open(path).convert("RGB"))
    return cache[page]


def build_figures(force: bool) -> dict:
    config.FINAL_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    real_figures = load_real_figures()
    page_cache: dict[int, np.ndarray] = {}

    index_entries = []
    review_entries = []
    correction_log = []

    for i, cand in enumerate(real_figures, start=1):
        figure_id = f"figure_{i:03d}"
        page = cand["page"]
        candidate_id = cand["candidate_id"]
        status = cand["ground_truth"]
        original_bbox = list(cand["bbox"])
        page_array = load_page_image(page, page_cache)

        if status == "NEEDS_CORRECTION":
            result = correct_crop(page_array, original_bbox)
            final_bbox = result.bbox
            final_status = "CORRECTED"
            correction_log.append({
                "figure_id": figure_id,
                "candidate_id": candidate_id,
                "source_page": page,
                "original_bbox": original_bbox,
                "final_bbox": final_bbox,
                "changed": result.changed,
                "reason": result.reason,
            })
        else:
            final_bbox = original_bbox
            final_status = "VALIDATED"

        image_name = f"{figure_id}.png"
        image_path = config.FINAL_FIGURES_DIR / image_name
        if force or not image_path.exists():
            x0, y0, x1, y1 = final_bbox
            crop = page_array[y0:y1, x0:x1]
            Image.fromarray(crop).save(image_path)

        source_image = f"page_{page:03d}.png"
        index_entries.append({
            "figure_id": figure_id,
            "source_page": page,
            "candidate_id": candidate_id,
            "status": final_status,
            "original_bbox": original_bbox,
            "final_bbox": final_bbox,
            "image": image_name,
            "source_image": source_image,
        })
        review_entries.append({
            "figure_id": figure_id,
            "candidate_id": candidate_id,
            "source_page": page,
            "status": final_status,
            "bbox": final_bbox,
            "review_status": "PENDING",
        })

    index = {"chapter_id": "math-4eme-tome1-ch01", "figures": index_entries}
    config.FINAL_FIGURES_INDEX_JSON.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config.FINAL_FIGURES_REVIEW_JSON.write_text(
        json.dumps(review_entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info("Wrote %d final figures to %s", len(index_entries), config.FINAL_FIGURES_DIR)
    logger.info("Wrote index: %s", config.FINAL_FIGURES_INDEX_JSON)
    logger.info("Wrote review queue (all PENDING): %s", config.FINAL_FIGURES_REVIEW_JSON)
    return {"index": index, "corrections": correction_log}


def build_contact_sheet() -> None:
    index = json.loads(config.FINAL_FIGURES_INDEX_JSON.read_text(encoding="utf-8"))
    figures = index["figures"]
    n = len(figures)
    cols = CONTACT_SHEET_COLUMNS
    rows = (n + cols - 1) // cols

    sheet_w = cols * CONTACT_SHEET_CELL_WIDTH
    sheet_h = rows * CONTACT_SHEET_CELL_HEIGHT
    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for i, entry in enumerate(figures):
        row, col = divmod(i, cols)
        cell_x0 = col * CONTACT_SHEET_CELL_WIDTH
        cell_y0 = row * CONTACT_SHEET_CELL_HEIGHT

        img_path = config.FINAL_FIGURES_DIR / entry["image"]
        fig_img = Image.open(img_path).convert("RGB")
        max_w = CONTACT_SHEET_CELL_WIDTH - 2 * CONTACT_SHEET_PADDING
        max_h = CONTACT_SHEET_IMAGE_HEIGHT
        scale = min(max_w / fig_img.width, max_h / fig_img.height, 1.0)
        thumb = fig_img.resize((max(1, int(fig_img.width * scale)), max(1, int(fig_img.height * scale))))

        paste_x = cell_x0 + CONTACT_SHEET_PADDING
        paste_y = cell_y0 + CONTACT_SHEET_PADDING
        sheet.paste(thumb, (paste_x, paste_y))
        draw.rectangle(
            [cell_x0 + 2, cell_y0 + 2, cell_x0 + CONTACT_SHEET_CELL_WIDTH - 2, cell_y0 + CONTACT_SHEET_CELL_HEIGHT - 2],
            outline=(200, 200, 200),
        )

        label_y = cell_y0 + CONTACT_SHEET_PADDING + max_h + 4
        text = (
            f"{entry['figure_id']}  page {entry['source_page']}  {entry['status']}\n"
            f"{entry['candidate_id']}"
        )
        draw.multiline_text((cell_x0 + CONTACT_SHEET_PADDING, label_y), text, fill=(0, 0, 0), font=font)

    sheet.save(config.FINAL_FIGURES_CONTACT_SHEET_PNG)
    logger.info("Wrote contact sheet: %s", config.FINAL_FIGURES_CONTACT_SHEET_PNG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the final Chapter 1 figure dataset (Phase 5a)")
    parser.add_argument("--force", action="store_true", help="Regenerate crops even if they already exist")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = build_figures(args.force)
        build_contact_sheet()
        logger.info("Done. %d figures finalized (%d corrected).",
                    len(result["index"]["figures"]), len(result["corrections"]))
    except Exception:
        logger.exception("build_final_figures failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
