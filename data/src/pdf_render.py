"""Shared PDF -> image rendering (PyMuPDF).

Used by both the OCR extraction stage (renders in-memory for Tesseract)
and the LLM reconstruction stage (renders to a cached PNG file sent to
Claude, and reused for side-by-side human review).
"""

from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


def render_page_to_image(page: fitz.Page, dpi: int) -> Image.Image:
    """Rasterize a PDF page to a PIL image."""
    zoom = dpi / 72  # PDF's default resolution is 72 dpi
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def render_page_to_png(pdf_path: Path, pdf_page_number: int, dpi: int, output_dir: Path) -> Path:
    """Render one PDF page (1-indexed) to a cached PNG file.

    Skips rendering if the file already exists, so the same image is
    reused across repeated/retried reconstruction calls and can be
    opened directly by a human reviewer.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"page_{pdf_page_number:03d}.png"
    if out_path.exists():
        return out_path

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(pdf_page_number - 1)  # fitz pages are 0-indexed
        image = render_page_to_image(page, dpi)
        image.save(out_path)
    finally:
        doc.close()

    return out_path
