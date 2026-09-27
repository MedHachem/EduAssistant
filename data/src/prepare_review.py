"""
Phase 4d - Human-review preparation.

Joins three existing, independently-generated outputs into one flat,
review-friendly list -- one row per candidate, plus a category-count
summary. This is a READ-ONLY join: it does not re-detect, re-refine, or
re-classify anything, and it never excludes a candidate for any reason.

Inputs:
  - visual_elements_report_refined.json (refine_visual_elements.py):
    seed_bbox (original detection), bbox (pixel-refined), plus
    refinement_uncertain / likely_text_box.
  - visual_elements_evaluation.json (evaluate_visual_elements.py):
    classification_hint + a plain-language explanation. SOFT HINTS
    ONLY -- see that module's docstring for validated failure modes.
  - figure_candidates_refined/index.json (extract_figure_candidates.py,
    run against the refined report): the actual cropped PNG path for
    each candidate.

IMPORTANT -- classification_hint is a soft triage hint, not a verified
label:
  - "figure"    : LIKELY a graphical figure (curve/diagram/geometry).
                  NOT confirmed -- verify against the image.
  - "text_only" : LIKELY plain text or a tinted callout box. NOT
                  guaranteed -- also known to catch genuine tables.
  - "ambiguous" : the classifier's signals disagreed or were
                  inconclusive. This is the safe default, not a
                  failure -- most mixed-content candidates correctly
                  land here.

Known failure modes (see evaluate_visual_elements.py's docstring for
full detail and specific examples): dense two-line theorem text can
read as a figure; decorative page banners can read as a figure; a real
graph with substantial intro text can read as text_only; genuine tables
currently read as text_only. None of this affects needs_review, which
is unconditionally true for every candidate here, regardless of hint.

This script does not decide anything and does not filter anything --
its only job is to make the existing information easier for a human to
scan quickly, grouped by hint so the likely-figures can be reviewed as
a batch, then the ambiguous ones, then a spot-check of text_only (which
is where mislabeled tables/mixed regions are known to hide).

Usage:
    python prepare_review.py
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("prepare_review")

HINT_MEANING = {
    "figure": "Likely a graphical figure (curve/diagram/geometry). NOT confirmed -- verify against the image.",
    "text_only": "Likely plain text or a tinted callout box. NOT guaranteed -- known to also catch genuine tables.",
    "ambiguous": "Classifier signals disagreed or were inconclusive. Needs a closer look; this is the safe default, not a failure.",
}

# Review order: likely figures first (primary interest), then the
# genuinely uncertain ones, then a spot-check pass over text_only
# (where mislabeled tables/mixed regions are known to hide).
HINT_ORDER = ("figure", "ambiguous", "text_only")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def load(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Required input not found: {path}. Run the corresponding stage first "
            f"(refine_visual_elements.py / evaluate_visual_elements.py / extract_figure_candidates.py)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


# Deterministic confidence score (that a candidate is a genuine figure),
# derived entirely from signals already computed by earlier stages --
# no new detection logic. A starting point per soft triage hint,
# lowered when the pixel-refinement stage itself distrusted its own
# growth (refinement_uncertain). Never used to filter/exclude anything
# -- needs_review stays unconditionally true regardless of this score,
# same as classification_hint.
_CONFIDENCE_BASE = {"figure": 0.8, "ambiguous": 0.5, "text_only": 0.2}


def compute_confidence(hint: str, refinement_uncertain: bool) -> float:
    score = _CONFIDENCE_BASE[hint]
    if refinement_uncertain:
        score = max(0.0, score - 0.2)
    return round(score, 2)


def build_rows(refined_report: dict, evaluation: dict, crops_index: dict) -> list:
    eval_by_id = {c["id"]: c for c in evaluation["candidates"]}
    crop_by_id = {c["id"]: c for c in crops_index["candidates"]}

    rows = []
    for page_entry in refined_report["pages"]:
        pdf_page_number = page_entry["pdf_page"]
        candidates = [e for e in page_entry["visual_elements"] if e.get("type") == "candidate"]

        for i, candidate in enumerate(candidates, start=1):
            candidate_id = f"page_{pdf_page_number:03d}_candidate_{i:02d}"
            ev = eval_by_id.get(candidate_id)
            crop = crop_by_id.get(candidate_id)

            hint = ev["category"] if ev else "ambiguous"
            explanation = ev["reason"] if ev else "not evaluated by evaluate_visual_elements.py"
            if ev is None:
                logger.warning("%s: no evaluation entry found, defaulting hint to 'ambiguous'", candidate_id)
            if crop is None:
                logger.warning("%s: no cropped image found in crops index", candidate_id)

            refinement_uncertain = bool(candidate.get("refinement_uncertain", False))
            rows.append({
                "candidate_id": candidate_id,
                "pdf_page": pdf_page_number,
                "type": "candidate",
                "classification_hint": hint,
                "hint_meaning": HINT_MEANING[hint],
                "hint_explanation": explanation,
                "confidence": compute_confidence(hint, refinement_uncertain),
                "refinement_uncertain": refinement_uncertain,
                "likely_text_box": bool(candidate.get("likely_text_box", False)),
                "seed_bbox": candidate.get("seed_bbox", candidate["bbox"]),
                "refined_bbox": candidate["bbox"],
                "bbox": candidate["bbox"],
                "image_path": crop["image"] if crop else None,
                "needs_review": True,
            })

    return rows


def render_text_report(rows: list, counts: dict) -> str:
    lines = [
        "VISUAL ELEMENT REVIEW",
        "=" * 22,
        "",
        "classification_hint is a SOFT TRIAGE HINT, not a verified label:",
        f"  figure     -- {HINT_MEANING['figure']}",
        f"  text_only  -- {HINT_MEANING['text_only']}",
        f"  ambiguous  -- {HINT_MEANING['ambiguous']}",
        "",
        "Known failure modes (see evaluate_visual_elements.py docstring for details):",
        "  1. Dense two-line theorem text can read as a figure.",
        "  2. Decorative page banners can read as a figure.",
        "  3. A real graph with substantial intro text can read as text_only.",
        "  4. Genuine tables currently read as text_only.",
        "",
        f"Total candidates: {sum(counts.values())}",
        f"  figure     : {counts['figure']}",
        f"  text_only  : {counts['text_only']}",
        f"  ambiguous  : {counts['ambiguous']}",
        "",
    ]

    for hint in HINT_ORDER:
        lines.append(f"--- {hint.upper()} ({counts[hint]}) ---")
        for r in rows:
            if r["classification_hint"] != hint:
                continue
            lines.append(f"{r['candidate_id']} (page {r['pdf_page']})")
            lines.append(f"  reason           : {r['hint_explanation']}")
            lines.append(f"  seed_bbox        : {r['seed_bbox']}")
            lines.append(f"  bbox (refined)   : {r['bbox']}")
            lines.append(f"  refinement_uncertain={r['refinement_uncertain']}  likely_text_box={r['likely_text_box']}")
            lines.append(f"  image            : {r['image_path']}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(refined_report_path: Path, evaluation_path: Path, crops_index_path: Path,
        output_json: Path, output_txt: Path) -> dict:
    refined_report = load(refined_report_path)
    evaluation = load(evaluation_path)
    crops_index = load(crops_index_path)

    rows = build_rows(refined_report, evaluation, crops_index)

    counts = {"figure": 0, "text_only": 0, "ambiguous": 0}
    for r in rows:
        counts[r["classification_hint"]] += 1

    output = {
        "note": (
            "classification_hint is a SOFT TRIAGE HINT, not a verified label. "
            "See evaluate_visual_elements.py's docstring for known failure modes. "
            "needs_review is unconditionally true for every candidate regardless of hint; "
            "nothing here is ever auto-excluded."
        ),
        "total_candidates": len(rows),
        "counts_by_hint": counts,
        "candidates": rows,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    output_txt.write_text(render_text_report(rows, counts), encoding="utf-8")

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human-review report preparation (Phase 4d)")
    parser.add_argument("--refined-report", type=Path, default=config.VISUAL_ELEMENTS_REFINED_REPORT_JSON)
    parser.add_argument("--evaluation", type=Path, default=config.VISUAL_ELEMENTS_EVALUATION_JSON)
    parser.add_argument("--crops-index", type=Path, default=config.FIGURE_CANDIDATES_REFINED_INDEX_JSON)
    parser.add_argument("--output-json", type=Path, default=config.VISUAL_ELEMENTS_REVIEW_JSON)
    parser.add_argument("--output-txt", type=Path, default=config.VISUAL_ELEMENTS_REVIEW_TXT)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.refined_report, args.evaluation, args.crops_index, args.output_json, args.output_txt)
        logger.info("Counts by hint: %s", result["counts_by_hint"])
        logger.info("Review reports written to %s and %s", args.output_json, args.output_txt)
    except Exception:
        logger.exception("Review preparation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
