"""
Unit + regression tests for embed_knowledge.py and validate_embeddings.py
(Phase 11).

All unit tests use a small, deterministic FAKE embedding backend (see
FakeBackend below) -- never a real model -- so this suite runs without
downloading BAAI/bge-m3 or requiring a GPU. Exactly one integration test
(TestRealModelIntegration) exercises the real sentence-transformers
model, and is SKIPPED (not failed) if sentence-transformers/the model
weights are not available in the current environment (matching the
project's established "skip an optional real dependency, never fail the
suite for its absence" convention -- e.g. jsonschema throughout every
prior phase's validator).

Chapter 1's own ids appear ONLY in TestChapter1Regression, never in
embed_knowledge.py/validate_embeddings.py themselves (checked directly
below).

Run:
    python test_embeddings.py
    python -m unittest test_embeddings
"""

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

import config
from embed_knowledge import (
    build_embedding_id,
    build_embedding_input,
    content_hash,
    file_hash,
    l2_normalize,
    run,
)
from validate_embeddings import validate

FAKE_DIMENSION = 8


class FakeBackend:
    """Deterministic, dependency-free stand-in for a real embedding
    model: turns each string into a fixed-size vector derived from its
    own sha256 hash. Same string -> same vector, always; different
    strings -> (overwhelmingly likely) different vectors. Records every
    text it was ever called with, so tests can assert on cache
    hits/misses precisely (whether the fake was called at all)."""

    def __init__(self, dimension: int = FAKE_DIMENSION):
        self.dimension = dimension
        self.calls: list[str] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls.extend(texts)
        rows = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            row = np.frombuffer(digest[: self.dimension * 4].ljust(self.dimension * 4, b"\x00"), dtype=np.uint8)
            row = row[: self.dimension].astype(np.float32)
            rows.append(row)
        return np.stack(rows, axis=0)


class NaNBackend:
    def __call__(self, texts: list[str]) -> np.ndarray:
        return np.full((len(texts), FAKE_DIMENSION), np.nan, dtype=np.float32)


class WrongDimensionBackend:
    def __call__(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), FAKE_DIMENSION + 1), dtype=np.float32)


def make_chunk(chunk_id, order=0, section_title="Section A", subsection_title=None,
               item_types=None, concepts=None, text="Some content.", content_role="statement"):
    return {
        "chapter_id": "doc-x-ch01",
        "order": order,
        "source_item_ids": [chunk_id.replace("chunk-doc-x-ch01-", "")],
        "item_types": item_types or ["theorem"],
        "section_id": "sec-a",
        "section_title": section_title,
        "subsection_id": "sub-a" if subsection_title else None,
        "subsection_title": subsection_title,
        "pdf_pages": [5],
        "topics": [section_title],
        "concepts": concepts or ["concept a"],
        "has_uncertain_content": False,
        "chunk_id": chunk_id,
        "content_role": content_role,
        "part_index": None,
        "part_count": None,
        "text": text,
        "figure_refs": [],
        "related_chunk_ids": [],
        "generation_methods": {
            "boundaries": "deterministic", "text_assembly": "deterministic",
            "topics": "deterministic", "concepts": "rule_based",
            "figure_refs": "deterministic", "related_chunk_ids": "rule_based",
        },
        "review_status": "NOT_REQUIRED",
    }


