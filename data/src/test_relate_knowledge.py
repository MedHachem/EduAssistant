"""
Unit + regression tests for relate_knowledge.py and validate_relations.py
(Phase 9).

Three test classes:
  - TestRelations: synthetic normalized/enrichment/association/review
    fixtures, one per required guarantee (applies_concept nearest-match,
    confidence tiers, tie-breaking, illustrates from human review vs.
    AUTO_MATCH, REJECTED blocks fallback, no chapter hardcoding, stable
    deterministic relation_id).
  - TestValidation: synthetic failure-injection cases for the validator.
  - TestChapter1Regression: runs the real relator + validator against
    the real Chapter 1 normalized/enrichment files, if present on disk.
    Chapter 1's own ids appear ONLY in this class, never in
    relate_knowledge.py/validate_relations.py themselves (checked
    directly below).

Run:
    python test_relate_knowledge.py
    python -m unittest test_relate_knowledge
"""

import json
import unittest
from pathlib import Path

import config
from relate_knowledge import relate
from validate_relations import validate


def make_normalized_item(item_id, item_type, order, section_id=None):
    return {
        "id": item_id, "type": item_type, "order": order,
        "chapter_id": "doc-x-ch01", "document_id": "doc-x",
        "section_id": section_id, "subsection_id": None,
        "title": None, "display_label": None, "content": "x",
        "proof": None,
        "links": {"definitions": [], "theorems": [], "properties": [], "formulas": [],
                   "methods": [], "exercises": [], "figures": []},
        "exercise_details": None,
        "uncertainty": {"has_uncertain_markers": False, "has_gap_markers": False, "uncertain_spans": []},
        "provenance": {"source_item_id": item_id, "document_id": "doc-x", "pdf_pages": [5],
                        "reconstructed_sources": ["page_005.md"], "bloc_type": item_type,
                        "bloc_numero": None, "continues_from_previous_page": False,
                        "continues_on_next_page": False, "original_content": "x"},
    }


def make_normalized(items):
    return {
        "schema_version": "normalized-1.0", "algorithm_version": "normalize-v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "document": {"id": "doc-x", "title": "T", "subject": "Math", "level": "L",
                     "country": "C", "source_pdf": "x.pdf", "total_pages": 50},
        "chapter": {"id": "doc-x-ch01", "document_id": "doc-x", "number": 1, "title": "Chap",
                    "pdf_page_start": 1, "pdf_page_end": 20},
        "sections": [], "subsections": [], "items": items,
    }


def make_enrichment_record(item_id, item_type, concepts):
    return {
        "item_id": item_id, "item_type": item_type, "topics": [], "keywords": [],
        "mathematical_entities": {"functions": [], "intervals": [], "equations": [], "notations": []},
        "exercise_type": None, "reasoning_types": [], "concepts": concepts,
        "generation_methods": {"topics": "not_populated", "keywords": "not_populated",
                                 "mathematical_entities": "not_populated", "exercise_type": "not_populated",
                                 "reasoning_types": "not_populated", "concepts": "rule_based"},
        "review_status": "NOT_REQUIRED",
    }


