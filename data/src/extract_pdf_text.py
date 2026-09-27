"""
Phase 1 - Knowledge ingestion: PDF -> OCR -> raw text files.

For each PDF page in the configured range:
  1. Try native PDF text extraction (PyMuPDF).
  2. If the page has no usable text (typical for a scanned/image page),
     render it to an image and run Tesseract OCR (French).
  3. Save the raw result as-is, one .txt file per page, named after the
     ORIGINAL PDF page number.

This script deliberately does NOT: call an LLM, produce JSON, identify
theorems/definitions/exercises, or otherwise interpret or "clean up"
the text. If OCR output looks wrong or uncertain, it is saved exactly
as produced -- later phases are responsible for cleaning/structuring.

Usage:
    python extract_pdf_text.py
    python extract_pdf_text.py --start 5 --end 27
    python extract_pdf_text.py --pdf ../other/source.pdf --output ../output/raw
"""

import argparse
import logging
import sys
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract

from PIL import Image
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
import config
from pdf_render import render_page_to_image

logger = logging.getLogger("pdf_ocr")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def extract_native_text(page: fitz.Page) -> str:
    """Pull embedded text straight out of the PDF page, if any."""
    return page.get_text("text") or ""


def ocr_image(image: Image.Image, language: str) -> str:
    """Run Tesseract OCR on an image and return the raw text, untouched."""
    return pytesseract.image_to_string(image, lang=language)


def process_page(page: fitz.Page, pdf_page_number: int) -> str:
    """Return raw text for one page: native extraction first, OCR fallback.

    `pdf_page_number` is 1-indexed (matches what a PDF viewer shows).
    """
    native_text = extract_native_text(page)

    if len(native_text.strip()) >= config.MIN_NATIVE_TEXT_CHARS:
        logger.info(
            "Page %d: native PDF text found (%d chars), OCR not needed",
            pdf_page_number, len(native_text.strip()),
        )
        return native_text

    logger.info("Page %d: no usable native text, falling back to OCR", pdf_page_number)
    image = render_page_to_image(page, config.OCR_DPI)
    return ocr_image(image, config.OCR_LANGUAGE)


def save_raw_text(output_dir: Path, pdf_page_number: int, text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"page_{pdf_page_number:03d}.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def run(pdf_path: Path, output_dir: Path, start_page: int, end_page: int) -> None:
    if config.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        logger.info("Opened %s (%d pages total)", pdf_path, total_pages)

        if start_page < 1 or end_page > total_pages or start_page > end_page:
            raise ValueError(
                f"Invalid page range {start_page}-{end_page} for a {total_pages}-page PDF"
            )

        processed, failed = 0, []
        for pdf_page_number in range(start_page, end_page + 1):
            try:
                page = doc.load_page(pdf_page_number - 1)  # fitz pages are 0-indexed
                text = process_page(page, pdf_page_number)
                out_path = save_raw_text(output_dir, pdf_page_number, text)
                logger.info("Page %d: saved -> %s", pdf_page_number, out_path)
                processed += 1
            except Exception:
                logger.exception("Page %d: failed to process, skipping", pdf_page_number)
                failed.append(pdf_page_number)

        total_requested = end_page - start_page + 1
        logger.info("Done. %d/%d pages processed successfully.", processed, total_requested)
        if failed:
            logger.warning("Failed pages (see errors above): %s", failed)
    finally:
        doc.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF -> OCR -> raw text (Phase 1)")
    parser.add_argument("--pdf", type=Path, default=config.PDF_PATH, help="Path to the source PDF")
    parser.add_argument("--output", type=Path, default=config.OUTPUT_DIR, help="Output directory for raw .txt files")
    parser.add_argument("--start", type=int, default=config.START_PAGE, help="First PDF page to process (1-indexed)")
    parser.add_argument("--end", type=int, default=config.END_PAGE, help="Last PDF page to process (1-indexed, inclusive)")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        run(args.pdf, args.output, args.start, args.end)
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
