"""
Unit + regression tests for normalize_knowledge.py and
validate_normalized_knowledge.py (Phase 7).

Two test classes:
  - TestNormalization: synthetic knowledge fixtures, one per required
    guarantee from the task brief (determinism, stable IDs, ordering,
    provenance preservation, math/LaTeX preservation, no item lost,
    tag stripping, irregularity detection, no chapter-specific
    hardcoding).
  - TestChapter1Regression: runs the real normalizer + validator
    against the real Chapter 1 knowledge JSON, if present on disk.
    Chapter 1's own ids/pages appear ONLY in this class's assertions,
    never in normalize_knowledge.py/validate_normalized_knowledge.py
    themselves (checked directly below).

Run:
    python test_normalize_knowledge.py
    python -m unittest test_normalize_knowledge
"""

import json
import unittest
from pathlib import Path

import config
from normalize_knowledge import normalize
from validate_normalized_knowledge import validate


def make_source(section_id="sec-a", subsection_id=None, chapter_page_range=(1, 20)):
    return {
        "document": {"id": "doc-x", "title": "T", "subject": "Math", "level": "L", "country": "C",
                     "source_pdf": "x.pdf", "total_pages": 50},
        "chapter": {"id": "doc-x-ch01", "document_id": "doc-x", "number": 1, "title": "Chap",
                    "pdf_page_start": chapter_page_range[0], "pdf_page_end": chapter_page_range[1]},
        "sections": [
            {"id": "sec-a", "chapter_id": "doc-x-ch01", "label": "I", "title": "Section A",
             "pdf_page_start": 1, "pdf_page_end": 10},
        ],
        "subsections": [],
        "concepts": [],
        "items": [],
    }


def make_item(item_id, item_type="theorem", pages=(5,), content="Some $x^2$ content.",
              section_id="sec-a", subsection_id=None, bloc_numero=None, title=None, proof=None):
    return {
        "id": item_id,
        "type": item_type,
        "document_id": "doc-x",
        "chapter_id": "doc-x-ch01",
        "section_id": section_id,
        "subsection_id": subsection_id,
        "title": title,
        "source": {
            "document_id": "doc-x",
            "pdf_pages": list(pages),
            "reconstructed_sources": [f"page_{p:03d}.md" for p in pages],
            "bloc_type": item_type,
            "bloc_numero": bloc_numero,
            "continues_from_previous_page": False,
            "continues_on_next_page": False,
        },
        "original_content": content,
        "proof": proof,
        "concepts": [],
        "links": {"definitions": [], "theorems": [], "properties": [], "formulas": [], "methods": [], "exercises": [], "figures": []},
        "exercise_details": None,
        "extracted_from": None,
        "uncertainty": {"has_uncertain_markers": False, "has_gap_markers": False, "uncertain_spans": []},
        "validation_status": "REVIEW_REQUIRED",
        "validation_history": [],
        "created_at": "2026-01-01T00:00:00Z",
        "schema_version": "1.0",
    }