def make_enrichment(records):
    return {"schema_version": "enrichment-1.0", "algorithm_version": "enrich-v1",
            "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "doc-x-ch01", "items": records}


def make_association(figure_id, decision, chosen_item_id=None):
    return {"figure_id": figure_id, "chapter_id": "doc-x-ch01", "source_page": 5,
            "candidate_image": f"{figure_id}.png", "decision": decision, "review_status": None,
            "chosen_association_id": None, "chosen_item_id": chosen_item_id, "relation": None,
            "score": None, "candidates": []}


def make_associations_file(assocs):
    return {"chapter_id": "doc-x-ch01", "algorithm_version": "assoc-v1", "generated_at": "2026-01-01T00:00:00Z",
            "summary": {}, "pipeline_status": "ASSOCIATION_REVIEW_REQUIRED", "associations": assocs}


class TestRelations(unittest.TestCase):
    def test_applies_concept_links_to_nearest_reference_item(self):
        items = [
            make_normalized_item("thm-1", "theorem", order=0),
            make_normalized_item("act-1", "activity", order=1),
            make_normalized_item("thm-2", "theorem", order=10),
        ]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["limites"]),
            make_enrichment_record("act-1", "activity", ["limites"]),
            make_enrichment_record("thm-2", "theorem", ["limites"]),
        ])
        result = relate(normalized, enrichment)
        rel = next(r for r in result["relations"] if r["source_id"] == "act-1")
        self.assertEqual(rel["target_id"], "thm-1")
        self.assertEqual(rel["signals"]["reading_order_distance"], 1)

    def test_no_relation_when_no_shared_concept(self):
        items = [make_normalized_item("thm-1", "theorem", order=0), make_normalized_item("act-1", "activity", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["limites"]),
            make_enrichment_record("act-1", "activity", ["intervalles"]),
        ])
        result = relate(normalized, enrichment)
        self.assertEqual(result["relations"], [])

    def test_confidence_tiers_from_distance(self):
        items = [
            make_normalized_item("thm-1", "theorem", order=0),
            make_normalized_item("act-high", "activity", order=5),
            make_normalized_item("act-medium", "activity", order=25),
            make_normalized_item("act-low", "activity", order=50),
        ]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["c"]),
            make_enrichment_record("act-high", "activity", ["c"]),
            make_enrichment_record("act-medium", "activity", ["c"]),
            make_enrichment_record("act-low", "activity", ["c"]),
        ])
        result = relate(normalized, enrichment)
        by_source = {r["source_id"]: r for r in result["relations"]}
        self.assertEqual(by_source["act-high"]["confidence"], "high")
        self.assertEqual(by_source["act-high"]["review_status"], "NOT_REQUIRED")
        self.assertEqual(by_source["act-medium"]["confidence"], "medium")
        self.assertEqual(by_source["act-medium"]["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(by_source["act-low"]["confidence"], "low")
        self.assertEqual(by_source["act-low"]["review_status"], "REVIEW_REQUIRED")

    def test_tie_breaks_toward_earlier_reference_item(self):
        items = [
            make_normalized_item("thm-early", "theorem", order=0),
            make_normalized_item("act-1", "activity", order=5),
            make_normalized_item("thm-late", "theorem", order=10),
        ]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-early", "theorem", ["c"]),
            make_enrichment_record("act-1", "activity", ["c"]),
            make_enrichment_record("thm-late", "theorem", ["c"]),
        ])
        result = relate(normalized, enrichment)
        rel = result["relations"][0]
        self.assertEqual(rel["target_id"], "thm-early")

    def test_reference_items_never_link_to_each_other(self):
        items = [make_normalized_item("thm-1", "theorem", order=0), make_normalized_item("prop-1", "property", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["c"]),
            make_enrichment_record("prop-1", "property", ["c"]),
        ])
        result = relate(normalized, enrichment)
        self.assertEqual(result["relations"], [])

    def test_relation_id_is_deterministic_and_content_derived(self):
        items = [make_normalized_item("thm-1", "theorem", order=0), make_normalized_item("act-1", "activity", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["c"]),
            make_enrichment_record("act-1", "activity", ["c"]),
        ])
        r1 = relate(normalized, enrichment)
        r2 = relate(normalized, enrichment)
        self.assertEqual(r1["relations"][0]["relation_id"], r2["relations"][0]["relation_id"])
        self.assertEqual(r1["relations"][0]["relation_id"], "rel-doc-x-ch01-applies_concept-act-1-thm-1")

    def test_illustrates_from_human_confirmed_review(self):
        associations = make_associations_file([make_association("figure_001", "REVIEW_REQUIRED", "it-1")])
        reviews = [{"figureId": "figure_001", "knowledgeItemId": "it-9", "status": "CONFIRMED"}]
        result = relate(make_normalized([]), make_enrichment([]), associations, reviews)
        rel = result["relations"][0]
        self.assertEqual(rel["type"], "illustrates")
        self.assertEqual(rel["target_id"], "it-9", "human decision overrides the algorithm's own chosen_item_id")
        self.assertEqual(rel["generation_method"], "human_confirmed")
        self.assertEqual(rel["confidence"], "high")
        self.assertEqual(rel["review_status"], "HUMAN_APPROVED")

    def test_illustrates_from_reassigned_is_weaker_than_confirmed(self):
        associations = make_associations_file([make_association("figure_001", "REVIEW_REQUIRED")])
        reviews = [{"figureId": "figure_001", "knowledgeItemId": "it-2", "status": "REASSIGNED"}]
        result = relate(make_normalized([]), make_enrichment([]), associations, reviews)
        rel = result["relations"][0]
        self.assertEqual(rel["confidence"], "medium")
        self.assertEqual(rel["review_status"], "REVIEW_REQUIRED")
        self.assertNotEqual(rel["review_status"], "HUMAN_APPROVED")

    def test_illustrates_rejected_review_blocks_relation_entirely(self):
        associations = make_associations_file([make_association("figure_001", "AUTO_MATCH", "it-1")])
        reviews = [{"figureId": "figure_001", "knowledgeItemId": None, "status": "REJECTED"}]
        result = relate(make_normalized([]), make_enrichment([]), associations, reviews)
        self.assertEqual(result["relations"], [], "a human REJECTED decision must never fall back to AUTO_MATCH")

    def test_illustrates_falls_back_to_auto_match_when_no_review_exists(self):
        associations = make_associations_file([make_association("figure_001", "AUTO_MATCH", "it-1")])
        result = relate(make_normalized([]), make_enrichment([]), associations, reviews=None)
        rel = result["relations"][0]
        self.assertEqual(rel["target_id"], "it-1")
        self.assertEqual(rel["generation_method"], "rule_based")
        self.assertEqual(rel["review_status"], "REVIEW_REQUIRED")

    def test_illustrates_no_match_and_no_review_produces_no_relation(self):
        associations = make_associations_file([make_association("figure_001", "NO_MATCH")])
        result = relate(make_normalized([]), make_enrichment([]), associations, reviews=None)
        self.assertEqual(result["relations"], [])

    def test_no_associations_file_means_zero_illustrates_relations(self):
        result = relate(make_normalized([]), make_enrichment([]), associations=None, reviews=None)
        self.assertEqual(result["relations"], [])

    def test_deterministic_rerun_produces_identical_output(self):
        items = [make_normalized_item("thm-1", "theorem", order=0), make_normalized_item("act-1", "activity", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("thm-1", "theorem", ["c"]),
            make_enrichment_record("act-1", "activity", ["c"]),
        ])
        r1 = relate(normalized, enrichment)
        r2 = relate(normalized, enrichment)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_no_chapter_specific_hardcoding_in_production_modules(self):
        for filename in ("relate_knowledge.py", "validate_relations.py"):
            src = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
            for token in ("math-4eme-tome1", "-ch01", "act-008", "prop-001"):
                self.assertNotIn(token, src, f"{filename} must not reference {token!r}")


