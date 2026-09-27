"""
Phase 4g (V3) - figure BBOX COMPLETENESS refinement.

WHY THIS EXISTS -- concrete evidence, not guesswork:

Manual inspection of the V2 contact sheet found real figures whose V2
crop was missing part of the figure -- e.g. page_025's three-curve
comparison graph (C1/C2/C3) had its right-hand "(C1)" curve label and
its bottom axis tick-number row cut off. Root cause, confirmed by
re-running classify_visual_elements_v2.py's own row/column banding on
that exact candidate: `trim_text_margins` decides what to KEEP by
looking at contiguous ink BANDS (a row or column strip where the mean
ink density across the WHOLE opposite axis clears 1%). A small, sparse
label like "(C1)" (just a few characters, in one narrow row/column
range) does not move that whole-axis mean above 1% -- so it produces NO
band at all, and `trim_text_margins` silently treats "no band" as "not
part of the figure" and clips it away. This is a real, structural
limitation of a BANDING approach: it can only ever include or exclude
whole rows/columns, and a small graphical element well inside the
figure's true extent can be too sparse to register as its own row/
column band, especially near an edge.

THE FIX -- CONNECTED COMPONENTS, not banding:

Instead of asking "does this whole row/column look like ink", this
stage asks "what is physically connected to (or a small label sitting
right next to) the figure's own core stroke mass", the same underlying
idea `refine_visual_elements.py` already uses for pixel-based bbox
growth, but applied a second time, AFTER classification, with a
completeness-specific twist: connected components are merged into the
kept region unconditionally when they touch/are close to the core, but
a component is only merged when it is SMALL (label-sized) -- a large,
paragraph-sized component sitting just outside the core is exactly what
V2's classification-stage trimming was built to keep out, and this
stage must never undo that.

This is a SEPARATE, additive stage on top of V2 (V2's own report/crops/
classification are never modified or re-run) -- see
refine_completeness_for_v3.py for the orchestration that reads
visual_elements_report_v2.json and writes visual_elements_report_v3.json
+ figure_candidates_v3/.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from classify_visual_elements_v2 import adaptive_ink_mask

# How far (pixels, same space as bbox) beyond the V2 bbox to search for
# missing fragments. Bounded and small -- V1's phase-4b growth already
# established a safe outer whitespace boundary around the whole figure
# (see refine_visual_elements.py); this stage recovers content V2's
# classification-time trimming may have cut from INSIDE that boundary,
# not a fresh from-scratch growth.
SEARCH_MARGIN_PX = 50

# Dilation radius for bridging a figure's own disjoint parts (curve vs
# axis label, separate branch, etc.) before connected-component
# labeling. Matches the same order of magnitude already validated for
# this exact purpose in refine_visual_elements.py
# (FIGURE_REFINEMENT_DILATION_RADIUS_PX = 20).
DILATION_RADIUS_PX = 15

# A component is eligible to be merged in as "a label/small graphical
# fragment belonging to the figure" only if it is small in BOTH
# dimensions. Calibrated generously above real observed label sizes
# (e.g. a "(C1)" curve tag measured ~97x25px) and well below real
# paragraph text component widths (400-1900px in this chapter's actual
# rejected text boxes) -- see figure_completeness_v3 test fixtures for
# the boundary cases this must get right.
LABEL_MAX_WIDTH_PX = 260
LABEL_MAX_HEIGHT_PX = 130

# Max gap (pixels) between a candidate component and the current kept
# region for it to still be considered "belonging to the same figure".
MERGE_GAP_PX = 45

# Safety backstop: never let the completeness pass grow the box to more
# than this multiple of the V2 bbox's own area -- a runaway merge into
# unrelated page content (which would indicate a bad anchor) is
# rejected wholesale, keeping the V2 bbox unchanged instead.
MAX_AREA_GROWTH_RATIO = 3.0


def _components(mask: np.ndarray, dilation_radius: int) -> tuple[np.ndarray, int]:
    yy, xx = np.ogrid[-dilation_radius:dilation_radius + 1, -dilation_radius:dilation_radius + 1]
    disk = (xx * xx + yy * yy) <= dilation_radius * dilation_radius
    dilated = ndimage.binary_dilation(mask, structure=disk)
    return ndimage.label(dilated, structure=np.ones((3, 3)))


def _bbox_of_labels(labeled: np.ndarray, labels: set[int]) -> tuple[int, int, int, int] | None:
    mask = np.isin(labeled, list(labels))
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    gap_x = max(0, max(bx0 - ax1, ax0 - bx1))
    gap_y = max(0, max(by0 - ay1, ay0 - by1))
    return max(gap_x, gap_y)


def refine_completeness(
    page_array: np.ndarray, v2_bbox: list[int], search_bbox: list[int] | None = None,
) -> tuple[list[int], bool]:
    """Grow `v2_bbox` to include any small, nearby, label-sized ink
    fragment that connected-component analysis shows belongs to the
    same figure -- without re-absorbing a paragraph-sized block V2
    already correctly excluded. Returns (new_bbox, changed); never
    shrinks, never returns something wildly larger (safety backstop),
    and leaves the bbox untouched if there's nothing to recover.

    `search_bbox`, when given, is V1's own already-whitespace-bounded
    refined bbox (pre_trim_bbox in the V2 report) -- reused as a KNOWN
    SAFE outer search limit instead of an arbitrary fixed margin. A
    first version of this function used a fixed +50px margin around
    v2_bbox and silently failed on real cases (page_011/page_013's
    curves) where V2's trim had cut MORE than 50px off the true extent
    -- the recovered component's own bbox touched the search window's
    edge (a clear "the true content goes further, we just can't see it"
    signal) but nothing detected that. Anchoring the search on V1's own
    bbox instead removes the guesswork: phase 4b already established
    that boundary via real pixel growth, so re-deriving a smaller one
    here was redundant AND lossy."""
    height, width = page_array.shape[:2]
    x0, y0, x1, y1 = v2_bbox
    if search_bbox:
        sx0, sy0, sx1, sy1 = search_bbox
        x0, y0, x1, y1 = min(x0, sx0), min(y0, sy0), max(x1, sx1), max(y1, sy1)
    wx0, wy0 = max(0, x0 - SEARCH_MARGIN_PX), max(0, y0 - SEARCH_MARGIN_PX)
    wx1, wy1 = min(width, x1 + SEARCH_MARGIN_PX), min(height, y1 + SEARCH_MARGIN_PX)
    window = page_array[wy0:wy1, wx0:wx1]
    x0, y0, x1, y1 = v2_bbox  # anchor still centers on V2's own bbox, not the widened search area

    ink = adaptive_ink_mask(window)
    if not ink.any():
        return list(v2_bbox), False

    labeled, n = _components(ink, DILATION_RADIUS_PX)
    if n == 0:
        return list(v2_bbox), False

    # Anchor on whatever is under the CENTRAL 50% of the current bbox
    # (in window-local coords) -- deliberately not the full bbox, so an
    # edge label/axis-number row that V2 already (correctly or not)
    # trimmed close to never anchors the search; the figure's own dense
    # core stroke mass always does.
    lx0, ly0, lx1, ly1 = x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0
    cx0, cx1 = lx0 + (lx1 - lx0) * 0.25, lx0 + (lx1 - lx0) * 0.75
    cy0, cy1 = ly0 + (ly1 - ly0) * 0.25, ly0 + (ly1 - ly0) * 0.75
    cx0, cy0 = max(0, int(cx0)), max(0, int(cy0))
    cx1, cy1 = min(labeled.shape[1], int(cx1) + 1), min(labeled.shape[0], int(cy1) + 1)
    anchor_region = labeled[cy0:cy1, cx0:cx1]
    keep = set(np.unique(anchor_region)) - {0}
    if not keep:
        return list(v2_bbox), False

    core = _bbox_of_labels(labeled, keep)
    grown = True
    while grown:
        grown = False
        for lbl in range(1, n + 1):
            if lbl in keep:
                continue
            comp_bbox = _bbox_of_labels(labeled, {lbl})
            if comp_bbox is None:
                continue
            cbx0, cby0, cbx1, cby1 = comp_bbox
            comp_w, comp_h = cbx1 - cbx0, cby1 - cby0
            if comp_w > LABEL_MAX_WIDTH_PX or comp_h > LABEL_MAX_HEIGHT_PX:
                continue  # too big to be a label -- likely a paragraph, never merge
            if _gap(core, comp_bbox) > MERGE_GAP_PX:
                continue
            keep.add(lbl)
            core = _bbox_of_labels(labeled, keep)
            grown = True

    # Compare the final core against v2_bbox directly (not "did we merge
    # an extra component") -- the anchor's OWN component can already be
    # larger than v2_bbox once the search window is wide enough to
    # reveal it (e.g. an axis label that was always connected to the
    # curve, just previously cropped out of view), and that must count
    # as a real recovery too.
    margin = 10
    core_abs = [
        core[0] + wx0 - margin, core[1] + wy0 - margin,
        core[2] + wx0 + margin, core[3] + wy0 + margin,
    ]
    if (
        core_abs[0] >= v2_bbox[0] and core_abs[1] >= v2_bbox[1]
        and core_abs[2] <= v2_bbox[2] and core_abs[3] <= v2_bbox[3]
    ):
        return list(v2_bbox), False  # core is fully inside v2_bbox already -- nothing to recover

    original_area = max(1, (x1 - x0) * (y1 - y0))
    new_area = max(1, (core_abs[2] - core_abs[0]) * (core_abs[3] - core_abs[1]))
    if new_area > MAX_AREA_GROWTH_RATIO * original_area:
        return list(v2_bbox), False  # safety backstop -- anchor likely grabbed unrelated content

    final_bbox = _accept_safe_growth_per_edge(page_array, v2_bbox, core_abs)
    return final_bbox, final_bbox != list(v2_bbox)


# A single edge's growth beyond this (pixels) is not accepted outright
# -- calibrated against real Chapter 1 cases: legitimate label/tick-row
# recoveries needed 42-97px in their short dimension (page_011's "-3"
# tag: 77px; page_025's bottom axis-number row: 70px); the two real
# paragraph-reabsorption regressions this stage must avoid needed
# 123-129px (page_027's exercise-statement lines). There is a real,
# narrow, ~25px gap between those two clusters in the ONLY chapter this
# was calibrated against -- a genuine remaining limitation (documented
# in the final report) is that a label needing >100px of recovery (e.g.
# page_013's "-3" tag, at ~123px) is conservatively left unrecovered
# rather than risk reabsorbing a paragraph at a similar distance.
EDGE_STRIP_SAFE_PX = 110


def _accept_safe_growth_per_edge(page_array: np.ndarray, v2_bbox: list[int], candidate_bbox: list[int]) -> list[int]:
    """Grow_completeness's connected-component search can, in one single
    dilated blob, legitimately recover a small label AND (if the true
    gap between a figure and an adjacent paragraph is small enough for
    the dilation radius to bridge) illegitimately reabsorb that whole
    paragraph -- exactly the thing V2's classification-time trim was
    built to keep out. A per-component size cap alone doesn't catch
    this when it happens as ONE fused blob rather than a separate
    merged component (confirmed on page_027's two NEEDS_CORRECTION
    figures: the recovered blob included full lines of exercise text).
    So each of the 4 candidate edges is checked independently and only
    accepted if its own growth is within EDGE_STRIP_SAFE_PX -- see that
    constant's comment for the real measurements this trades off."""
    x0, y0, x1, y1 = v2_bbox
    cx0, cy0, cx1, cy1 = candidate_bbox

    final = [x0, y0, x1, y1]
    if cx0 < x0 and (x0 - cx0) <= EDGE_STRIP_SAFE_PX:
        final[0] = cx0
    if cy0 < y0 and (y0 - cy0) <= EDGE_STRIP_SAFE_PX:
        final[1] = cy0
    if cx1 > x1 and (cx1 - x1) <= EDGE_STRIP_SAFE_PX:
        final[2] = cx1
    if cy1 > y1 and (cy1 - y1) <= EDGE_STRIP_SAFE_PX:
        final[3] = cy1
    return final
