"""
Phase 5b - Figure <-> Knowledge association (chapter-generic).

Reads a chapter's knowledge JSON (Phase 6 output: sections, subsections,
items) and its final figure manifest (Phase 5a's final_figures/index.json)
and produces a deterministic, explainable set of candidate/confirmed
relationships between figures and knowledge items. Additive only:
never modifies the knowledge JSON, the final figure PNGs/index, or any
V1-V4 detection output.

WHY NO ITEM GEOMETRY:
The knowledge JSON (as of Chapter 1) carries no per-item pixel bbox --
only `source.pdf_pages` (which page(s) an item's content came from) and
document reading order (the `items` array's own order). Rather than
inventing an item bounding box, this module treats item geometry as
UNAVAILABLE and falls back to two signals that ARE real, authored data:
  - same_page / same_section / same_subsection (from source.pdf_pages
    and the sections/subsections page ranges, which are authored, not
    invented)
  - reading_order_proximity: an ORDINAL (not pixel) comparison of "how
    far down this page's sequence of items is this one" vs "how far
    down this page's sequence of figures (by real figure bbox y0) is
    this one" -- both sides are real facts (array order; figure bbox),
    just not comparable in pixel space, so they are compared as
    normalized ordinal positions instead.
If a chapter's knowledge JSON later gains real per-item geometry, only
`_reading_order_proximity`'s inputs need to change -- the rest of the
scoring model is unaffected.

CHAPTER-GENERIC BY DESIGN: every identifier this module produces or
consumes (chapter_id, section_id, item_id, figure_id, page numbers) is
read from the input JSON at runtime. No page number, candidate ID, or
chapter ID is ever hardcoded in the matching logic itself; the ONLY
place Chapter 1 appears is as a CLI default path (see main()) and in
test/ground-truth data (see test_associate_figures_knowledge.py).

Usage:
    python associate_figures_knowledge.py
    python associate_figures_knowledge.py --knowledge-json <path> --figures-index <path>
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("associate_figures_knowledge")

# --- Scoring weights ---
# These four terms are the only signals this module can compute
# without inventing data (see module docstring). They sum to 1.0 on a
# same-page candidate with matching section+subsection and a perfect
# ordinal match, so a score is directly readable as "fraction of the
# available deterministic evidence satisfied":
#   same_page            0.45  -- the single strongest, unambiguous signal
#   same_section          0.20 -- corroborating structural evidence
#   same_subsection       0.10 -- finer corroborating structural evidence
#   reading_order_proximity (x0.25) -- tie-breaker among same-page items
WEIGHT_SAME_PAGE = 0.45
WEIGHT_SAME_SECTION = 0.20
WEIGHT_SAME_SUBSECTION = 0.10
WEIGHT_READING_ORDER_PROXIMITY = 0.25

# Flat penalty subtracted when a candidate comes from a NEIGHBORING
# page (only ever considered when the figure's own page has no items
# at all -- see generate_candidates). Large enough that a
# neighboring-page candidate can reach REVIEW_REQUIRED but never
# AUTO_MATCH on its own, since it is inherently less reliable than a
# same-page candidate.
NEIGHBOR_PAGE_PENALTY = 0.40

# A knowledge item's deterministic "what does a figure attached to this
# item usually mean" relation, keyed on the item's own `type` (existing,
# authored data -- not inferred from content). Deliberately small: see
# module docstring section 12/15 of the task brief -- do not over-engineer
# the relation taxonomy before real multi-chapter evidence exists.
RELATION_BY_ITEM_TYPE = {
    "theorem": "illustrates",
    "property": "illustrates",
    "definition": "illustrates",
    "activity": "supports",
    "exercise": "belongs_to_exercise",
    "remark": "related_to",
}
DEFAULT_RELATION = "related_to"


def load_knowledge(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_figures(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _page_range_map(entries: list[dict]) -> dict[int, str]:
    """page -> id of the section/subsection entry whose
    [pdf_page_start, pdf_page_end] range contains it. `entries` is a
    chapter's own `sections` or `subsections` list -- these ranges are
    authored data (already in the knowledge JSON), never invented here.
    Assumes non-overlapping ranges (true of every chapter inspected);
    on overlap, the earlier entry in document order wins."""
    mapping: dict[int, str] = {}
    for entry in entries:
        for page in range(entry["pdf_page_start"], entry["pdf_page_end"] + 1):
            mapping.setdefault(page, entry["id"])
    return mapping


def _items_by_page(items: list[dict]) -> dict[int, list[int]]:
    """page -> item indices (positions in the ORIGINAL `items` array,
    which is already in document reading order) whose
    source.pdf_pages includes that page."""
    by_page: dict[int, list[int]] = {}
    for idx, item in enumerate(items):
        for page in item["source"]["pdf_pages"]:
            by_page.setdefault(page, []).append(idx)
    return by_page


def _figures_by_page(figures: list[dict]) -> dict[int, list[dict]]:
    """page -> figures on that page, ordered top-to-bottom by their own
    real final_bbox y0 (tie-broken by figure_id for determinism)."""
    by_page: dict[int, list[dict]] = {}
    for fig in figures:
        by_page.setdefault(fig["source_page"], []).append(fig)
    for figs in by_page.values():
        figs.sort(key=lambda f: (f["final_bbox"][1], f["figure_id"]))
    return by_page


def _ordinal_frac(index: int, count: int) -> float:
    if count <= 1:
        return 0.5
    return (index + 0.5) / count


def _reading_order_proximity(figure_frac: float, item_frac: float) -> float:
    return max(0.0, 1.0 - abs(figure_frac - item_frac))


def _infer_relation(item_type: str) -> str:
    return RELATION_BY_ITEM_TYPE.get(item_type, DEFAULT_RELATION)


def generate_candidates(page: int, items_by_page: dict[int, list[int]]) -> tuple[list[int], bool]:
    """Returns (item indices, used_neighbor_fallback). Same-page items
    first; only if the figure's own page has NO items at all does this
    fall back to the immediate neighboring pages (page-1, page+1) --
    e.g. a full-bleed figure whose accompanying text was extracted onto
    an adjacent page. Never silently searches further afield."""
    same_page = items_by_page.get(page, [])
    if same_page:
        return list(same_page), False
    neighbors = list(items_by_page.get(page - 1, [])) + list(items_by_page.get(page + 1, []))
    return neighbors, bool(neighbors)


def score_candidate(
    *,
    same_page: bool,
    item_section_id: str | None,
    item_subsection_id: str | None,
    section_of_figure_page: str | None,
    subsection_of_figure_page: str | None,
    figure_ordinal_frac: float,
    item_ordinal_frac: float,
) -> tuple[float, dict]:
    same_section = section_of_figure_page is not None and item_section_id == section_of_figure_page
    same_subsection = subsection_of_figure_page is not None and item_subsection_id == subsection_of_figure_page
    reading_order_proximity = _reading_order_proximity(figure_ordinal_frac, item_ordinal_frac)

    score = 0.0
    if same_page:
        score += WEIGHT_SAME_PAGE
    if same_section:
        score += WEIGHT_SAME_SECTION
    if same_subsection:
        score += WEIGHT_SAME_SUBSECTION
    score += WEIGHT_READING_ORDER_PROXIMITY * reading_order_proximity
    if not same_page:
        score = max(0.0, score - NEIGHBOR_PAGE_PENALTY)

    signals = {
        "same_page": same_page,
        "neighboring_page": not same_page,
        "same_section": same_section,
        "same_subsection": same_subsection,
        "reading_order_proximity": round(reading_order_proximity, 4),
    }
    return round(min(score, 1.0), 4), signals


def decide(candidates: list[dict]) -> tuple[str, dict | None]:
    """candidates: list of {"score":..., "signals":..., "item_id":...},
    already sorted best-first. Returns (decision, chosen_candidate)."""
    if not candidates:
        return "NO_MATCH", None

    top = candidates[0]
    runner_up_score = candidates[1]["score"] if len(candidates) > 1 else 0.0

    if top["signals"]["neighboring_page"]:
        # Never auto-accept a neighboring-page guess -- see
        # NEIGHBOR_PAGE_PENALTY.
        if top["score"] >= config.ASSOCIATION_REVIEW_THRESHOLD:
            return "REVIEW_REQUIRED", top
        return "NO_MATCH", None

    if (
        top["score"] >= config.ASSOCIATION_AUTO_MATCH_THRESHOLD
        and (top["score"] - runner_up_score) >= config.ASSOCIATION_AUTO_MATCH_MARGIN
    ):
        return "AUTO_MATCH", top
    if top["score"] >= config.ASSOCIATION_REVIEW_THRESHOLD:
        return "REVIEW_REQUIRED", top
    return "NO_MATCH", None


def build_associations(knowledge: dict, figures_manifest: dict) -> dict:
    chapter_id = knowledge["chapter"]["id"]
    items = knowledge["items"]
    figures = figures_manifest["figures"]

    section_page_map = _page_range_map(knowledge.get("sections", []))
    subsection_page_map = _page_range_map(knowledge.get("subsections", []))
    items_by_page = _items_by_page(items)
    figures_by_page = _figures_by_page(figures)

    associations = []
    counts = {"AUTO_MATCH": 0, "REVIEW_REQUIRED": 0, "NO_MATCH": 0}

    for fig in sorted(figures, key=lambda f: f["figure_id"]):
        page = fig["source_page"]
        peer_figures = figures_by_page[page]
        figure_ordinal_frac = _ordinal_frac(peer_figures.index(fig), len(peer_figures))
        section_of_page = section_page_map.get(page)
        subsection_of_page = subsection_page_map.get(page)

        candidate_indices, _used_neighbor = generate_candidates(page, items_by_page)

        candidates = []
        for idx in candidate_indices:
            item = items[idx]
            same_page = page in item["source"]["pdf_pages"]
            item_page = page if same_page else next(
                p for p in item["source"]["pdf_pages"] if p in (page - 1, page + 1)
            )
            page_peers = items_by_page.get(item_page, [])
            item_ordinal_frac = _ordinal_frac(page_peers.index(idx), len(page_peers))

            score, signals = score_candidate(
                same_page=same_page,
                item_section_id=item.get("section_id"),
                item_subsection_id=item.get("subsection_id"),
                section_of_figure_page=section_of_page,
                subsection_of_figure_page=subsection_of_page,
                figure_ordinal_frac=figure_ordinal_frac,
                item_ordinal_frac=item_ordinal_frac,
            )
            candidates.append({
                "association_id": f"assoc-{chapter_id}-{fig['figure_id']}-{item['id']}",
                "item_id": item["id"],
                "item_type": item["type"],
                "relation": _infer_relation(item["type"]),
                "score": score,
                "signals": signals,
            })

        candidates.sort(key=lambda c: (-c["score"], c["item_id"]))
        decision, chosen = decide(candidates)
        if decision == "AUTO_MATCH":
            review_status = "AUTO_ACCEPTED"
        elif decision == "REVIEW_REQUIRED":
            review_status = "PENDING"
        else:
            review_status = None
        counts[decision] += 1

        associations.append({
            "figure_id": fig["figure_id"],
            "chapter_id": chapter_id,
            "source_page": page,
            "candidate_image": fig["image"],
            "decision": decision,
            "review_status": review_status,
            "chosen_association_id": chosen["association_id"] if chosen else None,
            "chosen_item_id": chosen["item_id"] if chosen else None,
            "relation": chosen["relation"] if chosen else None,
            "score": chosen["score"] if chosen else None,
            "candidates": candidates,
        })

    pipeline_status = "ASSOCIATION_REVIEW_REQUIRED" if counts["REVIEW_REQUIRED"] > 0 else "ASSOCIATION_AUTO_COMPLETED"

    return {
        "chapter_id": chapter_id,
        "algorithm_version": config.ASSOCIATION_ALGORITHM_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "total_figures": len(figures),
            "auto_match": counts["AUTO_MATCH"],
            "review_required": counts["REVIEW_REQUIRED"],
            "no_match": counts["NO_MATCH"],
        },
        "pipeline_status": pipeline_status,
        "associations": associations,
    }


def run(knowledge_path: Path, figures_index_path: Path, output_path: Path | None = None) -> dict:
    knowledge = load_knowledge(knowledge_path)
    figures_manifest = load_figures(figures_index_path)
    result = build_associations(knowledge, figures_manifest)

    out_path = output_path or config.associations_json(result["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return result


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Figure <-> knowledge association (Phase 5b)")
    parser.add_argument("--knowledge-json", type=Path, default=config.KNOWLEDGE_CHAPTER_01_JSON)
    parser.add_argument("--figures-index", type=Path, default=config.FINAL_FIGURES_INDEX_JSON)
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/associations/figure_knowledge.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.knowledge_json, args.figures_index, args.output)
        logger.info("Chapter %s: %s", result["chapter_id"], result["summary"])
        logger.info("Pipeline status: %s", result["pipeline_status"])
    except Exception:
        logger.exception("associate_figures_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