def make_chunks_doc(chunks):
    return {"schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
            "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "doc-x-ch01", "chunks": chunks}


def write_chunks(tmp_path: Path, chunks) -> Path:
    path = tmp_path / "knowledge_chunks.json"
    path.write_text(json.dumps(make_chunks_doc(chunks), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class TestEmbeddingInput(unittest.TestCase):
    def test_full_template_all_fields_present(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1", section_title="Branches infinies",
                            subsection_title="Etude des asymptotes", item_types=["activity"],
                            concepts=["branches infinies"], text="La courbe ci-contre...")
        result = build_embedding_input(chunk, chapter_title="Continuite et limites")
        expected = (
            "[Chapitre : Continuite et limites]\n"
            "[Section : Branches infinies]\n"
            "[Sous-section : Etude des asymptotes]\n"
            "[Type : activity]\n"
            "[Concepts : branches infinies]\n\n"
            "La courbe ci-contre..."
        )
        self.assertEqual(result, expected)

    def test_absent_field_contributes_no_line(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1", subsection_title=None)
        result = build_embedding_input(chunk, chapter_title=None)
        self.assertNotIn("Chapitre", result)
        self.assertNotIn("Sous-section", result)
        self.assertNotIn("None", result)

    def test_text_is_verbatim_never_rewritten(self):
        latex_text = r"Soit $f(x) = \dfrac{1}{x-1}$ et $\lim_{x \to 1^-} f(x) = -\infty$."
        chunk = make_chunk("chunk-doc-x-ch01-it-1", text=latex_text)
        result = build_embedding_input(chunk, chapter_title="Chap")
        self.assertIn(latex_text, result)

    def test_deterministic_construction(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1")
        r1 = build_embedding_input(chunk, "Chap")
        r2 = build_embedding_input(chunk, "Chap")
        self.assertEqual(r1, r2)

    def test_no_field_ever_produces_blank_placeholder_line(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1", concepts=[])
        result = build_embedding_input(chunk, chapter_title=None)
        self.assertNotIn("[Concepts : ]", result)


class TestContentHash(unittest.TestCase):
    def test_format_matches_schema_pattern(self):
        h = content_hash("some text")
        self.assertRegex(h, r"^sha256:[0-9a-f]{64}$")

    def test_same_input_same_hash(self):
        self.assertEqual(content_hash("abc"), content_hash("abc"))

    def test_different_input_different_hash(self):
        self.assertNotEqual(content_hash("abc"), content_hash("abd"))

    def test_never_hashes_the_vector(self):
        """A hash must depend only on the string -- unaffected by
        whatever a (fake) backend would produce for it."""
        text = "same text"
        h1 = content_hash(text)
        FakeBackend()([text])  # exercise the backend, discard the vector
        h2 = content_hash(text)
        self.assertEqual(h1, h2)


class TestEmbeddingIdentity(unittest.TestCase):
    def test_stable_deterministic_id(self):
        id1 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "abc123")
        id2 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "abc123")
        self.assertEqual(id1, id2)

    def test_different_model_different_id(self):
        id1 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "abc123")
        id2 = build_embedding_id("doc-x-ch01", "chunk-1", "some-org/other-model", "abc123")
        self.assertNotEqual(id1, id2)

    def test_different_revision_different_id(self):
        id1 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "revision-aaa")
        id2 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "revision-bbb")
        self.assertNotEqual(id1, id2)

    def test_not_a_sequential_counter(self):
        id1 = build_embedding_id("doc-x-ch01", "chunk-1", "BAAI/bge-m3", "rev")
        id2 = build_embedding_id("doc-x-ch01", "chunk-2", "BAAI/bge-m3", "rev")
        self.assertNotIn("-0", id1.replace(id1.split("-")[-1], ""))  # no counter suffix pattern
        self.assertNotEqual(id1, id2)


class TestL2Normalize(unittest.TestCase):
    def test_unit_norm_after_normalization(self):
        vectors = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
        normalized = l2_normalize(vectors)
        norms = np.linalg.norm(normalized, axis=1)
        np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-6)

    def test_zero_vector_stays_zero_no_nan(self):
        vectors = np.array([[0.0, 0.0]], dtype=np.float32)
        normalized = l2_normalize(vectors)
        self.assertFalse(np.isnan(normalized).any())
        np.testing.assert_array_equal(normalized, [[0.0, 0.0]])


