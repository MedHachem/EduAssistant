"""
Phase 4e (V2) - multi-signal candidate classification + text-margin bbox
trimming, deterministic pixel analysis only (numpy/scipy/PIL -- no
OpenCV, no OCR, no LLM; see config.py for why: cv2/skimage are not
installed in this environment, and per the design brief this stage must
remain scalable/cheap across future chapters without new heavy deps).

WHY THIS MODULE EXISTS -- concrete evidence, not guesswork:

Chapter 1's human figure review (68 candidates from
detect_visual_elements.py + refine_visual_elements.py) was used as
ground truth to find out exactly what V1 got wrong. Every one of the 68
refined crops was inspected directly (not sampled) and cross-checked
against the human counts. Two, and only two, systematic problems were
found -- both are pixel-measurable, not one-off:

1. FALSE POSITIVES (4 of 68): page_013_candidate_01, page_019_candidate_02
   (dense 1-2 line theorem/definition boxes) and page_019_candidate_03,
   page_025_candidate_01 (decorative pill banners like "Cours" /
   "Exercices et problèmes") were all hinted "figure" by
   evaluate_visual_elements.py's existing largest_component_frac /
   n_bands rule -- exactly the two failure modes that module's own
   docstring already named. Root cause: that rule only looks at whether
   ink forms ONE dominant blob and whether it LOOKS text-banded (>=3
   rows). A short, dense theorem statement or a solid-fill banner is
   both "one dominant blob" AND "too few text-line bands" -- it passes
   as a figure on those two signals alone.

   The signal that actually separates them, measured across all 68 real
   candidates: INK COVERAGE (fraction of the bbox that is non-background
   "ink"). All 13 confirmed real figures measured 0.048-0.168 (thin
   curve/axis strokes over mostly-blank grid paper). All 4 false
   positives measured 0.222-0.454 (solid glyph fill / banner fill is
   much denser per unit area than line art). This module adds that
   signal and requires it alongside the existing dominance/banding
   signals, rather than replacing them.

2. OVERSIZED BBOXES (6 of 68, the NEEDS_CORRECTION set): in every one of
   these, refine_visual_elements.py's connected-component pixel growth
   correctly found the figure, but ALSO absorbed an adjacent descriptive
   paragraph (intro statement above/beside the graph, or a trailing
   question list below it) into the SAME connected component, because
   the whitespace gap between "paragraph" and "graph" in this book's
   layout is frequently smaller than 2x the dilation radius used to
   bridge a figure's own disjoint parts (curve vs axis-label). Once
   they're one connected blob, growth can't tell them apart.

   Fix: after growth, split the (still oversized) bbox back into
   horizontal/vertical bands (same banding technique as
   evaluate_visual_elements.py) and drop the bands at the EDGES that
   look like paragraph text -- wide (spans most of the band's width)
   AND internally non-dominant (a paragraph's ink is many separate
   glyph/word blobs, not one continuous stroke) -- stopping as soon as a
   graphical band is reached. This is NOT a blind whitespace trim: a
   figure's own thin edge content (an axis label, a lone tick number)
   stays, because on its own it does not look like a multi-line
   paragraph band.

Both fixes were verified against the SAME 68-candidate ground truth
before being kept -- see detect_visual_elements_v2.py and
data/output/visual_detection_v2_evaluation.json for the actual
before/after numbers. Thresholds below are calibrated from that data,
not chosen a priori; each is documented with the real values that
justified it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

# --- Shared low-level pixel helpers (deliberately consistent with the
# existing adaptive-background approach in evaluate_visual_elements.py /
# refine_visual_elements.py, so all three stages agree on what "ink" means) ---

INK_DEVIATION_THRESHOLD = 60
COMPONENT_DILATION_RADIUS = 3
ROW_INK_FRACTION_THRESHOLD = 0.01
MIN_BAND_HEIGHT_PX = 15

# --- Classification thresholds, calibrated against all 68 Chapter 1
# candidates + their visually-confirmed ground truth (see module docstring
# and visual_detection_v2_evaluation.json for the full table) ---

# All 13 confirmed real figures measured ink_coverage 0.048-0.168; the
# nearest false positive (a decorative banner) measured 0.222. The floor
# sits in between, closer to the false-positive side for safety margin.
FIGURE_MAX_INK_COVERAGE = 0.19

# All 13 confirmed real figures measured dominant_fraction >= 0.51 (a
# curve is one continuous stroke, or a small number of them). Ordinary
# multi-line paragraph text measured 0.03-0.23 (separate glyphs/words
# never bridge into one blob at this dilation radius).
FIGURE_MIN_DOMINANT_FRACTION = 0.5

# All 13 confirmed real figures had at least one row-band spanning
# >=0.89 of the bbox width (the curve/grid/axis crosses most of the
# figure). Used together with the two signals above -- alone it would
# also match some short-line text boxes.
FIGURE_MIN_BAND_WIDTH_FRAC = 0.85

# Decorative pill/banner shapes (page_006_candidate_06, page_019_candidate_03,
# page_025_candidate_01, ...): a large fraction of the bbox is solid fill
# (ink_coverage 0.22-0.47, well above real figures) AND that fill is one
# dominant blob (>=0.84) AND the shape is a wide, short bar (aspect ratio
# >=3). Ordinary theorem/definition boxes are usually less elongated.
DECORATIVE_MIN_INK_COVERAGE = 0.30
DECORATIVE_MIN_DOMINANT_FRACTION = 0.75
DECORATIVE_MIN_ASPECT_RATIO = 3.0

# Conservative, best-effort table signal: many long, dense horizontal
# ink runs (row rulings/dense cell borders) AND at least a few vertical
# ones (column separators). Real tables in this chapter measured
# h_rulings 98-236 (all real figures measured <=11 -- their "rulings"
# are just dashed grid lines/axes, much shorter runs). Known limitation
# (documented, not silently hidden): a table with colored cell bands but
# no drawn separator lines (page_008_candidate_03) does not trip this
# and falls through to TEXT_BLOCK instead -- still correctly excluded
# from the figure queue, just mislabeled. find_tables() (PyMuPDF) cannot
# help here at all: this PDF has no vector/text layer for it to analyze
# (see detect_visual_elements.py's docstring), it only ever "succeeds"
# by finding nothing.
TABLE_MIN_H_RULINGS = 50
TABLE_MIN_V_RULINGS = 4
TABLE_MIN_INK_COVERAGE = 0.25
# A table's own cells are separate blobs; nothing in the 3 confirmed
# tables measured above 0.78 dominant_fraction. A candidate that is
# BOTH ruled-grid-like AND almost entirely one dominant blob (>0.85) is
# more likely a figure directly touching a ruled box than a real table
# -- safety margin for the mixed page_018_candidate_01 case (a theorem
# box glued to a graph with no whitespace gap between them).
TABLE_MAX_DOMINANT_FRACTION = 0.85

# Ordinary multi-line prose in this book measured 3-9 bands, all with
# dominant_fraction < 0.5 (separate word/line blobs never merge). But a
# figure whose oversized V1 crop still includes ONE adjacent
# intro/exercise-statement paragraph (not fully trimmed by
# trim_text_margins -- see its docstring) can also show 4-5 bands with
# similarly low whole-box dominant_fraction, because the sparse graph
# ink dilutes the average. Requiring >=5 bands before treating banding
# as a confident, hard "not a figure" signal keeps every observed real
# mixed figure+text case (all measured <=5 bands after best-effort
# trimming) out of the hard exclusion, at the cost of a few extra
# genuinely-pure short text boxes falling back to AMBIGUOUS instead of
# TEXT_BLOCK -- an intentional, safety-first trade-off (see module
# docstring: preserving real figures outranks precision).
TEXT_HARD_MIN_BANDS = 5
RULING_SPAN_FRACTION = 0.7
RULING_DENSITY_FRACTION = 0.85


def dominant_color(region: np.ndarray, bin_size: int = 8) -> np.ndarray:
    flat = region.reshape(-1, 3)
    binned = (flat // bin_size) * bin_size
    keys = binned[:, 0].astype(np.int32) * 65536 + binned[:, 1].astype(np.int32) * 256 + binned[:, 2].astype(np.int32)
    values, counts = np.unique(keys, return_counts=True)
    top = int(values[np.argmax(counts)])
    return np.array([(top >> 16) & 255, (top >> 8) & 255, top & 255])


def adaptive_ink_mask(region: np.ndarray) -> np.ndarray:
    """A pixel is 'ink' if it deviates from THIS region's own dominant
    background color -- so a pastel callout tint isn't misread as ink."""
    bg = dominant_color(region)
    diff = np.abs(region.astype(np.int16) - bg.astype(np.int16))
    return diff.max(axis=2) > INK_DEVIATION_THRESHOLD


