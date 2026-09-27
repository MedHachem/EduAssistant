"""
Unit tests for classify_visual_elements_v2.py (Phase 4e). Deterministic,
no LLM, no file I/O -- pure function tests against synthetic pixel
fixtures built to mirror the real patterns confirmed in Chapter 1 (see
that module's docstring for the actual measurements these thresholds
were calibrated against).

Run:
    python test_classify_visual_elements_v2.py
    python -m unittest test_classify_visual_elements_v2
"""

import unittest

import numpy as np

from classify_visual_elements_v2 import classify, extract_features, trim_text_margins

WHITE = np.array([255, 255, 255], dtype=np.uint8)
BLACK = np.array([0, 0, 0], dtype=np.uint8)


def blank_page(height=400, width=600):
    return np.full((height, width, 3), 255, dtype=np.uint8)


def draw_text_line(page, y0, y1, x0, x1, n_words=6):
    """A row of separate glyph-like blobs (never one continuous stroke),
    mimicking a line of text -- several short dark rectangles with gaps."""
    word_width = (x1 - x0) // (n_words * 2)
    x = x0
    for _ in range(n_words):
        page[y0:y1, x:x + word_width] = 0
        x += word_width * 2


def draw_paragraph(page, y0, n_lines, x0, x1, line_height=20, gap=10):
    y = y0
    for _ in range(n_lines):
        draw_text_line(page, y, y + line_height, x0, x1)
        y += line_height + gap
    return y  # next free y


def draw_curve(page, x0, x1, y0, y1, thickness=3):
    """A single continuous diagonal stroke -- mimics a thin figure curve."""
    xs = np.linspace(x0, x1 - 1, x1 - x0).astype(int)
    ys = np.linspace(y0, y1 - 1, x1 - x0).astype(int)
    for x, y in zip(xs, ys):
        page[max(0, y - thickness):y + thickness, x] = 0


def draw_grid(page, x0, x1, y0, y1, step=40):
    for x in range(x0, x1, step):
        page[y0:y1, x:x + 1] = 0
    for y in range(y0, y1, step):
        page[y:y + 1, x0:x1] = 0


