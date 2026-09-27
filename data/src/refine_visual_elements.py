"""
Phase 4b - Pixel-based candidate bbox refinement.

detect_visual_elements.py finds candidate SEEDS from embedded PDF image/
drawing/table objects. Diagnosis (against real crops in this chapter)
showed these seeds are frequently incomplete: the scan/compression
pipeline behind this PDF only splits out a separate image object for
the "busiest"/most colorful sub-region of a figure -- thin axis lines,
tick labels, and steep/sparse curve segments belonging to the SAME
figure often have no PDF object of their own and remain baked into the
excluded full-page background tile. No amount of clustering the PDF
objects can recover that content, because it was never a separate
object to begin with.

This stage fixes that by looking at actual PIXELS instead: for each
candidate, it re-derives the true visual extent from the already-
rendered page image (page_images/page_NNN.png), using classic,
deterministic image processing -- ink/background thresholding, binary
dilation, connected-component labeling via scipy.ndimage. No OCR, no
Claude/LLM, no ML classifier.

It also computes one new, purely deterministic signal --
`likely_text_box` -- from the refined region's dominant background
color: a colored theorem/reminder callout box has a distinctly tinted
dominant background (measurable channel spread away from grayscale),
while a real figure's background is plain white page. Empirically:
real figures measured background channel-spread ~0-2; callout boxes
measured ~48-64. This NEVER deletes a candidate -- it only adds a hint
for a human reviewer, exactly like `needs_review`.

Safety: if pixel-growth can't find a natural whitespace boundary within
a bounded search window around the seed (i.e. it would have to reach
the window's edge, or grow to background-scan size -- empirically this
is exactly what happens for callout boxes, which tend to sit close to
other page furniture), that candidate's growth is distrusted and the
ORIGINAL seed bbox is kept instead, flagged `refinement_uncertain: true`.

Input/output use the same report schema (see detect_visual_elements.py),
so extract_figure_candidates.py works UNCHANGED against the refined
report -- just point --report at it.

Usage:
    python refine_visual_elements.py
    python refine_visual_elements.py --input ../output/visual_elements_report.json
    python refine_visual_elements.py --force
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import config
from pdf_render import render_page_to_png

logger = logging.getLogger("refine_visual_elements")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_report(report_path: Path) -> dict:
    if not report_path.exists():
        raise FileNotFoundError(f"Detection report not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _disk_structure(radius: int) -> np.ndarray:
    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    return (xx * xx + yy * yy) <= radius * radius


def grow_bbox(page_array: np.ndarray, seed_bbox: list, margin: int, ink_threshold: int, dilation_radius: int):
    """Grow `seed_bbox` (pixel space) to the extent of whatever ink is
    connected to it, within a bounded search window. Returns
    (grown_bbox, hit_window_edge) -- hit_window_edge signals the growth
    may have run away rather than found a true whitespace boundary."""
    height, width = page_array.shape[0], page_array.shape[1]
    x0, y0, x1, y1 = seed_bbox

    wx0, wy0 = max(0, x0 - margin), max(0, y0 - margin)
    wx1, wy1 = min(width, x1 + margin), min(height, y1 + margin)
    window = page_array[wy0:wy1, wx0:wx1]

    deviation_from_white = 255 - window.min(axis=2).astype(np.int16)
    ink_mask = deviation_from_white > ink_threshold
    dilated = ndimage.binary_dilation(ink_mask, structure=_disk_structure(dilation_radius))
    labeled, _ = ndimage.label(dilated, structure=np.ones((3, 3)))

    sx0, sy0, sx1, sy1 = x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0
    seed_labels = set(np.unique(labeled[sy0:sy1, sx0:sx1]))
    seed_labels.discard(0)

    if not seed_labels:
        return list(seed_bbox), False  # no ink found under the seed at all; nothing to grow

    mask = np.isin(labeled, list(seed_labels))
    ys, xs = np.where(mask)

    hit_window_edge = bool(
        xs.min() == 0 or ys.min() == 0
        or xs.max() == window.shape[1] - 1 or ys.max() == window.shape[0] - 1
    )
    grown = [int(xs.min() + wx0), int(ys.min() + wy0), int(xs.max() + 1 + wx0), int(ys.max() + 1 + wy0)]
    return grown, hit_window_edge


def dominant_background_color(page_array: np.ndarray, bbox: list, bin_size: int = 8):
    """Most frequent color within bbox, coarsely binned -- this is the
    region's background (a real figure's background is white page; a
    callout box's background is its own tint), plus its coverage
    fraction."""
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1].reshape(-1, 3)
    if region.size == 0:
        return None, 0.0

    binned = (region // bin_size) * bin_size
    keys = binned[:, 0].astype(np.int32) * 65536 + binned[:, 1].astype(np.int32) * 256 + binned[:, 2].astype(np.int32)
    values, counts = np.unique(keys, return_counts=True)
    top = int(values[np.argmax(counts)])
    color = [(top >> 16) & 255, (top >> 8) & 255, top & 255]
    fraction = float(counts.max() / len(keys))
    return color, fraction


def refine_candidate(page_array: np.ndarray, candidate: dict) -> dict:
    seed_bbox = candidate["bbox"]
    page_area = page_array.shape[0] * page_array.shape[1]

    grown_bbox, hit_window_edge = grow_bbox(
        page_array, seed_bbox,
        config.FIGURE_REFINEMENT_SEARCH_MARGIN_PX,
        config.FIGURE_REFINEMENT_INK_THRESHOLD,
        config.FIGURE_REFINEMENT_DILATION_RADIUS_PX,
    )
    grown_area_ratio = ((grown_bbox[2] - grown_bbox[0]) * (grown_bbox[3] - grown_bbox[1])) / page_area

    refinement_uncertain = hit_window_edge or grown_area_ratio >= config.VISUAL_ELEMENT_BACKGROUND_AREA_RATIO
    final_bbox = list(seed_bbox) if refinement_uncertain else grown_bbox

    color, _color_fraction = dominant_background_color(page_array, final_bbox)
    color_spread = (max(color) - min(color)) if color else 0
    likely_text_box = color_spread > config.FIGURE_TEXT_BOX_COLOR_SPREAD_THRESHOLD

    refined = dict(candidate)
    refined["seed_bbox"] = seed_bbox
    refined["bbox"] = final_bbox
    refined["area_ratio"] = round(
        ((final_bbox[2] - final_bbox[0]) * (final_bbox[3] - final_bbox[1])) / page_area, 4
    )
    refined["refinement_uncertain"] = refinement_uncertain
    refined["likely_text_box"] = likely_text_box
    refined["background_color"] = color
    refined["background_color_spread"] = color_spread
    return refined


def load_page_array(pdf_path: Path, page_images_dir: Path, pdf_page_number: int) -> np.ndarray:
    image_path = page_images_dir / f"page_{pdf_page_number:03d}.png"
    if not image_path.exists():
        image_path = render_page_to_png(pdf_path, pdf_page_number, config.RECONSTRUCTION_IMAGE_DPI, page_images_dir)
    return np.array(Image.open(image_path).convert("RGB"))


def run(input_path: Path, output_path: Path, page_images_dir: Path, force: bool) -> dict:
    report = load_report(input_path)
    pdf_path = Path(report["source_pdf"])
    input_fingerprint = {"size": input_path.stat().st_size, "mtime": input_path.stat().st_mtime}

    if output_path.exists() and not force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("source_report_fingerprint") == input_fingerprint:
                logger.info("Refined report already up to date, skipping (use --force to redo): %s", output_path)
                return existing
        except (json.JSONDecodeError, KeyError):
            pass  # fall through and recompute

    pages_out = []
    refined_count, uncertain_count, text_box_count, errors = 0, 0, 0, 0

    for page_entry in report.get("pages", []):
        pdf_page_number = page_entry["pdf_page"]
        elements = page_entry.get("visual_elements", [])

        page_array = None
        page_load_failed = False
        refined_elements = []

        for element in elements:
            if element.get("type") != "candidate":
                refined_elements.append(element)
                continue

            if page_array is None and not page_load_failed:
                try:
                    page_array = load_page_array(pdf_path, page_images_dir, pdf_page_number)
                except Exception:
                    logger.exception(
                        "Page %d: could not load/render page image, keeping seed bbox(es) unrefined",
                        pdf_page_number,
                    )
                    page_load_failed = True

            if page_load_failed:
                unrefined = dict(element)
                unrefined["seed_bbox"] = element["bbox"]
                unrefined["refinement_uncertain"] = True
                unrefined["likely_text_box"] = False
                unrefined["background_color"] = None
                unrefined["background_color_spread"] = None
                refined_elements.append(unrefined)
                errors += 1
                continue

            try:
                refined = refine_candidate(page_array, element)
            except Exception:
                logger.exception(
                    "Page %d: failed to refine candidate bbox=%s, keeping seed bbox",
                    pdf_page_number, element.get("bbox"),
                )
                refined = dict(element)
                refined["seed_bbox"] = element["bbox"]
                refined["refinement_uncertain"] = True
                refined["likely_text_box"] = False
                refined["background_color"] = None
                refined["background_color_spread"] = None
                errors += 1
                refined_elements.append(refined)
                continue

            refined_count += 1
            uncertain_count += int(refined["refinement_uncertain"])
            text_box_count += int(refined["likely_text_box"])
            refined_elements.append(refined)

        pages_out.append({"pdf_page": pdf_page_number, "visual_elements": refined_elements})

    output_report = dict(report)
    output_report["pages"] = pages_out
    output_report["source_report"] = str(input_path)
    output_report["source_report_fingerprint"] = input_fingerprint
    output_report["refined_candidates"] = refined_count
    output_report["refinement_uncertain_count"] = uncertain_count
    output_report["likely_text_box_count"] = text_box_count
    output_report["refinement_errors"] = errors

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pixel-based visual-element bbox refinement (Phase 4b)")
    parser.add_argument("--input", type=Path, default=config.VISUAL_ELEMENTS_REPORT_JSON, help="Path to visual_elements_report.json (seed detections)")
    parser.add_argument("--output", type=Path, default=config.VISUAL_ELEMENTS_REFINED_REPORT_JSON, help="Path to write the refined report")
    parser.add_argument("--page-images", type=Path, default=config.PAGE_IMAGES_DIR, help="Directory with rendered page_NNN.png files (rendered on demand if missing)")
    parser.add_argument("--force", action="store_true", help="Recompute even if an up-to-date refined report already exists")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        report = run(args.input, args.output, args.page_images, args.force)
        logger.info(
            "Done. %d candidate(s) refined, %d uncertain (kept seed bbox), %d flagged likely_text_box, %d errors. Report: %s",
            report.get("refined_candidates", 0), report.get("refinement_uncertain_count", 0),
            report.get("likely_text_box_count", 0), report.get("refinement_errors", 0), args.output,
        )
    except Exception:
        logger.exception("Visual element refinement failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