class TestPipeline(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_new_chunk_is_computed(self):
        chunks_path = write_chunks(self.tmp_path, [make_chunk("chunk-doc-x-ch01-it-1")])
        backend = FakeBackend()
        out_dir = self.tmp_path / "out"
        summary = run(chunks_path, backend, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                      output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(summary["computed"], 1)
        self.assertEqual(summary["reused"], 0)
        self.assertEqual(len(backend.calls), 1)

    def test_unchanged_chunk_is_cache_hit_on_rerun(self):
        chunks_path = write_chunks(self.tmp_path, [make_chunk("chunk-doc-x-ch01-it-1")])
        backend = FakeBackend()
        out_dir = self.tmp_path / "out"
        run(chunks_path, backend, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        backend2 = FakeBackend()
        summary2 = run(chunks_path, backend2, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                       output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(summary2["reused"], 1)
        self.assertEqual(summary2["computed"], 0)
        self.assertEqual(len(backend2.calls), 0, "backend must not be called at all on a full cache hit")

    def test_changed_chunk_text_is_cache_miss(self):
        chunk = make_chunk("chunk-doc-x-ch01-it-1", text="Original text.")
        chunks_path = write_chunks(self.tmp_path, [chunk])
        out_dir = self.tmp_path / "out"
        run(chunks_path, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        changed_chunk = make_chunk("chunk-doc-x-ch01-it-1", text="Changed text.")
        chunks_path2 = write_chunks(self.tmp_path, [changed_chunk])
        backend2 = FakeBackend()
        summary2 = run(chunks_path2, backend2, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                       output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(summary2["computed"], 1)
        self.assertEqual(summary2["reused"], 0)

    def test_different_model_computes_separately_and_does_not_touch_other_models_dir(self):
        chunks_path = write_chunks(self.tmp_path, [make_chunk("chunk-doc-x-ch01-it-1")])
        out_dir_a = self.tmp_path / "model-a"
        out_dir_b = self.tmp_path / "model-b"
        run(chunks_path, FakeBackend(), model_name="fake/model-a", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir_a, chapter_title="Chap", progress=lambda m: None)
        run(chunks_path, FakeBackend(), model_name="fake/model-b", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir_b, chapter_title="Chap", progress=lambda m: None)
        self.assertTrue((out_dir_a / "manifest.json").exists())
        self.assertTrue((out_dir_b / "manifest.json").exists())
        records_a = json.loads((out_dir_a / "records.json").read_text(encoding="utf-8"))
        records_b = json.loads((out_dir_b / "records.json").read_text(encoding="utf-8"))
        self.assertNotEqual(records_a[0]["embedding_id"], records_b[0]["embedding_id"])

    def test_deleted_chunk_becomes_stale_not_removed(self):
        chunk_a = make_chunk("chunk-doc-x-ch01-it-1")
        chunk_b = make_chunk("chunk-doc-x-ch01-it-2", order=1)
        chunks_path = write_chunks(self.tmp_path, [chunk_a, chunk_b])
        out_dir = self.tmp_path / "out"
        run(chunks_path, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        chunks_path2 = write_chunks(self.tmp_path, [chunk_a])  # chunk_b removed
        summary2 = run(chunks_path2, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                       output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(summary2["stale"], 1)
        records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
        statuses = {r["chunk_id"]: r["status"] for r in records}
        self.assertEqual(statuses["chunk-doc-x-ch01-it-1"], "active")
        self.assertEqual(statuses["chunk-doc-x-ch01-it-2"], "stale")
        # the vector row must still exist, not be dropped
        vectors = np.load(out_dir / "vectors.npy")
        self.assertEqual(vectors.shape[0], 2)

    def test_row_index_matches_vectors_positionally(self):
        chunks = [make_chunk(f"chunk-doc-x-ch01-it-{i}", order=i, text=f"text {i}") for i in range(5)]
        chunks_path = write_chunks(self.tmp_path, chunks)
        out_dir = self.tmp_path / "out"
        backend = FakeBackend()
        run(chunks_path, backend, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
        vectors = np.load(out_dir / "vectors.npy")
        for rec in records:
            chunk = next(c for c in chunks if c["chunk_id"] == rec["chunk_id"])
            raw_vector = backend([build_embedding_input(chunk, "Chap")])[0]
            expected_vector = l2_normalize(raw_vector.reshape(1, -1))[0]
            np.testing.assert_array_equal(vectors[rec["row_index"]], expected_vector)

    def test_force_recomputes_even_when_unchanged(self):
        chunks_path = write_chunks(self.tmp_path, [make_chunk("chunk-doc-x-ch01-it-1")])
        out_dir = self.tmp_path / "out"
        run(chunks_path, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        backend2 = FakeBackend()
        summary2 = run(chunks_path, backend2, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                       output_dir=out_dir, force=True, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(summary2["computed"], 1)
        self.assertEqual(len(backend2.calls), 1)

    def test_rerun_with_no_changes_calls_backend_zero_times(self):
        chunks = [make_chunk(f"chunk-doc-x-ch01-it-{i}", order=i) for i in range(10)]
        chunks_path = write_chunks(self.tmp_path, chunks)
        out_dir = self.tmp_path / "out"
        run(chunks_path, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)

        backend2 = FakeBackend()
        run(chunks_path, backend2, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        self.assertEqual(len(backend2.calls), 0)


class TestValidation(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _run_pipeline(self, chunks, backend=None):
        chunks_path = write_chunks(self.tmp_path, chunks)
        out_dir = self.tmp_path / "out"
        run(chunks_path, backend or FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
            output_dir=out_dir, chapter_title="Chap", progress=lambda m: None)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
        vectors = np.load(out_dir / "vectors.npy")
        chunks_doc = json.loads(chunks_path.read_text(encoding="utf-8"))
        return manifest, records, vectors, chunks_doc, chunks_path

    def test_valid_output_passes(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertTrue(report["passed"], report["checks"])

    def test_dimension_mismatch_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        manifest["embedding_model"]["dimension"] = FAKE_DIMENSION + 1
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["count_and_shape"])

    def test_nan_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        vectors = vectors.copy()
        vectors[0, 0] = np.nan
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["numerical"])

    def test_inf_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        vectors = vectors.copy()
        vectors[0, 0] = np.inf
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["numerical"])

    def test_duplicate_embedding_id_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1"), make_chunk("chunk-doc-x-ch01-it-2", order=1)])
        records[1]["embedding_id"] = records[0]["embedding_id"]
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["duplicate_ids"])

    def test_row_index_out_of_order_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1"), make_chunk("chunk-doc-x-ch01-it-2", order=1)])
        records[0]["row_index"], records[1]["row_index"] = 5, 6
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["row_index"])

    def test_content_hash_mismatch_with_actual_chunk_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        records[0]["content_hash"] = content_hash("something else entirely")
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["content_hash"])

    def test_stale_source_chunks_hash_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        # simulate the chunks file having changed on disk after the manifest was written
        write_chunks(self.tmp_path, [make_chunk("chunk-doc-x-ch01-it-1", text="a different text")])
        report = validate(manifest, records, vectors, chunks_doc=None, chunks_path=chunks_path, chapter_title="Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["source_chunks_hash"])

    def test_missing_chunk_coverage_is_detected(self):
        manifest, records, vectors, chunks_doc, chunks_path = self._run_pipeline(
            [make_chunk("chunk-doc-x-ch01-it-1")])
        chunks_doc["chunks"].append(make_chunk("chunk-doc-x-ch01-it-2", order=1))
        report = validate(manifest, records, vectors, chunks_doc, chunks_path, "Chap")
        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["chunk_coverage"])


class TestMultipleChapters(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_two_chapters_never_share_or_corrupt_each_others_output(self):
        chunk_1 = make_chunk("chunk-ch01-it-1")
        chunk_1["chapter_id"] = "book-ch01"
        doc_1 = {"schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
                 "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "book-ch01", "chunks": [chunk_1]}
        path_1 = self.tmp_path / "ch01.json"
        path_1.write_text(json.dumps(doc_1), encoding="utf-8")

        chunk_2 = make_chunk("chunk-ch02-it-1")
        chunk_2["chapter_id"] = "book-ch02"
        doc_2 = {"schema_version": "chunking-1.0", "algorithm_version": "chunk-v1",
                 "generated_at": "2026-01-01T00:00:00Z", "chapter_id": "book-ch02", "chunks": [chunk_2]}
        path_2 = self.tmp_path / "ch02.json"
        path_2.write_text(json.dumps(doc_2), encoding="utf-8")

        out_1 = self.tmp_path / "ch01" / "embeddings"
        out_2 = self.tmp_path / "ch02" / "embeddings"
        summary_1 = run(path_1, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                        output_dir=out_1, chapter_title=None, progress=lambda m: None)
        summary_2 = run(path_2, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                        output_dir=out_2, chapter_title=None, progress=lambda m: None)
        self.assertEqual(summary_1["chapter_id"], "book-ch01")
        self.assertEqual(summary_2["chapter_id"], "book-ch02")
        records_1 = json.loads((out_1 / "records.json").read_text(encoding="utf-8"))
        records_2 = json.loads((out_2 / "records.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records_1), 1)
        self.assertEqual(len(records_2), 1)
        self.assertNotEqual(records_1[0]["chunk_id"], records_2[0]["chunk_id"])


class TestNoChapterSpecificHardcoding(unittest.TestCase):
    def test_no_chapter_specific_hardcoding_in_production_modules(self):
        for filename in ("embed_knowledge.py", "validate_embeddings.py"):
            src = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
            for token in ("math-4eme-tome1", "-ch01", "act-008"):
                self.assertNotIn(token, src, f"{filename} must not reference {token!r}")


class TestChapter1Regression(unittest.TestCase):
    """Chapter 1 is used ONLY as ground truth/fixture -- uses the FAKE
    backend (no real model download needed for this test); see
    TestRealModelIntegration below for the one test that uses the real
    model, skipped when unavailable."""

    @classmethod
    def setUpClass(cls):
        if not config.chunks_json(config.CHAPTER_01_ID).exists():
            raise unittest.SkipTest("Chapter 1 chunks JSON not found")
        cls.chunks_path = config.chunks_json(config.CHAPTER_01_ID)

    def test_real_chapter_1_chunks_embed_and_validate_with_fake_backend(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "embeddings"
            backend = FakeBackend(dimension=FAKE_DIMENSION)
            summary = run(self.chunks_path, backend, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                         output_dir=out_dir, chapter_title="Continuite et limites", progress=lambda m: None)
            self.assertEqual(summary["computed"], summary["total_chunks"])

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            records = json.loads((out_dir / "records.json").read_text(encoding="utf-8"))
            vectors = np.load(out_dir / "vectors.npy")
            chunks_doc = json.loads(self.chunks_path.read_text(encoding="utf-8"))
            report = validate(manifest, records, vectors, chunks_doc, self.chunks_path, "Continuite et limites")
            self.assertTrue(report["passed"], report["checks"])

    def test_rerun_on_real_chapter_1_chunks_is_fully_cached(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "embeddings"
            run(self.chunks_path, FakeBackend(), model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                output_dir=out_dir, chapter_title="Continuite et limites", progress=lambda m: None)
            backend2 = FakeBackend()
            summary2 = run(self.chunks_path, backend2, model_name="fake/model", model_revision="rev1", dimension=FAKE_DIMENSION,
                          output_dir=out_dir, chapter_title="Continuite et limites", progress=lambda m: None)
            self.assertEqual(summary2["reused"], summary2["total_chunks"])
            self.assertEqual(len(backend2.calls), 0)


class TestRealModelIntegration(unittest.TestCase):
    """The one test that touches the REAL model chosen in
    embedding_design.md §3. Skipped (not failed) if
    sentence-transformers isn't installed or the model can't be loaded
    (e.g. no network access to download it) -- this environment's own
    availability is checked directly, not assumed."""

    @classmethod
    def setUpClass(cls):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("sentence-transformers not installed")
        if not config.chunks_json(config.CHAPTER_01_ID).exists():
            raise unittest.SkipTest("Chapter 1 chunks JSON not found")
        try:
            from embed_knowledge import SentenceTransformerBackend
            cls.backend = SentenceTransformerBackend(device="cpu", batch_size=8)
        except Exception as e:  # pragma: no cover - environment-dependent
            raise unittest.SkipTest(f"Could not load {config.EMBEDDING_MODEL_NAME}: {e}")

    def test_real_model_produces_correctly_shaped_finite_vectors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "embeddings"
            summary = run(config.chunks_json(config.CHAPTER_01_ID), self.backend,
                          output_dir=out_dir, chapter_title="Continuite et limites",
                          progress=lambda m: None)
            vectors = np.load(out_dir / "vectors.npy")
            self.assertEqual(vectors.shape[1], config.EMBEDDING_DIMENSION)
            self.assertFalse(np.isnan(vectors).any())
            self.assertFalse(np.isinf(vectors).any())
            norms = np.linalg.norm(vectors, axis=1)
            np.testing.assert_allclose(norms, np.ones_like(norms), atol=1e-3)


if __name__ == "__main__":
    unittest.main()
