"""
Unit + regression tests for crop_correction.py (Phase 5a).
Deterministic, no LLM, no OpenCV/OCR.

Two test classes:
  - TestCropCorrectionInvariants: synthetic pixel fixtures checking the
    safety invariants that must hold for ANY input, not pixel-perfect
    correctness on any one drawing (per the task brief: pixel-perfect
    unit tests are not required for the six real human corrections --
    those stay visually reviewable via contact_sheet.png/review.json).
  - TestRegressionAgainstRealNeedsCorrection: runs correct_crop against
    the real 6 NEEDS_CORRECTION Chapter 1 page images, if present on
    disk, and checks the same invariants plus that a correction was
    actually found (changed=True) for every one of them, since all six
    are already confirmed (by human review) to contain attached
    non-figure content that a correction should remove.

Run:
    python test_crop_correction.py
    python -m unittest test_crop_correction
"""

import unittest

import numpy as np

import config
from crop_correction import correct_crop


def blank_page(height=400, width=600, bg=(255, 255, 255)):
    page = np.empty((height, width, 3), dtype=np.uint8)
    page[:, :] = bg
    return page


def draw_text_line(page, y0, y1, x0, x1, n_words=6, color=(0, 0, 0)):
    word_width = (x1 - x0) // (n_words * 2)
    x = x0
    for _ in range(n_words):
        page[y0:y1, x:x + word_width] = color
        x += word_width * 2


def draw_paragraph(page, y0, n_lines, x0, x1, line_height=20, gap=10, color=(0, 0, 0)):
    y = y0
    for _ in range(n_lines):
        draw_text_line(page, y, y + line_height, x0, x1, color=color)
        y += line_height + gap
    return y


def draw_curve(page, x0, x1, y0, y1, thickness=3, color=(200, 0, 120)):
    xs = np.linspace(x0, x1 - 1, x1 - x0).astype(int)
    ys = np.linspace(y0, y1 - 1, x1 - x0).astype(int)
    for x, y in zip(xs, ys):
        page[max(0, y - thickness):y + thickness, x] = color


def draw_axis(page, x0, x1, y0, y1, origin_x, origin_y, thickness=2, color=(0, 0, 0)):
    page[origin_y:origin_y + thickness, x0:x1] = color
    page[y0:y1, origin_x:origin_x + thickness] = color


class TestCropCorrectionInvariants(unittest.TestCase):
    """These invariants must hold no matter what correct_crop finds --
    see the task brief: 'bbox stays within page, bbox coordinates
    valid, crop generated, original figure remains inside final bbox,
    non-zero content, valid metadata'."""

    def _assert_valid_result(self, page, original_bbox, result):
        height, width = page.shape[:2]
        x0, y0, x1, y1 = result.bbox

        self.assertGreaterEqual(x0, 0)
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(x1, width)
        self.assertLessEqual(y1, height)
        self.assertLess(x0, x1, "bbox must have positive width")
        self.assertLess(y0, y1, "bbox must have positive height")

        ox0, oy0, ox1, oy1 = original_bbox
        self.assertGreaterEqual(x0, ox0, "correction must never expand past the original bbox")
        self.assertGreaterEqual(y0, oy0, "correction must never expand past the original bbox")
        self.assertLessEqual(x1, ox1, "correction must never expand past the original bbox")
        self.assertLessEqual(y1, oy1, "correction must never expand past the original bbox")

        crop = page[y0:y1, x0:x1]
        self.assertGreater(crop.size, 0)
        self.assertTrue((crop != crop[0, 0]).any() or crop.shape[0] * crop.shape[1] <= 1,
                         "crop must have non-uniform (non-blank) content")

        self.assertIsInstance(result.changed, bool)
        self.assertIsInstance(result.reason, str)
        self.assertGreater(len(result.reason), 0)

    def test_figure_with_text_beside_it_column_gap(self):
        """Paragraph in a left column, figure in a right column, with a
        real whitespace gap between -- the primary component method's
        target case."""
        page = blank_page(height=400, width=900)
        draw_paragraph(page, 40, n_lines=5, x0=30, x1=380)
        draw_axis(page, 450, 850, 60, 340, origin_x=470, origin_y=300)
        draw_curve(page, 470, 850, 80, 320)
        bbox = [0, 0, 900, 400]
        result = correct_crop(page, bbox)
        self._assert_valid_result(page, bbox, result)

    def test_figure_with_text_above_full_width_band(self):
        """A trailing text line directly above the figure across the
        full width, separated by a real blank row gap -- the band-trim
        fallback's target case."""
        page = blank_page(height=500, width=700)
        draw_text_line(page, 20, 50, 20, 680, n_words=10)
        draw_axis(page, 40, 660, 120, 460, origin_x=350, origin_y=400)
        draw_curve(page, 40, 660, 140, 440)
        bbox = [0, 0, 700, 500]
        result = correct_crop(page, bbox)
        self._assert_valid_result(page, bbox, result)

    def test_figure_embedded_in_tinted_box_beside_text(self):
        """A figure and paragraph text sharing the SAME row-band inside
        a gradient-tinted box (page_018_candidate_01's real shape) --
        neither connected components (already touching) nor band
        trimming (not a whole-width/height edge band) can resolve this;
        only the density-valley split can."""
        page = blank_page(height=500, width=1000, bg=(210, 235, 250))
        # simulate a subtle background gradient across the box, the
        # actual root cause that broke the naive approaches
        for x in range(1000):
            shade = 210 + int(15 * (x / 1000))
            page[:, x, 0] = shade
        draw_paragraph(page, 40, n_lines=4, x0=30, x1=420, color=(10, 10, 10))
        draw_axis(page, 520, 950, 60, 420, origin_x=560, origin_y=380)
        draw_curve(page, 560, 950, 80, 400)
        bbox = [0, 0, 1000, 500]
        result = correct_crop(page, bbox)
        self._assert_valid_result(page, bbox, result)

    def test_no_correction_needed_returns_unchanged_safely(self):
        """A bbox that is already a tight, isolated figure with no
        attached text: correct_crop must not corrupt it, and may
        legitimately report changed=False."""
        page = blank_page(height=300, width=300)
        draw_axis(page, 20, 280, 20, 280, origin_x=150, origin_y=150)
        draw_curve(page, 20, 280, 40, 260)
        bbox = [0, 0, 300, 300]
        result = correct_crop(page, bbox)
        self._assert_valid_result(page, bbox, result)

    def test_blank_region_does_not_crash(self):
        page = blank_page(height=200, width=200)
        bbox = [0, 0, 200, 200]
        result = correct_crop(page, bbox)
        x0, y0, x1, y1 = result.bbox
        self.assertEqual([x0, y0, x1, y1], bbox)
        self.assertFalse(result.changed)


