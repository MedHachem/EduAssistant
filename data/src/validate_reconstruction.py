"""
Phase 3b - Deterministic post-reconstruction validator.

Scans data/output/reconstructed/page_*.md and flags pages that likely
deserve human review, using only deterministic, low-false-positive
rules: tag balance, frontmatter consistency, QCM/choice formatting,
stray OCR artifacts, size sanity, and page-sequence gaps.

This script NEVER judges whether the reconstructed mathematical
content is correct -- it has no access to an LLM and makes no
semantic/visual judgment. It only surfaces mechanical signals; a human
still verifies flagged pages against `source_image`.

Usage:
    python validate_reconstruction.py
    python validate_reconstruction.py --input ../output/reconstructed
"""

import argparse
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger("validate_reconstruction")

ALLOWED_TAGS = {"bloc", "uncertain", "gap", "figure"}

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# Tag names must start with a letter, the tag must close on the same
# line, and nothing between the name and '>' may contain '$' -- keeps
# this from misfiring on compact math like "$a<b$, $f(a)>f(b)$" (a very
# common inequality pattern in this textbook), where a naive scan would
# otherwise treat "<b$, $f(a)>" as a tag named "b".
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)\b[^>$\n]*?/?>")

UNCERTAIN_OPEN_RE = re.compile(r"<uncertain\b[^>]*>", re.IGNORECASE)
UNCERTAIN_CLOSE_RE = re.compile(r"</uncertain>", re.IGNORECASE)
GAP_ANY_RE = re.compile(r"<gap\b", re.IGNORECASE)
GAP_SELF_CLOSED_RE = re.compile(r"<gap\b[^>]*?/>", re.IGNORECASE)
BLOC_OPEN_RE = re.compile(r"<bloc\b[^>]*>", re.IGNORECASE)
BLOC_CLOSE_RE = re.compile(r"</bloc>", re.IGNORECASE)
FIGURE_OPEN_RE = re.compile(r"<figure\b[^>]*>", re.IGNORECASE)
FIGURE_CLOSE_RE = re.compile(r"</figure>", re.IGNORECASE)

SQUARE_RE = re.compile(r"\\square")
DISPLAY_MATH_RE = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)
PAGE_FILENAME_RE = re.compile(r"page_(\d+)\.md$")

MIN_MEANINGFUL_CHARS = 20
SIZE_RATIO_LOW, SIZE_RATIO_HIGH = 0.3, 3.0


@dataclass
class PageResult:
    filename: str
    pdf_page: int | None
    issues: list = field(default_factory=list)

    @property
    def status(self) -> str:
        return "warning" if self.issues else "ok"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a reconstructed page into (frontmatter_dict, body).

    Our frontmatter is always flat key: value pairs written by
    reconstruct.py (never nested YAML), so a simple line parser is
    enough and avoids adding a PyYAML dependency for one file format
    we fully control ourselves.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    frontmatter = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        frontmatter[key.strip()] = value.strip()

    return frontmatter, text[match.end():]


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def check_tag_balance(body: str, issues: list) -> None:
    uncertain_open = len(UNCERTAIN_OPEN_RE.findall(body))
    uncertain_close = len(UNCERTAIN_CLOSE_RE.findall(body))
    if uncertain_open != uncertain_close:
        issues.append(
            f"Unclosed/mismatched <uncertain> tags (open={uncertain_open}, close={uncertain_close})"
        )

    bloc_open = len(BLOC_OPEN_RE.findall(body))
    bloc_close = len(BLOC_CLOSE_RE.findall(body))
    if bloc_open != bloc_close:
        issues.append(f"Unclosed/mismatched <bloc> tags (open={bloc_open}, close={bloc_close})")

    figure_open = len(FIGURE_OPEN_RE.findall(body))
    figure_close = len(FIGURE_CLOSE_RE.findall(body))
    if figure_open != figure_close:
        issues.append(f"Unclosed/mismatched <figure> tags (open={figure_open}, close={figure_close})")

    gap_any = len(GAP_ANY_RE.findall(body))
    gap_self_closed = len(GAP_SELF_CLOSED_RE.findall(body))
    if gap_any != gap_self_closed:
        issues.append("Malformed <gap> tag (not self-closed with '/>')")


def check_unexpected_tags(body: str, issues: list) -> None:
    found = {m.group(2).lower() for m in TAG_RE.finditer(body)}
    unexpected = sorted(found - ALLOWED_TAGS)
    if unexpected:
        issues.append(f"Unexpected tag(s) outside the allowed vocabulary: {', '.join(unexpected)}")


