"""
Phase 3 - Intelligent reconstruction with Claude.

For each page in the configured range:
  1. Load the mechanically-cleaned text (Phase 2 output).
  2. Load/render the original PDF page as a cached PNG image.
  3. Load neighboring pages' cleaned text as read-only context (helps
     Claude recognize content spanning a page break).
  4. Ask Claude to reconstruct the page -- correcting OCR errors,
     converting math to LaTeX, preserving structure, and flagging
     uncertainty -- using the image as the visual source of truth
     whenever the OCR text is ambiguous.
  5. Wrap the result in a small YAML frontmatter (page number, source
     image, computed uncertainty counts) and save one Markdown file
     per page.

This stage calls Claude through the locally authenticated Claude Code
CLI (`claude -p`, subscription auth -- no ANTHROPIC_API_KEY involved).
Pages that already have output are skipped unless --force is passed,
so a run can be resumed without redoing already-reconstructed pages
(useful since usage is rate-limited, see README).

Usage:
    python reconstruct.py
    python reconstruct.py --start 5 --end 6 --force
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import config
from claude_code_client import call_claude_code, check_claude_cli, strip_code_fence
from pdf_render import render_page_to_png
from prompts import SYSTEM_PROMPT, build_user_content

logger = logging.getLogger("reconstruct")

UNCERTAIN_TAG_RE = re.compile(r"<uncertain\b", re.IGNORECASE)
GAP_TAG_RE = re.compile(r"<gap\b", re.IGNORECASE)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def cleaned_text_path(cleaned_dir: Path, pdf_page_number: int) -> Path:
    return cleaned_dir / f"page_{pdf_page_number:03d}.txt"


def read_cleaned_text(cleaned_dir: Path, pdf_page_number: int) -> str | None:
    path = cleaned_text_path(cleaned_dir, pdf_page_number)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def reconstruct_page(
    pdf_path: Path,
    cleaned_dir: Path,
    page_images_dir: Path,
    pdf_page_number: int,
) -> tuple[str, Path]:
    """Call Claude Code for one page. Returns (reconstructed_body, source_image_path)."""
    cleaned_text = read_cleaned_text(cleaned_dir, pdf_page_number)
    if cleaned_text is None:
        raise FileNotFoundError(
            f"No cleaned text found for page {pdf_page_number} "
            f"(run clean_text.py first)"
        )

    previous_context = read_cleaned_text(cleaned_dir, pdf_page_number - config.CONTEXT_WINDOW_PAGES)
    next_context = read_cleaned_text(cleaned_dir, pdf_page_number + config.CONTEXT_WINDOW_PAGES)

    image_path = render_page_to_png(
        pdf_path, pdf_page_number, config.RECONSTRUCTION_IMAGE_DPI, page_images_dir
    )
    image_bytes = image_path.read_bytes()

    user_content = build_user_content(
        pdf_page_number, cleaned_text, previous_context, next_context, image_bytes
    )

    body = call_claude_code(
        SYSTEM_PROMPT, user_content, config.CLAUDE_MODEL, config.RECONSTRUCTION_TIMEOUT_SECONDS
    )
    body = strip_code_fence(body)
    return body, image_path


def build_frontmatter(pdf_page_number: int, image_path: Path, cleaned_path: Path, body: str) -> str:
    uncertain_count = len(UNCERTAIN_TAG_RE.findall(body))
    gap_count = len(GAP_TAG_RE.findall(body))
    needs_review = (uncertain_count + gap_count) > 0

    lines = [
        "---",
        f"pdf_page: {pdf_page_number}",
        f"source_image: {image_path.as_posix()}",
        f"cleaned_source: {cleaned_path.as_posix()}",
        f"needs_review: {str(needs_review).lower()}",
        f"uncertain_count: {uncertain_count}",
        f"gap_count: {gap_count}",
        "---",
        "",
    ]
    return "\n".join(lines)


def save_reconstructed_page(output_dir: Path, pdf_page_number: int, frontmatter: str, body: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"page_{pdf_page_number:03d}.md"
    out_path.write_text(f"{frontmatter}{body}\n", encoding="utf-8")
    return out_path


def run(
    pdf_path: Path,
    cleaned_dir: Path,
    output_dir: Path,
    page_images_dir: Path,
    start_page: int,
    end_page: int,
    force: bool,
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")
    if not cleaned_dir.exists():
        raise FileNotFoundError(
            f"Cleaned text directory not found: {cleaned_dir} (run clean_text.py first)"
        )

    check_claude_cli()

    processed, skipped, failed = 0, [], []
    for pdf_page_number in range(start_page, end_page + 1):
        out_path = output_dir / f"page_{pdf_page_number:03d}.md"
        if out_path.exists() and not force:
            logger.info("Page %d: already reconstructed, skipping (use --force to redo)", pdf_page_number)
            skipped.append(pdf_page_number)
            continue

        try:
            body, image_path = reconstruct_page(
                pdf_path, cleaned_dir, page_images_dir, pdf_page_number
            )
            cleaned_path = cleaned_text_path(cleaned_dir, pdf_page_number)
            frontmatter = build_frontmatter(pdf_page_number, image_path, cleaned_path, body)
            saved_path = save_reconstructed_page(output_dir, pdf_page_number, frontmatter, body)
            logger.info("Page %d: saved -> %s", pdf_page_number, saved_path)
            processed += 1
        except Exception:
            logger.exception("Page %d: failed to reconstruct, skipping", pdf_page_number)
            failed.append(pdf_page_number)

    total_requested = end_page - start_page + 1
    logger.info(
        "Done. %d reconstructed, %d skipped (already done), %d failed, out of %d requested.",
        processed, len(skipped), len(failed), total_requested,
    )
    if failed:
        logger.warning("Failed pages: %s", failed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claude-based page reconstruction (Phase 3)")
    parser.add_argument("--pdf", type=Path, default=config.PDF_PATH, help="Path to the source PDF")
    parser.add_argument("--cleaned", type=Path, default=config.CLEANED_DIR, help="Directory with cleaned page_*.txt files")
    parser.add_argument("--output", type=Path, default=config.RECONSTRUCTED_DIR, help="Output directory for reconstructed page_*.md files")
    parser.add_argument("--images", type=Path, default=config.PAGE_IMAGES_DIR, help="Directory for cached page_*.png images")
    parser.add_argument("--start", type=int, default=config.START_PAGE, help="First PDF page to process (1-indexed)")
    parser.add_argument("--end", type=int, default=config.END_PAGE, help="Last PDF page to process (1-indexed, inclusive)")
    parser.add_argument("--force", action="store_true", help="Reprocess pages that already have reconstructed output")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        run(args.pdf, args.cleaned, args.output, args.images, args.start, args.end, args.force)
    except Exception:
        logger.exception("Reconstruction pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
