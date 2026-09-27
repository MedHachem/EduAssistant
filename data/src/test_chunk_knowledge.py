"""
Unit + regression tests for chunk_knowledge.py and validate_chunks.py
(Phase 10).

Three test classes:
  - TestChunking: synthetic normalized/enrichment/relations fixtures,
    one per required guarantee (1:1 default, confirmed merge, false-
    positive merge prevention, oversized split, oversized-without-split-
    point, correction chunk, multi-page item, figure references,
    relation -> related_chunk_ids, uncertainty propagation, stable IDs,
    deterministic ordering, missing/invalid upstream references).
  - TestValidation: synthetic failure-injection cases for the validator.
  - TestChapter1Regression: runs the real chunker + validator against
    the real Chapter 1 files, if present on disk. Chapter 1's own ids
    appear ONLY in this class, never in chunk_knowledge.py/
    validate_chunks.py themselves (checked directly below).

Run:
    python test_chunk_knowledge.py
    python -m unittest test_chunk_knowledge
"""

import json
import unittest
from pathlib import Path

import config
from chunk_knowledge import chunk
from validate_chunks import validate


def make_item(item_id, item_type="theorem", order=0, section_id="sec-a", subsection_id=None,
              content="x", proof=None, pages=(5,), bloc_numero=None,
              exercise_details=None, uncertain=False, gap=False, figures=None):
    return {
        "id": item_id, "type": item_type, "order": order,
        "chapter_id": "doc-x-ch01", "document_id": "doc-x",
        "section_id": section_id, "subsection_id": subsection_id,
        "title": None, "display_label": None, "content": content, "proof": proof,
        "links": {"definitions": [], "theorems": [], "properties": [], "formulas": [],
                   "methods": [], "exercises": [], "figures": figures or []},
        "exercise_details": exercise_details,
        "uncertainty": {"has_uncertain_markers": uncertain, "has_gap_markers": gap, "uncertain_spans": []},
        "provenance": {"source_item_id": item_id, "document_id": "doc-x", "pdf_pages": list(pages),
                        "reconstructed_sources": [f"page_{p:03d}.md" for p in pages], "bloc_type": item_type,
                        "bloc_numero": bloc_numero, "continues_from_previous_page": False,
                        "continues_on_next_page": False, "original_content": content},
    }


def make_normalized(items, sections=None, subsections=None):
    return {
        "schema_version": "normalized-1.0", "algorithm_version": "normalize-v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "document": {"id": "doc-x", "title": "T", "subject": "Math", "level": "L",
                     "country": "C", "source_pdf": "x.pdf", "total_pages": 50},
        "chapter": {"id": "doc-x-ch01", "document_id": "doc-x", "number": 1, "title": "Chap",
                    "pdf_page_start": 1, "pdf_page_end": 20},
        "sections": sections or [{"id": "sec-a", "chapter_id": "doc-x-ch01", "label": "I", "title": "Section A",
                                    "pdf_page_start": 1, "pdf_page_end": 20, "order": 0, "irregularities": []}],
        "subsections": subsections or [],
        "items": items,
    }


def make_enrichment_record(item_id, item_type="theorem", topics=None, concepts=None):
    return {
        "item_id": item_id, "item_type": item_type, "topics": topics or ["Section A"], "keywords": [],
        "mathematical_entities": {"functions": [], "intervals": [], "equations": [], "notations": []},
        "exercise_type": None, "reasoning_types": [], "concepts": concepts or ["section a"],
        "generation_methods": {"topics": "deterministic", "keywords": "not_populated",
                                 "mathematical_entities": "not_populated", "exercise_type": "not_populated",
                                 "reasoning_types": "not_populated", "concepts": "rule_based"},
        "review_status": "NOT_REQUIRED",
    }


