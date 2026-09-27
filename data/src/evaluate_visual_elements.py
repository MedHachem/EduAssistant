"""
SOFT TRIAGE HINT generator -- NOT a ground-truth classifier, and not
wired into the detection/refinement/extraction pipeline.

Status (decided after manual review of results against real candidates
in this chapter): shipped as a soft hint to speed up human review, per
explicit instruction NOT to treat this as a confirmed classifier and
NOT to add further heuristic complexity at this stage. Every candidate
keeps needs_review=true regardless of what this script says; nothing
is ever excluded, reordered out of existence, or auto-resolved based on
its output. See prepare_review.py for how this feeds the human-review
report.

classification_hint meanings (soft, not guaranteed):
  - "figure"    : LIKELY a graphical figure. NOT confirmed.
  - "text_only" : LIKELY plain text or a tinted callout box. NOT
                  guaranteed -- also known to catch genuine tables.
  - "ambiguous" : signals disagreed or were inconclusive. This is the
                  safe default, not a failure.

KNOWN FAILURE MODES (confirmed by manually opening the actual crop for
every "figure" candidate in this chapter, not merely assumed from the
statistics -- roughly 33% of the "figure" bucket was wrong before this
was understood, so please read this list before trusting an individual
hint):
  1. Dense, tightly-spaced two-line theorem statements can bridge into
     one dominant connected blob AND produce too few text-line bands
     to trip the text rule -- indistinguishable from a figure by these
     two signals alone (e.g. page_013_candidate_01, page_019_candidate_02).
  2. Decorative page banners ("Cours", "Exercices et problèmes"
     pill-shaped headers) are genuinely one dominant graphical shape
     with no text-line structure -- not text-like, but also not a
     mathematical figure (page_019_candidate_03, page_025_candidate_01).
  3. Mixed text + graph regions: a real graph preceded/accompanied by
     substantial intro text can have the text portion dominate the
     row-band signal, landing the whole candidate in "text_only" and
     hiding a real figure (page_027_candidate_03).
  4. Genuine tables are currently bucketed into "text_only" (their row/
     column structure resembles text-line banding) -- safe (still
     flagged for review) but mislabeled; tables are not yet a
     recognized category of their own (page_008_candidate_04,
     page_009_candidate_01, page_020_candidate_01).

Signals (computed with an adaptive ink mask -- ink is defined as
deviation from THIS region's OWN dominant background color, not from
pure white, so a pastel callout-box tint isn't misread as ink; see git
history for the pure-white version's failure modes if reintroducing
that simplification is ever considered -- don't):
  - largest_component_frac: fraction of total ink in the single largest
    connected component after light dilation. A real curve/circle/axis
    system is typically one continuous stroke.
  - n_bands: number of horizontal "text-line" bands via row-wise ink
    projection, dropping bands under MIN_BAND_HEIGHT_PX (a single
    figure label can otherwise register as a spurious extra band).

Decision rule -- requires signals to AGREE, never lets one veto the
other (a strictly safety-improving tightening: it only ever moves a
previously wrong confident answer to "ambiguous", never the reverse):
  1. likely_text_box (existing tint signal)                -> text_only
  2. elif dominant component AND NOT text-banded            -> figure
  3. elif text-banded AND NOT dominant component            -> text_only
  4. else (signals disagree or are both weak)               -> ambiguous

This script reads the existing refined report and rendered page images
read-only. It does NOT modify detect_visual_elements.py,
refine_visual_elements.py, extract_figure_candidates.py, or any
existing report/bbox -- it writes its own separate evaluation report.

Usage:
    python evaluate_visual_elements.py
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import config

logger = logging.getLogger("evaluate_visual_elements")

INK_DEVIATION_THRESHOLD = 60  # from the region's OWN dominant background color, not pure white
COMPONENT_DILATION_RADIUS = 3
ROW_INK_FRACTION_THRESHOLD = 0.01
MIN_BAND_HEIGHT_PX = 15
TEXT_MIN_BANDS = 3
FIGURE_MIN_DOMINANT_FRACTION = 0.85


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def dominant_color(region: np.ndarray, bin_size: int = 8) -> np.ndarray:
    flat = region.reshape(-1, 3)
    binned = (flat // bin_size) * bin_size
    keys = binned[:, 0].astype(np.int32) * 65536 + binned[:, 1].astype(np.int32) * 256 + binned[:, 2].astype(np.int32)
    values, counts = np.unique(keys, return_counts=True)
    top = int(values[np.argmax(counts)])
    return np.array([(top >> 16) & 255, (top >> 8) & 255, top & 255])


def adaptive_ink_mask(region: np.ndarray) -> tuple:
    """A pixel is 'ink' if it deviates from THIS region's own dominant
    background color (whatever it is -- white paper or a tinted
    callout box) by more than INK_DEVIATION_THRESHOLD. Returns
    (ink_mask, dominant_background_color)."""
    bg = dominant_color(region)
    diff = np.abs(region.astype(np.int16) - bg.astype(np.int16))
    return diff.max(axis=2) > INK_DEVIATION_THRESHOLD, bg


def component_stats(ink: np.ndarray) -> dict:
    radius = COMPONENT_DILATION_RADIUS
    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    disk = (xx * xx + yy * yy) <= radius * radius
    dilated = ndimage.binary_dilation(ink, structure=disk)
    labeled, n = ndimage.label(dilated, structure=np.ones((3, 3)))
    if n == 0:
        return {"n_components": 0, "largest_component_frac": 0.0}
    sizes = ndimage.sum(dilated, labeled, range(1, n + 1))
    return {"n_components": int(n), "largest_component_frac": float(sizes.max() / sizes.sum())}


def row_band_stats(ink: np.ndarray) -> dict:
    row_frac = ink.mean(axis=1)
    has_ink = row_frac > ROW_INK_FRACTION_THRESHOLD

    bands, current_start = [], None
    for i, v in enumerate(has_ink):
        if v and current_start is None:
            current_start = i
        elif not v and current_start is not None:
            bands.append((current_start, i))
            current_start = None
    if current_start is not None:
        bands.append((current_start, len(has_ink)))

    # Drop bands too thin to plausibly be a real text line -- a single
    # small figure label (e.g. one axis letter) can otherwise register
    # as a spurious extra "band" and falsely trip the text-line count.
    significant_bands = [b for b in bands if (b[1] - b[0]) >= MIN_BAND_HEIGHT_PX]
    return {"n_bands": len(significant_bands)}


def classify(candidate: dict, region: np.ndarray) -> dict:
    ink, bg = adaptive_ink_mask(region)
    comp = component_stats(ink)
    bands = row_band_stats(ink)
    likely_text_box = bool(candidate.get("likely_text_box", False))
    is_dominant = comp["largest_component_frac"] >= FIGURE_MIN_DOMINANT_FRACTION
    is_banded = bands["n_bands"] >= TEXT_MIN_BANDS

    # Require signals to AGREE rather than letting either one veto the
    # other -- validated against real candidates: dense multi-line text
    # can bridge into one dominant component after dilation (falsely
    # agreeing with "figure"), and a real graph with substantial intro
    # text above/beside it can show several text-line bands (falsely
    # agreeing with "text"). Requiring agreement doesn't fix every case
    # (see evaluation notes) but never turns a previously-safe call
    # into a wrong confident one -- disagreement always falls to
    # "ambiguous", per the safety-first philosophy.
    if likely_text_box:
        category, reason = "text_only", "tinted callout-box background (existing signal)"
    elif is_dominant and not is_banded:
        category, reason = "figure", f"one dominant connected graphical shape ({comp['largest_component_frac']:.0%} of ink), no text-line banding"
    elif is_banded and not is_dominant:
        category, reason = "text_only", f"{bands['n_bands']} horizontal text-line bands, no dominant graphical shape"
    else:
        category, reason = "ambiguous", "signals disagree or are inconclusive -- needs human review"

    return {
        "category": category,
        "reason": reason,
        "n_components": comp["n_components"],
        "largest_component_frac": round(comp["largest_component_frac"], 4),
        "n_bands": bands["n_bands"],
        "background_color": bg.tolist(),
    }


def run(report_path: Path, page_images_dir: Path, output_json: Path, output_txt: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))

    results = []
    for page_entry in report["pages"]:
        pdf_page_number = page_entry["pdf_page"]
        candidates = [e for e in page_entry["visual_elements"] if e.get("type") == "candidate"]
        if not candidates:
            continue

        image_path = page_images_dir / f"page_{pdf_page_number:03d}.png"
        page_array = np.array(Image.open(image_path).convert("RGB"))

        for i, candidate in enumerate(candidates, start=1):
            x0, y0, x1, y1 = candidate["bbox"]
            region = page_array[y0:y1, x0:x1]
            evaluation = classify(candidate, region)
            results.append({
                "id": f"page_{pdf_page_number:03d}_candidate_{i:02d}",
                "pdf_page": pdf_page_number,
                "bbox": candidate["bbox"],
                "likely_text_box": candidate.get("likely_text_box", False),
                "refinement_uncertain": candidate.get("refinement_uncertain", False),
                **evaluation,
            })

    counts = {"figure": 0, "text_only": 0, "ambiguous": 0}
    for r in results:
        counts[r["category"]] += 1

    output = {
        "source_report": str(report_path),
        "total_candidates": len(results),
        "counts": counts,
        "candidates": results,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "VISUAL ELEMENT EVALUATION (prototype signals, not yet merged into pipeline)",
        "=" * 70,
        "",
        f"Total candidates: {len(results)} (categories are mutually exclusive, sum to total)",
        f"  figure     : {counts['figure']}",
        f"  text_only  : {counts['text_only']}",
        f"  ambiguous  : {counts['ambiguous']}",
        "",
    ]
    for category in ("figure", "text_only", "ambiguous"):
        lines.append(f"--- {category.upper()} ---")
        for r in results:
            if r["category"] == category:
                lines.append(
                    f"{r['id']}: {r['reason']} "
                    f"(n_components={r['n_components']}, largest_frac={r['largest_component_frac']}, n_bands={r['n_bands']})"
                )
        lines.append("")

    output_txt.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> None:
    setup_logging()
    report_path = config.VISUAL_ELEMENTS_REFINED_REPORT_JSON
    output_json = config.VISUAL_ELEMENTS_EVALUATION_JSON
    output_txt = config.VISUAL_ELEMENTS_EVALUATION_TXT
    result = run(report_path, config.PAGE_IMAGES_DIR, output_json, output_txt)
    logger.info("Counts: %s", result["counts"])
    logger.info("Reports written to %s and %s", output_json, output_txt)


if __name__ == "__main__":
    main()
