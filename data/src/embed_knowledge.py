"""
Phase 11 - Knowledge embeddings v1 (chapter-generic, deterministic
identity/caching; the actual vector VALUES come from a real neural
network and are the one part of this pipeline that is not itself
deterministic bit-for-bit across environments -- see
data/schema/embedding_design.md §8).

Reads a chapter's CHUNKS file (Phase 10) and produces one embedding
vector per chunk using the model chosen in embedding_design.md §3
(BAAI/bge-m3, MIT, 1024-dim, via sentence-transformers). Purely
additive: reads the chunks file, never modifies it (or any earlier
phase's output), and writes to a SEPARATE per-chapter, per-model
directory (data/output/<chapter_id>/embeddings/<model_id>/).

100% local, deterministic-where-it-matters:
  - The embedding INPUT (build_embedding_input) is a pure function of
    already-existing chunk fields -- never an LLM call, never a
    paraphrase, never a rewrite of the verbatim `text`/LaTeX.
  - content_hash is a plain sha256 of that exact input string.
  - embedding_id/cache decisions are made ENTIRELY from content_hash +
    (chunk_id, model, revision) -- never by comparing floating-point
    vectors (see embedding_design.md §4/§8).
  - The only non-deterministic-across-machines part is the model's own
    numerical output, which is why nothing here ever asserts vector
    equality -- only shape/dtype/NaN/Inf and identity consistency.

Install: `pip install -r requirements.txt` (adds sentence-transformers +
torch, CPU-only wheels are enough -- CUDA is used automatically via
`--device cuda` if a matching torch build is present, but is never
required).

Model download: the FIRST run of `SentenceTransformerBackend` fetches
BAAI/bge-m3's weights from the HuggingFace Hub (a few GB, cached under
the normal HF cache dir, typically `~/.cache/huggingface/hub`) and
pins them to the exact revision in config.EMBEDDING_MODEL_REVISION.
Every subsequent run reuses that local cache -- no network access
after the first successful run, and no silent upgrade to a newer
revision.

Usage:
    python embed_knowledge.py
    python embed_knowledge.py --chapter-id <chapter_id> --batch-size 16 --device cpu
    python embed_knowledge.py --force
    python embed_knowledge.py --validate

First execution (no cache yet) embeds every chunk in the chapter's
chunks file, in batches of --batch-size (default: see
config.EMBEDDING_DEFAULT_BATCH_SIZE), and reports e.g. "Cache: 0
reused, 102 to compute." Subsequent executions with an unchanged
chunks file report "Cache: 102 reused, 0 to compute" and make zero
calls into the model -- only a changed chunk (different content_hash),
a new chunk, or --force triggers recomputation for that chunk.
--force recomputes every chunk unconditionally (still without
recomputing chunks unrelated to this chapter/model/revision).

Output, per (chapter_id, model, revision), under
data/output/<chapter_id>/embeddings/<model_id>/:
  - manifest.json   -- schema in data/schema/embedding_manifest.schema.json
  - vectors.npy     -- float32 array, shape (vector_count, dimension)
  - records.json    -- one entry per row, records[i] <-> vectors[i]

Validation: `python validate_embeddings.py --chapter-id <chapter_id>`
(or pass `--validate` to this script to run it as part of the same
invocation) checks the manifest/records/vectors against the schema and
each other, writing a machine-readable
`.../embeddings/<model_id>/validation_report.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

import config

logger = logging.getLogger("embed_knowledge")


class EmbeddingBackend(Protocol):
    """Anything callable as `backend(list_of_strings) -> np.ndarray of
    shape (len(list_of_strings), dimension)` -- real backend
    (SentenceTransformerBackend) or a test fake, injected, never
    hardwired, so this module's own logic is testable without
    downloading a model (see test_embeddings.py)."""

    def __call__(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerBackend:
    """Real embedding backend for the model chosen in
    embedding_design.md §3. Imports sentence_transformers/torch lazily
    (only when actually instantiated), so importing embed_knowledge.py
    itself never requires either to be installed -- only actually
    computing a real embedding does."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL_NAME,
                 model_revision: str = config.EMBEDDING_MODEL_REVISION,
                 device: str | None = None, batch_size: int = config.EMBEDDING_DEFAULT_BATCH_SIZE):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, revision=model_revision, device=device)
        self.dimension = self._model.get_sentence_embedding_dimension()
        if model_name == config.EMBEDDING_MODEL_NAME and self.dimension != config.EMBEDDING_DIMENSION:
            # Only enforced for the DEFAULT design-chosen model -- guards
            # against BAAI/bge-m3 itself silently reporting an unexpected
            # dimension (e.g. a future revision change). An explicitly
            # different --model is the caller's own informed choice
            # (still recorded truthfully via this backend's own
            # .dimension, passed on to run() by main() below, never
            # silently assumed to be config.EMBEDDING_DIMENSION).
            raise ValueError(
                f"Loaded model '{model_name}'@{model_revision} reports dimension {self.dimension}, "
                f"expected {config.EMBEDDING_DIMENSION} (embedding_design.md §3) -- refusing to "
                f"silently proceed with an unexpected dimension."
            )

    def __call__(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=False,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


# --------------------------------------------------------------------
# Embedding input (embedding_design.md §2)
# --------------------------------------------------------------------

def build_embedding_input(chunk: dict, chapter_title: str | None) -> str:
    """Pure function of already-existing chunk fields (+ the chapter's
    own title, read once from the normalized JSON's `chapter.title` by
    the caller -- chunks do not carry it themselves). Uses ONLY:
    chapter_title, section_title, subsection_title, item_types,
    concepts -- deliberately excludes `topics` (redundant with section/
    subsection titles on every real chunk inspected),
    figure_refs/related_chunk_ids (not natural-language content), and
    exercise_type/reasoning_types (not present on a chunk at all,
    living instead on the enrichment record -- joining them back in
    would add a second upstream dependency this phase does not
    otherwise need). See embedding_design.md §2 for the full
    rationale and worked example.

    A field that is absent/empty contributes NO line at all -- never a
    blank placeholder. `chunk["text"]` is appended verbatim, byte for
    byte, after a single blank line -- never rewritten, summarized, or
    LaTeX-simplified."""
    lines: list[str] = []
    if chapter_title:
        lines.append(f"[Chapitre : {chapter_title}]")
    if chunk.get("section_title"):
        lines.append(f"[Section : {chunk['section_title']}]")
    if chunk.get("subsection_title"):
        lines.append(f"[Sous-section : {chunk['subsection_title']}]")
    if chunk.get("item_types"):
        lines.append(f"[Type : {', '.join(chunk['item_types'])}]")
    if chunk.get("concepts"):
        lines.append(f"[Concepts : {', '.join(chunk['concepts'])}]")

    header = "\n".join(lines)
    return f"{header}\n\n{chunk['text']}" if header else chunk["text"]


def content_hash(embedding_input: str) -> str:
    """sha256 of the EXACT embedding input string (never the source
    chunk text alone, never the vector) -- format
    'sha256:<64 lowercase hex>', matching
    embedding_manifest.schema.json's pattern exactly."""
    digest = hashlib.sha256(embedding_input.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def file_hash(path: Path) -> str:
    """Same sha256:<hex> format, over a file's raw bytes -- used for
    manifest.source_chunks_hash (embedding_design.md §7)."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def build_embedding_id(chapter_id: str, chunk_id: str, model_name: str, model_revision: str) -> str:
    """Deterministic, content-derived -- never a counter. The SAME
    chunk under a different model or revision always produces a
    DIFFERENT id (embedding_design.md §4/¨5), so it is never
    overwritten, only added alongside."""
    model_slug = config._embedding_model_id(model_name, model_revision)
    return f"emb-{chapter_id}-{chunk_id}-{model_slug}"


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """embedding_design.md §7/¨9: L2-normalize at storage time for
    cosine-similarity/dot-product compatibility with standard vector
    indexes. A degenerate all-zero vector (should never occur for real
    model output, but must not silently divide by zero if it ever does)
    is left as all-zero rather than producing NaN."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    safe_norms = np.where(norms == 0, 1.0, norms)
    return (vectors / safe_norms).astype(np.float32)


# --------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------

def _filter_metadata(chunk: dict) -> dict:
    return {
        "section_id": chunk["section_id"],
        "subsection_id": chunk["subsection_id"],
        "topics": chunk["topics"],
        "concepts": chunk["concepts"],
        "item_types": chunk["item_types"],
        "content_role": chunk["content_role"],
        "pdf_pages": chunk["pdf_pages"],
        "has_uncertain_content": chunk["has_uncertain_content"],
    }


def run(
    chunks_path: Path,
    backend: EmbeddingBackend,
    model_name: str = config.EMBEDDING_MODEL_NAME,
    model_revision: str = config.EMBEDDING_MODEL_REVISION,
    dimension: int = config.EMBEDDING_DIMENSION,
    output_dir: Path | None = None,
    batch_size: int = config.EMBEDDING_DEFAULT_BATCH_SIZE,
    force: bool = False,
    chapter_title: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Runs the full incremental embedding pipeline for one chapter and
    writes manifest.json/vectors.npy/records.json. Returns a summary
    dict (also used for the CLI's own final report). `backend` is
    injected -- callers pass SentenceTransformerBackend(...) for a real
    run, or a fake in tests (see test_embeddings.py)."""
    log = progress or (lambda msg: logger.info(msg))

    chunks_doc = json.loads(Path(chunks_path).read_text(encoding="utf-8"))
    chapter_id = chunks_doc["chapter_id"]
    chunks = chunks_doc["chunks"]
    source_hash = file_hash(chunks_path)

    out_dir = output_dir or config.embeddings_dir(chapter_id, model_name, model_revision)
    manifest_path = out_dir / "manifest.json"
    vectors_path = out_dir / "vectors.npy"
    records_path = out_dir / "records.json"

    existing_records: list[dict] = []
    existing_vectors: np.ndarray | None = None
    if not force and records_path.exists() and vectors_path.exists():
        existing_records = json.loads(records_path.read_text(encoding="utf-8"))
        existing_vectors = np.load(vectors_path)

    existing_by_key: dict[tuple, dict] = {}
    for i, rec in enumerate(existing_records):
        existing_by_key[(rec["chunk_id"], rec["embedding_model"], rec["model_revision"])] = {
            **rec, "_vector": existing_vectors[i] if existing_vectors is not None else None,
        }

    log(f"Chapter {chapter_id}: {len(chunks)} chunks in source file.")

    to_compute: list[tuple[dict, str, str]] = []  # (chunk, embedding_input, content_hash)
    reused_records: list[dict] = []
    reused_vectors: list[np.ndarray] = []
    current_chunk_ids = {c["chunk_id"] for c in chunks}

    for chunk in chunks:
        embedding_input = build_embedding_input(chunk, chapter_title)
        c_hash = content_hash(embedding_input)
        cache_key = (chunk["chunk_id"], model_name, model_revision)
        cached = existing_by_key.get(cache_key)

        if cached is not None and cached["content_hash"] == c_hash and not force:
            reused_records.append({k: v for k, v in cached.items() if k != "_vector"})
            reused_vectors.append(cached["_vector"])
        else:
            to_compute.append((chunk, embedding_input, c_hash))

    log(f"Cache: {len(reused_records)} reused, {len(to_compute)} to compute.")

    new_records: list[dict] = []
    new_vectors: list[np.ndarray] = []
    if to_compute:
        texts = [inp for _, inp, _ in to_compute]
        batches_total = (len(texts) + batch_size - 1) // batch_size
        computed_vectors: list[np.ndarray] = []
        for batch_num, start in enumerate(range(0, len(texts), batch_size), start=1):
            batch_texts = texts[start:start + batch_size]
            batch_vectors = backend(batch_texts)
            batch_vectors = np.asarray(batch_vectors, dtype=np.float32)
            if batch_vectors.ndim != 2 or batch_vectors.shape[1] != dimension:
                raise ValueError(
                    f"Embedding backend returned shape {batch_vectors.shape}, expected "
                    f"(*, {dimension}) -- refusing to store an unexpected dimension."
                )
            if np.isnan(batch_vectors).any():
                raise ValueError("Embedding backend produced NaN value(s) -- refusing to store corrupted vectors.")
            if np.isinf(batch_vectors).any():
                raise ValueError("Embedding backend produced Inf value(s) -- refusing to store corrupted vectors.")
            computed_vectors.append(batch_vectors)
            log(f"Batch {batch_num}/{batches_total}: {len(batch_texts)} chunk(s) embedded.")

        stacked = np.concatenate(computed_vectors, axis=0)
        stacked = l2_normalize(stacked) if config.EMBEDDING_NORMALIZATION == "l2" else stacked

        for (chunk, embedding_input, c_hash), vector in zip(to_compute, stacked):
            record = {
                "embedding_id": build_embedding_id(chapter_id, chunk["chunk_id"], model_name, model_revision),
                "chunk_id": chunk["chunk_id"],
                "chapter_id": chapter_id,
                "row_index": -1,  # assigned after final ordering below
                "content_hash": c_hash,
                "embedding_model": model_name,
                "model_revision": model_revision,
                "embedding_dimension": dimension,
                "normalization_strategy": config.EMBEDDING_NORMALIZATION,
                "created_at": _now_iso(),
                "pipeline_version": config.EMBEDDING_PIPELINE_VERSION,
                "filter_metadata": _filter_metadata(chunk),
                "status": "active",
            }
            new_records.append(record)
            new_vectors.append(vector)

    # Reused records keep their own row_index/status as-is except we
    # re-stamp row_index below to guarantee positional consistency;
    # ensure they are marked "active" (a chunk that was stale in a
    # prior run but has now reappeared is active again).
    for rec in reused_records:
        rec["status"] = "active"

    active_by_chunk_id = {r["chunk_id"]: r for r in reused_records + new_records}
    chunk_order = {c["chunk_id"]: i for i, c in enumerate(chunks)}
    active_ids_sorted = sorted(active_by_chunk_id.keys(), key=lambda cid: chunk_order[cid])

    final_records: list[dict] = []
    final_vectors: list[np.ndarray] = []
    vector_by_chunk_id = {
        **{r["chunk_id"]: v for r, v in zip(reused_records, reused_vectors)},
        **{r["chunk_id"]: v for r, v in zip(new_records, new_vectors)},
    }
    for chunk_id in active_ids_sorted:
        rec = dict(active_by_chunk_id[chunk_id])
        rec["row_index"] = len(final_records)
        final_records.append(rec)
        final_vectors.append(vector_by_chunk_id[chunk_id])

    # Stale: existed in a prior run, for this exact (model, revision),
    # but no longer present in the CURRENT chunks file -- kept, never
    # deleted, flagged (embedding_design.md §5).
    stale_entries = [
        v for k, v in existing_by_key.items()
        if k[0] not in current_chunk_ids
    ]
    stale_entries.sort(key=lambda r: r["chunk_id"])
    stale_count = 0
    for entry in stale_entries:
        rec = {k: v for k, v in entry.items() if k != "_vector"}
        rec["status"] = "stale"
        rec["row_index"] = len(final_records)
        final_records.append(rec)
        final_vectors.append(entry["_vector"])
        stale_count += 1

    vectors_array = np.stack(final_vectors, axis=0).astype(np.float32) if final_vectors else np.zeros(
        (0, dimension), dtype=np.float32
    )

    manifest = {
        "schema_version": "embedding-manifest-1.0",
        "pipeline_version": config.EMBEDDING_PIPELINE_VERSION,
        "chapter_id": chapter_id,
        "generated_at": _now_iso(),
        "embedding_model": {
            "name": model_name,
            "revision": model_revision,
            "framework": config.EMBEDDING_FRAMEWORK,
            "dimension": dimension,
        },
        "normalization_strategy": config.EMBEDDING_NORMALIZATION,
        "vector_dtype": config.EMBEDDING_DTYPE,
        "vector_count": len(final_records),
        "source_chunks_file": str(chunks_path),
        "source_chunks_hash": source_hash,
        "vectors_file": "vectors.npy",
        "records_file": "records.json",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, vectors_array)
    records_path.write_text(json.dumps(final_records, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"Wrote {vectors_path}, {records_path}, {manifest_path}")

    return {
        "chapter_id": chapter_id,
        "total_chunks": len(chunks),
        "reused": len(reused_records),
        "computed": len(new_records),
        "stale": stale_count,
        "vector_count": len(final_records),
        "dimension": dimension,
        "model": model_name,
        "model_revision": model_revision,
        "dtype": config.EMBEDDING_DTYPE,
        "manifest_path": str(manifest_path),
        "vectors_path": str(vectors_path),
        "records_path": str(records_path),
    }


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load_chapter_title(normalized_path: Path | None) -> str | None:
    if normalized_path is None or not Path(normalized_path).exists():
        return None
    normalized = json.loads(Path(normalized_path).read_text(encoding="utf-8"))
    return normalized.get("chapter", {}).get("title")


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge embeddings v1 (Phase 11)")
    parser.add_argument("--chapter-id", type=str, default=config.CHAPTER_01_ID,
                         help="Chapter id (used only to derive default paths below; never hardcoded in logic)")
    parser.add_argument("--chunks", type=Path, default=None,
                         help="Defaults to data/output/<chapter-id>/chunks/knowledge_chunks.json")
    parser.add_argument("--normalized", type=Path, default=None,
                         help="Optional, for the [Chapitre : ...] header line; "
                              "defaults to data/output/<chapter-id>/normalized/knowledge.json")
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter-id>/embeddings/<model_id>/")
    parser.add_argument("--model", type=str, default=config.EMBEDDING_MODEL_NAME)
    parser.add_argument("--revision", type=str, default=config.EMBEDDING_MODEL_REVISION)
    parser.add_argument("--batch-size", type=int, default=config.EMBEDDING_DEFAULT_BATCH_SIZE)
    parser.add_argument("--device", type=str, default=None, help="'cpu', 'cuda', or omit for auto-detect")
    parser.add_argument("--force", action="store_true", help="Recompute every chunk, ignoring the cache")
    parser.add_argument("--validate", action="store_true", help="Run validate_embeddings.py after embedding")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        chunks_path = args.chunks or config.chunks_json(args.chapter_id)
        normalized_path = args.normalized or config.normalized_json(args.chapter_id)
        chapter_title = _load_chapter_title(normalized_path)

        backend = SentenceTransformerBackend(
            model_name=args.model, model_revision=args.revision,
            device=args.device, batch_size=args.batch_size,
        )
        summary = run(
            chunks_path, backend, model_name=args.model, model_revision=args.revision,
            dimension=backend.dimension,
            output_dir=args.output, batch_size=args.batch_size, force=args.force,
            chapter_title=chapter_title,
        )
        logger.info(
            "Chapter %s: %d chunks -> %d reused, %d computed, %d stale (dimension=%d, model=%s@%s).",
            summary["chapter_id"], summary["total_chunks"], summary["reused"], summary["computed"],
            summary["stale"], summary["dimension"], summary["model"], summary["model_revision"][:12],
        )

        if args.validate:
            import validate_embeddings
            report = validate_embeddings.run(
                Path(summary["manifest_path"]), Path(summary["records_path"]), Path(summary["vectors_path"]),
                chunks_path,
            )
            logger.info("Validation %s: %d error(s).", "PASSED" if report["passed"] else "FAILED", report["total_errors"])
            if not report["passed"]:
                sys.exit(1)
    except Exception:
        logger.exception("embed_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
