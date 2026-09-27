"""
Unit tests for figure_completeness_v3.py (Phase 4g / V3). Deterministic,
no LLM, no real page images -- synthetic pixel fixtures mirroring the
real Chapter 1 patterns this module was built against (see that
module's docstring and data/output/visual_detection_v3_evaluation.json
for the real-crop evidence).

Run:
    python test_figure_completeness_v3.py
    python -m unittest test_figure_completeness_v3
"""

import unittest

import numpy as np

from figure_completeness_v3 import refine_completeness


def blank_page(height=500, width=700):
    return np.full((height, width, 3), 255, dtype=np.uint8)


def draw_axis(page, x0, x1, y0, y1, origin_x, origin_y):
    page[origin_y:origin_y + 2, x0:x1] = 0
    page[y0:y1, origin_x:origin_x + 2] = 0


def draw_curve(page, x0, x1, y0, y1, thickness=3):
    xs = np.linspace(x0, x1 - 1, x1 - x0).astype(int)
    ys = np.linspace(y0, y1 - 1, x1 - x0).astype(int)
    for x, y in zip(xs, ys):
        page[max(0, y - thickness):y + thickness, x] = 0


def draw_label(page, x0, y0, w=40, h=18):
    page[y0:y0 + h, x0:x0 + w] = 0


def draw_paragraph(page, y0, n_lines, x0, x1, line_height=20, gap=12):
    for i in range(n_lines):
        y = y0 + i * (line_height + gap)
        word_width = (x1 - x0) // 12
        x = x0
        for _ in range(6):
            page[y:y + line_height, x:x + word_width] = 0
            x += word_width * 2


