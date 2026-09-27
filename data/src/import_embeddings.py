"""
Phase 12 - PostgreSQL + pgvector import (chapter-generic, model-generic).

Reads a chapter's already-generated, already-validated embedding artifacts
(manifest.json/records.json/vectors.npy -- Phase 11 output) and syncs them
into a local PostgreSQL+pgvector table (one table PER EMBEDDING DIMENSION,
e.g. embeddings_1024 -- see data/schema/vector_db_design.md). This module
NEVER regenerates embeddings, never modifies the source artifacts, and
never creates schema (see init_vector_db_schema.py for that, deliberately
kept separate).

Reuses validate_embeddings.validate() for every check it already implements
(manifest schema, record schema, vector count/shape/dtype, NaN/Inf/empty,
duplicate embedding_id/chunk_id, row_index positional consistency,
content_hash format AND recomputed-value consistency, model/dimension/
normalization consistency, source_chunks_hash freshness) rather than
reimplementing them -- only two additional, DB-specific checks are added
here: the manifest's dimension against the ACTUAL target table's vector
column width, and normalization_strategy against the enum this table's
cosine index supports.

Identity/caching mirrors embed_knowledge.py's own rules one layer up:
embedding_id (deterministic, never a counter) is the upsert key;
content_hash (never floating-point vector equality) decides insert vs.
update vs. reuse; a chunk_id present in the DB for a given
(chapter_id, embedding_model, model_revision) but absent from the CURRENT
records.json is marked status='stale' (never deleted) -- see
data/schema/vector_db_design.md §7.

Install: `pip install -r requirements.txt` (adds psycopg[binary] + the
pgvector Python adapter). Requires the schema to already exist -- run
init_vector_db_schema.py once first.

Usage:
    python import_embeddings.py --chapter-id <chapter_id> --validate
    python import_embeddings.py --chapter-id <chapter_id> --dry-run
    python import_embeddings.py --chapter-id <chapter_id>
    python import_embeddings.py --chapter-id <chapter_id> --force
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

import config
import validate_embeddings
from embed_knowledge import _load_chapter_title

logger = logging.getLogger("import_embeddings")


# --------------------------------------------------------------------------
# Artifact loading
# --------------------------------------------------------------------------

def load_artifacts(embedding_dir: Path) -> tuple[dict, list[dict], np.ndarray]:
    manifest_path = embedding_dir / "manifest.json"
    records_path = embedding_dir / "records.json"
    vectors_path = embedding_dir / "vectors.npy"
    missing = [p.name for p in (manifest_path, records_path, vectors_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing embedding artifact(s) in {embedding_dir}: {missing}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = json.loads(records_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    return manifest, records, vectors


# --------------------------------------------------------------------------
# Pre-import validation (reuses validate_embeddings; adds only the 2 new
# DB-specific checks that module has no reason to know about)
# --------------------------------------------------------------------------

def table_dimension(conn: psycopg.Connection, table: str) -> int | None:
    """Introspects the ACTUAL vector column width of `table` from Postgres
    itself (never assumed from the table name alone) -- defensive against
    manual schema drift. Returns None if the table doesn't exist at all
    (e.g. a manifest declaring a dimension this project has never
    initialized a table for) -- a plain ``'name'::regclass`` cast would
    instead raise UndefinedTable, so existence is checked via
    to_regclass() (which returns NULL rather than raising) first."""
    exists = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
    if exists is None:
        return None
    row = conn.execute(
        "SELECT format_type(a.atttypid, a.atttypmod) "
        "FROM pg_attribute a WHERE a.attrelid = %s::regclass "
        "AND a.attname = 'embedding' AND NOT a.attisdropped",
        (table,),
    ).fetchone()
    if row is None:
        return None
    import re
    m = re.search(r"vector\((\d+)\)", row[0])
    return int(m.group(1)) if m else None


def _dimension_matches_table_errors(manifest: dict, target_table_dimension: int | None) -> list[str]:
    if target_table_dimension is None:
        return [f"target table does not exist or has no 'embedding' column -- run init_vector_db_schema.py first"]
    manifest_dim = manifest["embedding_model"]["dimension"]
    if manifest_dim != target_table_dimension:
        return [f"manifest dimension {manifest_dim} does not match target table's vector column dimension {target_table_dimension}"]
    return []


def _normalization_compatibility_errors(records: list[dict]) -> list[str]:
    errors = []
    allowed = {"l2", "none"}
    for rec in records:
        strategy = rec.get("normalization_strategy")
        if strategy not in allowed:
            errors.append(
                f"record {rec.get('embedding_id')}: normalization_strategy {strategy!r} is not one of "
                f"{sorted(allowed)} -- not compatible with the cosine-similarity index this table uses"
            )
    return errors


def pre_import_validate(manifest: dict, records: list[dict], vectors: np.ndarray,
                         chunks_doc: dict | None, chunks_path: Path | None,
                         chapter_title: str | None, dim_for_table: int | None) -> dict:
    report = validate_embeddings.validate(manifest, records, vectors, chunks_doc, chunks_path, chapter_title)
    report["checks"]["table_dimension"] = _dimension_matches_table_errors(manifest, dim_for_table)
    report["checks"]["normalization_compatibility"] = _normalization_compatibility_errors(records)
    report["total_errors"] = sum(len(v) for v in report["checks"].values())
    report["passed"] = report["total_errors"] == 0
    return report


# --------------------------------------------------------------------------
# Diff / classification (pure Python, no DB writes -- shared by --dry-run
# and the real import so both compute identical numbers)
# --------------------------------------------------------------------------

def fetch_existing(conn: psycopg.Connection, table: str, chapter_id: str,
                    embedding_model: str, model_revision: str) -> dict[str, dict]:
    """Existing rows for this exact (chapter_id, embedding_model,
    model_revision) scope only -- never touches other chapters/models
    (see vector_db_design.md §7, cases E/F)."""
    rows = conn.execute(
        f"SELECT embedding_id, chunk_id, content_hash, status FROM {table} "
        f"WHERE chapter_id = %s AND embedding_model = %s AND model_revision = %s",
        (chapter_id, embedding_model, model_revision),
    ).fetchall()
    return {r[0]: {"chunk_id": r[1], "content_hash": r[2], "status": r[3]} for r in rows}


def classify(records: list[dict], existing: dict[str, dict], force: bool) -> dict:
    to_insert, to_update, to_reuse = [], [], []
    for rec in records:
        prior = existing.get(rec["embedding_id"])
        if prior is None:
            to_insert.append(rec)
        elif force or prior["content_hash"] != rec["content_hash"] or prior["status"] != rec.get("status", "active"):
            to_update.append(rec)
        else:
            to_reuse.append(rec)

    current_chunk_ids = {r["chunk_id"] for r in records}
    stale_candidates = sorted({
        row["chunk_id"] for row in existing.values()
        if row["status"] == "active" and row["chunk_id"] not in current_chunk_ids
    })
    return {"insert": to_insert, "update": to_update, "reuse": to_reuse, "stale_candidates": stale_candidates}


# --------------------------------------------------------------------------
# Apply (real writes -- always inside one caller-managed transaction)
# --------------------------------------------------------------------------

_INSERT_SQL_TEMPLATE = """
INSERT INTO {table} (
    embedding_id, chunk_id, chapter_id, embedding_model, model_revision,
    content_hash, pipeline_version, normalization_strategy, status,
    filter_metadata, created_at, imported_at, embedding
) VALUES (
    %(embedding_id)s, %(chunk_id)s, %(chapter_id)s, %(embedding_model)s, %(model_revision)s,
    %(content_hash)s, %(pipeline_version)s, %(normalization_strategy)s, %(status)s,
    %(filter_metadata)s, %(created_at)s, now(), %(embedding)s
)
"""

_UPDATE_SQL_TEMPLATE = """
UPDATE {table} SET
    content_hash = %(content_hash)s,
    pipeline_version = %(pipeline_version)s,
    normalization_strategy = %(normalization_strategy)s,
    status = %(status)s,
    filter_metadata = %(filter_metadata)s,
    created_at = %(created_at)s,
    imported_at = now(),
    embedding = %(embedding)s