def check_ocr_artifacts(body: str, issues: list) -> None:
    prose = strip_tags(body)

    if '"' in prose:
        issues.append('Stray straight double-quote (") found -- possible unconverted OCR artifact')

    if any(unicodedata.category(ch) == "Cc" and ch not in ("\n", "\t") for ch in prose):
        issues.append("Non-printable control character found in reconstructed text")

    for line in prose.splitlines():
        stripped = line.lstrip()
        if "#" in stripped and not stripped.startswith("#"):
            issues.append("Stray '#' character found -- possible unconverted '≠' OCR artifact")
            break


def check_empty_content(body: str, issues: list) -> None:
    prose = strip_tags(body)
    meaningful = re.sub(r"[#>*\-\s]", "", prose)
    if len(meaningful) < MIN_MEANINGFUL_CHARS:
        issues.append(f"Reconstructed content is empty or nearly empty ({len(meaningful)} meaningful characters)")


def check_latex_balance(body: str, issues: list) -> None:
    # Check each display block's own captured content for true emptiness --
    # NOT a raw "$$\s*$$" scan, which would also match two separate,
    # non-empty $$...$$ blocks separated by a blank line.
    if any(m.group(1).strip() == "" for m in DISPLAY_MATH_RE.finditer(body)):
        issues.append("Empty display math expression detected ($$ $$)")

    remainder = DISPLAY_MATH_RE.sub("", body)

    dollar_count = remainder.count("$")
    if dollar_count % 2 != 0:
        issues.append("Unbalanced '$' delimiters (possible malformed inline math)")
    else:
        # Splitting on '$' alternates outside-math / inside-math segments,
        # starting with "outside" -- so odd indices are always the content
        # strictly between one pair of delimiters. This distinguishes a
        # truly empty "$ $" from "...$A$ $B$..." (two separate expressions
        # with only a space between them), which is NOT empty math.
        parts = remainder.split("$")
        if any(parts[i].strip() == "" for i in range(1, len(parts), 2)):
            issues.append("Empty inline math expression detected ($ $)")

    if body.count("{") != body.count("}"):
        issues.append("Unbalanced '{' / '}' (possible malformed LaTeX)")

    if body.count("\\left") != body.count("\\right"):
        issues.append("Unbalanced \\left / \\right")


def check_qcm_choices(body: str, issues: list) -> None:
    for line in body.splitlines():
        count = len(SQUARE_RE.findall(line))
        if count >= 2:
            issues.append(
                f"Multiple \\square choices found on a single line ({count}) -- "
                f"QCM/choice structure may need visual verification against the source image"
            )


def check_frontmatter(frontmatter: dict, body: str, filename: str, issues: list) -> None:
    if not frontmatter:
        issues.append("Missing or malformed YAML frontmatter block")

    uncertain_count = len(UNCERTAIN_OPEN_RE.findall(body))
    gap_count = len(GAP_ANY_RE.findall(body))

    declared_uncertain = frontmatter.get("uncertain_count")
    if declared_uncertain is not None and str(uncertain_count) != declared_uncertain:
        issues.append(
            f"Frontmatter uncertain_count ({declared_uncertain}) does not match "
            f"actual <uncertain> tags in body ({uncertain_count})"
        )

    declared_gap = frontmatter.get("gap_count")
    if declared_gap is not None and str(gap_count) != declared_gap:
        issues.append(
            f"Frontmatter gap_count ({declared_gap}) does not match "
            f"actual <gap> tags in body ({gap_count})"
        )

    declared_needs_review = frontmatter.get("needs_review")
    expected_needs_review = "true" if (uncertain_count + gap_count) > 0 else "false"
    if declared_needs_review is not None and declared_needs_review != expected_needs_review:
        issues.append(
            f"Frontmatter needs_review ({declared_needs_review}) does not match "
            f"actual uncertainty markers found ({expected_needs_review})"
        )

    match = PAGE_FILENAME_RE.search(filename)
    filename_page = int(match.group(1)) if match else None
    declared_page = frontmatter.get("pdf_page")
    if filename_page is not None and declared_page is not None and str(filename_page) != declared_page:
        issues.append(
            f"Frontmatter pdf_page ({declared_page}) does not match filename page number ({filename_page})"
        )

    source_image = frontmatter.get("source_image")
    if not source_image:
        issues.append("Missing 'source_image' in frontmatter")
    elif not Path(source_image).exists():
        issues.append(f"'source_image' path does not exist on disk: {source_image}")

    cleaned_source = frontmatter.get("cleaned_source")
    if not cleaned_source:
        issues.append("Missing 'cleaned_source' in frontmatter")
    elif not Path(cleaned_source).exists():
        issues.append(f"'cleaned_source' path does not exist on disk: {cleaned_source}")


