"""
Phase 3c - Claude-based visual/semantic validation (Layer 2).

Layer 1 (validate_reconstruction.py) is purely mechanical -- it cannot
tell whether reconstructed mathematical content actually matches what's
written/drawn on the source page (e.g. a well-formed LaTeX fraction
that simply transcribes the wrong sign). This stage asks Claude Code to
compare, for one page at a time:
  1. The original page image (visual source of truth).
  2. The cleaned OCR text (secondary textual reference).
  3. The reconstructed Markdown (the candidate being checked).

Claude judges FIDELITY to the source page -- never mathematical
correctness, and it never solves or corrects anything. See
prompts.VALIDATION_SYSTEM_PROMPT for the exact instructions/schema.

This is a real Claude Code call per page (billed against your plan's
usage), so by default it does NOT process every page. Selection is
explicit:
    --pages 6 7 23      validate exactly these pages
    --start 5 --end 10  validate a page range
    --all               validate every page found in the reconstructed dir
    (no selection flag)  validate whatever Layer 1 flagged as needing
                          review in the existing reconstruction_report.json

Regardless of what was just processed, a combined Layer 1 + Layer 2
"final quality report" is (re)written on every run, covering every page
found in the reconstructed directory (pages with no Layer 2 result yet
are marked "not_validated").

Usage:
    python validate_with_claude.py --pages 6 7 23
    python validate_with_claude.py --all --force
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from claude_code_client import call_claude_code, check_claude_cli, strip_code_fence
from pdf_render import render_page_to_png
from prompts import VALIDATION_RESULT_SCHEMA, VALIDATION_SYSTEM_PROMPT, build_validation_user_content
from validate_reconstruction import PAGE_FILENAME_RE, parse_frontmatter

logger = logging.getLogger("validate_with_claude")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def reconstructed_page_path(reconstructed_dir: Path, pdf_page_number: int) -> Path:
    return reconstructed_dir / f"page_{pdf_page_number:03d}.md"


def cleaned_text_path(cleaned_dir: Path, pdf_page_number: int) -> Path:
    return cleaned_dir / f"page_{pdf_page_number:03d}.txt"


def validation_result_path(validation_dir: Path, pdf_page_number: int) -> Path:
    return validation_dir / f"page_{pdf_page_number:03d}.json"


def discover_all_pages(reconstructed_dir: Path) -> list:
    pages = []
    for path in sorted(reconstructed_dir.glob("page_*.md")):
        match = PAGE_FILENAME_RE.search(path.name)
        if match:
            pages.append(int(match.group(1)))
    return pages


def load_pages_needing_review(layer1_report_path: Path) -> list:
    if not layer1_report_path.exists():
        raise FileNotFoundError(
            f"No deterministic validation report found at {layer1_report_path}. "
            f"Run validate_reconstruction.py first, or pass --pages / --start+--end / --all explicitly."
        )
    report = json.loads(layer1_report_path.read_text(encoding="utf-8"))
    return sorted(
        p["pdf_page"] for p in report["pages"]
        if p["status"] != "ok" and p["pdf_page"] is not None
    )


def validate_page_with_claude(
    pdf_path: Path,
    reconstructed_dir: Path,
    cleaned_dir: Path,
    page_images_dir: Path,
    pdf_page_number: int,
) -> dict:
    """Ask Claude to compare one page's reconstructed Markdown against
    its source image + cleaned text. Returns the parsed result dict."""
    md_path = reconstructed_page_path(reconstructed_dir, pdf_page_number)
    if not md_path.exists():
        raise FileNotFoundError(f"No reconstructed page found: {md_path}")

    txt_path = cleaned_text_path(cleaned_dir, pdf_page_number)
    if not txt_path.exists():
        raise FileNotFoundError(f"No cleaned text found: {txt_path}")

    _frontmatter, reconstructed_body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    cleaned_text = txt_path.read_text(encoding="utf-8")

    image_path = render_page_to_png(
        pdf_path, pdf_page_number, config.RECONSTRUCTION_IMAGE_DPI, page_images_dir
    )
    image_bytes = image_path.read_bytes()

    user_content = build_validation_user_content(
        pdf_page_number, cleaned_text, reconstructed_body, image_bytes
    )

    result_text = call_claude_code(
        VALIDATION_SYSTEM_PROMPT,
        user_content,
        config.CLAUDE_MODEL,
        config.RECONSTRUCTION_TIMEOUT_SECONDS,
        json_schema=VALIDATION_RESULT_SCHEMA,
    )
    result_text = strip_code_fence(result_text)
    result = json.loads(result_text)

    if result.get("pdf_page") != pdf_page_number:
        logger.warning(
            "Page %d: Claude's response declared pdf_page=%s, overriding with the requested page number",
            pdf_page_number, result.get("pdf_page"),
        )
        result["pdf_page"] = pdf_page_number

    return result


def run(
    pdf_path: Path,
    reconstructed_dir: Path,
    cleaned_dir: Path,
    page_images_dir: Path,
    validation_dir: Path,
    pages: list,
    force: bool,
) -> None:
    if not reconstructed_dir.exists():
        raise FileNotFoundError(f"Reconstructed directory not found: {reconstructed_dir}")

    check_claude_cli()

    processed, skipped, failed = 0, [], []
    for pdf_page_number in pages:
        out_path = validation_result_path(validation_dir, pdf_page_number)
        if out_path.exists() and not force:
            logger.info("Page %d: already validated, skipping (use --force to redo)", pdf_page_number)
            skipped.append(pdf_page_number)
            continue

        try:
            result = validate_page_with_claude(
                pdf_path, reconstructed_dir, cleaned_dir, page_images_dir, pdf_page_number
            )
            validation_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(
                "Page %d: status=%s confidence=%s issues=%d -> %s",
                pdf_page_number, result.get("status"), result.get("confidence"),
                len(result.get("issues", [])), out_path,
            )
            processed += 1
        except Exception:
            logger.exception("Page %d: Claude validation failed, skipping", pdf_page_number)
            failed.append(pdf_page_number)

    logger.info(
        "Done. %d validated, %d skipped (already done), %d failed, out of %d requested.",
        processed, len(skipped), len(failed), len(pages),
    )
    if failed:
        logger.warning("Failed pages: %s", failed)


def build_final_report(reconstructed_dir: Path, validation_dir: Path, layer1_report_path: Path) -> dict:
    layer1_by_page = {}
    if layer1_report_path.exists():
        layer1_report = json.loads(layer1_report_path.read_text(encoding="utf-8"))
        for p in layer1_report["pages"]:
            if p["pdf_page"] is not None:
                layer1_by_page[p["pdf_page"]] = {"status": p["status"], "issues": p["issues"]}

    pages = []
    for pdf_page_number in discover_all_pages(reconstructed_dir):
        layer1 = layer1_by_page.get(pdf_page_number, {"status": "not_run", "issues": []})

        layer2_path = validation_result_path(validation_dir, pdf_page_number)
        if layer2_path.exists():
            layer2 = json.loads(layer2_path.read_text(encoding="utf-8"))
        else:
            layer2 = {"status": "not_validated", "confidence": None, "issues": []}

        pages.append({"pdf_page": pdf_page_number, "layer1": layer1, "layer2": layer2})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(pages),
        "pages": pages,
    }


def render_final_text_report(report: dict) -> str:
    lines = ["FINAL QUALITY REPORT", "=" * len("FINAL QUALITY REPORT"), "", f"Total pages: {report['total_pages']}", ""]

    for p in report["pages"]:
        l1_status = p["layer1"]["status"]
        l2_status = p["layer2"]["status"]
        confidence = p["layer2"].get("confidence")
        conf_str = f" confidence={confidence}" if confidence is not None else ""
        lines.append(f"page_{p['pdf_page']:03d} -- layer1={l1_status}, layer2={l2_status}{conf_str}")

        for issue in p["layer1"]["issues"]:
            lines.append(f"  [layer1] {issue}")
        for issue in p["layer2"]["issues"]:
            if isinstance(issue, dict):
                lines.append(f"  [layer2:{issue.get('severity', '?')}] {issue.get('description', issue)}")
            else:
                lines.append(f"  [layer2] {issue}")

    return "\n".join(lines).rstrip() + "\n"


def resolve_pages(args: argparse.Namespace) -> list:
    if args.pages:
        return sorted(set(args.pages))
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            raise ValueError("--start and --end must be given together")
        return list(range(args.start, args.end + 1))
    if args.all:
        return discover_all_pages(args.reconstructed)
    return load_pages_needing_review(args.layer1_report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claude-based visual/semantic validation (Phase 3c)")
    parser.add_argument("--pdf", type=Path, default=config.PDF_PATH)
    parser.add_argument("--reconstructed", type=Path, default=config.RECONSTRUCTED_DIR)
    parser.add_argument("--cleaned", type=Path, default=config.CLEANED_DIR)
    parser.add_argument("--images", type=Path, default=config.PAGE_IMAGES_DIR)
    parser.add_argument("--validation-dir", type=Path, default=config.VALIDATION_DIR)
    parser.add_argument("--layer1-report", type=Path, default=config.RECONSTRUCTION_REPORT_JSON)
    parser.add_argument("--final-json", type=Path, default=config.FINAL_QUALITY_REPORT_JSON)
    parser.add_argument("--final-text", type=Path, default=config.FINAL_QUALITY_REPORT_TXT)
    parser.add_argument("--pages", type=int, nargs="+", help="Explicit list of PDF page numbers to validate")
    parser.add_argument("--start", type=int, help="First PDF page of a range to validate")
    parser.add_argument("--end", type=int, help="Last PDF page of a range to validate (inclusive)")
    parser.add_argument("--all", action="store_true", help="Validate every page found in the reconstructed directory")
    parser.add_argument("--force", action="store_true", help="Re-validate pages that already have a result")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        pages = resolve_pages(args)
        if not pages:
            logger.info("No pages selected (Layer 1 flagged nothing, or none matched). Nothing to validate.")
        else:
            logger.info("Selected %d page(s) for Claude visual validation: %s", len(pages), pages)
            run(args.pdf, args.reconstructed, args.cleaned, args.images, args.validation_dir, pages, args.force)

        final_report = build_final_report(args.reconstructed, args.validation_dir, args.layer1_report)
        args.final_json.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
        args.final_text.write_text(render_final_text_report(final_report), encoding="utf-8")
        logger.info("Final quality report written to %s and %s", args.final_json, args.final_text)
    except Exception:
        logger.exception("Claude validation pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