class TestNormalization(unittest.TestCase):
    def test_deterministic_rerun_produces_identical_output(self):
        source = make_source()
        source["items"] = [make_item("it-1"), make_item("it-2", content="Other $y$ content.")]
        r1 = normalize(source)
        r2 = normalize(source)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_stable_ids_reused_verbatim_not_regenerated(self):
        source = make_source()
        source["items"] = [make_item("doc-x-ch01-thm-042")]
        result = normalize(source)
        self.assertEqual(result["items"][0]["id"], "doc-x-ch01-thm-042")
        self.assertEqual(result["items"][0]["provenance"]["source_item_id"], "doc-x-ch01-thm-042")

    def test_ordering_is_explicit_and_preserved(self):
        source = make_source()
        source["items"] = [make_item("it-a"), make_item("it-b"), make_item("it-c")]
        result = normalize(source)
        orders = [item["order"] for item in result["items"]]
        self.assertEqual(orders, [0, 1, 2])
        ids_in_order = [item["id"] for item in result["items"]]
        self.assertEqual(ids_in_order, ["it-a", "it-b", "it-c"])

    def test_source_provenance_is_preserved(self):
        source = make_source()
        source["items"] = [make_item("it-1", pages=(5, 6))]
        result = normalize(source)
        prov = result["items"][0]["provenance"]
        self.assertEqual(prov["pdf_pages"], [5, 6])
        self.assertEqual(prov["reconstructed_sources"], ["page_005.md", "page_006.md"])
        self.assertEqual(prov["source_item_id"], "it-1")
        self.assertIn("$x^2$", prov["original_content"])

    def test_latex_content_is_preserved_unchanged(self):
        content = r"Soit $f(x) = \dfrac{1}{x-1}$ et $I = [0, 1[$. Alors $\lim_{x \to 1^-} f(x) = -\infty$."
        source = make_source()
        source["items"] = [make_item("it-1", content=content)]
        result = normalize(source)
        self.assertEqual(result["items"][0]["content"], content)

    def test_display_math_is_preserved(self):
        content = "Formule:\n\n$$\\int_0^1 x^2 \\,dx = \\frac{1}{3}$$\n\nFin."
        source = make_source()
        source["items"] = [make_item("it-1", content=content)]
        result = normalize(source)
        self.assertEqual(result["items"][0]["content"], content)

    def test_no_source_item_silently_disappears(self):
        source = make_source()
        source["items"] = [make_item(f"it-{i}") for i in range(10)]
        result = normalize(source)
        self.assertEqual(len(result["items"]), 10)
        self.assertEqual(
            {i["id"] for i in result["items"]},
            {f"it-{i}" for i in range(10)},
        )

    def test_inline_figure_tag_is_stripped_from_content_but_kept_in_provenance(self):
        content = (
            "Voici la courbe.\n\n"
            '<figure id="fig-1" status="described">Une parabole.</figure>'
        )
        source = make_source()
        item = make_item("it-1", content=content)
        item["links"]["figures"] = [{
            "pdf_page": 5, "reconstructed_figure_id": "fig-1", "candidate_id": None,
            "figure_status_in_source": "described", "match_status": "unresolved",
        }]
        source["items"] = [item]
        result = normalize(source)
        normalized_item = result["items"][0]

        self.assertNotIn("<figure", normalized_item["content"])
        self.assertEqual(normalized_item["content"], "Voici la courbe.")
        self.assertIn("<figure", normalized_item["provenance"]["original_content"])
        self.assertEqual(normalized_item["links"]["figures"][0]["reconstructed_figure_id"], "fig-1")

    def test_display_label_derived_only_when_bloc_numero_present(self):
        source = make_source()
        source["items"] = [
            make_item("it-1", item_type="activity", bloc_numero="3"),
            make_item("it-2", item_type="theorem", bloc_numero=None),
        ]
        result = normalize(source)
        self.assertEqual(result["items"][0]["display_label"], "Activité 3")
        self.assertIsNone(result["items"][1]["display_label"])

    def test_title_is_never_invented_only_copied(self):
        source = make_source()
        source["items"] = [make_item("it-1", title=None), make_item("it-2", title="Théorème (admis)")]
        result = normalize(source)
        self.assertIsNone(result["items"][0]["title"])
        self.assertEqual(result["items"][1]["title"], "Théorème (admis)")

    def test_irregular_subsection_label_is_flagged_not_corrected(self):
        source = make_source()
        source["subsections"] = [
            {"id": "sub-1", "section_id": "sec-a", "label": "I.1", "title": "First",
             "pdf_page_start": 1, "pdf_page_end": 2},
            {"id": "sub-2", "section_id": "sec-a", "label": "1.2", "title": "Second (mislabeled)",
             "pdf_page_start": 2, "pdf_page_end": 3},
            {"id": "sub-3", "section_id": "sec-a", "label": "I.3", "title": "Third",
             "pdf_page_start": 3, "pdf_page_end": 4},
        ]
        result = normalize(source)
        by_id = {s["id"]: s for s in result["subsections"]}
        self.assertEqual(by_id["sub-1"]["irregularities"], [])
        self.assertEqual(by_id["sub-3"]["irregularities"], [])
        self.assertEqual(by_id["sub-2"]["label"], "1.2", "label must be preserved verbatim, never rewritten")
        self.assertEqual(len(by_id["sub-2"]["irregularities"]), 1)
        self.assertIn("roman-numeral", by_id["sub-2"]["irregularities"][0])

    def test_regular_ad_hoc_labels_are_not_flagged(self):
        """A section with NO roman-numeral-convention subsections at all
        (e.g. 'Problème résolu', 'Solution') must not be flagged -- only
        a digit label appearing ALONGSIDE roman siblings is irregular."""
        source = make_source()
        source["subsections"] = [
            {"id": "sub-1", "section_id": "sec-a", "label": "Problème résolu", "title": "Problème résolu",
             "pdf_page_start": 1, "pdf_page_end": 2},
            {"id": "sub-2", "section_id": "sec-a", "label": "Solution", "title": "Solution",
             "pdf_page_start": 2, "pdf_page_end": 3},
        ]
        result = normalize(source)
        for sub in result["subsections"]:
            self.assertEqual(sub["irregularities"], [])

    def test_no_chapter_specific_hardcoding_in_production_modules(self):
        for filename in ("normalize_knowledge.py", "validate_normalized_knowledge.py"):
            src = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
            for token in ("math-4eme-tome1", "ch01", "act-008", "thm-017"):
                self.assertNotIn(token, src, f"{filename} must not reference {token!r}")


