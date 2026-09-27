"""
Phase 5a - deterministic figure crop correction.

Generic, reusable utility: given a page image and a bbox that is known
to CONTAIN a real figure plus some surrounding non-figure content (a
NEEDS_CORRECTION candidate), compute a tighter bbox that keeps the
figure's own graphical ink (curves, axes, geometric shapes) and its
close labels/tick values, while excluding attached paragraph text --
regardless of whether that text sits above, below, or beside the
figure. Nothing here is specific to Chapter 1 or to any candidate ID;
the six real NEEDS_CORRECTION crops from Chapter 1 are used only to
TEST this module (see test_crop_correction.py), never to special-case it.

APPROACH -- identify the figure first, not the text:

Earlier stages (classify_visual_elements_v2.py's trim_text_margins,
figure_completeness_v3.py's refine_completeness) both start from the
CURRENT (already-established) bbox edges and decide what to trim/grow
at each edge using row/column banding. That works well when the
attached text is cleanly above/below/beside the figure with a full-
width or full-height gap, but fails when text sits in a separate
COLUMN next to the figure (banding operates on whole rows/columns) or
when several unrelated text blocks surround the figure on multiple
sides (page_016_candidate_01: banner, theorem text, activity text, and
demonstration text all around one embedded graph).

This module instead ANCHORS on the figure's own ink directly: within
the given (oversized) bbox, find every connected ink component (after a
dilation just large enough to bridge a curve's own dashes/gaps and any
label sitting close to it -- same radius already validated for this
purpose in figure_completeness_v3.py); classify each component as
"graphical" (sparse relative to its own bounding box -- a curve, axis,
or geometric outline is never a dense rectangle of ink) or "text-like"
(dense, or large and dense enough to be a paragraph block); take the
union of the graphical components as the figure's core; then absorb
any SMALL nearby component (a tick label, curve tag, point name) within
a short gap of that core, however it looks, since a real annotation
belonging to the figure is small no matter its own density. Large or
distant components (paragraph text, headings, unrelated boxes) are
never absorbed, wherever they sit relative to the core.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from classify_visual_elements_v2 import adaptive_ink_mask, row_bands
from classify_visual_elements_v2 import trim_text_margins as _band_trim_text_margins

# Dilation radius (pixels, at the page images' native DPI) used to
# bridge a figure's own disjoint ink (dashed curve segments, an axis
# separated from a tick mark by anti-aliasing) into one connected
# component. Matches FIGURE_REFINEMENT_DILATION_RADIUS_PX /
# figure_completeness_v3.DILATION_RADIUS_PX, both already validated for
# the same purpose on this exact page-image resolution.
DILATION_RADIUS_PX = 15

# A component is "graphical" (part of the figure's own drawn structure)
# if it is large enough to matter AND sparse within its own bounding
# box -- a curve/axis/geometric outline never densely fills its own
# rectangle the way a block of text does. Matches the same fill-ratio
# philosophy validated in classify_visual_elements_v4.py against the 19
# real Chapter 1 figures.
#
# Fill ratio alone is NOT enough: a multi-line paragraph, once dilated
# enough to bridge line-to-line into one component, can ALSO read as
# "sparse" overall (real inter-line whitespace dilutes its density just
# like a curve's blank grid squares do -- confirmed on
# page_009_candidate_01's left-hand paragraph). Two more independent
# checks close this gap, matched against the SAME real component:
#   - n_bands: a real graph's ink is close to continuous top-to-bottom
#     (<=2 internal row-bands in every real figure component measured
#     here); a paragraph is ALWAYS split into as many bands as it has
#     text lines (>=4 measured on the same page's paragraph blocks).
#   - aspect ratio: a decorative full-width rule/banner component is
#     always far more elongated (12.6 measured for a page-width banner
#     bar) than any real figure component in this chapter (<=2.5).
GRAPHICAL_MAX_FILL_RATIO = 0.35
GRAPHICAL_MIN_AREA_FRAC = 0.03
GRAPHICAL_MAX_BANDS = 2
GRAPHICAL_MAX_ASPECT_RATIO = 8.0

# A component near the graphical core is absorbed as "belongs to the
# figure" (a tick label, curve tag, point name) only if it is small in
# BOTH dimensions and within a short gap of the core -- deliberately the
# same order of magnitude as figure_completeness_v3.py's
# LABEL_MAX_WIDTH_PX/LABEL_MAX_HEIGHT_PX/MERGE_GAP_PX, which were
# calibrated against real axis-label/curve-tag sizes in this chapter.
LABEL_MAX_WIDTH_PX = 260
LABEL_MAX_HEIGHT_PX = 130
MERGE_GAP_PX = 45

# Final safety margin added around the computed core so a label right
# at the new edge is not clipped.
OUTPUT_MARGIN_PX = 10

# A qualifying quadrant/half from _correct_crop_by_subregion_scan must
# retain at least this fraction of the ORIGINAL bbox's area -- every
# quadrant this scan can produce (at fracs 0.35-0.65) has area_frac
# between ~0.2275 and 0.25 of the original by construction, so this
# threshold is a guard against ever accepting something far smaller
# (e.g. a stray isolated heading), not a filter on normal quadrants.
MIN_SUBREGION_AREA_FRAC_OF_ORIGINAL = 0.15

# The post-selection _correct_crop_by_components refinement pass (see
# _correct_crop_by_subregion_scan) is only trusted to trim a REMAINING
# text edge within the already-selected quadrant, not to collapse it
# down to an unrelated small component inside it (e.g. a heading like
# "Activite 2" that happens to also look "graphical" on its own by the
# coarse checks). If refinement shrinks the selected sub-region by more
# than this, it is discarded in favour of the raw, unrefined sub-region.
REFINEMENT_MIN_AREA_FRAC_OF_SUBREGION = 0.3

# --- Density-valley split (see _correct_crop_by_density_split) ---
#
# A tinted theorem/callout box often has a subtle colour GRADIENT
# across its own background. adaptive_ink_mask picks ONE dominant
# colour for the whole region it is given, so across a large enough
# box, pixels far from that single sampled reference -- even genuine
# background -- register as false ink, silently bridging a figure to
# nearby text that would otherwise be clearly separated by whitespace
# (confirmed on page_018_candidate_01: the whole box read as one
# fill=0.64 blob even before any dilation). Tiling the reference colour
# (LOCAL_INK_TILE_PX) keeps it accurate across a gradient while still
# flagging real foreground ink (glyphs, curve strokes).
LOCAL_INK_TILE_PX = 32
LOCAL_INK_DEVIATION_THRESHOLD = 40

# The density profile (mean local-ink per column, or per row) is
# smoothed over a window scaled to the profile's own length before
# valley-searching, so single-pixel noise never registers as a "gap".
DENSITY_SMOOTHING_FRAC = 0.03

# Columns/rows below this absolute density are "unoccupied" -- used
# only to find where the real content starts/ends, so the valley
# search below never mistakes the bbox's own outer margin for a
# genuine internal gap between two blocks of content.
DENSITY_OCCUPIED_THRESHOLD = 0.02

# The valley search looks for the single lowest-density point strictly
# inside the occupied span (excluding this fraction of the span at
# each end, so it can never re-discover the occupied/margin boundary
# itself) and grows outward while density stays within
# DENSITY_VALLEY_TOLERANCE_RATIO of that minimum -- a real inter-block
# gap is a sustained low plateau, not a single sample.
DENSITY_VALLEY_INSET_FRAC = 0.1
DENSITY_VALLEY_TOLERANCE_RATIO = 1.6
MIN_VALLEY_WIDTH_FRAC = 0.02

# A raw (undilated) connected-component count, normalised by area, is
# the tie-breaker when BOTH sides of a density-valley split pass the
# coarse _region_is_graphical check (observed on page_016/018: a short
# 4-line theorem paragraph is sparse/low-band enough to pass that
# check too). Paragraph text is made of many small glyph/word
# components per unit area; a figure's ink (axis lines, one curve
# stroke, a few short labels) is not -- measured >=2x higher
# components-per-area on every real paragraph side tested here.
TEXT_COMPONENT_DENSITY_MIN_PX2 = 15


@dataclass
class CropCorrectionResult:
    bbox: list[int]
    changed: bool
    reason: str
    graphical_component_count: int


def _components(mask: np.ndarray, radius: int):
    if radius > 0:
        yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
        disk = (xx * xx + yy * yy) <= radius * radius
        mask = ndimage.binary_dilation(mask, structure=disk)
    return ndimage.label(mask, structure=np.ones((3, 3)))


def _bbox_of_labels(labeled: np.ndarray, labels: set[int]):
    mask = np.isin(labeled, list(labels))
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _gap(a, b) -> int:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    gap_x = max(0, max(bx0 - ax1, ax0 - bx1))
    gap_y = max(0, max(by0 - ay1, ay0 - by1))
    return max(gap_x, gap_y)


def _correct_crop_by_components(page_array: np.ndarray, bbox: list[int]) -> CropCorrectionResult:
    """Primary method: identify the figure's own graphical connected
    component(s) directly (see module docstring). Handles text that
    sits in a different COLUMN from the figure, or on several sides of
    it, which row/column banding cannot. Fails closed (returns
    unchanged) when the attached text is close enough to already be ONE
    connected component with the figure even before dilation -- no
    connected-component method can split an already-touching blob;
    correct_crop() falls back to band-based trimming for that case."""
    x0, y0, x1, y1 = bbox
    height, width = page_array.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    region = page_array[y0:y1, x0:x1]

    ink = adaptive_ink_mask(region)
    if not ink.any():
        return CropCorrectionResult(list(bbox), False, "no ink found in region", 0)

    labeled, n = _components(ink, DILATION_RADIUS_PX)
    if n == 0:
        return CropCorrectionResult(list(bbox), False, "no connected components found", 0)

    total_area = region.shape[0] * region.shape[1]
    # Density must come from the ORIGINAL (undilated) ink, not the
    # dilated mask: at DILATION_RADIUS_PX=15 (needed to bridge a
    # figure's own gaps into one component), a sparse curve's dilated
    # shape nearly fills its own bounding box just like text does --
    # dilation is only for CONNECTIVITY here, never for density.
    sizes = ndimage.sum(ink, labeled, range(1, n + 1))
    objs = ndimage.find_objects(labeled)

    graphical: set[int] = set()
    component_meta = {}
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        comp_h = sl[0].stop - sl[0].start
        comp_w = sl[1].stop - sl[1].start
        bbox_area = max(1, comp_h * comp_w)
        fill_ratio = sizes[i - 1] / bbox_area
        area_frac = bbox_area / total_area
        aspect_ratio = max(comp_w, comp_h) / max(1, min(comp_w, comp_h))
        n_bands = len(row_bands(ink[sl]))
        component_meta[i] = (comp_w, comp_h, fill_ratio, area_frac)
        if (
            area_frac >= GRAPHICAL_MIN_AREA_FRAC
            and fill_ratio <= GRAPHICAL_MAX_FILL_RATIO
            and n_bands <= GRAPHICAL_MAX_BANDS
            and aspect_ratio <= GRAPHICAL_MAX_ASPECT_RATIO
        ):
            graphical.add(i)

    if not graphical:
        return CropCorrectionResult(list(bbox), False, "no graphical (sparse, sufficiently large) component found", 0)

    keep = set(graphical)
    core = _bbox_of_labels(labeled, keep)

    grown = True
    while grown:
        grown = False
        for lbl, (comp_w, comp_h, _fill, _area) in component_meta.items():
            if lbl in keep:
                continue
            if comp_w > LABEL_MAX_WIDTH_PX or comp_h > LABEL_MAX_HEIGHT_PX:
                continue  # too big to be a label -- a paragraph/heading, never absorbed
            comp_bbox = _bbox_of_labels(labeled, {lbl})
            if comp_bbox is None or _gap(core, comp_bbox) > MERGE_GAP_PX:
                continue
            keep.add(lbl)
            core = _bbox_of_labels(labeled, keep)
            grown = True

    cx0, cy0, cx1, cy1 = core
    new_bbox = [
        max(x0, x0 + cx0 - OUTPUT_MARGIN_PX),
        max(y0, y0 + cy0 - OUTPUT_MARGIN_PX),
        min(x1, x0 + cx1 + OUTPUT_MARGIN_PX),
        min(y1, y0 + cy1 + OUTPUT_MARGIN_PX),
    ]
    changed = new_bbox != [x0, y0, x1, y1]
    reason = (
        f"component method: kept {len(keep)} component(s) ({len(graphical)} graphical + "
        f"{len(keep) - len(graphical)} absorbed label(s)); excluded {n - len(keep)} non-figure component(s)"
    )
    return CropCorrectionResult(new_bbox, changed, reason, len(graphical))


def _region_is_graphical(page_array: np.ndarray, bbox: list[int]) -> bool:
    x0, y0, x1, y1 = bbox
    if x1 - x0 < 20 or y1 - y0 < 20:
        return False
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)
    if not ink.any():
        return False
    total = region.shape[0] * region.shape[1]
    fill_ratio = float(ink.sum()) / total
    aspect_ratio = max(x1 - x0, y1 - y0) / max(1, min(x1 - x0, y1 - y0))
    bands = row_bands(ink)
    return fill_ratio <= GRAPHICAL_MAX_FILL_RATIO and aspect_ratio <= GRAPHICAL_MAX_ASPECT_RATIO and len(bands) <= GRAPHICAL_MAX_BANDS + 1


def _correct_crop_by_subregion_scan(page_array: np.ndarray, bbox: list[int]) -> CropCorrectionResult:
    """Third fallback: for a figure embedded WITHIN one quadrant/half of
    a larger mixed block (e.g. a theorem box with the graph drawn in its
    own right-hand portion, text filling the rest, AND more unrelated
    text below/beside the whole box) -- a pattern where neither
    connected components (figure+text already touch, no gap to split
    on) nor row/column banding (the graph and text share the same rows
    AND the same columns at different sub-positions) can succeed.

    Scans a fixed, generic geometric search pattern -- quadrants at a
    few split ratios, then halves only if no quadrant qualifies -- and
    keeps the SMALLEST/most targeted qualifying sub-rectangle: a
    quadrant is strictly more likely to have actually excluded an
    adjacent text region than a half covering the same side (a theorem
    box with text on the left and a graph on the right, both confined
    to the TOP half, is only correctly isolated by the top-right
    QUADRANT -- the top HALF alone still contains all of the left-hand
    text). Preferring quadrants first, not simply the largest qualifying
    rectangle, is what makes this actually exclude text rather than
    just enclose a bigger area that happens to still pass the coarse
    graphical check."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0

    def quadrants(frac: float):
        mx, my = x0 + int(w * frac), y0 + int(h * frac)
        return [
            [mx, y0, x1, my], [x0, y0, mx, my],  # top-right, top-left
            [mx, my, x1, y1], [x0, my, mx, y1],  # bottom-right, bottom-left
        ]

    def halves(frac: float):
        mx, my = x0 + int(w * frac), y0 + int(h * frac)
        return [[mx, y0, x1, y1], [x0, y0, mx, y1], [x0, my, x1, y1], [x0, y0, x1, my]]

    # A qualifying sub-region must still be a MEANINGFUL fraction of the
    # original block -- otherwise a small isolated heading/label (e.g.
    # "Activite 2", sparse and low-band on its own) can trivially pass
    # the coarse graphical check while being nowhere near the figure.
    min_area = MIN_SUBREGION_AREA_FRAC_OF_ORIGINAL * w * h

    best = None
    for frac in (0.5, 0.4, 0.6, 0.35, 0.65):
        for sub_bbox in quadrants(frac):
            area = (sub_bbox[2] - sub_bbox[0]) * (sub_bbox[3] - sub_bbox[1])
            if area >= min_area and _region_is_graphical(page_array, sub_bbox):
                if best is None or area < best[1]:
                    best = (sub_bbox, area)
        if best is not None:
            break  # a qualifying quadrant always wins over any half

    if best is None:
        for frac in (0.5, 0.4, 0.6):
            for sub_bbox in halves(frac):
                if _region_is_graphical(page_array, sub_bbox):
                    area = (sub_bbox[2] - sub_bbox[0]) * (sub_bbox[3] - sub_bbox[1])
                    if best is None or area > best[1]:
                        best = (sub_bbox, area)

    if best is None:
        return CropCorrectionResult(list(bbox), False, "no half/quadrant sub-region looked graphical either", 0)

    sub_bbox = best[0]
    # Re-run the component method WITHIN the winning sub-region to also
    # absorb any nearby small label just outside the raw half/quadrant
    # split (e.g. an axis label sitting just past the midline). Guard
    # against the refinement collapsing the quadrant down to an
    # unrelated small component inside it (see
    # REFINEMENT_MIN_AREA_FRAC_OF_SUBREGION above) -- fall back to the
    # raw sub-region if it does.
    refined = _correct_crop_by_components(page_array, sub_bbox)
    sub_area = (sub_bbox[2] - sub_bbox[0]) * (sub_bbox[3] - sub_bbox[1])
    if refined.changed:
        refined_area = (refined.bbox[2] - refined.bbox[0]) * (refined.bbox[3] - refined.bbox[1])
        final_bbox = refined.bbox if refined_area >= REFINEMENT_MIN_AREA_FRAC_OF_SUBREGION * sub_area else sub_bbox
    else:
        final_bbox = sub_bbox
    return CropCorrectionResult(final_bbox, True, "sub-region scan: figure found within one half/quadrant of the original bbox", 1)