def check_size_ratio(body: str, cleaned_source: str | None, issues: list) -> None:
    if not cleaned_source:
        return
    cleaned_path = Path(cleaned_source)
    if not cleaned_path.exists():
        return  # already flagged by check_frontmatter

    cleaned_len = len(cleaned_path.read_text(encoding="utf-8").strip())
    if cleaned_len < 5:
        return  # too small to compute a meaningful ratio

    reconstructed_len = len(strip_tags(body).strip())
    ratio = reconstructed_len / cleaned_len

    if ratio < SIZE_RATIO_LOW or ratio > SIZE_RATIO_HIGH:
        issues.append(
            f"Reconstructed content size is suspiciously different from the cleaned "
            f"source (ratio={ratio:.2f}, cleaned={cleaned_len} chars, "
            f"reconstructed={reconstructed_len} chars)"
        )


def validate_page(path: Path) -> PageResult:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)

    match = PAGE_FILENAME_RE.search(path.name)
    pdf_page = int(match.group(1)) if match else None

    result = PageResult(filename=path.name, pdf_page=pdf_page)

    check_tag_balance(body, result.issues)
    check_unexpected_tags(body, result.issues)
    check_ocr_artifacts(body, result.issues)
    check_empty_content(body, result.issues)
    check_latex_balance(body, result.issues)
    check_qcm_choices(body, result.issues)
    check_frontmatter(frontmatter, body, path.name, result.issues)
    check_size_ratio(body, frontmatter.get("cleaned_source"), result.issues)

    return result


def check_global_issues(results: list) -> list:
    issues = []
    page_to_files: dict = {}
    for r in results:
        if r.pdf_page is not None:
            page_to_files.setdefault(r.pdf_page, []).append(r.filename)

    for page, files in sorted(page_to_files.items()):
        if len(files) > 1:
            issues.append(f"Multiple files declare pdf_page {page}: {', '.join(files)}")

    if page_to_files:
        known_pages = sorted(page_to_files)
        expected = range(known_pages[0], known_pages[-1] + 1)
        missing = [p for p in expected if p not in page_to_files]
        if missing:
            issues.append(f"Missing page(s) in sequence: {missing}")

    return issues


def build_report(reconstructed_dir: Path) -> dict:
    paths = sorted(reconstructed_dir.glob("page_*.md"))
    results = [validate_page(p) for p in paths]
    global_issues = check_global_issues(results)

    pages_ok = sum(1 for r in results if r.status == "ok")
    pages_flagged = sum(1 for r in results if r.status == "warning")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reconstructed_dir": str(reconstructed_dir),
        "total_pages": len(results),
        "pages_ok": pages_ok,
        "pages_flagged": pages_flagged,
        "global_issues": global_issues,
        "pages": [
            {"file": r.filename, "pdf_page": r.pdf_page, "status": r.status, "issues": r.issues}
            for r in results
        ],
    }


def render_text_report(report: dict) -> str:
    lines = [
        "RECONSTRUCTION VALIDATION",
        "=" * len("RECONSTRUCTION VALIDATION"),
        "",
        f"Total pages: {report['total_pages']}",
        f"Pages OK: {report['pages_ok']}",
        f"Pages requiring review: {report['pages_flagged']}",
        "",
    ]

    if report["global_issues"]:
        lines.append("GLOBAL ISSUES")
        for issue in report["global_issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    for page in report["pages"]:
        if page["status"] != "warning":
            continue
        lines.append(f"WARNING {page['file']}")
        for issue in page["issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(reconstructed_dir: Path, json_out: Path, text_out: Path) -> dict:
    if not reconstructed_dir.exists():
        raise FileNotFoundError(f"Reconstructed directory not found: {reconstructed_dir}")

    report = build_report(reconstructed_dir)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    text_out.parent.mkdir(parents=True, exist_ok=True)
    text_out.write_text(render_text_report(report), encoding="utf-8")

    return report


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic post-reconstruction validator (Phase 3b)")
    parser.add_argument("--input", type=Path, default=config.RECONSTRUCTED_DIR, help="Directory with reconstructed page_*.md files")
    parser.add_argument("--json-out", type=Path, default=config.RECONSTRUCTION_REPORT_JSON, help="Path to write the JSON report")
    parser.add_argument("--text-out", type=Path, default=config.RECONSTRUCTION_REPORT_TXT, help="Path to write the human-readable text report")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        report = run(args.input, args.json_out, args.text_out)
        logger.info(
            "Validated %d pages: %d OK, %d flagged for review.",
            report["total_pages"], report["pages_ok"], report["pages_flagged"],
        )
        logger.info("Reports written to %s and %s", args.json_out, args.text_out)
    except Exception:
        logger.exception("Validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