class TestFigureCompleteness(unittest.TestCase):
    def test_graph_with_thin_axis_recovers_axis_line_just_outside_bbox(self):
        """1. A thin axis line sitting just outside the V2 bbox is
        recovered (never lost)."""
        page = blank_page()
        draw_axis(page, 50, 650, 100, 400, origin_x=350, origin_y=250)
        draw_curve(page, 50, 650, 120, 380)
        # V2 bbox clipped a bit inside the true extent of the axis/curve.
        v2_bbox = [70, 120, 630, 380]
        new_bbox, changed = refine_completeness(page, v2_bbox)
        self.assertTrue(changed)
        self.assertLessEqual(new_bbox[0], 55)
        self.assertGreaterEqual(new_bbox[2], 645)

    def test_graph_with_thin_curve_is_not_cut(self):
        """2. A thin curve extending slightly beyond the V2 bbox is
        recovered."""
        page = blank_page()
        draw_axis(page, 50, 650, 100, 400, origin_x=350, origin_y=250)
        draw_curve(page, 50, 650, 120, 380)
        v2_bbox = [60, 130, 600, 370]
        new_bbox, changed = refine_completeness(page, v2_bbox)
        self.assertTrue(changed)
        self.assertLessEqual(new_bbox[2] - new_bbox[0], 700)  # sane, no runaway growth
        self.assertGreaterEqual(new_bbox[2], 595)

    def test_label_separated_from_curve_is_recovered(self):
        """3. A small curve-name label sitting a short gap away from the
        curve/axis (disconnected pixels) is still recovered."""
        page = blank_page()
        draw_axis(page, 50, 650, 100, 400, origin_x=350, origin_y=250)
        draw_curve(page, 50, 650, 120, 380)
        draw_label(page, 600, 130)  # a short gap above the curve's endpoint
        v2_bbox = [70, 150, 590, 380]  # clipped just before the label
        new_bbox, changed = refine_completeness(page, v2_bbox)
        self.assertTrue(changed)
        self.assertGreaterEqual(new_bbox[2], 640)
        self.assertLessEqual(new_bbox[1], 135)

    def test_multiple_disconnected_fragments_are_unified(self):
        """4. A figure made of several disconnected pieces (axis, curve,
        two separate point labels) is still treated as one object."""
        page = blank_page()
        draw_axis(page, 50, 650, 100, 400, origin_x=350, origin_y=250)
        draw_curve(page, 50, 650, 120, 380)
        draw_label(page, 60, 110)     # top-left label, gap from axis
        draw_label(page, 610, 385)    # bottom-right label, gap from curve
        v2_bbox = [90, 140, 580, 370]  # clipped inside, missing both labels
        new_bbox, changed = refine_completeness(page, v2_bbox)
        self.assertTrue(changed)
        self.assertLessEqual(new_bbox[0], 65)
        self.assertGreaterEqual(new_bbox[2], 635)

    def test_figure_next_to_text_does_not_reabsorb_paragraph(self):
        """5. A paragraph beside the figure, close enough that dilation
        could bridge the gap, must NOT be reabsorbed even if a bit of
        it lies just outside the (already-correct) V2 bbox."""
        page = blank_page(height=500, width=900)
        draw_paragraph(page, 40, n_lines=5, x0=40, x1=380)
        draw_axis(page, 420, 860, 100, 400, origin_x=600, origin_y=250)
        draw_curve(page, 420, 860, 120, 380)
        v2_bbox = [420, 100, 860, 400]  # already tight around the figure only
        new_bbox, _ = refine_completeness(page, v2_bbox)
        self.assertGreaterEqual(new_bbox[0], 390)  # must not cross into the paragraph (small fixed safety margin allowed)

    def test_figure_below_text_does_not_reabsorb_paragraph(self):
        """6. Same, with the paragraph stacked above the figure instead
        of beside it."""
        page = blank_page(height=700, width=700)
        draw_paragraph(page, 20, n_lines=5, x0=40, x1=650)
        draw_axis(page, 50, 650, 320, 620, origin_x=350, origin_y=470)
        draw_curve(page, 50, 650, 340, 600)
        v2_bbox = [50, 320, 650, 620]  # already tight around the figure only
        new_bbox, _ = refine_completeness(page, v2_bbox)
        self.assertGreaterEqual(new_bbox[1], 290)  # must not creep up into the paragraph (small fixed safety margin allowed)

    def test_figure_with_surrounding_paragraph_on_all_sides(self):
        """7. A figure boxed in by paragraph text above AND below stays
        bounded to the figure -- oversized-crop protection must hold
        even when V3's own search window is generous."""
        page = blank_page(height=1000, width=700)
        draw_paragraph(page, 20, n_lines=4, x0=40, x1=650)
        draw_axis(page, 50, 650, 320, 520, origin_x=350, origin_y=420)
        draw_curve(page, 50, 650, 340, 500)
        draw_paragraph(page, 660, n_lines=4, x0=40, x1=650)
        v2_bbox = [50, 320, 650, 520]
        new_bbox, _ = refine_completeness(page, v2_bbox)
        self.assertGreaterEqual(new_bbox[1], 290)
        self.assertLessEqual(new_bbox[3], 550)

    def test_oversized_crop_is_not_grown_further(self):
        """8. If V2's bbox already (incorrectly) includes a paragraph,
        V3 must not make it WORSE by growing it even larger -- it should
        leave an already-oversized box alone rather than compounding
        the problem."""
        page = blank_page(height=700, width=700)
        draw_paragraph(page, 20, n_lines=5, x0=40, x1=650)
        draw_axis(page, 50, 650, 320, 620, origin_x=350, origin_y=470)
        draw_curve(page, 50, 650, 340, 600)
        oversized_v2_bbox = [30, 10, 660, 630]  # already includes the paragraph
        new_bbox, _ = refine_completeness(page, oversized_v2_bbox)
        area_before = (oversized_v2_bbox[2] - oversized_v2_bbox[0]) * (oversized_v2_bbox[3] - oversized_v2_bbox[1])
        area_after = (new_bbox[2] - new_bbox[0]) * (new_bbox[3] - new_bbox[1])
        self.assertLessEqual(area_after, area_before * 1.15)  # small fixed safety margin allowed, not unbounded growth


class TestSafetyInvariants(unittest.TestCase):
    def test_never_shrinks_below_v2_bbox(self):
        page = blank_page()
        draw_axis(page, 50, 650, 100, 400, origin_x=350, origin_y=250)
        draw_curve(page, 50, 650, 120, 380)
        v2_bbox = [200, 200, 500, 300]  # well inside the drawn content
        new_bbox, _ = refine_completeness(page, v2_bbox)
        self.assertLessEqual(new_bbox[0], v2_bbox[0])
        self.assertLessEqual(new_bbox[1], v2_bbox[1])
        self.assertGreaterEqual(new_bbox[2], v2_bbox[2])
        self.assertGreaterEqual(new_bbox[3], v2_bbox[3])

    def test_blank_region_is_a_no_op(self):
        page = blank_page()
        bbox = [10, 10, 100, 100]
        new_bbox, changed = refine_completeness(page, bbox)
        self.assertFalse(changed)
        self.assertEqual(new_bbox, bbox)


if __name__ == "__main__":
    unittest.main()