class TestValidation(unittest.TestCase):
    def _minimal_relations(self, relations):
        return {"schema_version": "relations-1.0", "algorithm_version": "relations-v1",
                "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "doc-x-ch01", "relations": relations}

    def _one_relation(self, **overrides):
        base = {
            "relation_id": "rel-doc-x-ch01-applies_concept-act-1-thm-1",
            "type": "applies_concept", "source_id": "act-1", "source_kind": "knowledge_item",
            "target_id": "thm-1", "target_kind": "knowledge_item", "confidence": "high",
            "generation_method": "rule_based", "review_status": "NOT_REQUIRED",
            "signals": {"shared_concepts": ["c"], "reading_order_distance": 1, "source_review_status": None},
        }
        base.update(overrides)
        return base

    def test_valid_output_passes(self):
        relations = self._minimal_relations([self._one_relation()])
        report = validate(relations)
        self.assertTrue(report["passed"])

    def test_duplicate_relation_id_is_detected(self):
        rel = self._one_relation()
        relations = self._minimal_relations([rel, dict(rel)])
        report = validate(relations)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["duplicate_relation_ids"])

    def test_orphan_item_reference_is_detected(self):
        relations = self._minimal_relations([self._one_relation(target_id="does-not-exist")])
        normalized = make_normalized([make_normalized_item("act-1", "activity", order=0)])
        report = validate(relations, normalized=normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["referential_integrity"])

    def test_low_confidence_not_required_is_detected(self):
        relations = self._minimal_relations([self._one_relation(confidence="low", review_status="NOT_REQUIRED")])
        report = validate(relations)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["consistency"])

    def test_llm_generated_not_required_is_detected(self):
        relations = self._minimal_relations([self._one_relation(generation_method="llm", review_status="NOT_REQUIRED")])
        report = validate(relations)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["consistency"])


class TestChapter1Regression(unittest.TestCase):
    """Chapter 1 is used ONLY as ground truth/fixture -- see
    test_no_chapter_specific_hardcoding_in_production_modules above."""

    @classmethod
    def setUpClass(cls):
        if not config.NORMALIZED_CHAPTER_01_JSON.exists() or not config.enrichment_json(config.CHAPTER_01_ID).exists():
            raise unittest.SkipTest("Chapter 1 normalized/enrichment JSON not found")
        cls.normalized = json.loads(config.NORMALIZED_CHAPTER_01_JSON.read_text(encoding="utf-8"))
        cls.enrichment = json.loads(config.enrichment_json(config.CHAPTER_01_ID).read_text(encoding="utf-8"))
        assoc_path = config.associations_json(config.CHAPTER_01_ID)
        cls.associations = json.loads(assoc_path.read_text(encoding="utf-8")) if assoc_path.exists() else None

    def test_deterministic_rerun_on_real_data(self):
        r1 = relate(self.normalized, self.enrichment, self.associations)
        r2 = relate(self.normalized, self.enrichment, self.associations)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_real_chapter_1_output_passes_validation(self):
        result = relate(self.normalized, self.enrichment, self.associations)
        report = validate(result, self.normalized, None)
        self.assertTrue(report["passed"], report["checks"])

    def test_every_relation_endpoint_is_a_real_item(self):
        result = relate(self.normalized, self.enrichment, self.associations)
        valid_ids = {i["id"] for i in self.normalized["items"]}
        for r in result["relations"]:
            if r["source_kind"] == "knowledge_item":
                self.assertIn(r["source_id"], valid_ids)
            if r["target_kind"] == "knowledge_item":
                self.assertIn(r["target_id"], valid_ids)

    def test_no_reference_item_is_ever_a_relation_source(self):
        result = relate(self.normalized, self.enrichment, self.associations)
        type_by_id = {i["id"]: i["type"] for i in self.normalized["items"]}
        for r in result["relations"]:
            if r["type"] == "applies_concept":
                self.assertIn(type_by_id[r["source_id"]], {"activity", "exercise", "example"})
                self.assertIn(type_by_id[r["target_id"]], {"theorem", "property", "definition"})


if __name__ == "__main__":
    unittest.main()