def dominant_component_fraction(ink: np.ndarray) -> float:
    if ink.size == 0 or not ink.any():
        return 0.0
    yy, xx = np.ogrid[-COMPONENT_DILATION_RADIUS:COMPONENT_DILATION_RADIUS + 1, -COMPONENT_DILATION_RADIUS:COMPONENT_DILATION_RADIUS + 1]
    disk = (xx * xx + yy * yy) <= COMPONENT_DILATION_RADIUS * COMPONENT_DILATION_RADIUS
    dilated = ndimage.binary_dilation(ink, structure=disk)
    labeled, n = ndimage.label(dilated, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0
    sizes = ndimage.sum(dilated, labeled, range(1, n + 1))
    return float(sizes.max() / sizes.sum())


@dataclass
class Band:
    start: int
    end: int
    width_frac: float
    dominant_frac: float

    @property
    def height(self) -> int:
        return self.end - self.start


def _bands_along_axis(ink: np.ndarray, axis: int) -> list[Band]:
    """axis=0: horizontal row-bands (for top/bottom trimming); axis=1:
    vertical column-bands (for left/right trimming, via a transposed mask)."""
    profile = ink.mean(axis=1 - axis if ink.ndim == 2 else axis)
    has_ink = profile > ROW_INK_FRACTION_THRESHOLD
    spans, start = [], None
    for i, v in enumerate(has_ink):
        if v and start is None:
            start = i
        elif not v and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(has_ink)))

    bands = []
    total = ink.shape[1 - axis] if axis == 0 else ink.shape[0]
    for s, e in spans:
        if e - s < MIN_BAND_HEIGHT_PX:
            continue
        strip = ink[s:e, :] if axis == 0 else ink[:, s:e]
        cross_axis = strip.any(axis=0) if axis == 0 else strip.any(axis=1)
        idx = np.where(cross_axis)[0]
        width_frac = (idx.max() - idx.min() + 1) / total if len(idx) else 0.0
        bands.append(Band(s, e, width_frac, dominant_component_fraction(strip)))
    return bands