def _local_ink_mask(region: np.ndarray, tile: int = LOCAL_INK_TILE_PX,
                     thresh: int = LOCAL_INK_DEVIATION_THRESHOLD) -> np.ndarray:
    """Like adaptive_ink_mask, but the 'dominant background colour' is
    computed separately PER TILE instead of once for the whole region
    -- see LOCAL_INK_TILE_PX above for why a single region-wide colour
    fails across a gradient-tinted box."""
    height, width = region.shape[:2]
    mask = np.zeros((height, width), dtype=bool)
    region16 = region.astype(np.int16)
    for ty in range(0, height, tile):
        for tx in range(0, width, tile):
            block = region16[ty:ty + tile, tx:tx + tile]
            bg = np.median(block.reshape(-1, 3), axis=0)
            mask[ty:ty + tile, tx:tx + tile] = np.abs(block - bg).max(axis=2) > thresh
    return mask


def _occupied_range(profile: np.ndarray, threshold: float = DENSITY_OCCUPIED_THRESHOLD) -> tuple[int, int]:
    idx = np.where(profile > threshold)[0]
    if len(idx) == 0:
        return 0, len(profile)
    return int(idx.min()), int(idx.max()) + 1


def _find_density_valley(profile: np.ndarray, lo_bound: int, hi_bound: int) -> tuple[int, int] | None:
    """Find the sustained low-density plateau strictly inside
    [lo_bound, hi_bound) -- a genuine whitespace corridor between two
    unrelated content blocks (as opposed to the lowest single sample,
    which is noise-sensitive). See DENSITY_VALLEY_* above."""
    span = hi_bound - lo_bound
    inset = max(1, int(span * DENSITY_VALLEY_INSET_FRAC))
    lo_search, hi_search = lo_bound + inset, hi_bound - inset
    if hi_search <= lo_search:
        return None

    interior = profile[lo_search:hi_search]
    min_idx = lo_search + int(np.argmin(interior))
    min_val = profile[min_idx]
    tolerance = min_val * DENSITY_VALLEY_TOLERANCE_RATIO + 1e-6

    lo = min_idx
    while lo - 1 > lo_search and profile[lo - 1] <= tolerance:
        lo -= 1
    hi = min_idx
    while hi + 1 < hi_search and profile[hi + 1] <= tolerance:
        hi += 1

    if hi + 1 - lo < max(1, int(MIN_VALLEY_WIDTH_FRAC * len(profile))):
        return None
    return lo, hi + 1