class TestValidation(unittest.TestCase):
    def test_valid_output_passes(self):
        source = make_source()
        source["items"] = [make_item("it-1")]
        normalized = normalize(source)
        report = validate(normalized, source)
        self.assertTrue(report["passed"])
        self.assertEqual(report["total_errors"], 0)

    def test_duplicate_id_is_detected(self):
        source = make_source()
        source["items"] = [make_item("dup-id"), make_item("dup-id")]
        normalized = normalize(source)
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(any("dup-id" in e for e in report["checks"]["duplicate_ids"]))

    def test_orphan_section_reference_is_detected(self):
        source = make_source()
        source["items"] = [make_item("it-1", section_id="does-not-exist")]
        normalized = normalize(source)
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["hierarchy"])

    def test_broken_ordering_is_detected(self):
        source = make_source()
        source["items"] = [make_item("it-1"), make_item("it-2")]
        normalized = normalize(source)
        normalized["items"][1]["order"] = 5  # corrupt it
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["item_ordering"])

    def test_page_outside_chapter_range_is_detected(self):
        source = make_source(chapter_page_range=(1, 5))
        source["items"] = [make_item("it-1", pages=(99,))]
        normalized = normalize(source)
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["page_references"])

    def test_unbalanced_latex_is_detected(self):
        source = make_source()
        source["items"] = [make_item("it-1", content="Unbalanced $x^2 + 1")]
        normalized = normalize(source)
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["latex_balance"])

    def test_lost_item_relative_to_source_is_detected(self):
        source = make_source()
        source["items"] = [make_item("it-1"), make_item("it-2")]
        normalized = normalize(source)
        normalized["items"].pop()  # simulate an item silently disappearing
        report = validate(normalized, source)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["no_lost_items"])


class TestChapter1Regression(unittest.TestCase):
    """Chapter 1 is used ONLY as ground truth/fixture -- see
    test_no_chapter_specific_hardcoding_in_production_modules above for
    the check that production code never references it."""

    @classmethod
    def setUpClass(cls):
        if not config.KNOWLEDGE_CHAPTER_01_JSON.exists():
            raise unittest.SkipTest("Chapter 1 knowledge JSON not found")
        cls.source = json.loads(config.KNOWLEDGE_CHAPTER_01_JSON.read_text(encoding="utf-8"))

    def test_all_100_items_normalized_with_no_loss(self):
        result = normalize(self.source)
        self.assertEqual(len(result["items"]), len(self.source["items"]))
        self.assertEqual(
            {i["id"] for i in result["items"]},
            {i["id"] for i in self.source["items"]},
        )

    def test_deterministic_rerun_on_real_data(self):
        r1 = normalize(self.source)
        r2 = normalize(self.source)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_real_chapter_1_output_passes_validation(self):
        result = normalize(self.source)
        report = validate(result, self.source)
        self.assertTrue(report["passed"], report["checks"])

    def test_ordering_matches_source_array_order(self):
        result = normalize(self.source)
        self.assertEqual(
            [i["id"] for i in result["items"]],
            [i["id"] for i in self.source["items"]],
        )


if __name__ == "__main__":
    unittest.main()
