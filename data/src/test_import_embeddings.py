"""
Phase 12 - tests for import_embeddings.py / init_vector_db_schema.py.

Uses a dedicated local PostgreSQL database (ai_education_test -- same
credentials as config.database_url(), only the database name differs) so
this suite needs no Docker and never touches the real ai_education
database. Schema is (re-)initialized once per run via
init_vector_db_schema.run(); embeddings_1024 is TRUNCATEd between tests for
isolation (never dropped -- schema init stays a separate concern from data,
matching vector_db_design.md §12).

Reuses test_embeddings.py's own fixture helpers (FakeBackend, make_chunk)
and embed_knowledge.run() to build real, self-consistent embedding
artifacts on disk for every scenario -- never hand-rolls a parallel
fixture-construction mechanism. Chapter 1's own ids appear ONLY in
TestChapter1RealImportRegression.

The whole suite is skipped (not failed) if ai_education_test is
unreachable, e.g. PostgreSQL isn't running in this environment.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

import config
import init_vector_db_schema
from init_vector_db_schema import pgvector_extension_status, PGVECTOR_MISSING_MESSAGE
from import_embeddings import apply_import, classify, fetch_existing, import_embeddings, load_artifacts
from embed_knowledge import run as embed_run, build_embedding_id, file_hash
from test_embeddings import FakeBackend, make_chunk


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


def _write_chunks_doc(path: Path, chunks: list[dict], chapter_id: str) -> Path:
    doc = {"schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
           "generated_at": "2026-01-01T00:00:00Z", "chapter_id": chapter_id, "chunks": chunks}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class FakeConnStub:
    """Minimal stand-in for a psycopg connection, used only to test
    pgvector_extension_status()'s own parsing/messaging without requiring
    an actual PostgreSQL server that lacks pgvector (this local environment
    always has it installed, per the earlier prerequisite check)."""

    def __init__(self, available: bool):
        self._available = available

    def execute(self, sql, params=None):
        class _Cursor:
            def __init__(self, row):
                self._row = row

            def fetchone(self):
                return self._row

        if "pg_available_extensions" in sql:
            return _Cursor(("0.8.6",) if self._available else None)
        return _Cursor(None)


@unittest.skipUnless(POSTGRES_AVAILABLE, "ai_education_test PostgreSQL database is not reachable")
class PgTestCase(unittest.TestCase):
    """Common setup shared by every DB-backed test: ensure the schema
    exists once, then TRUNCATE embeddings_1024 before each test."""

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

    def row_count(self, chapter_id: str | None = None) -> int:
        conn = psycopg.connect(TEST_DATABASE_URL)
        if chapter_id:
            n = conn.execute("SELECT count(*) FROM embeddings_1024 WHERE chapter_id = %s", (chapter_id,)).fetchone()[0]
        else:
            n = conn.execute("SELECT count(*) FROM embeddings_1024").fetchone()[0]
        conn.close()
        return n

    def fetch_rows(self, chapter_id: str) -> list[dict]:
        conn = psycopg.connect(TEST_DATABASE_URL)
        register_vector(conn)
        rows = conn.execute(
            "SELECT embedding_id, chunk_id, chapter_id, embedding_model, model_revision, "
            "content_hash, status, filter_metadata, embedding FROM embeddings_1024 WHERE chapter_id = %s",
            (chapter_id,),
        ).fetchall()
        conn.close()
        cols = ["embedding_id", "chunk_id", "chapter_id", "embedding_model", "model_revision",
                "content_hash", "status", "filter_metadata", "embedding"]
        results = []
        for r in rows:
            d = dict(zip(cols, r))
            v = d["embedding"]
            d["embedding"] = v.to_numpy() if hasattr(v, "to_numpy") else np.asarray(v)
            results.append(d)
        return results

    def build_artifact(self, chapter_id: str, chunk_ids: list[str], model="test/model", revision="rev1",
                        dimension=1024, chapter_title=None, texts=None) -> tuple[Path, Path]:
        """Builds a real, self-consistent embedding artifact (via the real
        embed_knowledge.run() + a FakeBackend) for `chapter_id`. Returns
        (embedding_dir, chunks_path). chunk_ids are prefixed with
        chapter_id -- mirroring the real system's own chunk_id convention
        ('chunk-<chapter_id>-<source_item_ids>', see
        knowledge_chunk.schema.json) -- so distinct chapters in the same
        test never collide against the table's (chunk_id, embedding_model,
        model_revision) unique constraint, which is NOT chapter-scoped."""
        texts = texts or {}
        chunks = [make_chunk(f"{chapter_id}-{cid}", order=i, text=texts.get(cid, f"Text for {cid}."))
                  for i, cid in enumerate(chunk_ids)]
        work_dir = self.tmp_path / f"work-{chapter_id}-{model.replace('/', '_')}-{revision}"
        work_dir.mkdir(parents=True, exist_ok=True)
        chunks_path = _write_chunks_doc(work_dir / "knowledge_chunks.json", chunks, chapter_id)
        embedding_dir = work_dir / "embeddings"
        embed_run(chunks_path, FakeBackend(dimension=dimension), model_name=model, model_revision=revision,
                  dimension=dimension, output_dir=embedding_dir, chapter_title=chapter_title,
                  progress=lambda m: None)
        return embedding_dir, chunks_path

    def corrupt_record(self, embedding_dir: Path, index: int, **overrides) -> None:
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        records[index].update(overrides)
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# 1. Database / schema initialization
# --------------------------------------------------------------------------

class TestSchemaInitialization(PgTestCase):
    def test_schema_creates_table_and_indexes(self):
        conn = psycopg.connect(TEST_DATABASE_URL)
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='embeddings_1024'").fetchall()}
        expected = {"embedding_id", "chunk_id", "chapter_id", "embedding_model", "model_revision",
                    "content_hash", "pipeline_version", "normalization_strategy", "status",
                    "filter_metadata", "created_at", "imported_at", "embedding"}
        self.assertEqual(expected, cols)
        indexes = {r[0] for r in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='embeddings_1024'").fetchall()}
        self.assertIn("embeddings_1024_embedding_cosine_idx", indexes)
        self.assertIn("embeddings_1024_chunk_model_revision_key", indexes)
        conn.close()

    def test_schema_init_is_idempotent(self):
        result1 = init_vector_db_schema.run(TEST_DATABASE_URL, config.VECTOR_DB_SCHEMA_SQL)
        result2 = init_vector_db_schema.run(TEST_DATABASE_URL, config.VECTOR_DB_SCHEMA_SQL)
        self.assertTrue(result1["pgvector_installed"])
        self.assertTrue(result2["pgvector_installed"])

    def test_dry_run_schema_init_creates_nothing_new(self):
        result = init_vector_db_schema.run(TEST_DATABASE_URL, config.VECTOR_DB_SCHEMA_SQL, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["statements_executed"], 8)


# --------------------------------------------------------------------------
# 2. pgvector extension requirement
# --------------------------------------------------------------------------

class TestPgvectorRequirement(unittest.TestCase):
    def test_available_extension_reported_true(self):
        status = pgvector_extension_status(FakeConnStub(available=True))
        self.assertTrue(status["available"])

    def test_missing_extension_reported_false_with_clear_message(self):
        status = pgvector_extension_status(FakeConnStub(available=False))
        self.assertFalse(status["available"])
        self.assertIn("pgvector", PGVECTOR_MISSING_MESSAGE)
        self.assertIn("PGROOT", PGVECTOR_MISSING_MESSAGE)

    @unittest.skipUnless(POSTGRES_AVAILABLE, "ai_education_test PostgreSQL database is not reachable")
    def test_real_server_reports_pgvector_available(self):
        conn = psycopg.connect(TEST_DATABASE_URL)
        status = pgvector_extension_status(conn)
        conn.close()
        self.assertTrue(status["available"])
        self.assertTrue(status["installed"])


# --------------------------------------------------------------------------
# 3. Valid import
# --------------------------------------------------------------------------

class TestValidImport(PgTestCase):
    def test_valid_import_inserts_all_active_rows(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-a", ["it-1", "it-2", "it-3"])
        report = import_embeddings(embedding_dir, "test-ch-a", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(report["inserted"], 3)
        self.assertEqual(report["errors"], [])
        self.assertEqual(self.row_count("test-ch-a"), 3)
        rows = self.fetch_rows("test-ch-a")
        self.assertTrue(all(r["status"] == "active" for r in rows))


# --------------------------------------------------------------------------
# 4. Invalid vector dimension
# --------------------------------------------------------------------------

class TestInvalidDimension(PgTestCase):
    def test_dimension_mismatch_against_table_is_rejected(self):
        # dimension=8 artifact, but embeddings_1024 requires 1024 -- must
        # be rejected by pre-import validation, never partially imported.
        embedding_dir, chunks_path = self.build_artifact("test-ch-dim", ["it-1"], dimension=8)
        report = import_embeddings(embedding_dir, "test-ch-dim", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["table_dimension"])
        self.assertEqual(self.row_count("test-ch-dim"), 0)


# --------------------------------------------------------------------------
# 5. Vector count mismatch
# --------------------------------------------------------------------------

class TestVectorCountMismatch(PgTestCase):
    def test_vector_count_mismatch_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-count", ["it-1", "it-2"])
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        extra = copy.deepcopy(records[0])
        extra["embedding_id"] = "emb-extra"
        extra["chunk_id"] = "chunk-extra"
        extra["row_index"] = 2  # out of bounds: vectors.npy still has only 2 rows
        records.append(extra)
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-count", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["count_and_shape"])
        self.assertEqual(self.row_count("test-ch-count"), 0)


# --------------------------------------------------------------------------
# 6. Invalid row_index
# --------------------------------------------------------------------------

class TestInvalidRowIndex(PgTestCase):
    def test_invalid_row_index_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-rowidx", ["it-1", "it-2"])
        self.corrupt_record(embedding_dir, 0, row_index=99)
        report = import_embeddings(embedding_dir, "test-ch-rowidx", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["row_index"])
        self.assertEqual(self.row_count("test-ch-rowidx"), 0)


# --------------------------------------------------------------------------
# 7. Duplicate embedding_id
# --------------------------------------------------------------------------

class TestDuplicateEmbeddingId(PgTestCase):
    def test_duplicate_embedding_id_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-dupemb", ["it-1", "it-2"])
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        records[1]["embedding_id"] = records[0]["embedding_id"]
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-dupemb", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["duplicate_ids"])
        self.assertEqual(self.row_count("test-ch-dupemb"), 0)


# --------------------------------------------------------------------------
# 8. Duplicate chunk_id
# --------------------------------------------------------------------------

class TestDuplicateChunkId(PgTestCase):
    def test_duplicate_chunk_id_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-dupchunk", ["it-1", "it-2"])
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        records[1]["chunk_id"] = records[0]["chunk_id"]
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-dupchunk", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["duplicate_ids"])
        self.assertEqual(self.row_count("test-ch-dupchunk"), 0)


# --------------------------------------------------------------------------
# 9. Missing model metadata
# --------------------------------------------------------------------------

class TestMissingModelMetadata(PgTestCase):
    def test_missing_model_metadata_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-nomodel", ["it-1"])
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        del records[0]["embedding_model"]
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-nomodel", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["record_schema"])
        self.assertEqual(self.row_count("test-ch-nomodel"), 0)


# --------------------------------------------------------------------------
# 10. Inconsistent model/revision
# --------------------------------------------------------------------------

class TestInconsistentModelRevision(PgTestCase):
    def test_inconsistent_revision_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-rev", ["it-1", "it-2"])
        self.corrupt_record(embedding_dir, 0, model_revision="some-other-revision")
        report = import_embeddings(embedding_dir, "test-ch-rev", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertTrue(report["validation"]["checks"]["manifest_consistency"])
        self.assertEqual(self.row_count("test-ch-rev"), 0)


# --------------------------------------------------------------------------
# 11. Missing content_hash
# --------------------------------------------------------------------------

class TestMissingContentHash(PgTestCase):
    def test_missing_content_hash_is_rejected(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-nohash", ["it-1"])
        records_path = embedding_dir / "records.json"
        records = json.loads(records_path.read_text(encoding="utf-8"))
        del records[0]["content_hash"]
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-nohash", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertFalse(report["validation"]["passed"])
        self.assertEqual(self.row_count("test-ch-nohash"), 0)


# --------------------------------------------------------------------------
# 12. Idempotent re-import
# --------------------------------------------------------------------------

class TestIdempotentReimport(PgTestCase):
    def test_second_identical_import_creates_no_duplicates(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-idem", ["it-1", "it-2", "it-3"])
        r1 = import_embeddings(embedding_dir, "test-ch-idem", TEST_DATABASE_URL, chunks_path=chunks_path)
        r2 = import_embeddings(embedding_dir, "test-ch-idem", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(r1["inserted"], 3)
        self.assertEqual(r2["inserted"], 0)
        self.assertEqual(r2["updated"], 0)
        self.assertEqual(r2["reused"], 3)
        self.assertEqual(self.row_count("test-ch-idem"), 3)


# --------------------------------------------------------------------------
# 13. Changed content_hash
# --------------------------------------------------------------------------

class TestChangedContentHash(PgTestCase):
    def test_changed_chunk_triggers_update_not_insert(self):
        embedding_dir, chunks_path = self.build_artifact(
            "test-ch-changed", ["it-1", "it-2"], texts={"it-1": "Original text."})
        r1 = import_embeddings(embedding_dir, "test-ch-changed", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(r1["inserted"], 2)
        changed_embedding_id = build_embedding_id("test-ch-changed", "test-ch-changed-it-1", "test/model", "rev1")
        before = {r["embedding_id"]: r["embedding"] for r in self.fetch_rows("test-ch-changed")}

        # Edit the source chunk text and regenerate the artifact in place
        # (embed_knowledge.py's own cache recomputes only the changed chunk).
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))["chunks"]
        chunks[0]["text"] = "Completely different text now."
        _write_chunks_doc(chunks_path, chunks, "test-ch-changed")
        embed_run(chunks_path, FakeBackend(dimension=1024), model_name="test/model", model_revision="rev1",
                  dimension=1024, output_dir=embedding_dir, chapter_title=None, progress=lambda m: None)

        r2 = import_embeddings(embedding_dir, "test-ch-changed", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(r2["inserted"], 0)
        self.assertEqual(r2["updated"], 1)
        self.assertEqual(r2["reused"], 1)
        self.assertEqual(self.row_count("test-ch-changed"), 2)

        after = {r["embedding_id"]: r["embedding"] for r in self.fetch_rows("test-ch-changed")}
        # embedding_id is content-derived from chunk_id+model+revision, not
        # content_hash -- it stays the same identity; only the vector differs.
        self.assertFalse(np.array_equal(before[changed_embedding_id], after[changed_embedding_id]))


# --------------------------------------------------------------------------
# 14. New chunk
# --------------------------------------------------------------------------

class TestNewChunk(PgTestCase):
    def test_new_chunk_is_inserted_without_touching_existing_rows(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-new", ["it-1", "it-2"])
        import_embeddings(embedding_dir, "test-ch-new", TEST_DATABASE_URL, chunks_path=chunks_path)

        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))["chunks"]
        chunks.append(make_chunk("test-ch-new-it-3", order=2, text="Brand new chunk."))
        _write_chunks_doc(chunks_path, chunks, "test-ch-new")
        embed_run(chunks_path, FakeBackend(dimension=1024), model_name="test/model", model_revision="rev1",
                  dimension=1024, output_dir=embedding_dir, chapter_title=None, progress=lambda m: None)

        report = import_embeddings(embedding_dir, "test-ch-new", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(report["reused"], 2)
        self.assertEqual(self.row_count("test-ch-new"), 3)


# --------------------------------------------------------------------------
# 15. Stale chunk
# --------------------------------------------------------------------------

class TestStaleChunk(PgTestCase):
    def test_chunk_absent_from_artifact_is_marked_stale_not_deleted(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-stale", ["it-1", "it-2", "it-3"])
        import_embeddings(embedding_dir, "test-ch-stale", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(self.row_count("test-ch-stale"), 3)

        # Simulate a later artifact snapshot where one chunk's record was
        # dropped entirely (not just marked stale within records.json) --
        # the DB-import-level staleness case, distinct from Phase 11's own
        # file-level stale bookkeeping.
        records = json.loads((embedding_dir / "records.json").read_text(encoding="utf-8"))
        vectors = np.load(embedding_dir / "vectors.npy")
        removed = records[1]
        kept_records = [r for r in records if r["embedding_id"] != removed["embedding_id"]]
        kept_vectors = np.delete(vectors, removed["row_index"], axis=0)
        for i, r in enumerate(sorted(kept_records, key=lambda r: r["row_index"])):
            r["row_index"] = i
        (embedding_dir / "records.json").write_text(json.dumps(kept_records, ensure_ascii=False, indent=2), encoding="utf-8")
        np.save(embedding_dir / "vectors.npy", kept_vectors)

        # ALSO remove the corresponding chunk from chunks_path so the
        # "current artifact" stays internally self-consistent (the removed
        # chunk is truly gone everywhere, not just from records.json) --
        # otherwise validate_embeddings' own chunk-coverage check correctly
        # rejects the mismatch (every active chunk must have a record).
        chunks_doc = json.loads(chunks_path.read_text(encoding="utf-8"))
        chunks_doc["chunks"] = [c for c in chunks_doc["chunks"] if c["chunk_id"] != removed["chunk_id"]]
        chunks_path.write_text(json.dumps(chunks_doc, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = json.loads((embedding_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["vector_count"] = len(kept_records)
        manifest["source_chunks_hash"] = file_hash(chunks_path)
        (embedding_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        report = import_embeddings(embedding_dir, "test-ch-stale", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(report["stale_marked"], 1)
        self.assertEqual(self.row_count("test-ch-stale"), 3)  # kept, never deleted
        rows = {r["chunk_id"]: r["status"] for r in self.fetch_rows("test-ch-stale")}
        self.assertEqual(rows[removed["chunk_id"]], "stale")


# --------------------------------------------------------------------------
# 16. Chapter isolation
# --------------------------------------------------------------------------

class TestChapterIsolation(PgTestCase):
    def test_two_chapters_do_not_interfere(self):
        dir_a, chunks_a = self.build_artifact("test-ch-iso-a", ["it-1", "it-2"])
        dir_b, chunks_b = self.build_artifact("test-ch-iso-b", ["it-1", "it-2", "it-3"])
        import_embeddings(dir_a, "test-ch-iso-a", TEST_DATABASE_URL, chunks_path=chunks_a)
        import_embeddings(dir_b, "test-ch-iso-b", TEST_DATABASE_URL, chunks_path=chunks_b)

        self.assertEqual(self.row_count("test-ch-iso-a"), 2)
        self.assertEqual(self.row_count("test-ch-iso-b"), 3)
        report_a_reimport = import_embeddings(dir_a, "test-ch-iso-a", TEST_DATABASE_URL, chunks_path=chunks_a)
        self.assertEqual(report_a_reimport["reused"], 2)
        self.assertEqual(self.row_count("test-ch-iso-b"), 3)  # untouched by chapter A's re-import


# --------------------------------------------------------------------------
# 17. Model/revision isolation
# --------------------------------------------------------------------------

class TestModelRevisionIsolation(PgTestCase):
    def test_different_revision_coexists_never_overwrites(self):
        dir_r1, chunks_r1 = self.build_artifact("test-ch-mr", ["it-1", "it-2"], model="test/model", revision="rev1")
        import_embeddings(dir_r1, "test-ch-mr", TEST_DATABASE_URL, chunks_path=chunks_r1)
        self.assertEqual(self.row_count("test-ch-mr"), 2)

        dir_r2, chunks_r2 = self.build_artifact("test-ch-mr", ["it-1", "it-2"], model="test/model", revision="rev2")
        import_embeddings(dir_r2, "test-ch-mr", TEST_DATABASE_URL, chunks_path=chunks_r2)

        self.assertEqual(self.row_count("test-ch-mr"), 4)  # 2 (rev1) + 2 (rev2), never merged/overwritten
        revisions = {r["model_revision"] for r in self.fetch_rows("test-ch-mr")}
        self.assertEqual(revisions, {"rev1", "rev2"})


# --------------------------------------------------------------------------
# 18. Metadata preservation
# --------------------------------------------------------------------------

class TestMetadataPreservation(PgTestCase):
    def test_filter_metadata_round_trips_exactly(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1", section_title="Section Riche",
                            subsection_title="Sous-section", item_types=["theorem", "activity"],
                            concepts=["concept a", "concept b"])
        work_dir = self.tmp_path / "meta"
        work_dir.mkdir()
        chunks_path = _write_chunks_doc(work_dir / "knowledge_chunks.json", [chunk], "test-ch-meta")
        embedding_dir = work_dir / "embeddings"
        embed_run(chunks_path, FakeBackend(dimension=1024), model_name="test/model", model_revision="rev1",
                  dimension=1024, output_dir=embedding_dir, chapter_title=None, progress=lambda m: None)

        import_embeddings(embedding_dir, "test-ch-meta", TEST_DATABASE_URL, chunks_path=chunks_path)

        source_records = json.loads((embedding_dir / "records.json").read_text(encoding="utf-8"))
        stored = self.fetch_rows("test-ch-meta")[0]
        self.assertEqual(stored["filter_metadata"], source_records[0]["filter_metadata"])


# --------------------------------------------------------------------------
# 19. Cosine-compatible vector storage
# --------------------------------------------------------------------------

class TestCosineCompatibleStorage(PgTestCase):
    def test_vectors_are_unit_norm_and_queryable_by_cosine(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-cos", ["it-1", "it-2", "it-3"])
        import_embeddings(embedding_dir, "test-ch-cos", TEST_DATABASE_URL, chunks_path=chunks_path)

        rows = self.fetch_rows("test-ch-cos")
        for r in rows:
            arr = np.asarray(r["embedding"])
            self.assertEqual(arr.shape, (1024,))
            self.assertAlmostEqual(float(np.linalg.norm(arr)), 1.0, places=4)

        conn = psycopg.connect(TEST_DATABASE_URL)
        register_vector(conn)
        probe = rows[0]["embedding"]
        ranked = conn.execute(
            "SELECT chunk_id FROM embeddings_1024 WHERE chapter_id = %s ORDER BY embedding <=> %s LIMIT 1",
            ("test-ch-cos", probe),
        ).fetchone()
        conn.close()
        self.assertEqual(ranked[0], rows[0]["chunk_id"])  # a vector is its own nearest neighbor


# --------------------------------------------------------------------------
# 20. Dry-run
# --------------------------------------------------------------------------

class TestDryRun(PgTestCase):
    def test_dry_run_computes_diff_without_writing(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-dry", ["it-1", "it-2"])
        report = import_embeddings(embedding_dir, "test-ch-dry", TEST_DATABASE_URL, chunks_path=chunks_path, dry_run=True)
        self.assertEqual(report["inserted"], 2)
        self.assertEqual(self.row_count("test-ch-dry"), 0)  # nothing actually written


# --------------------------------------------------------------------------
# 21. Corrupted/missing artifacts
# --------------------------------------------------------------------------

class TestCorruptedOrMissingArtifacts(PgTestCase):
    def test_missing_vectors_npy_raises_before_any_db_write(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-missing", ["it-1"])
        (embedding_dir / "vectors.npy").unlink()
        with self.assertRaises(FileNotFoundError):
            import_embeddings(embedding_dir, "test-ch-missing", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(self.row_count("test-ch-missing"), 0)

    def test_missing_manifest_raises_before_any_db_write(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-missing2", ["it-1"])
        (embedding_dir / "manifest.json").unlink()
        with self.assertRaises(FileNotFoundError):
            import_embeddings(embedding_dir, "test-ch-missing2", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(self.row_count("test-ch-missing2"), 0)


# --------------------------------------------------------------------------
# 22. Transaction rollback
# --------------------------------------------------------------------------

class TestTransactionRollback(PgTestCase):
    def test_mid_batch_failure_rolls_back_everything(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-rollback", ["it-1", "it-2", "it-3"])
        manifest, records, vectors = load_artifacts(embedding_dir)

        # Corrupt the SECOND record so it violates the DB's content_hash
        # CHECK constraint -- bypassing Python-level pre-validation on
        # purpose, to exercise the DB transaction boundary in isolation.
        records[1]["content_hash"] = "not-a-valid-hash"
        diff = {"insert": records, "update": [], "reuse": [], "stale_candidates": []}

        conn = psycopg.connect(TEST_DATABASE_URL)
        register_vector(conn)
        with self.assertRaises(Exception):
            with conn.transaction():
                apply_import(conn, "embeddings_1024", records, vectors, diff,
                             "test-ch-rollback", "test/model", "rev1")
        conn.close()

        self.assertEqual(self.row_count("test-ch-rollback"), 0)  # all-or-nothing: record 1 never persisted either


# --------------------------------------------------------------------------
# 23. Empty import
# --------------------------------------------------------------------------

class TestEmptyImport(PgTestCase):
    def test_empty_chunks_file_produces_zero_rows_no_error(self):
        work_dir = self.tmp_path / "empty"
        work_dir.mkdir()
        chunks_path = _write_chunks_doc(work_dir / "knowledge_chunks.json", [], "test-ch-empty")
        embedding_dir = work_dir / "embeddings"
        embed_run(chunks_path, FakeBackend(dimension=1024), model_name="test/model", model_revision="rev1",
                  dimension=1024, output_dir=embedding_dir, chapter_title=None, progress=lambda m: None)

        report = import_embeddings(embedding_dir, "test-ch-empty", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["inserted"], 0)
        self.assertEqual(self.row_count("test-ch-empty"), 0)

    def test_all_chunks_removed_marks_all_existing_rows_stale(self):
        embedding_dir, chunks_path = self.build_artifact("test-ch-empty2", ["it-1", "it-2"])
        import_embeddings(embedding_dir, "test-ch-empty2", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(self.row_count("test-ch-empty2"), 2)

        _write_chunks_doc(chunks_path, [], "test-ch-empty2")
        embed_run(chunks_path, FakeBackend(dimension=1024), model_name="test/model", model_revision="rev1",
                  dimension=1024, output_dir=embedding_dir, chapter_title=None, progress=lambda m: None)

        # embed_knowledge.py's OWN file-level bookkeeping keeps a record per
        # removed chunk (status flips to 'stale' WITHIN records.json,
        # per Phase 11's design) rather than dropping it from the file
        # entirely -- so this flows through the normal field-level UPDATE
        # path (status changed from 'active'->'stale'), not this module's
        # own orphan-detection path (stale_marked, exercised instead by
        # TestStaleChunk's hand-crafted "record vanished entirely" case).
        report = import_embeddings(embedding_dir, "test-ch-empty2", TEST_DATABASE_URL, chunks_path=chunks_path)
        self.assertEqual(report["updated"], 2)
        self.assertEqual(report["stale_marked"], 0)
        self.assertEqual(self.row_count("test-ch-empty2"), 2)  # kept, never deleted
        self.assertTrue(all(r["status"] == "stale" for r in self.fetch_rows("test-ch-empty2")))


# --------------------------------------------------------------------------
# 24. Multiple chapters using the same embeddings_1024 table
# --------------------------------------------------------------------------

class TestMultipleChaptersSameTable(PgTestCase):
    def test_multiple_chapters_coexist_in_one_physical_table(self):
        dir_a, chunks_a = self.build_artifact("test-ch-multi-a", ["it-1"])
        dir_b, chunks_b = self.build_artifact("test-ch-multi-b", ["it-1"])
        dir_c, chunks_c = self.build_artifact("test-ch-multi-c", ["it-1"])
        for d, c, cid in ((dir_a, chunks_a, "test-ch-multi-a"), (dir_b, chunks_b, "test-ch-multi-b"),
                           (dir_c, chunks_c, "test-ch-multi-c")):
            import_embeddings(d, cid, TEST_DATABASE_URL, chunks_path=c)

        conn = psycopg.connect(TEST_DATABASE_URL)
        distinct_chapters = {r[0] for r in conn.execute(
            "SELECT DISTINCT chapter_id FROM embeddings_1024 WHERE chapter_id LIKE 'test-ch-multi-%'").fetchall()}
        conn.close()
        self.assertEqual(distinct_chapters, {"test-ch-multi-a", "test-ch-multi-b", "test-ch-multi-c"})


# --------------------------------------------------------------------------
# Chapter 1 regression (real fixture, real artifact files -- imported into
# the TEST database, never the real ai_education database, to keep this
# automated suite side-effect-free against real/production data)
# --------------------------------------------------------------------------

class TestChapter1RealImportRegression(PgTestCase):
    def test_real_chapter_1_embeddings_import_cleanly(self):
        embedding_dir = config.embeddings_dir(config.CHAPTER_01_ID)
        chunks_path = config.chunks_json(config.CHAPTER_01_ID)
        if not (embedding_dir / "manifest.json").exists():
            self.skipTest("Real Chapter 1 embedding artifacts not present in this environment")

        report = import_embeddings(embedding_dir, config.CHAPTER_01_ID, TEST_DATABASE_URL,
                                    chunks_path=chunks_path, normalized_path=config.normalized_json(config.CHAPTER_01_ID))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["inserted"], 102)
        self.assertEqual(self.row_count(config.CHAPTER_01_ID), 102)

        rows = self.fetch_rows(config.CHAPTER_01_ID)
        self.assertEqual(len({r["embedding_id"] for r in rows}), 102)
        self.assertEqual(len({r["chunk_id"] for r in rows}), 102)
        self.assertTrue(all(r["embedding_model"] == "BAAI/bge-m3" for r in rows))
        self.assertTrue(all(r["model_revision"] == "5617a9f61b028005a4858fdac845db406aefb181" for r in rows))
        self.assertTrue(all(r["status"] == "active" for r in rows))
        self.assertTrue(all(np.asarray(r["embedding"]).shape == (1024,) for r in rows))

        report2 = import_embeddings(embedding_dir, config.CHAPTER_01_ID, TEST_DATABASE_URL,
                                     chunks_path=chunks_path, normalized_path=config.normalized_json(config.CHAPTER_01_ID))
        self.assertEqual(report2["inserted"], 0)
        self.assertEqual(report2["reused"], 102)
        self.assertEqual(self.row_count(config.CHAPTER_01_ID), 102)


if __name__ == "__main__":
    unittest.main()