def make_enrichment(records):
    return {"schema_version": "enrichment-1.0", "algorithm_version": "enrich-v1",
            "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "doc-x-ch01", "items": records}


def make_relation(source_id, target_id, rel_type="applies_concept", source_kind="knowledge_item",
                   target_kind="knowledge_item", confidence="high"):
    return {
        "relation_id": f"rel-doc-x-ch01-{rel_type}-{source_id}-{target_id}",
        "type": rel_type, "source_id": source_id, "source_kind": source_kind,
        "target_id": target_id, "target_kind": target_kind, "confidence": confidence,
        "generation_method": "rule_based" if rel_type == "applies_concept" else "human_confirmed",
        "review_status": "NOT_REQUIRED", "signals": {},
    }


def make_relations(rels):
    return {"schema_version": "relations-1.0", "algorithm_version": "relations-v1",
            "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "doc-x-ch01", "relations": rels}


def make_figures_index(figure_ids):
    return {"chapter_id": "doc-x-ch01", "figures": [
        {"figure_id": fid, "source_page": 5, "candidate_id": None, "status": "VALIDATED",
         "original_bbox": [0, 0, 1, 1], "final_bbox": [0, 0, 1, 1], "image": f"{fid}.png",
         "source_image": "page_005.png"} for fid in figure_ids
    ]}


def sub_question(label, text=None, subs=None):
    return {"label": label, "text": text, "sub_questions": subs or []}


def exercise_details(statement=None, questions=None, correction_present=False, correction_content=None,
                      qcm_choices=None):
    return {
        "statement": statement, "questions": questions or [],
        "correction": {"present_in_source": correction_present, "content": correction_content},
        "qcm_choices": qcm_choices,
    }


class TestChunking(unittest.TestCase):
    def test_default_one_item_to_one_chunk(self):
        items = [make_item("it-1", "theorem", order=0)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        self.assertEqual(len(result["chunks"]), 1)
        c = result["chunks"][0]
        self.assertEqual(c["source_item_ids"], ["it-1"])
        self.assertEqual(c["content_role"], "statement")
        self.assertIsNone(c["part_index"])
        self.assertEqual(c["generation_methods"]["boundaries"], "deterministic")
        self.assertEqual(c["review_status"], "NOT_REQUIRED")

    def test_confirmed_fragmentation_merge(self):
        items = [
            make_item("exo-a", "exercise", order=10, bloc_numero="8",
                       content="Etudier la limite.\n\n1. f(x)=...", pages=(24,)),
            make_item("exo-b", "exercise", order=11, bloc_numero="8",
                       content="4. f(x)=... en 1.", pages=(25,)),
        ]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("exo-a", "exercise", concepts=["limites"]),
            make_enrichment_record("exo-b", "exercise", concepts=["section a"]),
        ])
        result = chunk(normalized, enrichment)
        self.assertEqual(len(result["chunks"]), 1)
        c = result["chunks"][0]
        self.assertEqual(c["source_item_ids"], ["exo-a", "exo-b"])
        self.assertEqual(c["pdf_pages"], [24, 25])
        self.assertIn("limites", c["concepts"])
        self.assertEqual(c["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(c["generation_methods"]["boundaries"], "rule_based")
        self.assertIn("Etudier la limite.", c["text"])
        self.assertIn("4. f(x)=... en 1.", c["text"])

    def test_false_positive_merge_prevented_by_non_adjacent_order(self):
        """Same type/section/bloc_numero but order gap > 1 -- must NOT merge
        (mirrors the real act-013/act-016 case in Chapter 1)."""
        items = [
            make_item("act-a", "activity", order=5, bloc_numero="1"),
            make_item("filler", "theorem", order=6),
            make_item("act-b", "activity", order=7, bloc_numero="1"),
        ]
        normalized = make_normalized(items)
        enrichment = make_enrichment([
            make_enrichment_record("act-a", "activity"),
            make_enrichment_record("filler", "theorem"),
            make_enrichment_record("act-b", "activity"),
        ])
        result = chunk(normalized, enrichment)
        statement_chunks = [c for c in result["chunks"] if c["content_role"] == "statement"]
        self.assertEqual(len(statement_chunks), 3)
        for c in statement_chunks:
            self.assertEqual(len(c["source_item_ids"]), 1)

    def test_false_positive_merge_prevented_by_different_section(self):
        items = [
            make_item("act-a", "activity", order=0, section_id="sec-a", bloc_numero="1"),
            make_item("act-b", "activity", order=1, section_id="sec-b", bloc_numero="1"),
        ]
        sections = [
            {"id": "sec-a", "chapter_id": "doc-x-ch01", "label": "I", "title": "A",
             "pdf_page_start": 1, "pdf_page_end": 5, "order": 0, "irregularities": []},
            {"id": "sec-b", "chapter_id": "doc-x-ch01", "label": "II", "title": "B",
             "pdf_page_start": 6, "pdf_page_end": 10, "order": 1, "irregularities": []},
        ]
        normalized = make_normalized(items, sections=sections)
        enrichment = make_enrichment([make_enrichment_record("act-a"), make_enrichment_record("act-b")])
        result = chunk(normalized, enrichment)
        statement_chunks = [c for c in result["chunks"] if c["content_role"] == "statement"]
        self.assertEqual(len(statement_chunks), 2)

    def test_oversized_item_with_valid_split_point_splits_by_top_level_question(self):
        long_text = "x" * 2000
        details = exercise_details(questions=[
            sub_question("1", "First part."), sub_question("2", "Second part."),
        ])
        items = [make_item("exo-1", "exercise", order=0, content=long_text, exercise_details=details)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("exo-1", "exercise")])
        result = chunk(normalized, enrichment)
        parts = [c for c in result["chunks"] if c["content_role"] == "statement"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]["part_index"], 0)
        self.assertEqual(parts[0]["part_count"], 2)
        self.assertEqual(parts[1]["part_index"], 1)
        self.assertIn("First part.", parts[0]["text"])
        self.assertIn("Second part.", parts[1]["text"])
        self.assertEqual(parts[0]["review_status"], "REVIEW_REQUIRED")

    def test_oversized_item_without_valid_split_point_stays_whole(self):
        """Long text but only ONE top-level question (or none) -- never
        force-split by character count alone."""
        long_text = "x" * 2000
        details = exercise_details(statement=long_text, questions=[])
        items = [make_item("exo-1", "exercise", order=0, content=long_text, exercise_details=details)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("exo-1", "exercise")])
        result = chunk(normalized, enrichment)
        parts = [c for c in result["chunks"] if c["content_role"] == "statement"]
        self.assertEqual(len(parts), 1)
        self.assertIsNone(parts[0]["part_index"])

    def test_correction_chunk_is_separate_and_not_duplicated_in_statement(self):
        content = "Enonce.\n\n### Solution\n\nVoici la solution."
        details = exercise_details(
            questions=[sub_question("1", "Question.")],
            correction_present=True, correction_content="Voici la solution.",
        )
        items = [make_item("exo-1", "exercise", order=0, content=content, exercise_details=details)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("exo-1", "exercise")])
        result = chunk(normalized, enrichment)
        by_role = {c["content_role"]: c for c in result["chunks"] if len(result["chunks"]) <= 2}
        statement = next(c for c in result["chunks"] if c["content_role"] == "statement")
        correction = next(c for c in result["chunks"] if c["content_role"] == "correction")
        self.assertNotIn("Voici la solution.", statement["text"])
        self.assertEqual(correction["text"], "Voici la solution.")
        self.assertIn(correction["chunk_id"], statement["related_chunk_ids"])
        self.assertIn(statement["chunk_id"], correction["related_chunk_ids"])
        self.assertEqual(correction["review_status"], "NOT_REQUIRED")

    def test_multi_page_item_pdf_pages_is_union(self):
        items = [make_item("it-1", "exercise", order=0, pages=(5, 6, 7))]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1", "exercise")])
        result = chunk(normalized, enrichment)
        self.assertEqual(result["chunks"][0]["pdf_pages"], [5, 6, 7])

    def test_figure_references_from_links_figures(self):
        items = [make_item("it-1", figures=[
            {"pdf_page": 5, "reconstructed_figure_id": "fig-x", "candidate_id": None,
             "figure_status_in_source": "described", "match_status": "unresolved"},
        ])]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        refs = result["chunks"][0]["figure_refs"]
        self.assertEqual(refs, [{"source": "links.figures", "reconstructed_figure_id": "fig-x",
                                  "figure_id": None, "confidence": None}])

    def test_figure_references_from_illustrates_relation(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        relations = make_relations([make_relation("figure_001", "it-1", rel_type="illustrates",
                                                     source_kind="figure", confidence="high")])
        figures_index = make_figures_index(["figure_001"])
        result = chunk(normalized, enrichment, relations, figures_index)
        refs = result["chunks"][0]["figure_refs"]
        self.assertEqual(refs, [{"source": "relation:illustrates", "reconstructed_figure_id": None,
                                  "figure_id": "figure_001", "confidence": "high"}])

    def test_applies_concept_relation_populates_related_chunk_ids_both_directions(self):
        items = [make_item("thm-1", "theorem", order=0), make_item("act-1", "activity", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("thm-1"), make_enrichment_record("act-1")])
        relations = make_relations([make_relation("act-1", "thm-1", rel_type="applies_concept")])
        result = chunk(normalized, enrichment, relations)
        by_source = {tuple(c["source_item_ids"]): c for c in result["chunks"]}
        self.assertIn(by_source[("thm-1",)]["chunk_id"], by_source[("act-1",)]["related_chunk_ids"])
        self.assertIn(by_source[("act-1",)]["chunk_id"], by_source[("thm-1",)]["related_chunk_ids"])

    def test_illustrates_relation_never_produces_related_chunk_ids(self):
        """Illustrates' source is a figure, not a chunk -- it must show
        up only in figure_refs, never related_chunk_ids."""
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        relations = make_relations([make_relation("figure_001", "it-1", rel_type="illustrates", source_kind="figure")])
        result = chunk(normalized, enrichment, relations)
        self.assertEqual(result["chunks"][0]["related_chunk_ids"], [])

    def test_uncertain_content_propagates(self):
        items = [make_item("it-1", uncertain=True)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        self.assertTrue(result["chunks"][0]["has_uncertain_content"])

    def test_uncertain_content_false_by_default(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        self.assertFalse(result["chunks"][0]["has_uncertain_content"])

    def test_deterministic_chunk_ids_and_rerun(self):
        items = [make_item("it-1", order=0), make_item("it-2", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1"), make_enrichment_record("it-2")])
        r1 = chunk(normalized, enrichment)
        r2 = chunk(normalized, enrichment)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)
        self.assertEqual(r1["chunks"][0]["chunk_id"], "chunk-doc-x-ch01-it-1")

    def test_deterministic_ordering(self):
        items = [make_item("it-2", order=1), make_item("it-1", order=0)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1"), make_enrichment_record("it-2")])
        result = chunk(normalized, enrichment)
        self.assertEqual([c["source_item_ids"][0] for c in result["chunks"]], ["it-1", "it-2"])

    def test_missing_relations_and_figures_index_produce_empty_metadata_not_errors(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment, relations=None, figures_index=None)
        c = result["chunks"][0]
        self.assertEqual(c["related_chunk_ids"], [])
        self.assertEqual(c["figure_refs"], [])

    def test_invalid_figure_id_is_nulled_out_not_left_dangling(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        relations = make_relations([make_relation("figure_999", "it-1", rel_type="illustrates", source_kind="figure")])
        figures_index = make_figures_index(["figure_001"])  # figure_999 does not exist
        result = chunk(normalized, enrichment, relations, figures_index)
        self.assertIsNone(result["chunks"][0]["figure_refs"][0]["figure_id"])

    def test_no_chapter_specific_hardcoding_in_production_modules(self):
        for filename in ("chunk_knowledge.py", "validate_chunks.py"):
            src = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
            for token in ("math-4eme-tome1", "-ch01", "act-008", "exo-001", "exo-009", "exo-010"):
                self.assertNotIn(token, src, f"{filename} must not reference {token!r}")


class TestValidation(unittest.TestCase):
    def test_valid_output_passes(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        report = validate(result, normalized)
        self.assertTrue(report["passed"], report["checks"])

    def test_duplicate_chunk_id_is_detected(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        result["chunks"].append(dict(result["chunks"][0]))
        report = validate(result, normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["duplicate_chunk_ids"])

    def test_missing_item_coverage_is_detected(self):
        items = [make_item("it-1"), make_item("it-2", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1"), make_enrichment_record("it-2")])
        result = chunk(normalized, enrichment)
        result["chunks"].pop()
        report = validate(result, normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["item_coverage"])

    def test_tampered_chunk_id_is_detected(self):
        items = [make_item("it-1")]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1")])
        result = chunk(normalized, enrichment)
        result["chunks"][0]["chunk_id"] = "chunk-tampered"
        report = validate(result, normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["stable_ids"])

    def test_bad_split_part_count_is_detected(self):
        long_text = "x" * 2000
        details = exercise_details(questions=[sub_question("1", "A"), sub_question("2", "B")])
        items = [make_item("exo-1", "exercise", order=0, content=long_text, exercise_details=details)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("exo-1", "exercise")])
        result = chunk(normalized, enrichment)
        result["chunks"][0]["part_count"] = 5  # corrupt it
        report = validate(result, normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["split_consistency"])

    def test_bad_ordering_is_detected(self):
        items = [make_item("it-1", order=0), make_item("it-2", order=1)]
        normalized = make_normalized(items)
        enrichment = make_enrichment([make_enrichment_record("it-1"), make_enrichment_record("it-2")])
        result = chunk(normalized, enrichment)
        result["chunks"].reverse()
        report = validate(result, normalized)
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["ordering"])


class TestChapter1Regression(unittest.TestCase):
    """Chapter 1 is used ONLY as ground truth/fixture -- see
    test_no_chapter_specific_hardcoding_in_production_modules above."""

    @classmethod
    def setUpClass(cls):
        required = [config.NORMALIZED_CHAPTER_01_JSON, config.enrichment_json(config.CHAPTER_01_ID)]
        if not all(p.exists() for p in required):
            raise unittest.SkipTest("Chapter 1 normalized/enrichment JSON not found")
        cls.normalized = json.loads(config.NORMALIZED_CHAPTER_01_JSON.read_text(encoding="utf-8"))
        cls.enrichment = json.loads(config.enrichment_json(config.CHAPTER_01_ID).read_text(encoding="utf-8"))
        rel_path = config.relations_json(config.CHAPTER_01_ID)
        cls.relations = json.loads(rel_path.read_text(encoding="utf-8")) if rel_path.exists() else None
        fig_path = config.FINAL_FIGURES_INDEX_JSON
        cls.figures_index = json.loads(fig_path.read_text(encoding="utf-8")) if fig_path.exists() else None

    def test_deterministic_rerun_on_real_data(self):
        r1 = chunk(self.normalized, self.enrichment, self.relations, self.figures_index)
        r2 = chunk(self.normalized, self.enrichment, self.relations, self.figures_index)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_real_chapter_1_output_passes_validation(self):
        result = chunk(self.normalized, self.enrichment, self.relations, self.figures_index)
        report = validate(result, self.normalized, self.figures_index)
        self.assertTrue(report["passed"], report["checks"])

    def test_every_normalized_item_is_covered(self):
        result = chunk(self.normalized, self.enrichment, self.relations, self.figures_index)
        statement_chunks = [c for c in result["chunks"] if c["content_role"] == "statement"]
        covered = {iid for c in statement_chunks for iid in c["source_item_ids"]}
        self.assertEqual(covered, {i["id"] for i in self.normalized["items"]})


if __name__ == "__main__":
    unittest.main()
