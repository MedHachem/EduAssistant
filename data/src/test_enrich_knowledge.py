"""
Unit + regression tests for enrich_knowledge.py and validate_enrichment.py
(Phase 8).

Three test classes:
  - TestEnrichment: synthetic normalized-knowledge fixtures + a small
    synthetic glossary, one per required guarantee from the task brief
    (topics from hierarchy, glossary-only keywords, conservative entity
    extraction, structural exercise_type, rule-based-or-unclassified
    reasoning_types, controlled concepts, generation_methods,
    NOT_REQUIRED review status, stable item_id, no chapter hardcoding).
  - TestValidation: synthetic failure-injection cases for the validator.
  - TestChapter1Regression: runs the real enricher + validator against
    the real Chapter 1 normalized JSON, if present on disk. Chapter 1's
    own ids/pages appear ONLY in this class, never in
    enrich_knowledge.py/validate_enrichment.py themselves (checked
    directly below).

Run:
    python test_enrich_knowledge.py
    python -m unittest test_enrich_knowledge
"""

import json
import unittest
from pathlib import Path

import config
from enrich_knowledge import enrich
from validate_enrichment import validate


def glossary():
    return {
        "keywords": [
            {"term": "limite", "concept": "limites"},
            {"term": "asymptote", "concept": "branches infinies"},
            {"term": "continue", "concept": "continuité"},
        ],
        "reasoning_verbs": [
            {"verb": "montrer", "tag": "prove"},
            {"verb": "calculer", "tag": "compute"},
        ],
    }


def make_normalized(sections=None, subsections=None, items=None):
    return {
        "schema_version": "normalized-1.0",
        "algorithm_version": "normalize-v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "document": {"id": "doc-x", "title": "T", "subject": "Math", "level": "L",
                     "country": "C", "source_pdf": "x.pdf", "total_pages": 50},
        "chapter": {"id": "doc-x-ch01", "document_id": "doc-x", "number": 1, "title": "Chap",
                    "pdf_page_start": 1, "pdf_page_end": 20},
        "sections": sections or [],
        "subsections": subsections or [],
        "items": items or [],
    }


def make_item(item_id, item_type="theorem", content="Soit $f$ une fonction.",
              section_id=None, subsection_id=None, order=0, proof=None,
              exercise_details=None):
    return {
        "id": item_id,
        "type": item_type,
        "order": order,
        "chapter_id": "doc-x-ch01",
        "document_id": "doc-x",
        "section_id": section_id,
        "subsection_id": subsection_id,
        "title": None,
        "display_label": None,
        "content": content,
        "proof": proof,
        "links": {"definitions": [], "theorems": [], "properties": [], "formulas": [],
                   "methods": [], "exercises": [], "figures": []},
        "exercise_details": exercise_details,
        "uncertainty": {"has_uncertain_markers": False, "has_gap_markers": False, "uncertain_spans": []},
        "provenance": {
            "source_item_id": item_id, "document_id": "doc-x", "pdf_pages": [5],
            "reconstructed_sources": ["page_005.md"], "bloc_type": item_type,
            "bloc_numero": None, "continues_from_previous_page": False,
            "continues_on_next_page": False, "original_content": content,
        },
    }


def make_section(id_, title, chapter_id="doc-x-ch01", order=0):
    return {"id": id_, "chapter_id": chapter_id, "label": title[:1], "title": title,
            "pdf_page_start": 1, "pdf_page_end": 10, "order": order, "irregularities": []}


def make_subsection(id_, title, section_id, order=0):
    return {"id": id_, "section_id": section_id, "label": title[:1], "title": title,
            "pdf_page_start": 1, "pdf_page_end": 5, "order": order, "irregularities": []}


