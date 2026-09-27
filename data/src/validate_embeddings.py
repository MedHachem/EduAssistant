"""
Phase 11 - structural + numerical validation for knowledge embeddings.

Checks the output of embed_knowledge.py against
embedding_manifest.schema.json (structural/required-field validation)
plus numerical and cross-referential checks a JSON Schema alone cannot
express: vector count/dimension/dtype, NaN/Inf/empty vectors, duplicate
IDs, orphan/missing embeddings, row_index <-> vectors.npy positional
consistency, content_hash format AND recomputed-value consistency
(recomputes build_embedding_input from the actual chunk + chapter title
and re-hashes it -- catches a template change that silently invalidated
old records), model/dimension/normalization consistency, source_chunks_hash
freshness, and stale-record bookkeeping.

Chapter-generic: takes the manifest/records/vectors/chunks paths as
arguments; never assumes a chapter_id.

Usage:
    python validate_embeddings.py
    python validate_embeddings.py --manifest <path> --records <path> --vectors <path> --chunks <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

import config
from embed_knowledge import build_embedding_input, content_hash, file_hash, _load_chapter_title

logger = logging.getLogger("validate_embeddings")


def _schema_errors(manifest: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed -- skipped schema validation (pip install jsonschema)"]

    schema = json.loads(config.EMBEDDING_SCHEMA_JSON.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{e.message} (at {list(e.path)})" for e in validator.iter_errors(manifest)]


def _record_schema_errors(records: list[dict]) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []
    schema_doc = json.loads(config.EMBEDDING_SCHEMA_JSON.read_text(encoding="utf-8"))
    record_schema = schema_doc["$defs"]["EmbeddingRecord"]
    validator = jsonschema.Draft202012Validator({**record_schema, "$defs": schema_doc["$defs"]})
    errors = []
    for i, rec in enumerate(records):
        for e in validator.iter_errors(rec):
            errors.append(f"records[{i}] ({rec.get('embedding_id')}): {e.message} (at {list(e.path)})")
    return errors


def _count_and_shape_errors(manifest: dict, records: list[dict], vectors: np.ndarray) -> list[str]:
    errors = []
    if vectors.ndim != 2:
        errors.append(f"vectors.npy has {vectors.ndim} dimension(s), expected 2")
        return errors
    if vectors.shape[0] != len(records):
        errors.append(f"vector count {vectors.shape[0]} does not match records count {len(records)}")
    if vectors.shape[0] != manifest["vector_count"]:
        errors.append(f"vector count {vectors.shape[0]} does not match manifest.vector_count {manifest['vector_count']}")
    expected_dim = manifest["embedding_model"]["dimension"]
    if vectors.shape[1] != expected_dim:
        errors.append(f"vector dimension {vectors.shape[1]} does not match manifest dimension {expected_dim}")
    if vectors.dtype != np.float32:
        errors.append(f"vectors.npy dtype is {vectors.dtype}, expected float32")
    return errors


def _numerical_errors(vectors: np.ndarray) -> list[str]:
    errors = []
    if vectors.size == 0:
        return errors
    if np.isnan(vectors).any():
        rows = sorted(set(np.argwhere(np.isnan(vectors))[:, 0].tolist()))
        errors.append(f"NaN value(s) found in vector row(s): {rows}")
    if np.isinf(vectors).any():
        rows = sorted(set(np.argwhere(np.isinf(vectors))[:, 0].tolist()))
        errors.append(f"Inf value(s) found in vector row(s): {rows}")
    zero_rows = [i for i in range(vectors.shape[0]) if not np.any(vectors[i])]
    if zero_rows:
        errors.append(f"empty (all-zero) vector(s) at row(s): {zero_rows}")
    return errors


def _duplicate_id_errors(records: list[dict]) -> list[str]:
    errors = []
    seen_embedding_ids: set[str] = set()
    seen_chunk_ids_per_model_rev: dict[tuple, set[str]] = {}
    for rec in records:
        eid = rec["embedding_id"]
        if eid in seen_embedding_ids:
            errors.append(f"duplicate embedding_id: {eid}")
        seen_embedding_ids.add(eid)

        key = (rec["embedding_model"], rec["model_revision"])
        seen = seen_chunk_ids_per_model_rev.setdefault(key, set())
        if rec["chunk_id"] in seen:
            errors.append(f"duplicate chunk_id {rec['chunk_id']!r} within model/revision {key}")
        seen.add(rec["chunk_id"])
    return errors


def _row_index_errors(records: list[dict], vectors: np.ndarray) -> list[str]:
    errors = []
    indices = sorted(rec["row_index"] for rec in records)
    if indices != list(range(len(records))):
        errors.append(f"row_index values are not exactly 0..{len(records) - 1}: {indices}")
        return errors
    for rec in records:
        if rec["row_index"] >= vectors.shape[0]:
            errors.append(f"record {rec['embedding_id']}: row_index {rec['row_index']} is out of bounds for vectors.npy")
    return errors


def _chunk_coverage_errors(records: list[dict], chunks_doc: dict | None) -> list[str]:
    if chunks_doc is None:
        return []
    errors = []
    current_chunk_ids = {c["chunk_id"] for c in chunks_doc["chunks"]}
    active_chunk_ids = {r["chunk_id"] for r in records if r.get("status", "active") == "active"}

    missing = current_chunk_ids - active_chunk_ids
    if missing:
        errors.append(f"{len(missing)} chunk(s) in the source file have no active embedding record: {sorted(missing)}")

    for rec in records:
        if rec.get("status", "active") == "active" and rec["chunk_id"] not in current_chunk_ids:
            errors.append(f"record {rec['embedding_id']}: chunk_id {rec['chunk_id']!r} is 'active' but not in the "
                           f"current chunks file (should be 'stale')")
        if rec.get("status") == "stale" and rec["chunk_id"] in current_chunk_ids:
            errors.append(f"record {rec['embedding_id']}: chunk_id {rec['chunk_id']!r} is marked 'stale' but IS "
                           f"present in the current chunks file (should be 'active')")
    return errors


def _content_hash_errors(records: list[dict], chunks_doc: dict | None, chapter_title: str | None) -> list[str]:
    errors = []
    hash_re_ok = lambda h: isinstance(h, str) and h.startswith("sha256:") and len(h) == 71
    for rec in records:
        if not hash_re_ok(rec["content_hash"]):
            errors.append(f"record {rec['embedding_id']}: malformed content_hash {rec['content_hash']!r}")

    if chunks_doc is None:
        return errors
    chunks_by_id = {c["chunk_id"]: c for c in chunks_doc["chunks"]}
    for rec in records:
        if rec.get("status") == "stale":
            continue  # the source chunk no longer exists -- nothing to recompute against
        chunk = chunks_by_id.get(rec["chunk_id"])
        if chunk is None:
            continue  # already reported by _chunk_coverage_errors
        expected_input = build_embedding_input(chunk, chapter_title)
        expected_hash = content_hash(expected_input)
        if rec["content_hash"] != expected_hash:
            errors.append(
                f"record {rec['embedding_id']}: content_hash {rec['content_hash']} does not match a fresh "
                f"recomputation of build_embedding_input for chunk {rec['chunk_id']!r} -- the chunk or the "
                f"embedding-input template changed since this record was written"
            )
    return errors


def _manifest_consistency_errors(manifest: dict, records: list[dict]) -> list[str]:
    errors = []
    for rec in records:
        if rec["embedding_model"] != manifest["embedding_model"]["name"]:
            errors.append(f"record {rec['embedding_id']}: embedding_model {rec['embedding_model']!r} != manifest {manifest['embedding_model']['name']!r}")
        if rec["model_revision"] != manifest["embedding_model"]["revision"]:
            errors.append(f"record {rec['embedding_id']}: model_revision {rec['model_revision']!r} != manifest {manifest['embedding_model']['revision']!r}")
        if rec["embedding_dimension"] != manifest["embedding_model"]["dimension"]:
            errors.append(f"record {rec['embedding_id']}: embedding_dimension {rec['embedding_dimension']} != manifest {manifest['embedding_model']['dimension']}")
        if rec["normalization_strategy"] != manifest["normalization_strategy"]:
            errors.append(f"record {rec['embedding_id']}: normalization_strategy {rec['normalization_strategy']!r} != manifest {manifest['normalization_strategy']!r}")
    return errors


def _source_hash_errors(manifest: dict, chunks_path: Path | None) -> list[str]:
    if chunks_path is None or not Path(chunks_path).exists():
        return []
    actual_hash = file_hash(chunks_path)
    if manifest["source_chunks_hash"] != actual_hash:
        return [
            f"manifest.source_chunks_hash {manifest['source_chunks_hash']} does not match the current "
            f"chunks file's actual hash {actual_hash} -- embeddings are stale relative to the chunks on disk"
        ]
    return []


def validate(manifest: dict, records: list[dict], vectors: np.ndarray,
             chunks_doc: dict | None = None, chunks_path: Path | None = None,
             chapter_title: str | None = None) -> dict:
    checks = {
        "manifest_schema": _schema_errors(manifest),
        "record_schema": _record_schema_errors(records),
        "count_and_shape": _count_and_shape_errors(manifest, records, vectors),
        "numerical": _numerical_errors(vectors),
        "duplicate_ids": _duplicate_id_errors(records),
        "row_index": _row_index_errors(records, vectors),
        "chunk_coverage": _chunk_coverage_errors(records, chunks_doc),
        "content_hash": _content_hash_errors(records, chunks_doc, chapter_title),
        "manifest_consistency": _manifest_consistency_errors(manifest, records),
        "source_chunks_hash": _source_hash_errors(manifest, chunks_path),
    }
    total_errors = sum(len(v) for v in checks.values())

    active = [r for r in records if r.get("status", "active") == "active"]
    stale = [r for r in records if r.get("status") == "stale"]

    return {
        "chapter_id": manifest.get("chapter_id"),
        "pipeline_version": manifest.get("pipeline_version"),
        "counts": {
            "records": len(records),
            "active": len(active),
            "stale": len(stale),
            "vectors": int(vectors.shape[0]) if vectors.ndim == 2 else 0,
            "dimension": manifest.get("embedding_model", {}).get("dimension"),
        },
        "passed": total_errors == 0,
        "total_errors": total_errors,
        "checks": checks,
    }


def run(manifest_path: Path, records_path: Path, vectors_path: Path,
        chunks_path: Path | None = None, normalized_path: Path | None = None,
        output_path: Path | None = None) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    records = json.loads(Path(records_path).read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    chunks_doc = json.loads(Path(chunks_path).read_text(encoding="utf-8")) if chunks_path and Path(chunks_path).exists() else None
    chapter_title = _load_chapter_title(normalized_path) if normalized_path else None

    report = validate(manifest, records, vectors, chunks_doc, chunks_path, chapter_title)

    out_path = output_path or Path(manifest_path).parent / "validation_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return report


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate knowledge embeddings output (Phase 11)")
    parser.add_argument("--chapter-id", type=str, default=config.CHAPTER_01_ID)
    parser.add_argument("--model", type=str, default=config.EMBEDDING_MODEL_NAME)
    parser.add_argument("--revision", type=str, default=config.EMBEDDING_MODEL_REVISION)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--records", type=Path, default=None)
    parser.add_argument("--vectors", type=Path, default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--normalized", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        manifest_path = args.manifest or config.embeddings_manifest_json(args.chapter_id, args.model, args.revision)
        records_path = args.records or config.embeddings_records_json(args.chapter_id, args.model, args.revision)
        vectors_path = args.vectors or config.embeddings_vectors_npy(args.chapter_id, args.model, args.revision)
        chunks_path = args.chunks or config.chunks_json(args.chapter_id)
        normalized_path = args.normalized or config.normalized_json(args.chapter_id)

        report = run(manifest_path, records_path, vectors_path, chunks_path, normalized_path, args.output)
        logger.info("Validation %s: %d error(s) across %d check group(s)",
                     "PASSED" if report["passed"] else "FAILED", report["total_errors"], len(report["checks"]))
        if not report["passed"]:
            for name, errors in report["checks"].items():
                for e in errors:
                    logger.error("[%s] %s", name, e)
            sys.exit(1)
    except Exception:
        logger.exception("validate_embeddings failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