def row_bands(ink: np.ndarray) -> list[Band]:
    return _bands_along_axis(ink, axis=0)


def column_bands(ink: np.ndarray) -> list[Band]:
    return _bands_along_axis(ink, axis=1)


def ruling_line_counts(ink: np.ndarray) -> tuple[int, int]:
    """Count rows/columns that look like a solid ruling line: ink spans
    most of the width/height AND is nearly continuous across that span
    (a drawn line/dense cell border), as opposed to sparse text glyphs
    or a curve (which only occupies a narrow x-range per row)."""
    h, w = ink.shape
    horiz = 0
    for r in range(h):
        xs = np.where(ink[r])[0]
        if len(xs) < 2:
            continue
        span = xs.max() - xs.min() + 1
        if span / w > RULING_SPAN_FRACTION and len(xs) / span > RULING_DENSITY_FRACTION:
            horiz += 1
    vert = 0
    for c in range(w):
        ys = np.where(ink[:, c])[0]
        if len(ys) < 2:
            continue
        span = ys.max() - ys.min() + 1
        if span / h > RULING_SPAN_FRACTION and len(ys) / span > RULING_DENSITY_FRACTION:
            vert += 1
    return horiz, vert


@dataclass
class CandidateFeatures:
    ink_coverage: float
    dominant_fraction: float
    n_row_bands: int
    max_row_band_width_frac: float
    aspect_ratio: float
    h_rulings: int
    v_rulings: int
    likely_text_box: bool
    row_bands: list[Band] = field(default_factory=list)
    column_bands: list[Band] = field(default_factory=list)


def extract_features(page_array: np.ndarray, bbox: list[int], likely_text_box: bool) -> CandidateFeatures:
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)
    bands = row_bands(ink)
    cbands = column_bands(ink)
    h_rulings, v_rulings = ruling_line_counts(ink)
    return CandidateFeatures(
        ink_coverage=float(ink.mean()),
        dominant_fraction=dominant_component_fraction(ink),
        n_row_bands=len(bands),
        max_row_band_width_frac=max((b.width_frac for b in bands), default=0.0),
        aspect_ratio=(x1 - x0) / max(1, (y1 - y0)),
        h_rulings=h_rulings,
        v_rulings=v_rulings,
        likely_text_box=likely_text_box,
        row_bands=bands,
        column_bands=cbands,
    )


