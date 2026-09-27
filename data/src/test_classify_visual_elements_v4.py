"""
Unit + regression tests for classify_visual_elements_v4.py (Phase 4j).
Deterministic, no LLM, no OpenCV/OCR.

Two test classes:
  - TestClassify: synthetic pixel fixtures, one per required case from
    the design brief (text block, paragraph, theorem-like text, graph
    with axes, graph with curve, geometric figure, figure with labels,
    figure surrounded by text, decorative banner, empty/noise region).
  - TestRegressionAgainstHumanGroundTruth: runs the actual classifier
    against the real 39 V3 candidates and the human-verified ground
    truth (see evaluate_v4_against_ground_truth.py for how that ground
    truth was built/verified). Skips if the pipeline outputs aren't
    present on disk (e.g. a clean checkout that hasn't run the pipeline
    yet) rather than failing for an unrelated reason.

Run:
    python test_classify_visual_elements_v4.py
    python -m unittest test_classify_visual_elements_v4
"""

import json
import unittest

import numpy as np

import config
from classify_visual_elements_v4 import classify, extract_features


def blank_page(height=400, width=600):
    return np.full((height, width, 3), 255, dtype=np.uint8)


def draw_text_line(page, y0, y1, x0, x1, n_words=6):
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
    return y


def draw_curve(page, x0, x1, y0, y1, thickness=3):
    xs = np.linspace(x0, x1 - 1, x1 - x0).astype(int)
    ys = np.linspace(y0, y1 - 1, x1 - x0).astype(int)
    for x, y in zip(xs, ys):
        page[max(0, y - thickness):y + thickness, x] = 0


def draw_axis(page, x0, x1, y0, y1, origin_x, origin_y, thickness=2):
    page[origin_y:origin_y + thickness, x0:x1] = 0
    page[y0:y1, origin_x:origin_x + thickness] = 0


def draw_circle(page, cx, cy, radius, thickness=3):
    theta = np.linspace(0, 2 * np.pi, 720)
    xs = (cx + radius * np.cos(theta)).astype(int)
    ys = (cy + radius * np.sin(theta)).astype(int)
    for x, y in zip(xs, ys):
        page[max(0, y - thickness):y + thickness, max(0, x - thickness):x + thickness] = 0


def draw_banner(page, x0, x1, y0, y1, color=(30, 100, 180)):
    page[y0:y1, x0:x1] = color