def _component_density_per_area(page_array: np.ndarray, bbox: list[int]) -> float:
    """Raw (undilated) connected ink components per 10,000px^2 -- see
    TEXT_COMPONENT_DENSITY_MIN_PX2 above: a discriminator between
    'paragraph text' (many small glyph/word components) and 'figure'
    (few, larger components) for two candidates that are otherwise
    both plausible by the coarse sparse/low-band checks alone."""
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)
    labeled, n = ndimage.label(ink, structure=np.ones((3, 3)))
    if n == 0:
        return 0.0
    sizes = ndimage.sum(ink, labeled, range(1, n + 1))
    significant = int((sizes >= TEXT_COMPONENT_DENSITY_MIN_PX2).sum())
    area = max(1, region.shape[0] * region.shape[1])
    return significant / area * 10_000


def _pick_graphical_side(page_array: np.ndarray, candidates: list[list[int]]) -> list[int] | None:
    """Given two (or more) candidate sub-bboxes from a density-valley
    split, return the one that is the figure, or None if this split
    isn't a usable text/figure separation at all."""
    qualifying = [c for c in candidates if _region_is_graphical(page_array, c)]
    if len(qualifying) == 1:
        return qualifying[0]
    if len(qualifying) > 1:
        # Both sides pass the coarse check (e.g. a short paragraph is
        # sparse/low-band enough too) -- break the tie with component
        # density (see TEXT_COMPONENT_DENSITY_MIN_PX2).
        return min(qualifying, key=lambda c: _component_density_per_area(page_array, c))
    return None


