"""
Phase 5 - Figure candidate extraction (deterministic PNG crops).

Reads data/output/visual_elements_report.json (produced by
detect_visual_elements.py) and, for every element flagged
"type": "candidate", renders a cropped PNG of that region directly from
the source PDF -- with a small margin so labels/axes/legends aren't cut
off at the edge. "full_page_scan" entries are ignored entirely: they
are explicitly not figure candidates.

100% deterministic: PyMuPDF rendering only. No OCR, no Claude/LLM/any
API call, no semantic classification of what a candidate actually is.
This step's only job is to turn "here's a bbox" into "here's a PNG a
human can look at."

Coordinate note: candidate bboxes in the report are in PIXEL space at
config.RECONSTRUCTION_IMAGE_DPI (that's how detect_visual_elements.py
produced them, to match the already-rendered page_images/*.png 1:1).
The crop margin (config.FIGURE_CROP_MARGIN_PX) is applied in that SAME
pixel space -- it's converted to PDF points only internally, for the
actual PyMuPDF clip/render call.

Generic by design: the PDF path, page range, and candidates all come
from the report itself. Nothing about "chapter 1" or specific page
numbers is hardcoded here -- point --report at any compatible report
(a different chapter, a different book) and it works unchanged.

Usage:
    python extract_figure_candidates.py
    python extract_figure_candidates.py --report ../output/visual_elements_report.json
    python extract_figure_candidates.py --force
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

import config

logger = logging.getLogger("extract_figure_candidates")


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


def validate_bbox(bbox) -> bool:
    return (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) for v in bbox)
        and bbox[2] > bbox[0]
        and bbox[3] > bbox[1]
    )


def crop_rect_px(bbox_px: list, margin_px: float, page_width_px: float, page_height_px: float) -> list:
    """Expand a pixel-space bbox by margin_px (same pixel space) and
    clamp the result to the page's own pixel bounds."""
    x0, y0, x1, y1 = bbox_px
    return [
        max(0.0, x0 - margin_px),
        max(0.0, y0 - margin_px),
        min(page_width_px, x1 + margin_px),
        min(page_height_px, y1 + margin_px),
    ]


def render_crop(page: fitz.Page, crop_px: list, dpi: int) -> fitz.Pixmap:
    zoom = dpi / 72
    x0, y0, x1, y1 = crop_px
    clip_pt = fitz.Rect(x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom)
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip_pt, colorspace=fitz.csRGB, alpha=False)


def build_contact_sheet(index_entries: list, data_dir: Path, contact_sheet_path: Path) -> None:
    """Optional bonus: a single grid image of every generated crop, for
    quick human scanning. Best-effort -- never fails the whole run."""
    if not index_entries:
        return

    thumb_size = 260
    label_height = 20
    cell_size = thumb_size + label_height
    columns = max(1, int(len(index_entries) ** 0.5))
    rows = -(-len(index_entries) // columns)  # ceil division

    sheet = Image.new("RGB", (columns * cell_size, rows * cell_size), "white")
    draw = ImageDraw.Draw(sheet)

    for i, entry in enumerate(index_entries):
        image_path = data_dir / entry["image"]
        if not image_path.exists():
            continue
        try:
            with Image.open(image_path) as im:
                thumb = im.copy()
        except Exception:
            continue
        thumb.thumbnail((thumb_size, thumb_size))
        col, row = i % columns, i // columns
        x = col * cell_size + (thumb_size - thumb.width) // 2
        y = row * cell_size + (thumb_size - thumb.height) // 2
        sheet.paste(thumb, (x, y))
        draw.text((col * cell_size + 4, row * cell_size + thumb_size + 2), entry["id"], fill="black")

    contact_sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet_path)