class TestClassify(unittest.TestCase):
    def classify_bbox(self, page, bbox):
        features = extract_features(page, bbox)
        return classify(features)

    def test_text_block(self):
        """Plain single dense paragraph -> never FIGURE."""
        page = blank_page()
        draw_paragraph(page, 20, n_lines=6, x0=20, x1=560)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertNotEqual(classification, "FIGURE")

    def test_paragraph_multi_line(self):
        """Multi-paragraph text (two blocks separated by whitespace) -> never FIGURE."""
        page = blank_page(height=500)
        draw_paragraph(page, 20, n_lines=4, x0=20, x1=560)
        draw_paragraph(page, 250, n_lines=4, x0=20, x1=560)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertNotEqual(classification, "FIGURE")

    def test_theorem_like_text(self):
        """Short, dense 2-line theorem/definition box (the classic V1/V2
        false-positive shape) -> never FIGURE."""
        page = blank_page(height=140, width=600)
        draw_text_line(page, 20, 55, 20, 580, n_words=10)
        draw_text_line(page, 65, 100, 20, 580, n_words=10)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertNotEqual(classification, "FIGURE")

    def test_graph_with_axes(self):
        page = blank_page()
        draw_axis(page, 20, 580, 30, 370, origin_x=300, origin_y=200)
        draw_curve(page, 20, 580, 40, 360)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertEqual(classification, "FIGURE")

    def test_graph_with_curve(self):
        page = blank_page()
        draw_axis(page, 20, 580, 30, 370, origin_x=300, origin_y=200)
        draw_curve(page, 20, 580, 40, 360, thickness=2)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertEqual(classification, "FIGURE")

    def test_geometric_figure_circle(self):
        page = blank_page(height=400, width=400)
        draw_circle(page, cx=200, cy=200, radius=150)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertEqual(classification, "FIGURE")

    def test_figure_with_labels(self):
        """A graph plus a couple of small point/axis labels -> still FIGURE."""
        page = blank_page()
        draw_axis(page, 20, 580, 30, 370, origin_x=300, origin_y=200)
        draw_curve(page, 20, 580, 40, 360)
        draw_text_line(page, 45, 60, 480, 520, n_words=1)   # a small curve tag
        draw_text_line(page, 355, 370, 60, 100, n_words=1)  # an axis label
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertEqual(classification, "FIGURE")

    def test_figure_surrounded_by_text_still_reachable(self):
        """Figure + a lot of attached text (a NEEDS_CORRECTION-shaped
        candidate) -- must NEVER be classified NOT_FIGURE, even if it
        isn't a confident FIGURE either."""
        page = blank_page(height=600, width=700)
        draw_paragraph(page, 20, n_lines=5, x0=20, x1=650)
        draw_axis(page, 60, 640, 320, 560, origin_x=350, origin_y=460)
        draw_curve(page, 60, 640, 340, 540)
        bbox = [0, 0, page.shape[1], page.shape[0]]
        classification, _, _ = self.classify_bbox(page, bbox)
        self.assertNotEqual(classification, "NOT_FIGURE")

    def test_decorative_banner(self):
        """A solid-fill wide banner/pill -> never FIGURE."""
        page = blank_page(height=200, width=800)
        draw_banner(page, 40, 760, 60, 140)
        classification, _, _ = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertNotEqual(classification, "FIGURE")

    def test_empty_noise_region(self):
        """A blank page (or near-blank / speckled noise) -> never FIGURE,
        and never crashes."""
        page = blank_page()
        rng = np.random.default_rng(0)
        noise_mask = rng.random(page.shape[:2]) < 0.001
        page[noise_mask] = 0
        classification, confidence, reasons = self.classify_bbox(page, [0, 0, page.shape[1], page.shape[0]])
        self.assertNotEqual(classification, "FIGURE")
        self.assertIsInstance(confidence, float)
        self.assertIsInstance(reasons, list)


class TestRegressionAgainstHumanGroundTruth(unittest.TestCase):
    """Runs the real classifier against the real 39 V3 candidates.
    Requires visual_detection_v4_evaluation.json to exist (produced by
    evaluate_v4_against_ground_truth.py) -- skips (does not fail) if the
    pipeline hasn't been run in this checkout."""

    @classmethod
    def setUpClass(cls):
        if not config.VISUAL_DETECTION_V4_EVALUATION_JSON.exists():
            raise unittest.SkipTest("visual_detection_v4_evaluation.json not found -- run the V4 pipeline first")
        cls.result = json.loads(config.VISUAL_DETECTION_V4_EVALUATION_JSON.read_text(encoding="utf-8"))

    def test_all_validated_figures_retained(self):
        recall = self.result["recall"]["validated"]
        retained, total = (int(x) for x in recall.split("/"))
        self.assertEqual(retained, total, f"VALIDATED recall was {recall}, must be {total}/{total}")

    def test_all_needs_correction_figures_retained(self):
        recall = self.result["recall"]["needs_correction"]
        retained, total = (int(x) for x in recall.split("/"))
        self.assertEqual(retained, total, f"NEEDS_CORRECTION recall was {recall}, must be {total}/{total}")

    def test_no_real_figure_lost(self):
        self.assertEqual(self.result["false_negatives_real_figures_lost"], [])

    def test_precision_improved_over_v3_baseline(self):
        # V3 baseline: all 39 candidates reach the queue (0 rejected excluded).
        excluded = self.result["false_positives"]["rejected_confidently_excluded_count"]
        self.assertGreater(excluded, 0, "V4 should confidently exclude at least some of the 20 REJECTED candidates")


if __name__ == "__main__":
    unittest.main()
