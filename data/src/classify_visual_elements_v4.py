"""
Phase 4j (V4) - deterministic FIGURE / NOT_FIGURE / FIGURE_REVIEW
classification, calibrated against a new, corrected, visually-verified
human ground truth for the 39 V3 candidates.

WHY V4 EXISTS -- concrete evidence, not guesswork:

The new ground truth (39 V3 candidates, re-checked against the actual
figure_candidates_v3/index.json filenames -- NOT the mis-numbered ids an
earlier evaluation script had used) showed that V2/V3's existing soft
classifier (classify_visual_elements_v2.classify) already achieves
PERFECT recall (all 19 real figures reach the FIGURE/AMBIGUOUS queue),
but ZERO precision improvement on the hardest 20: every single REJECTED
candidate lands in AMBIGUOUS too, because V2's TEXT_BLOCK rule requires
>=5 row-bands (TEXT_HARD_MIN_BANDS), and most of these 20 are SHORT
(1-4 line) theorem/definition/heading blocks that never reach 5 bands --
a deliberate V2 safety margin (see that module's docstring) that turned
out to leave essentially the whole 39-candidate set unresolved.

V4's job is narrower and more targeted than "detect a figure from
scratch": distinguish, among candidates that ALL already survived V1-V3
(so none of them are e.g. running headers or huge full-page scans),
which ones contain genuine curve/graph/geometric ink versus which are
purely textual -- using signals that survived direct calibration
against all 39 real candidates (see module-level constants below, each
documented with the actual measured values that justified it).

KEY NEW SIGNAL: max_sparse_component_area_frac. Existing V2 signals
(ink_coverage, dominant_fraction from a LIGHTLY DILATED mask) describe
the region as a whole and are easily confused by a short dense text
block that happens to bridge into one blob (V2's documented failure
mode). V4 additionally looks at UNDILATED (raw) connected components:
a real curve/axis, even a short one, is SPARSE within its own bounding
box (a diagonal or curved stroke covers a small fraction of the
rectangle around it) and LARGE relative to the page region (it is not
one character). A run of dense text, even after light dilation, is
never sparse+large in this sense at zero dilation -- individual glyphs
remain small, separate blobs. This directly answers Sec. 9.C/E/G of the
design brief (graphical ink / curve detection / component size
distribution) without OpenCV, using only numpy/scipy connected-
component labeling already used elsewhere in this pipeline.

ARCHITECTURE (Sec. 5 of the design brief): classification only. This
module does NOT touch crop_quality / bbox correction -- V3's completeness
refinement already exists for that (figure_completeness_v3.py) and is
unrelated to whether something is a figure at all. A NEEDS_CORRECTION
candidate is exactly "classified FIGURE, crop still oversized" and V4
does not try to resolve the crop side of that.

NO LLM, NO OpenCV, NO OCR (Tesseract is not installed/on PATH in this
environment -- verified before writing this module; per the design
brief, OCR is optional supporting evidence, never mandatory, so its
absence does not block V4). numpy + scipy.ndimage + PIL only, all
already dependencies of this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from classify_visual_elements_v2 import (
    adaptive_ink_mask,
    dominant_component_fraction,
    ruling_line_counts,
    row_bands,
)

Classification = str  # "FIGURE" | "NOT_FIGURE" | "FIGURE_REVIEW"

# --- Thresholds, each calibrated against the measured distribution over
# all 39 real V3 candidates (13 VALIDATED + 6 NEEDS_CORRECTION + 20
# REJECTED, ground truth re-verified visually against the real
# figure_candidates_v3/index.json filenames). See
# visual_detection_v4_evaluation.json for the full per-candidate feature
# dump these were read off of.

# PATHWAY A -- "clean figure signature" (carried over from
# classify_visual_elements_v2.py, already proven on the 13 VALIDATED):
# sparse ink, one dominant connected stroke, spanning most of the crop.
FIGURE_MAX_INK_COVERAGE = 0.20
FIGURE_MIN_DOMINANT_FRACTION = 0.5
FIGURE_MIN_BAND_WIDTH_FRAC = 0.85

# PATHWAY B -- "sparse large component present" -- catches a real
# figure even when merged with adjacent text inflates ink_coverage/
# dominant_fraction (the whole point of V4). Measured on real
# NEEDS_CORRECTION candidates: page_025_candidate_01 (a 3-curve
# comparison graph with a leftover formula line above it) scored 0.044;
# page_027_candidate_04 (curve with one leftover intro line) scored
# 0.028. The floor sits just under the smaller of the two so both
# clear it; every one of the 20 REJECTED candidates that also has SOME
# large sparse component (decorative pill borders, one bracket/brace in
# a piecewise-function text block) is separated out by the aspect-ratio
# gate below instead, not by this floor.
SPARSE_COMPONENT_MIN_AREA_FRAC = 0.025
SPARSE_COMPONENT_MAX_FILL_RATIO = 0.35
SPARSE_COMPONENT_MIN_AREA_FRAC_FOR_COUNT = 0.0015

# Universal gate for BOTH pathways: every one of the 19 real figures
# measured a bbox aspect ratio (width/height) between 0.60 and 2.68.
# Decorative banners/pill headers and page-footer bars that otherwise
# trip pathway B (a banner's rounded outline is exactly a large, sparse,
# low-fill "component") measured 3.96-4.90 -- always far more elongated
# than any real figure in this chapter. The gate is set well outside
# the observed figure range (0.30-3.2) for margin.
ASPECT_RATIO_MIN = 0.30
ASPECT_RATIO_MAX = 3.2

# Confident NOT_FIGURE requires BOTH of these low simultaneously.
# Rationale: dominant_fraction and max_sparse_component_area_frac fail
# independently for different reasons (a bridged text blob can still
# have high dominant_fraction; a text block with one long underline/
# rule can still register a sparse component) -- requiring EITHER alone
# to be low is not safe, but ALL 19 real figures measured
# dominant_fraction >= 0.46, and the one real figure with a low
# dominant_fraction (page_009_candidate_01, mixed text+graph laid out
# side by side, dominant_fraction=0.21) still measured a non-trivial
# max_sparse_component_area_frac=0.017 -- comfortably above this floor.
# Conversely, 10 of the 20 REJECTED candidates measured BOTH low
# simultaneously and none of the 19 real figures do, in this dataset.
NOT_FIGURE_MAX_DOMINANT_FRACTION = 0.35
NOT_FIGURE_MAX_SPARSE_AREA_FRAC = 0.005


@dataclass
class V4Features:
    ink_density: float
    text_density: float  # dominant component's own fill ratio (dense=text-like)
    long_component_score: float  # max sparse+large raw-component area fraction
    curve_score: int  # count of qualifying sparse raw components
    axis_score: int  # horizontal + vertical ruling-line count
    text_line_score: int  # row-band count
    geometric_score: float  # 1.0 if aspect ratio is figure-plausible, else 0.0
    dominant_fraction: float
    aspect_ratio: float
    max_band_width_frac: float


def _dominant_component_fill_ratio(ink: np.ndarray) -> tuple[float, float]:
    """Light dilation (radius 3, matches classify_visual_elements_v2's
    own dominant_component_fraction) -- returns (dominant_fraction,
    dominant_component's own fill ratio = its pixel count / its own
    bounding box area). A bridged text blob is DENSE within its own
    bbox (high fill); a curve/axis is sparse even when it is the
    dominant component."""
    radius = 3
    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    disk = (xx * xx + yy * yy) <= radius * radius
    dilated = ndimage.binary_dilation(ink, structure=disk)
    labeled, n = ndimage.label(dilated, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0, 0.0
    sizes = ndimage.sum(dilated, labeled, range(1, n + 1))
    dominant_label = int(np.argmax(sizes)) + 1
    dominant_fraction = float(sizes.max() / sizes.sum())
    ys, xs = np.where(labeled == dominant_label)
    bbox_area = max(1, (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))
    fill_ratio = float(sizes.max() / bbox_area)
    return dominant_fraction, fill_ratio


def _sparse_component_stats(
    ink: np.ndarray,
    min_area_frac: float = SPARSE_COMPONENT_MIN_AREA_FRAC_FOR_COUNT,
    max_fill: float = SPARSE_COMPONENT_MAX_FILL_RATIO,
) -> tuple[float, int]:
    """RAW (undilated) connected components -- a real curve/axis is one
    continuous, SPARSE (low fill relative to its own bbox), LARGE
    (relative to the whole region) shape even in isolation; individual
    text glyphs never are, at zero dilation. Returns
    (largest_qualifying_component_area_frac, qualifying_component_count)."""
    h, w = ink.shape
    total_area = h * w
    labeled, n = ndimage.label(ink, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0, 0
    sizes = ndimage.sum(ink, labeled, range(1, n + 1))
    objs = ndimage.find_objects(labeled)
    best_frac = 0.0
    count = 0
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        comp_h = sl[0].stop - sl[0].start
        comp_w = sl[1].stop - sl[1].start
        bbox_area = max(1, comp_h * comp_w)
        area_frac = bbox_area / total_area
        fill = sizes[i] / bbox_area
        if area_frac >= min_area_frac and fill <= max_fill:
            count += 1
            best_frac = max(best_frac, sizes[i] / total_area)
    return best_frac, count


def extract_features(page_array: np.ndarray, bbox: list[int]) -> V4Features:
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)

    ink_density = float(ink.mean())
    dominant_fraction, text_density = _dominant_component_fill_ratio(ink)
    long_component_score, curve_score = _sparse_component_stats(ink)
    h_rulings, v_rulings = ruling_line_counts(ink)
    bands = row_bands(ink)
    max_band_width_frac = max((b.width_frac for b in bands), default=0.0)
    aspect_ratio = (x1 - x0) / max(1, (y1 - y0))
    geometric_score = 1.0 if ASPECT_RATIO_MIN <= aspect_ratio <= ASPECT_RATIO_MAX else 0.0

    return V4Features(
        ink_density=round(ink_density, 4),
        text_density=round(text_density, 3),
        long_component_score=round(long_component_score, 4),
        curve_score=curve_score,
        axis_score=h_rulings + v_rulings,
        text_line_score=len(bands),
        geometric_score=geometric_score,
        dominant_fraction=round(dominant_fraction, 3),
        aspect_ratio=round(aspect_ratio, 2),
        max_band_width_frac=round(max_band_width_frac, 3),
    )


def classify(f: V4Features) -> tuple[Classification, float, list[str]]:
    """Returns (classification, confidence, reason_codes).

    Two independent, OR-combined pathways to FIGURE (never require every
    signal to agree -- a real figure only needs to convincingly clear
    ONE of two different, complementary tests); a conservative,
    AND-combined pathway to NOT_FIGURE (both a low dominant_fraction AND
    no sparse large component -- see that constant's docstring for why
    both are required); everything else is FIGURE_REVIEW, never silently
    dropped."""
    ar_ok = ASPECT_RATIO_MIN <= f.aspect_ratio <= ASPECT_RATIO_MAX
    reasons: list[str] = []

    pathway_a = (
        f.ink_density <= FIGURE_MAX_INK_COVERAGE
        and f.dominant_fraction >= FIGURE_MIN_DOMINANT_FRACTION
        and f.max_band_width_frac >= FIGURE_MIN_BAND_WIDTH_FRAC
        and ar_ok
    )
    pathway_b = f.long_component_score >= SPARSE_COMPONENT_MIN_AREA_FRAC and ar_ok

    if pathway_a:
        reasons.append("CLEAN_FIGURE_SIGNATURE")
    if pathway_b:
        reasons.append("SPARSE_GRAPHICAL_COMPONENT_FOUND")
    if not ar_ok:
        reasons.append("ASPECT_RATIO_OUTSIDE_FIGURE_RANGE")

    if pathway_a or pathway_b:
        confidence = 0.9 if (pathway_a and pathway_b) else 0.8 if pathway_a else 0.65
        return "FIGURE", confidence, reasons

    not_figure = (
        f.dominant_fraction < NOT_FIGURE_MAX_DOMINANT_FRACTION
        and f.long_component_score < NOT_FIGURE_MAX_SPARSE_AREA_FRAC
    )
    if not_figure:
        reasons.append("LOW_DOMINANCE_NO_GRAPHICAL_EVIDENCE")
        return "NOT_FIGURE", 0.75, reasons

    reasons.append("MIXED_SIGNALS_NEEDS_HUMAN_REVIEW")
    return "FIGURE_REVIEW", 0.4, reasons