class TestRegressionAgainstRealNeedsCorrection(unittest.TestCase):
    """Runs the real classifier against the real 6 NEEDS_CORRECTION
    Chapter 1 candidates. Skips (does not fail) if the pipeline outputs
    aren't present on disk."""

    NEEDS_CORRECTION = [
        ("page_009_candidate_01", 9, [139, 82, 2085, 1016]),
        ("page_015_candidate_02", 15, [139, 1948, 2066, 2753]),
        ("page_016_candidate_01", 16, [135, 92, 2085, 1792]),
        ("page_018_candidate_01", 18, [135, 1603, 2066, 2323]),
        ("page_025_candidate_01", 25, [1303, 476, 1948, 1034]),
        ("page_027_candidate_04", 27, [141, 510, 983, 1038]),
    ]

    @classmethod
    def setUpClass(cls):
        if not config.PAGE_IMAGES_DIR.exists():
            raise unittest.SkipTest("page_images/ not found -- run the OCR/rendering pipeline first")
        from PIL import Image
        cls.Image = Image

    def _load(self, page):
        path = config.PAGE_IMAGES_DIR / f"page_{page:03d}.png"
        if not path.exists():
            self.skipTest(f"{path} not found")
        return np.array(self.Image.open(path).convert("RGB"))

    def test_every_needs_correction_candidate_is_corrected(self):
        for name, page, bbox in self.NEEDS_CORRECTION:
            with self.subTest(candidate=name):
                arr = self._load(page)
                result = correct_crop(arr, bbox)

                height, width = arr.shape[:2]
                x0, y0, x1, y1 = result.bbox
                self.assertGreaterEqual(x0, 0)
                self.assertGreaterEqual(y0, 0)
                self.assertLessEqual(x1, width)
                self.assertLessEqual(y1, height)
                self.assertLess(x0, x1)
                self.assertLess(y0, y1)

                ox0, oy0, ox1, oy1 = bbox
                self.assertGreaterEqual(x0, ox0)
                self.assertGreaterEqual(y0, oy0)
                self.assertLessEqual(x1, ox1)
                self.assertLessEqual(y1, oy1)

                self.assertTrue(result.changed, f"{name}: expected a correction to be found")

                crop = arr[y0:y1, x0:x1]
                self.assertGreater(crop.size, 0)


if __name__ == "__main__":
    unittest.main()