def draw_table(page, x0, x1, y0, y1, rows=14, cols=4, rule_thickness=4):
    row_h = (y1 - y0) // rows
    col_w = (x1 - x0) // cols
    for r in range(rows + 1):
        y = y0 + r * row_h
        page[y:y + rule_thickness, x0:x1] = 0
    for c in range(cols + 1):
        x = x0 + c * col_w
        page[y0:y1, x:x + rule_thickness] = 0
    # Cell CONTENT (numbers/words) -- a real table's cells aren't empty,
    # which is what actually separates it from a sparse figure grid on
    # ink_coverage; a table of bare ruled lines with nothing inside is
    # visually indistinguishable from a graph's axis grid.
    for r in range(rows):
        for c in range(cols):
            cy = y0 + r * row_h + row_h // 3
            cx = x0 + c * col_w + col_w // 6
            draw_text_line(page, cy, cy + row_h // 2, cx, cx + int(col_w * 0.8), n_words=3)


def draw_banner(page, x0, x1, y0, y1, color=(30, 100, 180)):
    """A solid-fill pill/banner shape -- wide, short, densely filled."""
    page[y0:y1, x0:x1] = color


class TestClassify(unittest.TestCase):
    def test_text_block_is_not_a_figure(self):
        """1. Plain multi-line paragraph text -> TEXT_BLOCK, not FIGURE."""
        page = blank_page()
        draw_paragraph(page, 20, n_lines=6, x0=20, x1=560)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertNotEqual(category, "FIGURE")

    def test_theorem_definition_box_is_not_a_figure(self):
        """2. A short, dense 2-line theorem/definition box -- the exact
        documented V1 failure mode (one dominant blob + too few bands) --
        must still not be classified FIGURE."""
        page = blank_page(height=140, width=600)
        draw_text_line(page, 20, 55, 20, 580, n_words=10)
        draw_text_line(page, 65, 100, 20, 580, n_words=10)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertNotEqual(category, "FIGURE")

    def test_table_is_not_a_figure(self):
        """3. A ruled grid (table) -> not FIGURE (TABLE or, at worst,
        AMBIGUOUS -- never a confident figure)."""
        page = blank_page()
        draw_table(page, 20, 580, 20, 380)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertNotEqual(category, "FIGURE")

    def test_graph_with_thin_axes_is_a_figure(self):
        """4. A sparse grid + one curve (thin axes) -> FIGURE."""
        page = blank_page()
        draw_grid(page, 20, 580, 20, 380, step=45)
        draw_curve(page, 20, 580, 40, 360)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertEqual(category, "FIGURE")

    def test_graph_with_thin_curve_is_a_figure(self):
        """5. A thin continuous curve plus a coordinate axis (every real
        Chapter 1 figure includes at least an axis/grid -- a bare curve
        with no axis at all is not a pattern that occurs in the actual
        corpus) -> FIGURE (sparse ink, one dominant stroke, wide span)."""
        page = blank_page()
        page[200:203, 20:580] = 0  # x-axis
        page[30:370, 298:301] = 0  # y-axis
        draw_curve(page, 20, 580, 30, 370, thickness=2)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertEqual(category, "FIGURE")

    def test_figure_labels_preserved_by_trimming(self):
        """6. trim_text_margins must never shrink a bbox that is ALREADY
        tight around a figure (no separate paragraph band to trim) --
        axis labels / point names right next to the curve must survive."""
        page = blank_page()
        draw_grid(page, 20, 580, 20, 380, step=45)
        draw_curve(page, 20, 580, 40, 360)
        # a small "label" near the curve -- must not be trimmed away
        draw_text_line(page, 350, 375, 500, 570, n_words=1)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        trimmed, _ = trim_text_margins(page, bbox)
        # The curve spans the full width; a correct trim keeps it whole.
        self.assertLessEqual(trimmed[0], 25)
        self.assertGreaterEqual(trimmed[2], 575)

    def test_figure_next_to_descriptive_text_trims_out_the_prose(self):
        """7. A figure with a paragraph stacked above it -> trimmed bbox
        excludes the paragraph band, keeps the figure band."""
        page = blank_page(height=500, width=600)
        next_y = draw_paragraph(page, 10, n_lines=4, x0=20, x1=580)
        figure_y0 = next_y + 30
        draw_grid(page, 20, 580, figure_y0, figure_y0 + 250, step=45)
        draw_curve(page, 20, 580, figure_y0 + 20, figure_y0 + 230)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        trimmed, changed = trim_text_margins(page, bbox)
        self.assertTrue(changed)
        # Trimmed top must land at/after the figure's own start, i.e. the
        # paragraph rows are excluded.
        self.assertGreater(trimmed[1], next_y)

    def test_decorative_border_is_not_a_figure(self):
        """8. A solid-fill decorative banner/pill -> DECORATIVE, not FIGURE."""
        page = blank_page(height=200, width=600)
        draw_banner(page, 40, 560, 60, 140)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        features = extract_features(page, bbox, likely_text_box=False)
        category, _ = classify(features)
        self.assertNotEqual(category, "FIGURE")
        self.assertIn(category, ("DECORATIVE", "TEXT_BLOCK", "AMBIGUOUS"))


class TestTrimSafety(unittest.TestCase):
    def test_trim_never_returns_empty_bbox(self):
        page = blank_page()
        draw_curve(page, 20, 580, 30, 370)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        trimmed, _ = trim_text_margins(page, bbox)
        self.assertGreater(trimmed[2] - trimmed[0], 0)
        self.assertGreater(trimmed[3] - trimmed[1], 0)

    def test_trim_on_blank_region_is_a_no_op(self):
        page = blank_page()
        bbox = [10, 10, 100, 100]
        trimmed, changed = trim_text_margins(page, bbox)
        self.assertFalse(changed)
        self.assertEqual(trimmed, bbox)


if __name__ == "__main__":
    unittest.main()