class TestEnrichment(unittest.TestCase):
    def test_one_record_per_normalized_item(self):
        normalized = make_normalized(items=[make_item("it-1"), make_item("it-2")])
        result = enrich(normalized, glossary())
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual({r["item_id"] for r in result["items"]}, {"it-1", "it-2"})

    def test_stable_item_id_reused_verbatim(self):
        normalized = make_normalized(items=[make_item("doc-x-ch01-thm-042")])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["item_id"], "doc-x-ch01-thm-042")

    def test_topics_from_section_and_subsection_hierarchy(self):
        sec = make_section("sec-a", "Branches infinies")
        sub = make_subsection("sub-a", "Etude des asymptotes", "sec-a")
        normalized = make_normalized(
            sections=[sec], subsections=[sub],
            items=[make_item("it-1", section_id="sec-a", subsection_id="sub-a")],
        )
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(record["topics"], ["Branches infinies", "Etude des asymptotes"])
        self.assertEqual(record["generation_methods"]["topics"], "deterministic")

    def test_topics_not_populated_when_no_section(self):
        normalized = make_normalized(items=[make_item("it-1", section_id=None)])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(record["topics"], [])
        self.assertEqual(record["generation_methods"]["topics"], "not_populated")

    def test_keywords_only_from_glossary_including_plural(self):
        normalized = make_normalized(items=[
            make_item("it-1", content="Soit $f$ une fonction continue. Determiner les limites."),
        ])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(set(record["keywords"]), {"continue", "limite"})
        self.assertEqual(record["generation_methods"]["keywords"], "rule_based")

    def test_word_not_in_glossary_is_never_a_keyword(self):
        normalized = make_normalized(items=[
            make_item("it-1", content="Soit une fonction croissante et bornee."),
        ])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(record["keywords"], [])
        self.assertEqual(record["generation_methods"]["keywords"], "not_populated")

    def test_keyword_does_not_match_substring_of_unrelated_word(self):
        """'continue' must not match inside 'continuellement'."""
        normalized = make_normalized(items=[
            make_item("it-1", content="Le phénomène se reproduit continuellement dans la nature."),
        ])
        result = enrich(normalized, glossary())
        self.assertNotIn("continue", result["items"][0]["keywords"])

    def test_mathematical_entities_extracted_conservatively(self):
        content = "Soit $f(x) = x^2$ sur $]-\\infty,-1[$ avec $x=-1$ et $\\lim_{x \\to 1} f(x)$."
        normalized = make_normalized(items=[make_item("it-1", content=content)])
        result = enrich(normalized, glossary())
        entities = result["items"][0]["mathematical_entities"]
        self.assertIn("f", entities["functions"])
        self.assertIn("]-\\infty,-1[", entities["intervals"])
        self.assertIn("x=-1", entities["equations"])
        self.assertIn("lim", entities["notations"])

    def test_bare_variable_is_never_misread_as_a_function(self):
        """'x(1-x)' is 'x times (1-x)', not a function named x -- see
        enrich_knowledge.py's FUNCTION_NAME_LETTERS allow-list."""
        content = "Soit $f(x)=16x^2(1-x)^2$ une fonction."
        normalized = make_normalized(items=[make_item("it-1", content=content)])
        result = enrich(normalized, glossary())
        entities = result["items"][0]["mathematical_entities"]
        self.assertIn("f", entities["functions"])
        self.assertNotIn("x", entities["functions"])

    def test_no_entities_found_is_not_populated(self):
        normalized = make_normalized(items=[make_item("it-1", content="Une phrase sans notation.")])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(record["mathematical_entities"], {"functions": [], "intervals": [], "equations": [], "notations": []})
        self.assertEqual(record["generation_methods"]["mathematical_entities"], "not_populated")

    def test_exercise_type_qcm_from_structural_evidence(self):
        details = {"statement": "Choisir.", "questions": [], "qcm_choices": [{"label": "A", "text": "1", "marked_correct_in_source": None}], "correction": {"present_in_source": False, "content": None}}
        normalized = make_normalized(items=[make_item("it-1", item_type="exercise", exercise_details=details)])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["exercise_type"], "qcm")

    def test_exercise_type_structured_multi_question(self):
        details = {"statement": None, "questions": [{"label": "1", "text": "Calculer.", "sub_questions": []}], "qcm_choices": None, "correction": {"present_in_source": False, "content": None}}
        normalized = make_normalized(items=[make_item("it-1", item_type="activity", exercise_details=details)])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["exercise_type"], "structured_multi_question")

    def test_exercise_type_unstructured_statement(self):
        details = {"statement": "Un enonce simple.", "questions": [], "qcm_choices": None, "correction": {"present_in_source": False, "content": None}}
        normalized = make_normalized(items=[make_item("it-1", item_type="activity", exercise_details=details)])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["exercise_type"], "unstructured_statement")

    def test_exercise_type_null_for_non_exercise_shaped_item_type(self):
        normalized = make_normalized(items=[make_item("it-1", item_type="theorem", exercise_details=None)])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertIsNone(record["exercise_type"])
        self.assertEqual(record["generation_methods"]["exercise_type"], "not_populated")

    def test_reasoning_type_from_strong_verb_pattern(self):
        details = {"statement": "Montrer que f est continue.", "questions": [], "qcm_choices": None, "correction": {"present_in_source": False, "content": None}}
        normalized = make_normalized(items=[make_item("it-1", item_type="exercise", exercise_details=details)])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["reasoning_types"], ["prove"])

    def test_reasoning_type_unclassified_when_exercise_shaped_but_no_verb_matches(self):
        details = {"statement": "Une phrase neutre sans verbe connu.", "questions": [], "qcm_choices": None, "correction": {"present_in_source": False, "content": None}}
        normalized = make_normalized(items=[make_item("it-1", item_type="activity", exercise_details=details)])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["reasoning_types"], ["unclassified"])

    def test_reasoning_type_empty_not_unclassified_for_non_exercise_item(self):
        """A theorem STATEMENT has no 'reasoning type' at all -- empty
        list (not_populated), never ['unclassified']."""
        normalized = make_normalized(items=[make_item("it-1", item_type="theorem", exercise_details=None)])
        result = enrich(normalized, glossary())
        record = result["items"][0]
        self.assertEqual(record["reasoning_types"], [])
        self.assertEqual(record["generation_methods"]["reasoning_types"], "not_populated")

    def test_concepts_are_controlled_and_deduplicated_case_insensitively(self):
        sec = make_section("sec-a", "Branches infinies")
        normalized = make_normalized(
            sections=[sec],
            items=[make_item("it-1", section_id="sec-a", content="Une asymptote de la courbe.")],
        )
        result = enrich(normalized, glossary())
        concepts = result["items"][0]["concepts"]
        self.assertEqual(concepts.count("branches infinies"), 1, "topic-derived and keyword-derived concept must collapse to one entry")
        self.assertNotIn("Branches infinies", concepts, "concepts must be lowercase-normalized, distinct from topics")

    def test_generation_methods_present_for_every_field(self):
        normalized = make_normalized(items=[make_item("it-1")])
        result = enrich(normalized, glossary())
        methods = result["items"][0]["generation_methods"]
        for field in ("topics", "keywords", "mathematical_entities", "exercise_type", "reasoning_types", "concepts"):
            self.assertIn(field, methods)
            self.assertIn(methods[field], {"deterministic", "rule_based", "llm", "not_populated"})

    def test_review_status_is_not_required_when_no_llm_field_exists(self):
        normalized = make_normalized(items=[make_item("it-1")])
        result = enrich(normalized, glossary())
        self.assertEqual(result["items"][0]["review_status"], "NOT_REQUIRED")

    def test_deterministic_rerun_produces_identical_output(self):
        normalized = make_normalized(items=[make_item("it-1"), make_item("it-2", content="Calculer la limite.")])
        r1 = enrich(normalized, glossary())
        r2 = enrich(normalized, glossary())
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_no_chapter_specific_hardcoding_in_production_modules(self):
        """Guards against chapter/item IDENTIFIERS baked into production
        logic. Generic French vocabulary words may legitimately appear
        in illustrative comments (they are DATA, in math_glossary_fr.json,
        not logic) -- this test is intentionally about identifiers, not
        about banning natural-language examples from comments."""
        for filename in ("enrich_knowledge.py", "validate_enrichment.py"):
            src = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
            for token in ("math-4eme-tome1", "-ch01", "act-008", "thm-017"):
                self.assertNotIn(token, src, f"{filename} must not reference {token!r}")