WHERE embedding_id = %(embedding_id)s
"""

_STALE_SQL_TEMPLATE = """
UPDATE {table} SET status = 'stale', imported_at = now()
WHERE chapter_id = %s AND embedding_model = %s AND model_revision = %s
  AND status = 'active' AND chunk_id = ANY(%s)
"""


def _record_params(rec: dict, vector_row: np.ndarray) -> dict:
    return {
        "embedding_id": rec["embedding_id"],
        "chunk_id": rec["chunk_id"],
        "chapter_id": rec["chapter_id"],
        "embedding_model": rec["embedding_model"],
        "model_revision": rec["model_revision"],
        "content_hash": rec["content_hash"],
        "pipeline_version": rec["pipeline_version"],
        "normalization_strategy": rec["normalization_strategy"],
        "status": rec.get("status", "active"),
        "filter_metadata": Jsonb(rec["filter_metadata"]),
        "created_at": rec["created_at"],
        "embedding": np.asarray(vector_row, dtype=np.float32),
    }


def apply_import(conn: psycopg.Connection, table: str, records: list[dict], vectors: np.ndarray,
                  diff: dict, chapter_id: str, embedding_model: str, model_revision: str) -> None:
    """Executes every write for one import inside the CALLER's transaction
    -- never opens/commits its own, so a caller wrapping this in
    `with conn.transaction():` gets full rollback-on-failure for free."""
    by_id = {r["embedding_id"]: r for r in records}
    row_index_by_id = {r["embedding_id"]: r["row_index"] for r in records}

    insert_sql = _INSERT_SQL_TEMPLATE.format(table=table)
    update_sql = _UPDATE_SQL_TEMPLATE.format(table=table)
    stale_sql = _STALE_SQL_TEMPLATE.format(table=table)

    for rec in diff["insert"]:
        conn.execute(insert_sql, _record_params(rec, vectors[row_index_by_id[rec["embedding_id"]]]))
    for rec in diff["update"]:
        conn.execute(update_sql, _record_params(rec, vectors[row_index_by_id[rec["embedding_id"]]]))
    if diff["stale_candidates"]:
        conn.execute(stale_sql, (chapter_id, embedding_model, model_revision, diff["stale_candidates"]))


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def import_embeddings(
    embedding_dir: Path,
    chapter_id: str,
    database_url: str,
    chunks_path: Path | None = None,
    normalized_path: Path | None = None,
    table: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    validate_only: bool = False,
    output_path: Path | None = None,
) -> dict:
    manifest, records, vectors = load_artifacts(embedding_dir)
    chunks_doc = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path and chunks_path.exists() else None
    chapter_title = _load_chapter_title(normalized_path) if normalized_path else None

    report: dict = {
        "chapter_id": manifest.get("chapter_id"),
        "embedding_model": manifest.get("embedding_model", {}).get("name"),
        "model_revision": manifest.get("embedding_model", {}).get("revision"),
        "embedding_dimension": manifest.get("embedding_model", {}).get("dimension"),
        "dry_run": dry_run,
        "input_embeddings": len(records),
        "inserted": 0, "updated": 0, "reused": 0, "stale_marked": 0, "skipped": 0,
        "errors": [],
    }

    target_table = table or config.vector_table_name(manifest.get("embedding_model", {}).get("dimension"))
    report["table"] = target_table

    conn = psycopg.connect(database_url, autocommit=False)
    try:
        register_vector(conn)

        dim = table_dimension(conn, target_table)
        validation = pre_import_validate(manifest, records, vectors, chunks_doc, chunks_path, chapter_title, dim)
        report["validation"] = validation

        if not validation["passed"]:
            report["errors"] = [f"[{name}] {e}" for name, errs in validation["checks"].items() for e in errs]
            _write_report(report, output_path, embedding_dir)
            return report

        if validate_only:
            report["skipped"] = len(records)
            _write_report(report, output_path, embedding_dir)
            return report

        existing = fetch_existing(conn, target_table, manifest["chapter_id"],
                                   manifest["embedding_model"]["name"], manifest["embedding_model"]["revision"])
        diff = classify(records, existing, force=force)

        report["inserted"] = len(diff["insert"])
        report["updated"] = len(diff["update"])
        report["reused"] = len(diff["reuse"])
        report["stale_marked"] = len(diff["stale_candidates"])

        if dry_run:
            conn.rollback()  # discard the read-only transaction opened above; nothing was written
            _write_report(report, output_path, embedding_dir)
            return report

        # Commit the read-only transaction opened by table_dimension()/
        # fetch_existing() above BEFORE starting the write transaction --
        # otherwise `with conn.transaction():` would nest as a SAVEPOINT
        # inside it rather than being the outer transaction, and its
        # "commit" at exit would only release that savepoint, leaving the
        # real transaction (and every INSERT/UPDATE in it) uncommitted and
        # silently discarded on conn.close() (see the identical bug fixed
        # in init_vector_db_schema.py).
        conn.commit()
        with conn.transaction():
            apply_import(conn, target_table, records, vectors, diff,
                         manifest["chapter_id"], manifest["embedding_model"]["name"],
                         manifest["embedding_model"]["revision"])

        _write_report(report, output_path, embedding_dir)
        return report
    except Exception as e:
        report["errors"].append(str(e))
        _write_report(report, output_path, embedding_dir)
        raise
    finally:
        conn.close()


def _write_report(report: dict, output_path: Path | None, embedding_dir: Path) -> None:
    out_path = output_path or embedding_dir / "db_import_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s", out_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import knowledge embeddings into PostgreSQL+pgvector (Phase 12)")
    parser.add_argument("--chapter-id", type=str, default=config.CHAPTER_01_ID)
    parser.add_argument("--model", type=str, default=config.EMBEDDING_MODEL_NAME)
    parser.add_argument("--revision", type=str, default=config.EMBEDDING_MODEL_REVISION)
    parser.add_argument("--embedding-dir", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/embeddings/<model_id>/")
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--normalized", type=Path, default=None)
    parser.add_argument("--database-url", type=str, default=None,
                         help="Defaults to config.database_url() (DATABASE_URL env var / .env / POSTGRES_* vars)")
    parser.add_argument("--table", type=str, default=None, help="Defaults to embeddings_<dimension>")
    parser.add_argument("--dry-run", action="store_true", help="Validate + compute the diff; write nothing")
    parser.add_argument("--force", action="store_true", help="Re-upsert every row, ignoring the up-to-date check")
    parser.add_argument("--validate", action="store_true", help="Run pre-import validation only; never opens a write path")
    parser.add_argument("--output", type=Path, default=None, help="Report path; defaults to <embedding-dir>/db_import_report.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        embedding_dir = args.embedding_dir or config.embeddings_dir(args.chapter_id, args.model, args.revision)
        chunks_path = args.chunks or config.chunks_json(args.chapter_id)
        normalized_path = args.normalized or config.normalized_json(args.chapter_id)
        db_url = args.database_url or config.database_url()

        report = import_embeddings(
            embedding_dir=embedding_dir, chapter_id=args.chapter_id, database_url=db_url,
            chunks_path=chunks_path, normalized_path=normalized_path, table=args.table,
            dry_run=args.dry_run, force=args.force, validate_only=args.validate,
            output_path=args.output,
        )

        logger.info(
            "Chapter %s: input=%d inserted=%d updated=%d reused=%d stale=%d skipped=%d errors=%d "
            "(table=%s, model=%s@%s, dim=%s%s)",
            report["chapter_id"], report["input_embeddings"], report["inserted"], report["updated"],
            report["reused"], report["stale_marked"], report["skipped"], len(report["errors"]),
            report["table"], report["embedding_model"], report["model_revision"], report["embedding_dimension"],
            " DRY-RUN" if report["dry_run"] else "",
        )
        if report["errors"]:
            for e in report["errors"]:
                logger.error(e)
            sys.exit(1)
    except Exception:
        logger.exception("import_embeddings failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
