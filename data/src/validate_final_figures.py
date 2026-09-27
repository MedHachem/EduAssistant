"""
Phase 5a - automated validation report for the final figure dataset.

Checks, per figure_NNN, as many of the task's 10-point checklist as are
actually automatable from pixels alone (deterministic, no LLM):
  1. figure present       -- index.json entry + PNG file both exist
  2. output PNG exists    -- (see 1)
  3. bbox inside page     -- final_bbox within the source page's pixel bounds
  4. no accidental page border -- outer 3px edge of the crop is not a
     long, near-uniformly dark line (a scanned physical page edge/
     binding shadow), which would indicate the crop drifted outside the
     figure's own content
  5. image resolution sufficient -- width and height both above a
     reasonable floor for a reviewable figure
  6. non-zero / non-blank content -- crop is not a uniform blank region
  7. no important ink cut at the crop edge -- ink density in the outer
     3px band on each of the 4 edges is not implausibly high (a curve
     or axis sliced exactly at the boundary shows as a long dense line
     hugging that edge; occasional single label pixels do not)

Checks 8-10 (figure completeness beyond edge-cutting, axis-completeness,
math-label preservation, exclusion of unrelated paragraph text) are the
ones the task brief itself flags as requiring human judgement -- they
are exactly why review.json exists with review_status="PENDING" for
every entry, and are NOT claimed as automatically verified here.

Usage:
    python validate_final_figures.py
"""

from __future__ import annotations

import json
import logging
import sys

import numpy as np
from PIL import Image

import config

logger = logging.getLogger("validate_final_figures")

MIN_WIDTH_PX = 60
MIN_HEIGHT_PX = 60
EDGE_BAND_PX = 3
EDGE_DARK_FRACTION_THRESHOLD = 0.9
EDGE_DARK_PIXEL_THRESHOLD = 80


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])


def check_edge_not_cut(crop: np.ndarray) -> list[str]:
    """Flags an edge as suspicious if it looks like a long, dense, dark
    line running the full length of that edge -- consistent with a
    curve/axis sliced exactly at the crop boundary rather than a
    handful of incidental label pixels."""
    gray = crop.mean(axis=2)
    dark = gray < EDGE_DARK_PIXEL_THRESHOLD
    problems = []
    edges = {
        "top": dark[:EDGE_BAND_PX, :],
        "bottom": dark[-EDGE_BAND_PX:, :],
        "left": dark[:, :EDGE_BAND_PX],
        "right": dark[:, -EDGE_BAND_PX:],
    }
    for name, band in edges.items():
        # collapse the band to "is this column/row dark anywhere in the band"
        line = band.any(axis=0) if name in ("top", "bottom") else band.any(axis=1)
        if line.mean() > EDGE_DARK_FRACTION_THRESHOLD:
            problems.append(f"{name} edge is a long dense dark line (possible content cut at crop boundary)")
    return problems


def validate() -> dict:
    index = json.loads(config.FINAL_FIGURES_INDEX_JSON.read_text(encoding="utf-8"))
    results = []
    page_cache: dict[int, tuple[int, int]] = {}

    for entry in index["figures"]:
        figure_id = entry["figure_id"]
        problems = []
        image_path = config.FINAL_FIGURES_DIR / entry["image"]

        if not image_path.exists():
            problems.append("output PNG missing")
            results.append({"figure_id": figure_id, "passed": False, "problems": problems})
            continue

        crop = np.array(Image.open(image_path).convert("RGB"))
        h, w = crop.shape[:2]

        if w < MIN_WIDTH_PX or h < MIN_HEIGHT_PX:
            problems.append(f"resolution too small ({w}x{h}, minimum {MIN_WIDTH_PX}x{MIN_HEIGHT_PX})")

        if crop.std() < 1.0:
            problems.append("crop content is blank/uniform")

        page = entry["source_page"]
        if page not in page_cache:
            with Image.open(config.PAGE_IMAGES_DIR / entry["source_image"]) as img:
                page_cache[page] = img.size  # (width, height)
        page_w, page_h = page_cache[page]
        x0, y0, x1, y1 = entry["final_bbox"]
        if x0 < 0 or y0 < 0 or x1 > page_w or y1 > page_h or x0 >= x1 or y0 >= y1:
            problems.append(f"final_bbox {entry['final_bbox']} out of page bounds ({page_w}x{page_h})")

        problems.extend(check_edge_not_cut(crop))

        results.append({"figure_id": figure_id, "passed": len(problems) == 0, "problems": problems})

    report = {
        "chapter_id": index["chapter_id"],
        "total_figures": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "results": results,
        "note": (
            "Automated checks cover presence, resolution, non-blank content, "
            "bbox-in-page, and obvious edge-cut heuristics only. Full figure "
            "completeness (axes/labels/curves fully preserved, unrelated text "
            "fully excluded) is confirmed via human review -- see review.json."
        ),
    }
    config.FINAL_FIGURES_VALIDATION_REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    setup_logging()
    report = validate()
    logger.info("Validation: %d/%d passed", report["passed"], report["total_figures"])
    for r in report["results"]:
        if not r["passed"]:
            logger.info("  %s: %s", r["figure_id"], "; ".join(r["problems"]))
    logger.info("Report written to %s", config.FINAL_FIGURES_VALIDATION_REPORT_JSON)


if __name__ == "__main__":
    main()