def _correct_crop_by_density_split(page_array: np.ndarray, bbox: list[int]) -> CropCorrectionResult:
    """Second fallback: for a figure sharing space with attached text
    that is already touching it (no gap for _correct_crop_by_components
    to split on) in a layout row/column banding cannot resolve either
    (text and figure occupy different COLUMNS within the same overall
    row-band, e.g. a theorem box with paragraph text on the left and a
    graph on the right -- classify_visual_elements_v2.trim_text_margins
    only trims whole-width/height edge bands, so a same-row column
    split is invisible to it).

    Finds the actual content boundary directly from the image instead
    of guessing a fixed split fraction: locates a genuine low-density
    corridor in a local (gradient-safe) ink-density profile, first
    across columns (within the bbox's own largest row-band, for
    side-by-side layouts), then across rows (full bbox, for stacked
    layouts) if no usable column split was found. Splits there and
    keeps whichever side is the figure."""
    x0, y0, x1, y1 = bbox
    region = page_array[y0:y1, x0:x1]
    ink = adaptive_ink_mask(region)
    if not ink.any():
        return CropCorrectionResult(list(bbox), False, "no ink for density split", 0)

    local_ink = _local_ink_mask(region)
    sub_bbox = None

    bands = row_bands(ink)
    if bands:
        main = max(bands, key=lambda b: b.end - b.start)
        strip = local_ink[main.start:main.end, :]
        if strip.size:
            profile = strip.mean(axis=0)
            k = max(3, int(len(profile) * DENSITY_SMOOTHING_FRAC))
            smoothed = np.convolve(profile, np.ones(k) / k, mode="same")
            occ_lo, occ_hi = _occupied_range(smoothed)
            valley = _find_density_valley(smoothed, occ_lo, occ_hi)
            if valley:
                mid = (valley[0] + valley[1]) // 2
                candidates = [
                    [x0, y0 + main.start, x0 + mid, y0 + main.end],
                    [x0 + mid, y0 + main.start, x1, y0 + main.end],
                ]
                sub_bbox = _pick_graphical_side(page_array, candidates)

    if sub_bbox is None:
        profile = local_ink.mean(axis=1)
        k = max(3, int(len(profile) * DENSITY_SMOOTHING_FRAC))
        smoothed = np.convolve(profile, np.ones(k) / k, mode="same")
        occ_lo, occ_hi = _occupied_range(smoothed)
        valley = _find_density_valley(smoothed, occ_lo, occ_hi)
        if valley:
            mid = (valley[0] + valley[1]) // 2
            candidates = [[x0, y0, x1, y0 + mid], [x0, y0 + mid, x1, y1]]
            sub_bbox = _pick_graphical_side(page_array, candidates)

    if sub_bbox is None:
        return CropCorrectionResult(list(bbox), False, "no usable density valley found on either axis", 0)

    # Refine within the winning side, with the same anti-collapse guard
    # used by _correct_crop_by_subregion_scan.
    refined = _correct_crop_by_components(page_array, sub_bbox)
    sub_area = (sub_bbox[2] - sub_bbox[0]) * (sub_bbox[3] - sub_bbox[1])
    if refined.changed:
        refined_area = (refined.bbox[2] - refined.bbox[0]) * (refined.bbox[3] - refined.bbox[1])
        final_bbox = refined.bbox if refined_area >= REFINEMENT_MIN_AREA_FRAC_OF_SUBREGION * sub_area else sub_bbox
    else:
        final_bbox = sub_bbox

    mx0, my0, mx1, my1 = final_bbox
    final_bbox = [
        max(x0, mx0 - OUTPUT_MARGIN_PX), max(y0, my0 - OUTPUT_MARGIN_PX),
        min(x1, mx1 + OUTPUT_MARGIN_PX), min(y1, my1 + OUTPUT_MARGIN_PX),
    ]
    return CropCorrectionResult(final_bbox, True, "density-valley split isolated the figure from attached text on one side", 1)