def run(report_path: Path, output_dir: Path, index_path: Path, force: bool, make_contact_sheet: bool) -> dict:
    report = load_report(report_path)

    pdf_path = Path(report.get("source_pdf", ""))
    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF referenced by report not found: {pdf_path}")

    dpi = config.RECONSTRUCTION_IMAGE_DPI
    margin_px = config.FIGURE_CROP_MARGIN_PX
    zoom = dpi / 72
    data_dir = output_dir.parent  # .../data/output -- "image" paths in the index are relative to here

    candidates_found = 0
    crops_generated = 0
    crops_skipped_cache = 0
    errors = 0
    index_entries = []

    doc = fitz.open(pdf_path)
    try:
        total_pages_doc = doc.page_count

        for page_entry in report.get("pages", []):
            pdf_page_number = page_entry.get("pdf_page")
            candidates = [e for e in page_entry.get("visual_elements", []) if e.get("type") == "candidate"]
            if not candidates:
                continue

            if not isinstance(pdf_page_number, int) or not (1 <= pdf_page_number <= total_pages_doc):
                logger.error(
                    "Report entry has invalid/out-of-range pdf_page=%r, skipping its %d candidate(s)",
                    pdf_page_number, len(candidates),
                )
                errors += len(candidates)
                continue

            page = doc.load_page(pdf_page_number - 1)
            page_width_px = page.rect.width * zoom
            page_height_px = page.rect.height * zoom
            page_dir = output_dir / f"page_{pdf_page_number:03d}"

            for i, candidate in enumerate(candidates, start=1):
                candidates_found += 1
                candidate_id = f"page_{pdf_page_number:03d}_candidate_{i:02d}"
                bbox = candidate.get("bbox")

                if not validate_bbox(bbox):
                    logger.error("%s: invalid bbox %r, skipping", candidate_id, bbox)
                    errors += 1
                    continue

                crop_px = crop_rect_px(bbox, margin_px, page_width_px, page_height_px)
                if crop_px[2] <= crop_px[0] or crop_px[3] <= crop_px[1]:
                    logger.error(
                        "%s: bbox collapses to an empty region after clamping to the page, skipping", candidate_id
                    )
                    errors += 1
                    continue

                image_path = page_dir / f"{candidate_id}.png"
                relative_image_path = image_path.relative_to(data_dir).as_posix()

                if image_path.exists() and not force:
                    crops_skipped_cache += 1
                else:
                    try:
                        page_dir.mkdir(parents=True, exist_ok=True)
                        render_crop(page, crop_px, dpi).save(image_path)
                        crops_generated += 1
                    except Exception:
                        logger.exception("%s: failed to render/save crop, skipping", candidate_id)
                        errors += 1
                        continue

                index_entries.append({
                    "id": candidate_id,
                    "pdf_page": pdf_page_number,
                    "bbox": bbox,
                    "crop_bbox": [round(v) for v in crop_px],
                    "image": relative_image_path,
                    "area_ratio": candidate.get("area_ratio"),
                    "needs_review": candidate.get("needs_review"),
                    "detection_reason": candidate.get("detection_reason"),
                    "signals": candidate.get("signals"),
                })
    finally:
        doc.close()

    index = {
        "source_pdf": report.get("source_pdf"),
        "page_range": report.get("page_range"),
        "candidates": index_entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    if make_contact_sheet:
        try:
            build_contact_sheet(index_entries, data_dir, output_dir / "contact_sheet.png")
        except Exception:
            logger.exception("Contact sheet generation failed (non-fatal, crops/index are still valid)")

    return {
        "pages_scanned": report.get("total_pages"),
        "candidates_found": candidates_found,
        "crops_generated": crops_generated,
        "crops_skipped_cache": crops_skipped_cache,
        "errors": errors,
        "output_dir": output_dir,
        "index_path": index_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic figure-candidate PNG extraction (Phase 5)")
    parser.add_argument("--report", type=Path, default=config.VISUAL_ELEMENTS_REPORT_JSON, help="Path to visual_elements_report.json")
    parser.add_argument("--output", type=Path, default=config.FIGURE_CANDIDATES_DIR, help="Output directory for crop PNGs")
    parser.add_argument("--index", type=Path, default=config.FIGURE_CANDIDATES_INDEX_JSON, help="Path to write index.json")
    parser.add_argument("--force", action="store_true", help="Regenerate crops that already exist on disk")
    parser.add_argument("--no-contact-sheet", action="store_true", help="Skip generating the bonus contact_sheet.png")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        stats = run(args.report, args.output, args.index, args.force, not args.no_contact_sheet)
        print()
        print("Figure candidate extraction")
        print("-" * len("Figure candidate extraction"))
        print(f"PDF pages scanned : {stats['pages_scanned']}")
        print(f"Candidates found  : {stats['candidates_found']}")
        print(f"Crops generated   : {stats['crops_generated']}")
        print(f"Skipped           : {stats['crops_skipped_cache']}")
        print(f"Errors            : {stats['errors']}")
        print()
        print("Output:")
        print(stats["output_dir"])
        print(stats["index_path"])
    except Exception:
        logger.exception("Figure candidate extraction failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