class TestValidation(unittest.TestCase):
    def test_valid_output_passes(self):
        normalized = make_normalized(items=[make_item("it-1")])
        enrichment = enrich(normalized, glossary())
        report = validate(enrichment, normalized, glossary())
        self.assertTrue(report["passed"])
        self.assertEqual(report["total_errors"], 0)

    def test_missing_enrichment_record_is_detected(self):
        normalized = make_normalized(items=[make_item("it-1"), make_item("it-2")])
        enrichment = enrich(normalized, glossary())
        enrichment["items"].pop()
        report = validate(enrichment, normalized, glossary())
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["no_lost_items"])

    def test_duplicate_item_id_is_detected(self):
        normalized = make_normalized(items=[make_item("it-1")])
        enrichment = enrich(normalized, glossary())
        enrichment["items"].append(dict(enrichment["items"][0]))
        report = validate(enrichment, normalized, glossary())
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["duplicate_item_ids"])

    def test_uncontrolled_topic_value_is_detected(self):
        normalized = make_normalized(items=[make_item("it-1")])
        enrichment = enrich(normalized, glossary())
        enrichment["items"][0]["topics"] = ["Some Invented Topic"]
        report = validate(enrichment, normalized, glossary())
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["controlled_vocabulary"])

    def test_uncontrolled_keyword_value_is_detected(self):
        normalized = make_normalized(items=[make_item("it-1")])
        enrichment = enrich(normalized, glossary())
        enrichment["items"][0]["keywords"] = ["mot-invente"]
        report = validate(enrichment, normalized, glossary())
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["controlled_vocabulary"])

    def test_llm_field_without_review_required_is_detected(self):
        normalized = make_normalized(items=[make_item("it-1")])
        enrichment = enrich(normalized, glossary())
        enrichment["items"][0]["generation_methods"]["concepts"] = "llm"
        # review_status stays NOT_REQUIRED -- inconsistent
        report = validate(enrichment, normalized, glossary())
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["generation_method_consistency"])


