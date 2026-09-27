"""
Phase 13 - tests for search_embeddings.py.

Uses the same dedicated local PostgreSQL test database as
test_import_embeddings.py (ai_education_test) -- no Docker required, never
touches the real ai_education database. embeddings_1024 is TRUNCATEd
between tests for isolation.

Ranking-specific tests insert HAND-CRAFTED vectors with an analytically
known cosine similarity directly into embeddings_1024 (bypassing the
embedding pipeline entirely) via a small angle-based construction
(_vector_at_angle) -- so expected order/scores are known constants, not
just "semantically plausible" (per semantic_search_design.md §14).

Chapter 1's own ids appear ONLY in TestChapter1RealSearchIntegration.
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
from import_embeddings import import_embeddings
from search_embeddings import (
    search, validate_request, SearchValidationError, SearchIncompatibleModelError,
)


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
    """A unit vector [cos(theta), sin(theta), 0, ..., 0]. Its cosine
    similarity against _vector_at_angle(0) (i.e. [1, 0, ..., 0]) is
    EXACTLY cos(theta_degrees) -- an analytically known constant, not an
    approximation, letting ranking tests assert exact expected scores."""
    theta = math.radians(theta_degrees)
    v = np.zeros(dimension, dtype=np.float32)
    v[0] = math.cos(theta)
    v[1] = math.sin(theta)
    return v


class FixedVectorBackend:
    """Test double that always returns the SAME pre-chosen vector,
    regardless of the input text -- gives full, precise control over the
    'query embedding' step so ranking/dimension/compatibility tests can
    assert exact, known outcomes (see EmbeddingBackend protocol in
    embed_knowledge.py, which this satisfies structurally)."""

    def __init__(self, vector: np.ndarray, model_name="test/model", model_revision="rev1"):
        self.dimension = vector.shape[0]
        self._vector = np.asarray(vector, dtype=np.float32)
        self.model_name = model_name
        self.model_revision = model_revision
        self.calls: list[str] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls.extend(texts)
        return np.tile(self._vector, (len(texts), 1)).astype(np.float32)


def _write_chunks(tmp_path: Path, chapter_id: str, chunk_texts: dict[str, str]) -> Path:
    doc = {
        "schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
        "generated_at": "2026-01-01T00:00:00Z", "chapter_id": chapter_id,
        "chunks": [{"chunk_id": cid, "text": text} for cid, text in chunk_texts.items()],
    }
    path = tmp_path / f"{chapter_id}-chunks.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


DEFAULT_FILTER_METADATA = {
    "section_id": None, "subsection_id": None, "topics": [], "concepts": [],
    "item_types": [], "content_role": "statement", "pdf_pages": [], "has_uncertain_content": False,
}


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
                    revision="rev1", status="active", filter_metadata: dict | None = None,
                    embedding_id: str | None = None) -> str:
        filter_metadata = filter_metadata if filter_metadata is not None else dict(DEFAULT_FILTER_METADATA)
        embedding_id = embedding_id or f"emb-{chapter_id}-{chunk_id}-{model}-{revision}"
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
        return embedding_id


# --------------------------------------------------------------------------
# 1. Query validation
# --------------------------------------------------------------------------

class TestQueryValidation(unittest.TestCase):
    def test_non_string_query_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query=123, chapter_id="ch-1", top_k=5, filters=None)

    def test_missing_chapter_id_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="hello", chapter_id="", top_k=5, filters=None)

    def test_top_k_out_of_range_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="hello", chapter_id="ch-1", top_k=0, filters=None)
        with self.assertRaises(SearchValidationError):
            validate_request(query="hello", chapter_id="ch-1", top_k=config.SEARCH_MAX_TOP_K + 1, filters=None)

    def test_top_k_non_int_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="hello", chapter_id="ch-1", top_k=5.5, filters=None)
        with self.assertRaises(SearchValidationError):
            validate_request(query="hello", chapter_id="ch-1", top_k=True, filters=None)

    def test_valid_request_does_not_raise(self):
        validate_request(query="hello", chapter_id="ch-1", top_k=5, filters=None)


# --------------------------------------------------------------------------
# 2. Empty query
# --------------------------------------------------------------------------

class TestEmptyQuery(unittest.TestCase):
    def test_empty_string_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="", chapter_id="ch-1", top_k=5, filters=None)

    def test_whitespace_only_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="   \n\t  ", chapter_id="ch-1", top_k=5, filters=None)


# --------------------------------------------------------------------------
# 3. Valid query
# --------------------------------------------------------------------------

class TestValidQuery(PgTestCase):
    def test_valid_query_returns_ranked_results(self):
        self.insert_row("ch-valid", "c1", _vector_at_angle(0))
        self.insert_row("ch-valid", "c2", _vector_at_angle(90))
        chunks_path = _write_chunks(self.tmp_path, "ch-valid", {"c1": "Text one.", "c2": "Text two."})

        results = search(
            query="anything", chapter_id="ch-valid", top_k=5,
            embedding_model="test/model", model_revision="rev1",
            database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
            backend=FixedVectorBackend(_vector_at_angle(0)),
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["chunk_id"], "c1")
        self.assertAlmostEqual(results[0]["score"], 1.0, places=4)


# --------------------------------------------------------------------------
# 4. Query embedding dimension
# --------------------------------------------------------------------------

class TestQueryEmbeddingDimension(PgTestCase):
    def test_dimension_mismatch_against_existing_table_is_rejected(self):
        self.insert_row("ch-dim", "c1", _vector_at_angle(0))
        chunks_path = _write_chunks(self.tmp_path, "ch-dim", {"c1": "Text."})
        wrong_dim_backend = FixedVectorBackend(np.zeros(999, dtype=np.float32))

        with self.assertRaises(SearchIncompatibleModelError):
            search(query="q", chapter_id="ch-dim", embedding_model="test/model", model_revision="rev1",
                   database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                   backend=wrong_dim_backend, table="embeddings_1024")

    def test_nonexistent_table_is_rejected(self):
        chunks_path = _write_chunks(self.tmp_path, "ch-dim2", {})
        with self.assertRaises(SearchIncompatibleModelError):
            search(query="q", chapter_id="ch-dim2", embedding_model="test/model", model_revision="rev1",
                   database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                   backend=FixedVectorBackend(np.zeros(8, dtype=np.float32)))


# --------------------------------------------------------------------------
# 5. Model compatibility
# --------------------------------------------------------------------------

class TestModelCompatibility(PgTestCase):
    def test_unindexed_revision_raises_when_chapter_has_other_data(self):
        self.insert_row("ch-model", "c1", _vector_at_angle(0), model="test/model", revision="rev1")
        chunks_path = _write_chunks(self.tmp_path, "ch-model", {"c1": "Text."})

        with self.assertRaises(SearchIncompatibleModelError):
            search(query="q", chapter_id="ch-model", embedding_model="test/model", model_revision="rev-unknown",
                   database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                   backend=FixedVectorBackend(_vector_at_angle(0), model_revision="rev-unknown"))

    def test_chapter_with_no_data_at_all_returns_empty_not_raise(self):
        chunks_path = _write_chunks(self.tmp_path, "ch-empty-chapter", {})
        results = search(query="q", chapter_id="ch-empty-chapter", embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(results, [])


# --------------------------------------------------------------------------
# 6. Chapter isolation
# --------------------------------------------------------------------------

class TestChapterIsolation(PgTestCase):
    def test_search_chapter_a_never_returns_chapter_b_rows(self):
        self.insert_row("ch-iso-a", "a1", _vector_at_angle(0))
        self.insert_row("ch-iso-b", "b1", _vector_at_angle(0))
        chunks_a = _write_chunks(self.tmp_path, "ch-iso-a", {"a1": "A text."})

        results = search(query="q", chapter_id="ch-iso-a", embedding_model="test/model", model_revision="rev1",
                          database_url=TEST_DATABASE_URL, chunks_path=chunks_a,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual([r["chunk_id"] for r in results], ["a1"])


# --------------------------------------------------------------------------
# 7. top_k
# --------------------------------------------------------------------------

class TestTopK(PgTestCase):
    def _seed_five_rows(self, chapter_id="ch-topk"):
        for i in range(5):
            self.insert_row(chapter_id, f"c{i}", _vector_at_angle(i * 10))
        return _write_chunks(self.tmp_path, chapter_id, {f"c{i}": f"Text {i}" for i in range(5)})

    def test_top_k_1(self):
        chunks_path = self._seed_five_rows()
        results = search(query="q", chapter_id="ch-topk", top_k=1, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(len(results), 1)

    def test_top_k_5(self):
        chunks_path = self._seed_five_rows()
        results = search(query="q", chapter_id="ch-topk", top_k=5, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(len(results), 5)

    def test_top_k_10_returns_only_5_available(self):
        chunks_path = self._seed_five_rows()
        results = search(query="q", chapter_id="ch-topk", top_k=10, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(len(results), 5)


# --------------------------------------------------------------------------
# 8. Metadata filters
# --------------------------------------------------------------------------

class TestMetadataFilters(PgTestCase):
    def _seed(self):
        self.insert_row("ch-filt", "c1", _vector_at_angle(0), filter_metadata={
            **DEFAULT_FILTER_METADATA, "section_id": "sec-a", "content_role": "statement",
            "concepts": ["continuite"], "pdf_pages": [6], "has_uncertain_content": False,
        })
        self.insert_row("ch-filt", "c2", _vector_at_angle(5), filter_metadata={
            **DEFAULT_FILTER_METADATA, "section_id": "sec-b", "content_role": "correction",
            "concepts": ["limites"], "pdf_pages": [9], "has_uncertain_content": True,
        })
        return _write_chunks(self.tmp_path, "ch-filt", {"c1": "One.", "c2": "Two."})

    def _search(self, chunks_path, filters):
        return search(query="q", chapter_id="ch-filt", top_k=10, embedding_model="test/model",
                      model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                      backend=FixedVectorBackend(_vector_at_angle(0)), filters=filters)

    def test_section_id_filter(self):
        chunks_path = self._seed()
        results = self._search(chunks_path, {"section_id": "sec-b"})
        self.assertEqual([r["chunk_id"] for r in results], ["c2"])

    def test_content_role_filter(self):
        chunks_path = self._seed()
        results = self._search(chunks_path, {"content_role": "correction"})
        self.assertEqual([r["chunk_id"] for r in results], ["c2"])

    def test_concepts_any_of_filter(self):
        chunks_path = self._seed()
        results = self._search(chunks_path, {"concepts": ["continuite", "something-else"]})
        self.assertEqual([r["chunk_id"] for r in results], ["c1"])

    def test_pdf_pages_any_of_filter(self):
        chunks_path = self._seed()
        results = self._search(chunks_path, {"pdf_pages": [9, 100]})
        self.assertEqual([r["chunk_id"] for r in results], ["c2"])

    def test_has_uncertain_content_filter(self):
        chunks_path = self._seed()
        results = self._search(chunks_path, {"has_uncertain_content": True})
        self.assertEqual([r["chunk_id"] for r in results], ["c2"])


# --------------------------------------------------------------------------
# 9. Cosine ranking
# --------------------------------------------------------------------------

class TestCosineRanking(PgTestCase):
    def test_known_similarity_vectors_rank_in_expected_order(self):
        self.insert_row("ch-rank", "match", _vector_at_angle(0))       # similarity 1.0
        self.insert_row("ch-rank", "half", _vector_at_angle(60))        # similarity 0.5
        self.insert_row("ch-rank", "orthogonal", _vector_at_angle(90))  # similarity 0.0
        chunks_path = _write_chunks(self.tmp_path, "ch-rank",
                                     {"match": "m", "half": "h", "orthogonal": "o"})

        results = search(query="q", chapter_id="ch-rank", top_k=10, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))

        self.assertEqual([r["chunk_id"] for r in results], ["match", "half", "orthogonal"])
        self.assertAlmostEqual(results[0]["score"], 1.0, places=4)
        self.assertAlmostEqual(results[1]["score"], 0.5, places=4)
        self.assertAlmostEqual(results[2]["score"], 0.0, places=4)


# --------------------------------------------------------------------------
# 10. Result ordering
# --------------------------------------------------------------------------

class TestResultOrdering(PgTestCase):
    def test_descending_score_order(self):
        self.insert_row("ch-order", "low", _vector_at_angle(80))
        self.insert_row("ch-order", "high", _vector_at_angle(10))
        chunks_path = _write_chunks(self.tmp_path, "ch-order", {"low": "l", "high": "h"})
        results = search(query="q", chapter_id="ch-order", top_k=10, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(results[0]["chunk_id"], "high")

    def test_tie_broken_deterministically_by_embedding_id(self):
        id_a = self.insert_row("ch-tie", "c-a", _vector_at_angle(0), embedding_id="emb-tie-a")
        id_b = self.insert_row("ch-tie", "c-b", _vector_at_angle(0), embedding_id="emb-tie-b")
        chunks_path = _write_chunks(self.tmp_path, "ch-tie", {"c-a": "a", "c-b": "b"})

        results1 = search(query="q", chapter_id="ch-tie", top_k=10, embedding_model="test/model",
                           model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                           backend=FixedVectorBackend(_vector_at_angle(0)))
        results2 = search(query="q", chapter_id="ch-tie", top_k=10, embedding_model="test/model",
                           model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                           backend=FixedVectorBackend(_vector_at_angle(0)))
        order1 = [r["chunk_id"] for r in results1]
        order2 = [r["chunk_id"] for r in results2]
        self.assertEqual(order1, order2)
        self.assertEqual(order1, ["c-a", "c-b"])  # emb-tie-a < emb-tie-b lexicographically


# --------------------------------------------------------------------------
# 11. Zero results
# --------------------------------------------------------------------------

class TestZeroResults(PgTestCase):
    def test_empty_chapter_returns_empty_list(self):
        chunks_path = _write_chunks(self.tmp_path, "ch-nodata", {})
        results = search(query="q", chapter_id="ch-nodata", embedding_model="test/model", model_revision="rev1",
                          database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(results, [])

    def test_filters_exclude_everything_returns_empty_list(self):
        self.insert_row("ch-overfilter", "c1", _vector_at_angle(0),
                         filter_metadata={**DEFAULT_FILTER_METADATA, "section_id": "sec-a"})
        chunks_path = _write_chunks(self.tmp_path, "ch-overfilter", {"c1": "x"})
        results = search(query="q", chapter_id="ch-overfilter", embedding_model="test/model", model_revision="rev1",
                          database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)),
                          filters={"section_id": "sec-does-not-exist"})
        self.assertEqual(results, [])


# --------------------------------------------------------------------------
# 12. Fewer results than top_k
# --------------------------------------------------------------------------

class TestFewerResultsThanTopK(PgTestCase):
    def test_top_k_larger_than_available_returns_all_available(self):
        self.insert_row("ch-few", "c1", _vector_at_angle(0))
        self.insert_row("ch-few", "c2", _vector_at_angle(20))
        self.insert_row("ch-few", "c3", _vector_at_angle(40))
        chunks_path = _write_chunks(self.tmp_path, "ch-few", {"c1": "1", "c2": "2", "c3": "3"})
        results = search(query="q", chapter_id="ch-few", top_k=10, embedding_model="test/model",
                          model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(len(results), 3)


# --------------------------------------------------------------------------
# 13. Multiple chapters
# --------------------------------------------------------------------------

class TestMultipleChapters(PgTestCase):
    def test_three_chapters_searched_independently(self):
        # chunk_id is prefixed per-chapter, mirroring the real system's own
        # 'chunk-<chapter_id>-...' convention -- embeddings_1024's
        # (chunk_id, embedding_model, model_revision) unique constraint is
        # NOT chapter-scoped, so a bare "c1" reused across chapters with the
        # same model/revision would otherwise collide (see the identical
        # fix in test_import_embeddings.py's build_artifact()).
        for chapter in ("ch-multi-x", "ch-multi-y", "ch-multi-z"):
            self.insert_row(chapter, f"{chapter}-c1", _vector_at_angle(0))
        chunks = {ch: _write_chunks(self.tmp_path, ch, {f"{ch}-c1": "text"})
                  for ch in ("ch-multi-x", "ch-multi-y", "ch-multi-z")}
        for chapter, chunks_path in chunks.items():
            results = search(query="q", chapter_id=chapter, embedding_model="test/model", model_revision="rev1",
                              database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                              backend=FixedVectorBackend(_vector_at_angle(0)))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["chapter_id"], chapter)


# --------------------------------------------------------------------------
# 14. Deterministic behavior
# --------------------------------------------------------------------------

class TestDeterministicBehavior(PgTestCase):
    def test_same_query_run_twice_is_identical(self):
        self.insert_row("ch-det", "c1", _vector_at_angle(0))
        self.insert_row("ch-det", "c2", _vector_at_angle(30))
        chunks_path = _write_chunks(self.tmp_path, "ch-det", {"c1": "1", "c2": "2"})
        r1 = search(query="q", chapter_id="ch-det", embedding_model="test/model", model_revision="rev1",
                    database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                    backend=FixedVectorBackend(_vector_at_angle(0)))
        r2 = search(query="q", chapter_id="ch-det", embedding_model="test/model", model_revision="rev1",
                    database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                    backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(r1, r2)


# --------------------------------------------------------------------------
# 15. Invalid filters
# --------------------------------------------------------------------------

class TestInvalidFilters(unittest.TestCase):
    def test_unknown_filter_key_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="q", chapter_id="ch-1", top_k=5, filters={"not_a_real_field": "x"})

    def test_wrong_type_filter_value_rejected(self):
        with self.assertRaises(SearchValidationError):
            validate_request(query="q", chapter_id="ch-1", top_k=5, filters={"concepts": "not-a-list"})
        with self.assertRaises(SearchValidationError):
            validate_request(query="q", chapter_id="ch-1", top_k=5, filters={"pdf_pages": ["not", "ints"]})
        with self.assertRaises(SearchValidationError):
            validate_request(query="q", chapter_id="ch-1", top_k=5, filters={"has_uncertain_content": "yes"})


# --------------------------------------------------------------------------
# 16. Missing chunk artifact
# --------------------------------------------------------------------------

class TestMissingChunkArtifact(PgTestCase):
    def test_orphan_chunk_id_excluded_with_warning_not_crash(self):
        self.insert_row("ch-orphan", "present", _vector_at_angle(0))
        self.insert_row("ch-orphan", "ghost", _vector_at_angle(5))
        # "ghost" deliberately absent from the chunks file.
        chunks_path = _write_chunks(self.tmp_path, "ch-orphan", {"present": "real chunk"})

        results = search(query="q", chapter_id="ch-orphan", embedding_model="test/model", model_revision="rev1",
                          database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual([r["chunk_id"] for r in results], ["present"])


# --------------------------------------------------------------------------
# 17. chunk_id -> authoritative text resolution
# --------------------------------------------------------------------------

class TestChunkTextResolution(PgTestCase):
    def test_returned_text_matches_source_chunk_file_exactly(self):
        exact_text = "Soit f une fonction definie sur un intervalle I -- texte exact."
        self.insert_row("ch-text", "c1", _vector_at_angle(0))
        chunks_path = _write_chunks(self.tmp_path, "ch-text", {"c1": exact_text})
        results = search(query="q", chapter_id="ch-text", embedding_model="test/model", model_revision="rev1",
                          database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                          backend=FixedVectorBackend(_vector_at_angle(0)))
        self.assertEqual(results[0]["text"], exact_text)


# --------------------------------------------------------------------------
# 18. Model/revision mismatch never mixes scores
# --------------------------------------------------------------------------

class TestModelRevisionMismatch(PgTestCase):
    def test_different_revision_never_mixes_with_another_revisions_rows(self):
        self.insert_row("ch-rev-mix", "c-rev1", _vector_at_angle(0), model="test/model", revision="rev1")
        self.insert_row("ch-rev-mix", "c-rev2", _vector_at_angle(0), model="test/model", revision="rev2")
        chunks_path = _write_chunks(self.tmp_path, "ch-rev-mix", {"c-rev1": "1", "c-rev2": "2"})

        results_rev1 = search(query="q", chapter_id="ch-rev-mix", embedding_model="test/model",
                               model_revision="rev1", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                               backend=FixedVectorBackend(_vector_at_angle(0)))
        results_rev2 = search(query="q", chapter_id="ch-rev-mix", embedding_model="test/model",
                               model_revision="rev2", database_url=TEST_DATABASE_URL, chunks_path=chunks_path,
                               backend=FixedVectorBackend(_vector_at_angle(0)))

        self.assertEqual([r["chunk_id"] for r in results_rev1], ["c-rev1"])
        self.assertEqual([r["chunk_id"] for r in results_rev2], ["c-rev2"])


# --------------------------------------------------------------------------
# Chapter 1 real integration (real model, real imported data -- skipped if
# unavailable, never failed)
# --------------------------------------------------------------------------

class TestChapter1RealSearchIntegration(PgTestCase):
    def test_real_query_against_real_chapter_1_embeddings(self):
        embedding_dir = config.embeddings_dir(config.CHAPTER_01_ID)
        chunks_path = config.chunks_json(config.CHAPTER_01_ID)
        if not (embedding_dir / "manifest.json").exists():
            self.skipTest("Real Chapter 1 embedding artifacts not present in this environment")
        try:
            from embed_knowledge import SentenceTransformerBackend
            backend = SentenceTransformerBackend()
        except Exception as e:
            self.skipTest(f"Real BAAI/bge-m3 model not available in this environment: {e}")

        import_report = import_embeddings(embedding_dir, config.CHAPTER_01_ID, TEST_DATABASE_URL,
                                           chunks_path=chunks_path,
                                           normalized_path=config.normalized_json(config.CHAPTER_01_ID))
        self.assertEqual(import_report["errors"], [])

        results = search(
            query="Comment etudier les variations d'une fonction ?",
            chapter_id=config.CHAPTER_01_ID, top_k=5,
            embedding_model=config.EMBEDDING_MODEL_NAME, model_revision=config.EMBEDDING_MODEL_REVISION,
            database_url=TEST_DATABASE_URL, chunks_path=chunks_path, backend=backend,
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 5)
        for r in results:
            self.assertEqual(r["chapter_id"], config.CHAPTER_01_ID)
            self.assertTrue(r["text"])
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
