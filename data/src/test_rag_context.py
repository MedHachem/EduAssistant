"""
Phase 14 - tests for rag_context.py.

Uses the same dedicated local PostgreSQL test database as
test_search_embeddings.py / test_import_embeddings.py (ai_education_test)
-- no Docker required, never touches the real ai_education database.
embeddings_1024 is TRUNCATEd between tests for isolation.

Ranking/selection tests insert hand-crafted, angle-based vectors with an
analytically known cosine similarity (see test_search_embeddings.py's own
_vector_at_angle) directly into embeddings_1024, paired with a matching
synthetic knowledge_chunks.json fixture carrying the extra fields
rag_context.py reads beyond SearchResult (related_chunk_ids, item_types,
order, review_status, figure_refs).

Chapter 1's own ids appear ONLY in TestChapter1RealRagRegression.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

import config
import init_vector_db_schema
from embed_knowledge import file_hash
from rag_context import assemble_context
from search_embeddings import SearchIncompatibleModelError


def _test_database_url() -> str:
    parts = urlsplit(config.database_url())
    return urlunsplit((parts.scheme, parts.netloc, "/ai_education_test", parts.query, parts.fragment))


TEST_DATABASE_URL = _test_database_url()


def _postgres_test_db_available() -> bool:
    try:
        conn = psycopg.connect(TEST_DATABASE_URL, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _postgres_test_db_available()

DIMENSION = 1024


def _vector_at_angle(theta_degrees: float, dimension: int = DIMENSION) -> np.ndarray:
    """A unit vector [cos(theta), sin(theta), 0, ..., 0] -- its cosine
    similarity against _vector_at_angle(0) is EXACTLY cos(theta_degrees),
    an analytically known constant (mirrors test_search_embeddings.py)."""
    theta = math.radians(theta_degrees)
    v = np.zeros(dimension, dtype=np.float32)
    v[0] = math.cos(theta)
    v[1] = math.sin(theta)
    return v


class FixedVectorBackend:
    """Always returns the same pre-chosen vector regardless of input text
    -- full control over the 'query embedding' step (mirrors
    test_search_embeddings.py's own double)."""

    def __init__(self, vector: np.ndarray, model_name="test/model", model_revision="rev1"):
        self.dimension = vector.shape[0]
        self._vector = np.asarray(vector, dtype=np.float32)
        self.model_name = model_name
        self.model_revision = model_revision
        self.calls: list[str] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls.extend(texts)
        return np.tile(self._vector, (len(texts), 1)).astype(np.float32)


DEFAULT_FILTER_METADATA = {
    "section_id": None, "subsection_id": None, "topics": [], "concepts": [],
    "item_types": [], "content_role": "statement", "pdf_pages": [], "has_uncertain_content": False,
}


def _make_chunk(chunk_id: str, chapter_id: str, order: int, content_role="statement",
                 item_types=None, section_id="sec-a", subsection_id=None,
                 related_chunk_ids=None, review_status="NOT_REQUIRED",
                 has_uncertain_content=False, figure_refs=None, text=None,
                 source_item_ids=None, topics=None, concepts=None, pdf_pages=None) -> dict:
    return {
        "chunk_id": chunk_id, "chapter_id": chapter_id, "order": order,
        "content_role": content_role, "part_index": None, "part_count": None,
        "source_item_ids": source_item_ids or [chunk_id],
        "item_types": item_types or ["exercise"],
        "section_id": section_id, "section_title": section_id,
        "subsection_id": subsection_id, "subsection_title": subsection_id,
        "pdf_pages": pdf_pages or [1], "topics": topics or ["Topic"],
        "concepts": concepts or ["concept"],
        "text": text or f"Text for {chunk_id}.",
        "figure_refs": figure_refs or [],
        "related_chunk_ids": related_chunk_ids or [],
        "has_uncertain_content": has_uncertain_content,
        "generation_methods": {
            "boundaries": "deterministic", "text_assembly": "deterministic",
            "topics": "deterministic", "concepts": "rule_based",
            "figure_refs": "deterministic", "related_chunk_ids": "rule_based",
        },
        "review_status": review_status,
    }


def _write_chunks_file(tmp_path: Path, chapter_id: str, chunks: list[dict]) -> Path:
    doc = {"schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
           "generated_at": "2026-01-01T00:00:00Z", "chapter_id": chapter_id, "chunks": chunks}
    path = tmp_path / f"{chapter_id}-chunks.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_relations_file(tmp_path: Path, chapter_id: str, relations: list[dict]) -> Path:
    doc = {"schema_version": "relations-1.0", "algorithm_version": "relations-v1",
           "generated_at": "2026-01-01T00:00:00Z", "chapter_id": chapter_id, "relations": relations}
    path = tmp_path / f"{chapter_id}-relations.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@unittest.skipUnless(POSTGRES_AVAILABLE, "ai_education_test PostgreSQL database is not reachable")
class PgTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_vector_db_schema.run(TEST_DATABASE_URL, config.VECTOR_DB_SCHEMA_SQL)

    def setUp(self):
        self.tmp_path = Path(tempfile.mkdtemp())
        conn = psycopg.connect(TEST_DATABASE_URL)
        conn.execute("TRUNCATE embeddings_1024")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def insert_row(self, chapter_id: str, chunk_id: str, vector: np.ndarray, model="test/model",
                    revision="rev1", status="active", filter_metadata: dict | None = None) -> None:
        filter_metadata = filter_metadata if filter_metadata is not None else dict(DEFAULT_FILTER_METADATA)
        embedding_id = f"emb-{chapter_id}-{chunk_id}-{model}-{revision}"
        conn = psycopg.connect(TEST_DATABASE_URL)
        register_vector(conn)
        conn.execute(
            "INSERT INTO embeddings_1024 (embedding_id, chunk_id, chapter_id, embedding_model, "
            "model_revision, content_hash, pipeline_version, normalization_strategy, status, "
            "filter_metadata, created_at, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)",
            (embedding_id, chunk_id, chapter_id, model, revision, "sha256:" + "0" * 64,
             "test-v1", "l2", status, Jsonb(filter_metadata), np.asarray(vector, dtype=np.float32)),
        )
        conn.commit()
        conn.close()

    def seed_environment(self, chapter_id: str, specs: list[dict]) -> Path:
        """Each spec must have 'angle'; remaining keys pass through to
        _make_chunk. Inserts one DB row (vector at that angle) + one
        chunks.json record per spec, then returns the chunks_path."""
        chunks = []
        for spec in specs:
            spec = dict(spec)
            angle = spec.pop("angle")
            chunk_id = spec["chunk_id"]
            record = _make_chunk(chapter_id=chapter_id, **spec)
            chunks.append(record)
            # filter_metadata must mirror the chunk record's own fields --
            # search() derives section_id/subsection_id/content_role/etc.
            # for the caller ENTIRELY from the stored filter_metadata, not
            # from the chunks.json file, so a mismatch here would silently
            # break every diversity/content-role-dependent test.
            filter_metadata = {
                "section_id": record["section_id"], "subsection_id": record["subsection_id"],
                "topics": record["topics"], "concepts": record["concepts"],
                "item_types": record["item_types"], "content_role": record["content_role"],
                "pdf_pages": record["pdf_pages"], "has_uncertain_content": record["has_uncertain_content"],
            }
            self.insert_row(chapter_id, chunk_id, _vector_at_angle(angle), filter_metadata=filter_metadata)
        return _write_chunks_file(self.tmp_path, chapter_id, chunks)

    def run_assemble(self, chapter_id, chunks_path, relations_path=None, **kwargs):
        return assemble_context(
            query="q", chapter_id=chapter_id, embedding_model="test/model", model_revision="rev1",
            database_url=TEST_DATABASE_URL, chunks_path=chunks_path, relations_path=relations_path,
            backend=FixedVectorBackend(_vector_at_angle(0)), **kwargs,
        )


# 1. Seed with no expansion
class TestSeedNoExpansion(PgTestCase):
    def test_seed_with_no_expansion_relation_stays_single_chunk_cluster(self):
        chunks_path = self.seed_environment("ch-1", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-1", chunks_path)
        self.assertEqual(r["expansions"], [])
        self.assertEqual(r["clusters_total"], 1)
        self.assertEqual(len(r["context"]), 1)


# 2. Correction -> statement
class TestCorrectionPullsStatement(PgTestCase):
    def test_correction_pulls_statement(self):
        chunks_path = self.seed_environment("ch-2", [
            {"chunk_id": "corr", "order": 2, "angle": 0, "content_role": "correction",
             "item_types": ["exercise"], "related_chunk_ids": ["stmt"]},
            {"chunk_id": "stmt", "order": 1, "angle": 90, "content_role": "statement",
             "item_types": ["exercise"]},
        ])
        # candidate_top_k=1 forces ONLY 'corr' back as a candidate/seed --
        # 'stmt' must arrive purely via E1 expansion, never as its own
        # independent seed (which would trivially satisfy the assertion
        # for the wrong reason).
        r = self.run_assemble("ch-2", chunks_path, candidate_top_k=1)
        self.assertEqual(len(r["expansions"]), 1)
        self.assertEqual(r["expansions"][0]["chunk_id"], "stmt")
        self.assertEqual(r["expansions"][0]["reason"], "expansion:correction_pair")
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertIn("stmt", chunk_ids)


# 3. Statement does not automatically -> correction
class TestStatementDoesNotPullCorrection(PgTestCase):
    def test_statement_does_not_pull_correction(self):
        chunks_path = self.seed_environment("ch-3", [
            {"chunk_id": "stmt", "order": 1, "angle": 0, "content_role": "statement",
             "item_types": ["exercise"], "related_chunk_ids": ["corr"]},
            {"chunk_id": "corr", "order": 2, "angle": 90, "content_role": "correction",
             "item_types": ["exercise"], "related_chunk_ids": ["stmt"]},
        ])
        # candidate_top_k=1: only 'stmt' comes back as a candidate/seed --
        # 'corr' must never appear, whether as an independent seed or an
        # expansion.
        r = self.run_assemble("ch-3", chunks_path, candidate_top_k=1)
        self.assertEqual(r["expansions"], [])
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertNotIn("corr", chunk_ids)


# 4. activity/exercise -> one concept chunk
class TestExercisePullsOneConceptChunk(PgTestCase):
    def test_exercise_pulls_one_concept_chunk(self):
        chunks_path = self.seed_environment("ch-4", [
            {"chunk_id": "exo", "order": 5, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-4", chunks_path, candidate_top_k=1)
        self.assertEqual(len(r["expansions"]), 1)
        self.assertEqual(r["expansions"][0]["chunk_id"], "thm")
        self.assertEqual(r["expansions"][0]["reason"], "expansion:applies_concept")


# 5. Deterministic concept selection by smallest order
class TestConceptSelectionDeterministic(PgTestCase):
    def test_concept_expansion_picks_smallest_order_when_multiple_qualify(self):
        chunks_path = self.seed_environment("ch-5", [
            {"chunk_id": "exo", "order": 10, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm-late", "thm-early", "prop-mid"]},
            {"chunk_id": "thm-late", "order": 8, "angle": 90, "item_types": ["theorem"]},
            {"chunk_id": "thm-early", "order": 2, "angle": 90, "item_types": ["theorem"]},
            {"chunk_id": "prop-mid", "order": 5, "angle": 90, "item_types": ["property"]},
        ])
        r = self.run_assemble("ch-5", chunks_path, candidate_top_k=1)
        self.assertEqual(len(r["expansions"]), 1)
        self.assertEqual(r["expansions"][0]["chunk_id"], "thm-early")


# 6. theorem/property/definition does not expand to exercise
class TestConceptSeedNoExpansion(PgTestCase):
    def test_concept_seed_does_not_expand_to_exercise(self):
        chunks_path = self.seed_environment("ch-6", [
            {"chunk_id": "thm", "order": 1, "angle": 0, "item_types": ["theorem"],
             "related_chunk_ids": ["exo1", "exo2"]},
            {"chunk_id": "exo1", "order": 2, "angle": 90, "item_types": ["exercise"]},
            {"chunk_id": "exo2", "order": 3, "angle": 91, "item_types": ["exercise"]},
        ])
        r = self.run_assemble("ch-6", chunks_path, candidate_top_k=1)
        self.assertEqual(r["expansions"], [])
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(chunk_ids, ["thm"])


# 7. Deduplication
class TestExpansionDeduplication(PgTestCase):
    def test_expansion_target_already_seed_is_deduplicated(self):
        chunks_path = self.seed_environment("ch-7", [
            {"chunk_id": "thm", "order": 1, "angle": 0, "item_types": ["theorem"]},
            {"chunk_id": "exo1", "order": 2, "angle": 1, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "exo2", "order": 3, "angle": 2, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
        ])
        r = self.run_assemble("ch-7", chunks_path, candidate_top_k=10)
        # thm is an independent seed (own high score); neither exo should
        # add a duplicate expansion for it.
        self.assertEqual(r["expansions"], [])
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(chunk_ids.count("thm"), 1)


# 8. Section diversity cap
class TestSectionDiversityCap(PgTestCase):
    def test_section_cap_rejects_lowest_scoring_over_cap(self):
        specs = [{"chunk_id": f"c{i}", "order": i, "angle": i * 5, "section_id": "sec-a",
                  "item_types": ["exercise"]} for i in range(5)]
        chunks_path = self.seed_environment("ch-8", specs)
        r = self.run_assemble("ch-8", chunks_path, candidate_top_k=10,
                               max_chunks_per_section=3, max_chunks_per_subsection=2)
        self.assertEqual(r["seed_count"], 3)
        rejected_ids = {x["chunk_id"] for x in r["rejected_seeds"]}
        self.assertEqual(rejected_ids, {"c3", "c4"})  # lowest-scoring 2 (largest angle) rejected
        for x in r["rejected_seeds"]:
            self.assertEqual(x["rejection_reason"], "section_cap")


# 9. Subsection diversity cap
class TestSubsectionDiversityCap(PgTestCase):
    def test_subsection_cap_rejects_lowest_scoring_over_cap(self):
        specs = [{"chunk_id": f"c{i}", "order": i, "angle": i * 5, "section_id": "sec-a",
                  "subsection_id": "sub-a", "item_types": ["exercise"]} for i in range(3)]
        chunks_path = self.seed_environment("ch-9", specs)
        r = self.run_assemble("ch-9", chunks_path, candidate_top_k=10,
                               max_chunks_per_section=10, max_chunks_per_subsection=2)
        self.assertEqual(r["seed_count"], 2)
        rejected_ids = {x["chunk_id"] for x in r["rejected_seeds"]}
        self.assertEqual(rejected_ids, {"c2"})
        self.assertEqual(r["rejected_seeds"][0]["rejection_reason"], "subsection_cap")


# 10. Null subsection handling
class TestNullSubsectionHandling(PgTestCase):
    def test_null_subsection_chunks_not_capped_by_subsection(self):
        specs = [{"chunk_id": f"c{i}", "order": i, "angle": i * 5, "section_id": "sec-a",
                  "subsection_id": None, "item_types": ["exercise"]} for i in range(3)]
        chunks_path = self.seed_environment("ch-10", specs)
        r = self.run_assemble("ch-10", chunks_path, candidate_top_k=10,
                               max_chunks_per_section=10, max_chunks_per_subsection=1)
        # subsection cap=1 would reject all but 1 IF null-subsection chunks
        # shared a bucket -- they must not.
        self.assertEqual(r["seed_count"], 3)


# 11. Expansion is not re-filtered by seed diversity
class TestExpansionBypassesDiversity(PgTestCase):
    def test_expansion_bypasses_diversity_caps(self):
        # 3 exercises in sec-a (cap=3, so all 3 survive as seeds), each
        # pointing to its OWN distinct concept chunk also in sec-a --
        # concept chunks would be the 4th/5th/6th members of sec-a if
        # they were subject to the same cap, but they must not be.
        specs = [
            {"chunk_id": "exo1", "order": 10, "angle": 0, "section_id": "sec-a",
             "item_types": ["exercise"], "related_chunk_ids": ["thm1"]},
            {"chunk_id": "exo2", "order": 11, "angle": 1, "section_id": "sec-a",
             "item_types": ["exercise"], "related_chunk_ids": ["thm2"]},
            {"chunk_id": "exo3", "order": 12, "angle": 2, "section_id": "sec-a",
             "item_types": ["exercise"], "related_chunk_ids": ["thm3"]},
            {"chunk_id": "thm1", "order": 1, "angle": 90, "section_id": "sec-a", "item_types": ["theorem"]},
            {"chunk_id": "thm2", "order": 2, "angle": 90, "section_id": "sec-a", "item_types": ["theorem"]},
            {"chunk_id": "thm3", "order": 3, "angle": 90, "section_id": "sec-a", "item_types": ["theorem"]},
        ]
        chunks_path = self.seed_environment("ch-11", specs)
        r = self.run_assemble("ch-11", chunks_path, candidate_top_k=10, max_chunks_per_section=3)
        self.assertEqual(r["seed_count"], 3)
        self.assertEqual(len(r["expansions"]), 3)
        chunk_ids = {c["chunk_id"] for c in r["context"]}
        self.assertEqual(chunk_ids, {"exo1", "exo2", "exo3", "thm1", "thm2", "thm3"})


# 12. Cluster creation
class TestClusterCreation(PgTestCase):
    def test_cluster_creation_seed_plus_expansion(self):
        chunks_path = self.seed_environment("ch-12", [
            {"chunk_id": "exo", "order": 5, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-12", chunks_path, candidate_top_k=1)
        self.assertEqual(r["clusters_total"], 1)
        self.assertEqual(len(r["context"]), 2)


# 13. Cluster ordering (by seed score descending)
class TestClusterOrdering(PgTestCase):
    def test_clusters_ordered_by_seed_score_descending(self):
        chunks_path = self.seed_environment("ch-13", [
            {"chunk_id": "low", "order": 1, "angle": 80, "item_types": ["theorem"]},
            {"chunk_id": "high", "order": 2, "angle": 10, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-13", chunks_path)
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(chunk_ids, ["high", "low"])


# 14. Within-cluster order (by `order` ascending)
class TestWithinClusterOrder(PgTestCase):
    def test_within_cluster_ordered_by_chunk_order_field(self):
        # seed's own order (10) is LARGER than its expansion's order (1) --
        # final order within the cluster must still be [expansion, seed].
        chunks_path = self.seed_environment("ch-14", [
            {"chunk_id": "exo", "order": 10, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-14", chunks_path, candidate_top_k=1)
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(chunk_ids, ["thm", "exo"])


# 15. Chunk-count budget
class TestChunkCountBudget(PgTestCase):
    def test_chunk_count_budget_stops_at_first_overflow(self):
        specs = [{"chunk_id": f"c{i}", "order": i, "angle": i * 2, "section_id": f"sec-{i}",
                  "item_types": ["theorem"]} for i in range(5)]
        chunks_path = self.seed_environment("ch-15", specs)
        r = self.run_assemble("ch-15", chunks_path, candidate_top_k=10, max_context_chunks=3,
                               max_context_chars=100000, max_chunks_per_section=10)
        self.assertEqual(r["context_chunk_count"], 3)
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(chunk_ids, ["c0", "c1", "c2"])


# 16. Character budget
class TestCharacterBudget(PgTestCase):
    def test_character_budget_stops_at_first_overflow(self):
        specs = [
            {"chunk_id": "c0", "order": 0, "angle": 0, "section_id": "sec-0",
             "item_types": ["theorem"], "text": "x" * 40},
            {"chunk_id": "c1", "order": 1, "angle": 2, "section_id": "sec-1",
             "item_types": ["theorem"], "text": "y" * 40},
            {"chunk_id": "c2", "order": 2, "angle": 4, "section_id": "sec-2",
             "item_types": ["theorem"], "text": "z" * 40},
        ]
        chunks_path = self.seed_environment("ch-16", specs)
        r = self.run_assemble("ch-16", chunks_path, candidate_top_k=10, max_context_chunks=10,
                               max_context_chars=80, max_chunks_per_section=10)
        self.assertEqual(r["context_chunk_count"], 2)
        self.assertLessEqual(r["context_char_count"], 80)


# 17. Whole-cluster behavior (never split a cluster across the boundary)
class TestWholeClusterBudget(PgTestCase):
    def test_never_splits_a_cluster_across_budget_boundary(self):
        chunks_path = self.seed_environment("ch-17", [
            {"chunk_id": "exo", "order": 2, "angle": 0, "section_id": "sec-a",
             "item_types": ["exercise"], "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "section_id": "sec-a", "item_types": ["theorem"]},
        ])
        # candidate_top_k=1: only 'exo' comes back as a candidate/seed, so
        # 'thm' arrives purely via E2 expansion, forming ONE real 2-member
        # cluster (not two independent 1-chunk clusters). max_context_chunks=1
        # forces that cluster to be a 'would exceed' case for anything
        # after the first -- but since it IS the first/top cluster, it
        # must survive whole (both members), never split down to just 1.
        r = self.run_assemble("ch-17", chunks_path, candidate_top_k=1, max_context_chunks=1,
                               max_chunks_per_section=10)
        self.assertEqual(r["context_chunk_count"], 2)
        self.assertIsNotNone(r["budget_overflow_note"])


# 18. No back-fill after budget overflow
class TestNoBackfill(PgTestCase):
    def test_no_backfill_of_smaller_later_cluster(self):
        chunks_path = self.seed_environment("ch-18", [
            {"chunk_id": "big1", "order": 1, "angle": 0, "section_id": "sec-a",
             "item_types": ["exercise"], "related_chunk_ids": ["big1-thm"]},
            {"chunk_id": "big1-thm", "order": 0, "angle": 89, "section_id": "sec-a", "item_types": ["theorem"]},
            {"chunk_id": "small", "order": 3, "angle": 5, "section_id": "sec-b", "item_types": ["theorem"]},
        ])
        # budget=2 chunks: cluster 1 (big1+big1-thm, seed score highest at
        # angle 0) uses all 2 slots; cluster 2 ('small', 1 chunk) would
        # technically fit in the remaining 0... it doesn't (0 slots left)
        # -- but even if it did have room, back-filling is not attempted;
        # this test asserts 'small' is excluded because cluster 1 already
        # fills the whole budget, and the walk simply moves forward
        # in order (never reordering to slot 'small' in ahead of a
        # bigger, lower-scoring cluster).
        # candidate_top_k=2: only 'big1' and 'small' come back as
        # candidates/seeds -- 'big1-thm' must arrive purely via E2
        # expansion (never independently, which would defeat the point).
        r = self.run_assemble("ch-18", chunks_path, candidate_top_k=2, max_context_chunks=2,
                               max_chunks_per_section=10)
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertEqual(set(chunk_ids), {"big1", "big1-thm"})
        self.assertNotIn("small", chunk_ids)


# 19. Highest-scoring cluster survives character overflow
class TestTopClusterSurvivesOverflow(PgTestCase):
    def test_top_cluster_survives_even_when_alone_exceeding_char_budget(self):
        chunks_path = self.seed_environment("ch-19", [
            {"chunk_id": "only", "order": 1, "angle": 0, "item_types": ["theorem"],
             "text": "x" * 500},
        ])
        r = self.run_assemble("ch-19", chunks_path, max_context_chars=10, max_context_chunks=10)
        self.assertEqual(r["context_chunk_count"], 1)
        self.assertEqual(r["context"][0]["chunk_id"], "only")
        self.assertIsNotNone(r["budget_overflow_note"])


# 20. figure_refs without confirmed figure_id
class TestFigureRefsUnconfirmed(PgTestCase):
    def test_figure_refs_without_confirmation_never_resolves_figure_id(self):
        chunks_path = self.seed_environment("ch-20", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["activity"],
             "figure_refs": [{"source": "links.figures", "reconstructed_figure_id": "fig-x",
                               "figure_id": None, "confidence": None}]},
        ])
        r = self.run_assemble("ch-20", chunks_path)
        c = r["context"][0]
        self.assertTrue(c["has_potential_figure"])
        self.assertEqual(c["reconstructed_figure_id"], "fig-x")
        self.assertIsNone(c["figure_id"])


# 21. Confirmed + high-confidence figure fixture
class TestConfirmedFigureResolution(PgTestCase):
    def test_confirmed_high_confidence_illustrates_resolves_figure_id(self):
        chunks_path = self.seed_environment("ch-21", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["activity"],
             "source_item_ids": ["item-c1"],
             "figure_refs": [{"source": "links.figures", "reconstructed_figure_id": "fig-x",
                               "figure_id": None, "confidence": None}]},
        ])
        relations_path = _write_relations_file(self.tmp_path, "ch-21", [{
            "relation_id": "rel-1", "type": "illustrates", "source_id": "figure_001",
            "source_kind": "figure", "target_id": "item-c1", "target_kind": "knowledge_item",
            "confidence": "high", "generation_method": "human_confirmed",
            "review_status": "HUMAN_APPROVED", "signals": {},
        }])
        r = self.run_assemble("ch-21", chunks_path, relations_path=relations_path)
        c = r["context"][0]
        self.assertEqual(c["figure_id"], "figure_001")

    def test_rule_based_high_confidence_illustrates_does_not_resolve(self):
        # An algorithmic AUTO_MATCH-sourced 'high' confidence illustrates
        # relation (generation_method 'rule_based') must NOT unlock
        # resolution -- only a genuine human_confirmed decision may.
        chunks_path = self.seed_environment("ch-21b", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["activity"],
             "source_item_ids": ["item-c1"],
             "figure_refs": [{"source": "links.figures", "reconstructed_figure_id": "fig-x",
                               "figure_id": None, "confidence": None}]},
        ])
        relations_path = _write_relations_file(self.tmp_path, "ch-21b", [{
            "relation_id": "rel-1", "type": "illustrates", "source_id": "figure_001",
            "source_kind": "figure", "target_id": "item-c1", "target_kind": "knowledge_item",
            "confidence": "high", "generation_method": "rule_based",
            "review_status": "REVIEW_REQUIRED", "signals": {},
        }])
        r = self.run_assemble("ch-21b", chunks_path, relations_path=relations_path)
        self.assertIsNone(r["context"][0]["figure_id"])


# 22. Uncertainty flag preservation
class TestUncertaintyFlagPreservation(PgTestCase):
    def test_has_uncertain_content_included_and_flagged(self):
        chunks_path = self.seed_environment("ch-22", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["theorem"],
             "has_uncertain_content": True, "review_status": "REVIEW_REQUIRED"},
        ])
        r = self.run_assemble("ch-22", chunks_path)
        c = r["context"][0]
        self.assertTrue(c["has_uncertain_content"])
        self.assertEqual(c["review_status"], "REVIEW_REQUIRED")


# 23. HUMAN_REJECTED exclusion
class TestHumanRejectedExclusion(PgTestCase):
    def test_human_rejected_chunk_excluded(self):
        chunks_path = self.seed_environment("ch-23", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["theorem"],
             "review_status": "HUMAN_REJECTED"},
            {"chunk_id": "c2", "order": 2, "angle": 5, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-23", chunks_path, candidate_top_k=10)
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertNotIn("c1", chunk_ids)
        self.assertIn("c2", chunk_ids)
        reasons = {x["chunk_id"]: x["rejection_reason"] for x in r["rejected_seeds"]}
        self.assertEqual(reasons.get("c1"), "human_rejected")

    def test_human_rejected_expansion_target_excluded(self):
        chunks_path = self.seed_environment("ch-23b", [
            {"chunk_id": "exo", "order": 2, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"],
             "review_status": "HUMAN_REJECTED"},
        ])
        r = self.run_assemble("ch-23b", chunks_path)
        self.assertEqual(r["expansions"], [])
        chunk_ids = [c["chunk_id"] for c in r["context"]]
        self.assertNotIn("thm", chunk_ids)


# 24. Empty search results
class TestEmptySearchResults(PgTestCase):
    def test_empty_search_results_produce_valid_empty_context(self):
        chunks_path = _write_chunks_file(self.tmp_path, "ch-24-empty", [])
        r = self.run_assemble("ch-24-empty", chunks_path)
        self.assertEqual(r["candidate_count"], 0)
        self.assertEqual(r["context"], [])
        self.assertTrue(r["diagnostics"])

    def test_incompatible_model_revision_propagates(self):
        chunks_path = self.seed_environment("ch-24b", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["theorem"]},
        ])
        with self.assertRaises(SearchIncompatibleModelError):
            assemble_context(
                query="q", chapter_id="ch-24b", embedding_model="test/model", model_revision="rev-unknown",
                database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                backend=FixedVectorBackend(_vector_at_angle(0), model_revision="rev-unknown"),
            )


# 25. Deterministic repeated execution
class TestDeterministicRepeatedExecution(PgTestCase):
    def test_same_query_run_twice_is_identical(self):
        chunks_path = self.seed_environment("ch-25", [
            {"chunk_id": "exo", "order": 5, "angle": 0, "item_types": ["exercise"],
             "related_chunk_ids": ["thm"]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"]},
            {"chunk_id": "other", "order": 2, "angle": 30, "item_types": ["theorem"]},
        ])
        r1 = self.run_assemble("ch-25", chunks_path, candidate_top_k=10)
        r2 = self.run_assemble("ch-25", chunks_path, candidate_top_k=10)
        self.assertEqual(r1, r2)


# 26. Provenance correctness
class TestProvenanceCorrectness(PgTestCase):
    def test_provenance_fields_complete_and_correct(self):
        chunks_path = self.seed_environment("ch-26", [
            {"chunk_id": "exo", "order": 5, "angle": 0, "item_types": ["exercise"],
             "section_id": "sec-a", "subsection_id": "sub-a", "related_chunk_ids": ["thm"],
             "topics": ["T"], "concepts": ["C"], "pdf_pages": [3]},
            {"chunk_id": "thm", "order": 1, "angle": 90, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-26", chunks_path, candidate_top_k=1)
        by_id = {c["chunk_id"]: c for c in r["context"]}
        seed = by_id["exo"]
        self.assertIsInstance(seed["score"], float)
        self.assertEqual(seed["inclusion_reason"], "semantic_match")
        self.assertIsNone(seed["expanded_from_chunk_id"])
        self.assertEqual(seed["section_id"], "sec-a")
        self.assertEqual(seed["subsection_id"], "sub-a")
        self.assertEqual(seed["topics"], ["T"])
        self.assertEqual(seed["concepts"], ["C"])
        self.assertEqual(seed["pdf_pages"], [3])
        self.assertEqual(seed["embedding_model"], "test/model")
        self.assertEqual(seed["model_revision"], "rev1")

        expansion = by_id["thm"]
        self.assertIsNone(expansion["score"])
        self.assertEqual(expansion["inclusion_reason"], "expansion:applies_concept")
        self.assertEqual(expansion["expanded_from_chunk_id"], "exo")


# 27. source_chunks_hash
class TestSourceChunksHash(PgTestCase):
    def test_source_chunks_hash_present_and_matches_file_hash(self):
        chunks_path = self.seed_environment("ch-27", [
            {"chunk_id": "c1", "order": 1, "angle": 0, "item_types": ["theorem"]},
        ])
        r = self.run_assemble("ch-27", chunks_path)
        self.assertEqual(r["source_chunks_hash"], file_hash(chunks_path))
        self.assertTrue(r["source_chunks_hash"].startswith("sha256:"))


# 28. Real Chapter 1 regression
class TestChapter1RealRagRegression(PgTestCase):
    def test_real_chapter_1_variations_query_matches_design_behavior(self):
        embedding_dir = config.embeddings_dir(config.CHAPTER_01_ID)
        chunks_path = config.chunks_json(config.CHAPTER_01_ID)
        if not (embedding_dir / "manifest.json").exists():
            self.skipTest("Real Chapter 1 embedding artifacts not present in this environment")
        try:
            from embed_knowledge import SentenceTransformerBackend
            backend = SentenceTransformerBackend()
        except Exception as e:
            self.skipTest(f"Real BAAI/bge-m3 model not available in this environment: {e}")

        from import_embeddings import import_embeddings
        import_report = import_embeddings(
            embedding_dir, config.CHAPTER_01_ID, TEST_DATABASE_URL, chunks_path=chunks_path,
            normalized_path=config.normalized_json(config.CHAPTER_01_ID),
        )
        self.assertEqual(import_report["errors"], [])

        r = assemble_context(
            query="Comment étudier les variations d'une fonction ?",
            chapter_id=config.CHAPTER_01_ID,
            embedding_model=config.EMBEDDING_MODEL_NAME, model_revision=config.EMBEDDING_MODEL_REVISION,
            database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
            relations_path=config.relations_json(config.CHAPTER_01_ID),
            backend=backend,
        )

        self.assertGreater(r["candidate_count"], 0)
        self.assertGreater(r["seed_count"], 0)
        self.assertGreater(len(r["context"]), 0)
        self.assertLessEqual(r["context_chunk_count"], config.RAG_MAX_CONTEXT_CHUNKS)
        self.assertLessEqual(r["context_char_count"], config.RAG_MAX_CONTEXT_CHARS + 5000)  # top-cluster exception slack

        # thm-019 and prop-001 are expected to enter the context as
        # expansions, per the approved design's own worked Example B --
        # they should never appear in the raw top candidates for this
        # exact exercise-phrased query, only via concept-support expansion.
        expansion_ids = {e["chunk_id"] for e in r["expansions"]}
        context_ids = {c["chunk_id"] for c in r["context"]}
        self.assertTrue(expansion_ids, "expected at least one concept-support expansion")
        # Not every computed expansion is guaranteed to survive the final
        # budget (a later cluster can legitimately be cut, per the
        # design's own no-back-fill rule) -- only assert that at least
        # one genuinely landed in the final context, not that all did.
        self.assertTrue(expansion_ids & context_ids, "expected at least one expansion to survive the budget")

        for c in r["context"]:
            self.assertEqual(c["chapter_id"], config.CHAPTER_01_ID)
            self.assertIn(c["inclusion_reason"], {"semantic_match", "expansion:correction_pair", "expansion:applies_concept"})
            if c["inclusion_reason"] == "semantic_match":
                self.assertIsInstance(c["score"], float)
            else:
                self.assertIsNone(c["score"])

        scores = [c["score"] for c in r["context"] if c["score"] is not None]
        # Seed scores must appear in the same relative order Semantic
        # Search itself produced (clusters ordered by seed score desc).
        self.assertEqual(scores, sorted(scores, reverse=True))

        self.assertEqual(r["source_chunks_hash"], file_hash(chunks_path))


if __name__ == "__main__":
    unittest.main()