def classify(f: CandidateFeatures) -> tuple[str, str]:
    """Returns (category, reason). category is one of FIGURE, TABLE,
    TEXT_BLOCK, DECORATIVE, AMBIGUOUS. Signals are required to AGREE
    (never let one veto the other) -- disagreement always falls to
    AMBIGUOUS, so a genuine figure that misses one signal is still
    surfaced for human review, never silently dropped."""
    if f.likely_text_box:
        return "TEXT_BLOCK", "tinted callout/reminder box background"

    if (
        f.ink_coverage >= DECORATIVE_MIN_INK_COVERAGE
        and f.dominant_fraction >= DECORATIVE_MIN_DOMINANT_FRACTION
        and f.aspect_ratio >= DECORATIVE_MIN_ASPECT_RATIO
    ):
        return "DECORATIVE", (
            f"wide solid-fill shape (ink_coverage={f.ink_coverage:.2f}, "
            f"dominant_fraction={f.dominant_fraction:.2f}, aspect_ratio={f.aspect_ratio:.1f}) -- banner/pill/heading, not a figure"
        )

    if (
        f.h_rulings >= TABLE_MIN_H_RULINGS
        and f.v_rulings >= TABLE_MIN_V_RULINGS
        and f.ink_coverage >= TABLE_MIN_INK_COVERAGE
        and f.dominant_fraction <= TABLE_MAX_DOMINANT_FRACTION
    ):
        return "TABLE", f"regular ruled grid ({f.h_rulings} horizontal / {f.v_rulings} vertical ruling lines)"

    if (
        f.ink_coverage <= FIGURE_MAX_INK_COVERAGE
        and f.dominant_fraction >= FIGURE_MIN_DOMINANT_FRACTION
        and f.max_row_band_width_frac >= FIGURE_MIN_BAND_WIDTH_FRAC
    ):
        return "FIGURE", (
            f"sparse ink (coverage={f.ink_coverage:.2f}) forming one dominant connected stroke "
            f"({f.dominant_fraction:.2f}) spanning {f.max_row_band_width_frac:.2f} of the crop width"
        )

    if f.n_row_bands >= TEXT_HARD_MIN_BANDS and f.dominant_fraction < FIGURE_MIN_DOMINANT_FRACTION:
        return "TEXT_BLOCK", f"{f.n_row_bands} text-line bands, no dominant graphical stroke"

    return "AMBIGUOUS", "signals disagree or are inconclusive -- needs human review"


def _is_text_like_band(band: Band) -> bool:
    """A band 'looks like a paragraph strip': it spans most of the
    available width AND its own ink is NOT one continuous stroke (many
    separate glyph/word blobs) -- a real figure's edge content (an axis
    label, a lone tick number) is narrow (low width_frac) even when it
    sits in its own band."""
    return band.width_frac >= 0.7 and band.dominant_frac < 0.5


def _trim_edge_bands(bands: list[Band], total_span: int) -> tuple[int, int] | None:
    """Given bands covering [0, total_span), drop text-like bands from
    both ends until a non-text-like (graphical) band is reached on each
    side. Returns the (start, end) of the surviving core, or None if
    there is nothing to trim / not enough bands to safely judge.

    Deliberately edge-inward only (not "find the best band anywhere and
    expand"): an anchor-and-expand version was tried and discarded --
    against the real 6 NEEDS_CORRECTION cases it occasionally anchored
    on a dense heading/banner band instead of the actual figure band
    and trimmed the real figure OUT of the crop. Edge-inward can miss a
    figure buried between two text blocks (page_016_candidate_01), but
    it never actively removes a figure it already has -- see
    classify_visual_elements_v2's module docstring and
    visual_detection_v2_evaluation.json for the documented trade-off."""
    if len(bands) < 2:
        return None

    lo, hi = 0, len(bands) - 1
    while lo < hi and _is_text_like_band(bands[lo]):
        lo += 1
    while hi > lo and _is_text_like_band(bands[hi]):
        hi -= 1

    if lo == 0 and hi == len(bands) - 1:
        return None  # nothing trimmed

    core_start, core_end = bands[lo].start, bands[hi].end
    # Never trim away more than 60% of the original span -- a safety
    # backstop against an unexpected band pattern being over-aggressive.
    if (core_end - core_start) < 0.4 * total_span:
        return None
    return core_start, core_end


def trim_text_margins(page_array: np.ndarray, bbox: list[int]) -> tuple[list[int], bool]:
    """Conservatively shrink `bbox` to exclude paragraph-text bands at
    its top/bottom/left/right edges, keeping any graphical core intact.
    Returns (new_bbox, changed). Never expands, never returns an empty
    box, and leaves bbox untouched when the band pattern is not a clear
    text-margin case (safety over aggressiveness, per design brief)."""
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)
    if not ink.any():
        return list(bbox), False

    changed = False
    height, width = ink.shape

    rows = row_bands(ink)
    vertical_trim = _trim_edge_bands(rows, height)
    if vertical_trim:
        new_y0, new_y1 = y0 + vertical_trim[0], y0 + vertical_trim[1]
        changed = True
    else:
        new_y0, new_y1 = y0, y1

    cols = column_bands(ink)
    horizontal_trim = _trim_edge_bands(cols, width)
    if horizontal_trim:
        new_x0, new_x1 = x0 + horizontal_trim[0], x0 + horizontal_trim[1]
        changed = True
    else:
        new_x0, new_x1 = x0, x1

    if not changed:
        return list(bbox), False

    # Small safety margin so a label right at the new edge isn't clipped.
    margin = 10
    trimmed = [
        max(x0, new_x0 - margin),
        max(y0, new_y0 - margin),
        min(x1, new_x1 + margin),
        min(y1, new_y1 + margin),
    ]
    return trimmed, True