def correct_crop(page_array: np.ndarray, bbox: list[int]) -> CropCorrectionResult:
    """Compute a tightened bbox for a NEEDS_CORRECTION candidate. Only
    ever shrinks (or leaves unchanged) within the given bbox -- never
    expands beyond it, since the caller's bbox is already known to
    contain the complete figure (established by earlier pipeline
    stages); this stage only removes attached non-figure content.

    Complementary passes, tried in order -- each handles a real-world
    layout the previous one cannot:
      1. Connected-component analysis (see _correct_crop_by_components):
         works when there is a genuine whitespace gap between the
         figure and the attached text, however that text is arranged
         (a separate column beside the figure, several blocks on
         different sides), because it never assumes text is only
         above/below/beside in a whole-row/column sense.
      2. Row/column band trimming (classify_visual_elements_v2.
         trim_text_margins): a fallback for the opposite situation --
         text close enough to the figure that they are already ONE
         connected blob even before dilation (no connected-component
         split is possible), but still separable by ROW/COLUMN banding
         because the text still forms whole-width/height band(s) at an
         edge.
      3. Density-valley split (see _correct_crop_by_density_split): for
         text and figure that are both already touching AND share the
         same row-band at different column positions (or vice versa) --
         e.g. a theorem box with paragraph text on one side and a graph
         on the other, both edge-to-edge -- so neither of the above can
         separate them. Finds the real content boundary from a
         gradient-safe local ink-density profile instead of banding.
      4. Quadrant/half sub-region scan (see
         _correct_crop_by_subregion_scan): last-resort geometric scan
         for anything still unresolved.
    If nothing changes anything, the bbox is returned unchanged -- this
    stage never guesses, and the candidate stays fully reviewable (see
    review.json in the calling pipeline)."""
    component_result = _correct_crop_by_components(page_array, bbox)
    if component_result.changed:
        return component_result

    band_bbox, band_changed = _band_trim_text_margins(page_array, bbox)
    if band_changed:
        return CropCorrectionResult(
            band_bbox, True,
            "component method found nothing to change; band-trim fallback removed an edge text band",
            component_result.graphical_component_count,
        )

    density_result = _correct_crop_by_density_split(page_array, bbox)
    if density_result.changed:
        return density_result

    subregion_result = _correct_crop_by_subregion_scan(page_array, bbox)
    if subregion_result.changed:
        return subregion_result

    return CropCorrectionResult(
        list(bbox), False,
        f"no method found a safe correction ({component_result.reason})",
        component_result.graphical_component_count,
    )
