"""
Phase 4 - Deterministic visual-element candidate detection.

Scans PDF pages and flags CANDIDATE regions that might be mathematical
visual elements (graphs, geometry figures, diagrams, charts, tables,
illustrations) -- combining three independent, purely deterministic
signals:
  1. Embedded raster images (page.get_images() / get_image_rects()).
  2. Vector drawings (page.get_drawings()) -- axes, lines, circles,
     polygons, curves, geometric constructions: content that never
     appears in get_images() at all.
  3. PyMuPDF's own structural table detector (page.find_tables()).

No rendering, no pixel/CV analysis, no Claude/LLM call. This is
candidate detection only -- it never attempts to semantically classify
a region as "a graph" vs. "a triangle" vs. "an illustration"; every
candidate is marked needs_review=True by design.

Default scope is the currently-configured chapter (config.START_PAGE /
config.END_PAGE), not the whole document -- override with --start/--end
for a different range (e.g. a future chapter) when needed. The
detection algorithm itself never hardcodes a page number.

Key empirical finding driving this design (verified against the actual
source PDF before writing this): it has NO vector graphics layer at all
on the currently configured chapter, and every page is composed of many
small raster image tiles rather than one clean "this is the figure"
object -- true of colored theorem/reminder callout boxes, running
headers/footers, AND actual graphs alike. So:
  - Any embedded-image xref recurring across 2+ pages ANYWHERE in the
    whole document is page furniture (checked globally, independent of
    the requested range, for the strongest signal) -- excluded.
  - Fragments (image/drawing/table bboxes) are only merged with pieces
    they actually overlap/touch (zero gap tolerance): any positive
    proximity tolerance chains unrelated same-page content (a callout
    box, a border, a real figure) into one meaningless page-spanning
    blob, since this layout keeps them all fairly close together.
  - A single fragment, or a merged cluster, covering a large fraction
    of the page is reported separately as "full_page_scan" (not a
    figure candidate), rather than silently dropped.
  - A merged cluster far too small to plausibly be a meaningful figure
    (obvious icon/border noise) is conservatively dropped; anything
    above that floor is kept as needs_review=True rather than guessed
    at, per design.

Usage:
    python detect_visual_elements.py                  # current chapter (config.START_PAGE..END_PAGE)
    python detect_visual_elements.py --start 28 --end 40   # a different chapter
    python detect_visual_elements.py --force
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

import config

logger = logging.getLogger("detect_visual_elements")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def find_recurring_xrefs(doc: fitz.Document) -> set:
    """Any embedded-image xref appearing on more than one page across the
    WHOLE document is page furniture (running header/footer, logo,
    border) -- never a candidate, regardless of its size or shape.

    (Vector drawings have no comparable shared-object identity in this
    PDF format -- each is defined inline per page -- so this recurrence
    check is image-specific; see the module docstring / limitations.)
    """
    xref_pages = {}
    for page_number in range(1, doc.page_count + 1):
        page = doc.load_page(page_number - 1)
        for img in page.get_images(full=True):
            xref_pages.setdefault(img[0], set()).add(page_number)
    return {xref for xref, pages in xref_pages.items() if len(pages) > 1}


def collect_fragments(page: fitz.Page, recurring_xrefs: set) -> tuple:
    """Gather every raw candidate fragment on a page, tagged by which
    evidence source produced it. Returns (fragments, background_fragments):
    fragments too big on their OWN (>= background area ratio) are
    bucketed separately so they never enter clustering -- otherwise a
    single near-full-page fragment would touch/overlap almost everything
    else on the page and swallow it into one meaningless cluster.
    """
    page_area = page.rect.width * page.rect.height
    fragments, background_fragments = [], []

    def add(bbox: list, source: str) -> None:
        area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / page_area
        target = background_fragments if area_ratio >= config.VISUAL_ELEMENT_BACKGROUND_AREA_RATIO else fragments
        target.append({"bbox": bbox, "source": source})

    # 1. Embedded raster images. Two independent, deliberately narrow
    # exclusions -- see config.py for the measurements behind both:
    #   a. Hairline slivers (< VISUAL_ELEMENT_MIN_FRAGMENT_PT in either
    #      dimension) -- the finest border/rule grid step, unambiguous
    #      noise in any shape.
    #   b. Long thin bars -- thin in one dimension AND running a large
    #      fraction of the page's width/height -- are decorative rule/
    #      border lines, not figure fragments, regardless of how thin
    #      they are. A small-but-BOUNDED thin fragment (a real axis/tick
    #      piece) is kept either way.
    for img in page.get_images(full=True):
        xref = img[0]
        if xref in recurring_xrefs:
            continue
        for rect in page.get_image_rects(xref):
            if (
                rect.width < config.VISUAL_ELEMENT_MIN_FRAGMENT_PT
                or rect.height < config.VISUAL_ELEMENT_MIN_FRAGMENT_PT
            ):
                continue
            short_side, long_side = sorted([rect.width, rect.height])
            is_long_side_horizontal = rect.width >= rect.height
            page_dimension = page.rect.width if is_long_side_horizontal else page.rect.height
            if (
                short_side < config.VISUAL_ELEMENT_MIN_FRAGMENT_PT * 3
                and long_side > config.VISUAL_ELEMENT_MAX_RULE_LENGTH_RATIO * page_dimension
            ):
                continue  # long thin bar: decorative rule/border, not a figure fragment
            add([rect.x0, rect.y0, rect.x1, rect.y1], "image")

    # 2. Vector drawings (axes, lines, circles, polygons, curves...).
    # No minimum-size filter here: a single path segment (e.g. one tick
    # mark or one side of a triangle) can be legitimately tiny and only
    # becomes meaningful once clustered with the rest of the figure.
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width <= 0 or rect.height <= 0:
            continue
        add([rect.x0, rect.y0, rect.x1, rect.y1], "drawing")

    # 3. PyMuPDF's own structural table detector. Purely a bonus check:
    # gracefully degrades to nothing if the installed PyMuPDF version
    # doesn't support it, or it errors on a given page.
    try:
        for table in page.find_tables().tables:
            add(list(table.bbox), "table")
    except Exception:
        logger.debug("find_tables() unavailable/failed on this page, skipping")

    return fragments, background_fragments


def cluster_fragments(fragments: list, gap: float) -> list:
    """Merge fragment bboxes that overlap/touch (within `gap` points,
    0 = must actually overlap or share an edge) into unified candidate
    regions, tracking which evidence source(s) contributed to each."""
    clusters = [{"bbox": list(f["bbox"]), "sources": {f["source"]}, "count": 1} for f in fragments]

    def touching(a, b):
        return not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1])

    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            if clusters[i] is None:
                continue
            for j in range(i + 1, len(clusters)):
                if clusters[j] is None:
                    continue
                a, b = clusters[i]["bbox"], clusters[j]["bbox"]
                if touching(a, b):
                    clusters[i] = {
                        "bbox": [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])],
                        "sources": clusters[i]["sources"] | clusters[j]["sources"],
                        "count": clusters[i]["count"] + clusters[j]["count"],
                    }
                    clusters[j] = None
                    merged = True
        clusters = [c for c in clusters if c is not None]

    return clusters


def _signals(sources: set) -> dict:
    return {
        "embedded_images": "image" in sources,
        "vector_drawings": "drawing" in sources,
        "table": "table" in sources,
    }


def _source_description(sources: set, count: int) -> str:
    parts = []
    if "image" in sources:
        parts.append("embedded image fragment(s)")
    if "drawing" in sources:
        parts.append("vector drawing path(s)")
    if "table" in sources:
        parts.append("table structure")
    return f"{count} {' + '.join(parts)}"


def build_full_page_scan(cluster: dict, page_area: float, dpi: int) -> dict:
    x0, y0, x1, y1 = cluster["bbox"]
    area_ratio = ((x1 - x0) * (y1 - y0)) / page_area
    zoom = dpi / 72
    return {
        "type": "full_page_scan",
        "bbox": [round(x0 * zoom), round(y0 * zoom), round(x1 * zoom), round(y1 * zoom)],
        "needs_review": False,
        "detection_reason": (
            f"Region covers {area_ratio:.1%} of the page -- treated as the page's own "
            f"full-page scan/background, not a figure candidate"
        ),
        "signals": _signals(cluster["sources"]),
        "area_ratio": round(area_ratio, 4),
    }


def classify_cluster(cluster: dict, page_area: float, dpi: int):
    """Returns a candidate dict, a full_page_scan dict (if several
    medium fragments chained together into something background-sized),
    or None (obvious icon/fragment noise, conservatively dropped)."""
    x0, y0, x1, y1 = cluster["bbox"]
    area_ratio = ((x1 - x0) * (y1 - y0)) / page_area

    if area_ratio >= config.VISUAL_ELEMENT_BACKGROUND_AREA_RATIO:
        return build_full_page_scan(cluster, page_area, dpi)

    if area_ratio < config.VISUAL_ELEMENT_MIN_AREA_RATIO:
        return None  # obvious tiny icon/fragment noise

    zoom = dpi / 72
    return {
        "type": "candidate",
        "bbox": [round(x0 * zoom), round(y0 * zoom), round(x1 * zoom), round(y1 * zoom)],
        "needs_review": True,
        "detection_reason": (
            f"{_source_description(cluster['sources'], cluster['count'])} clustered, "
            f"covering {area_ratio:.1%} of the page"
        ),
        "signals": _signals(cluster["sources"]),
        "area_ratio": round(area_ratio, 4),
    }


def detect_page(page: fitz.Page, recurring_xrefs: set, dpi: int) -> list:
    page_area = page.rect.width * page.rect.height
    fragments, background_fragments = collect_fragments(page, recurring_xrefs)

    elements = []
    for cluster in cluster_fragments(fragments, config.VISUAL_ELEMENT_CLUSTER_GAP_PT):
        result = classify_cluster(cluster, page_area, dpi)
        if result is not None:
            elements.append(result)

    for cluster in cluster_fragments(background_fragments, config.VISUAL_ELEMENT_CLUSTER_GAP_PT):
        elements.append(build_full_page_scan(cluster, page_area, dpi))

    return elements


def pdf_fingerprint(pdf_path: Path) -> dict:
    stat = pdf_path.stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime}


def run(pdf_path: Path, output_path: Path, start_page: int, end_page: int, force: bool) -> dict:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")

    fingerprint = pdf_fingerprint(pdf_path)

    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        if start_page < 1 or end_page > total_pages or start_page > end_page:
            raise ValueError(f"Invalid page range {start_page}-{end_page} for a {total_pages}-page PDF")

        if output_path.exists() and not force:
            try:
                existing = json.loads(output_path.read_text(encoding="utf-8"))
                if (
                    existing.get("source_pdf_fingerprint") == fingerprint
                    and existing.get("page_range") == [start_page, end_page]
                ):
                    logger.info(
                        "Report already up to date for this PDF/page range, skipping "
                        "(use --force to redo): %s", output_path,
                    )
                    return existing
            except (json.JSONDecodeError, KeyError):
                pass  # fall through and recompute

        logger.info("Pass 1/2: scanning all %d page(s) for recurring (decorative) embedded images...", total_pages)
        recurring_xrefs = find_recurring_xrefs(doc)
        logger.info("Found %d recurring image xref(s) treated as page furniture", len(recurring_xrefs))

        logger.info("Pass 2/2: detecting candidate visual elements on pages %d-%d...", start_page, end_page)
        pages_report = []
        total_candidates = 0
        for pdf_page_number in range(start_page, end_page + 1):
            page = doc.load_page(pdf_page_number - 1)
            elements = detect_page(page, recurring_xrefs, config.RECONSTRUCTION_IMAGE_DPI)
            pages_report.append({"pdf_page": pdf_page_number, "visual_elements": elements})
            total_candidates += sum(1 for e in elements if e["type"] == "candidate")
    finally:
        doc.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_pdf": str(pdf_path),
        "source_pdf_fingerprint": fingerprint,
        "page_range": [start_page, end_page],
        "total_pages": len(pages_report),
        "pages_with_candidates": sum(
            1 for p in pages_report if any(e["type"] == "candidate" for e in p["visual_elements"])
        ),
        "total_candidates": total_candidates,
        "pages": pages_report,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic visual-element candidate detection (Phase 4)")
    parser.add_argument("--pdf", type=Path, default=config.PDF_PATH, help="Path to the source PDF")
    parser.add_argument("--output", type=Path, default=config.VISUAL_ELEMENTS_REPORT_JSON, help="Path to write the JSON report")
    parser.add_argument("--start", type=int, default=config.START_PAGE, help="First PDF page to scan (1-indexed, default: current chapter's config.START_PAGE)")
    parser.add_argument("--end", type=int, default=config.END_PAGE, help="Last PDF page to scan, inclusive (default: current chapter's config.END_PAGE)")
    parser.add_argument("--force", action="store_true", help="Recompute even if an up-to-date report already exists")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        report = run(args.pdf, args.output, args.start, args.end, args.force)
        logger.info(
            "Done. %d/%d pages have at least one candidate, %d candidate(s) total. Report: %s",
            report["pages_with_candidates"], report["total_pages"], report["total_candidates"], args.output,
        )
    except Exception:
        logger.exception("Visual element detection failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