class TestChapter1Regression(unittest.TestCase):
    """Chapter 1 is used ONLY as ground truth/fixture -- see
    test_no_chapter_specific_hardcoding_in_production_modules above."""

    @classmethod
    def setUpClass(cls):
        if not config.NORMALIZED_CHAPTER_01_JSON.exists():
            raise unittest.SkipTest("Chapter 1 normalized JSON not found")
        cls.normalized = json.loads(config.NORMALIZED_CHAPTER_01_JSON.read_text(encoding="utf-8"))
        cls.glossary = json.loads(config.MATH_GLOSSARY_FR_JSON.read_text(encoding="utf-8"))

    def test_all_100_items_get_exactly_one_record(self):
        result = enrich(self.normalized, self.glossary)
        self.assertEqual(len(result["items"]), len(self.normalized["items"]))
        self.assertEqual(
            {r["item_id"] for r in result["items"]},
            {i["id"] for i in self.normalized["items"]},
        )

    def test_deterministic_rerun_on_real_data(self):
        r1 = enrich(self.normalized, self.glossary)
        r2 = enrich(self.normalized, self.glossary)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_real_chapter_1_output_passes_validation(self):
        result = enrich(self.normalized, self.glossary)
        report = validate(result, self.normalized, self.glossary)
        self.assertTrue(report["passed"], report["checks"])

    def test_no_field_ever_uses_llm_in_v1(self):
        result = enrich(self.normalized, self.glossary)
        for record in result["items"]:
            self.assertNotIn("llm", record["generation_methods"].values())
            self.assertEqual(record["review_status"], "NOT_REQUIRED")

    def test_every_theorem_property_definition_remark_has_null_exercise_type(self):
        result = enrich(self.normalized, self.glossary)
        non_exercise_types = {"theorem", "property", "definition", "remark"}
        for record in result["items"]:
            if record["item_type"] in non_exercise_types:
                self.assertIsNone(record["exercise_type"])
                self.assertEqual(record["reasoning_types"], [])


if __name__ == "__main__":
    unittest.main()
