"""
Phase 2 - Mechanical text cleaning (no OCR correction, no LLM).

Reads every data/output/raw/page_*.txt and writes a whitespace-normalized
copy to data/output/cleaned/page_*.txt.

This stage ONLY touches whitespace, stray control characters, and
Unicode accent composition. It never substitutes, deletes, or "fixes"
a character -- in particular it never touches anything that could be
a letter, digit, or mathematical symbol, and it never removes a line
just because it looks like noise (e.g. a lone page-number footer).
Correcting OCR/math errors is the job of the later LLM reconstruction
stage, which also has access to the original page image and can make
informed judgment calls this script cannot safely make blind.

Usage:
    python clean_text.py
    python clean_text.py --input ../output/raw --output ../output/cleaned
"""

import argparse
import logging
import re
import sys
import unicodedata
from pathlib import Path

import config

logger = logging.getLogger("clean_text")

# 3+ blank lines -> 1 blank line
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Runs of horizontal whitespace (spaces/tabs) -> single space
_HORIZONTAL_WHITESPACE_RE = re.compile(r"[ \t]+")


def _is_droppable_control_char(ch: str) -> bool:
    """True for Unicode control characters (category Cc) other than
    newline/tab -- pure extraction artifacts (NUL, form-feed, ...),
    never visible content."""
    return unicodedata.category(ch) == "Cc" and ch not in ("\n", "\t")


def normalize_unicode(text: str) -> str:
    """Compose accented characters consistently (NFC). Never removes
    a diacritic or changes a character's identity."""
    return unicodedata.normalize("NFC", text)


def strip_control_characters(text: str) -> str:
    return "".join(ch for ch in text if not _is_droppable_control_char(ch))


def normalize_line(line: str) -> str:
    line = _HORIZONTAL_WHITESPACE_RE.sub(" ", line)
    return line.strip()


def collapse_blank_lines(text: str) -> str:
    return _EXCESS_BLANK_LINES_RE.sub("\n\n", text)


def clean_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    text = normalize_unicode(text)
    text = strip_control_characters(text)

    lines = [normalize_line(line) for line in text.split("\n")]
    text = "\n".join(lines)

    text = collapse_blank_lines(text)
    return text.strip("\n") + "\n"


def clean_file(input_path: Path, output_dir: Path) -> Path:
    raw_text = input_path.read_text(encoding="utf-8")
    cleaned = clean_text(raw_text)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / input_path.name
    output_path.write_text(cleaned, encoding="utf-8")
    return output_path


def run(input_dir: Path, output_dir: Path) -> None:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    input_files = sorted(input_dir.glob("page_*.txt"))
    if not input_files:
        logger.warning("No page_*.txt files found in %s", input_dir)
        return

    logger.info("Cleaning %d page(s) from %s -> %s", len(input_files), input_dir, output_dir)

    processed, failed = 0, []
    for input_path in input_files:
        try:
            output_path = clean_file(input_path, output_dir)
            logger.info("%s -> %s", input_path.name, output_path)
            processed += 1
        except Exception:
            logger.exception("Failed to clean %s, skipping", input_path.name)
            failed.append(input_path.name)

    logger.info("Done. %d/%d pages cleaned successfully.", processed, len(input_files))
    if failed:
        logger.warning("Failed files: %s", failed)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mechanical whitespace cleaning of raw OCR pages")
    parser.add_argument("--input", type=Path, default=config.OUTPUT_DIR, help="Directory containing raw page_*.txt files")
    parser.add_argument("--output", type=Path, default=config.CLEANED_DIR, help="Directory to write cleaned page_*.txt files")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        run(args.input, args.output)
    except Exception:
        logger.exception("Cleaning pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
