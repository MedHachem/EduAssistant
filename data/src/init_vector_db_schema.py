"""
Phase 12 - PostgreSQL + pgvector schema initialization.

Applies data/schema/vector_db_schema.sql idempotently (CREATE EXTENSION IF
NOT EXISTS vector, CREATE TABLE/INDEX IF NOT EXISTS) against whichever
database config.database_url() resolves to (DATABASE_URL env var, or a
repo-root .env file, or the individual POSTGRES_* variables -- never a
hardcoded credential). Deliberately separate from import_embeddings.py:
this script only ever creates/updates schema objects, never touches row
data (see data/schema/vector_db_design.md §12).

This script never installs PostgreSQL or pgvector itself, and never
silently substitutes a different Vector DB if pgvector's extension files
aren't present on the target server -- if `CREATE EXTENSION vector` fails
for that reason, it reports the exact prerequisite (build pgvector for this
PostgreSQL installation; see vector_db_design.md §2/§3) and exits
non-zero rather than working around it.

Usage:
    python init_vector_db_schema.py
    python init_vector_db_schema.py --database-url postgresql://user:pass@host:port/db
    python init_vector_db_schema.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

import config

logger = logging.getLogger("init_vector_db_schema")


def pgvector_extension_status(conn: psycopg.Connection) -> dict:
    """Reports whether pgvector is available to CREATE EXTENSION and/or
    already installed in the target database -- distinct facts (a server
    can have the extension FILES present without any one database having
    run CREATE EXTENSION yet)."""
    available = conn.execute(
        "SELECT default_version FROM pg_available_extensions WHERE name = 'vector'"
    ).fetchone()
    installed = conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    return {
        "available": available is not None,
        "available_version": available[0] if available else None,
        "installed": installed is not None,
        "installed_version": installed[0] if installed else None,
    }


PGVECTOR_MISSING_MESSAGE = (
    "pgvector is not available on this PostgreSQL server (no 'vector' entry "
    "in pg_available_extensions). This project does not substitute a "
    "different Vector DB when pgvector is missing -- see "
    "data/schema/vector_db_design.md. To fix: build/install pgvector for "
    "THIS PostgreSQL installation (e.g. on Windows: Visual Studio Build "
    "Tools + `nmake /f Makefile.win` / `nmake /f Makefile.win install` "
    "from https://github.com/pgvector/pgvector, with PGROOT pointed at "
    "this PostgreSQL install directory), then re-run this script."
)


def _split_statements(sql_text: str) -> list[str]:
    """Strips '--' comment LINES first, then splits the remaining SQL on
    ';' -- doing it in the other order would let a semicolon used as plain
    punctuation inside a comment (e.g. 'the schema; foo is...') fracture
    that comment line in two, leaking its second half through as if it
    were a real statement."""
    sql_only = "\n".join(
        line for line in sql_text.splitlines() if not line.strip().startswith("--")
    )
    return [s.strip() for s in sql_only.split(";") if s.strip()]


def apply_schema(conn: psycopg.Connection, schema_sql_path: Path, dry_run: bool = False) -> list[str]:
    """Executes every statement in schema_sql_path inside one transaction.
    Returns the list of statements executed (or that WOULD be executed, if
    dry_run). Raises (and lets the caller's transaction roll back) on the
    first failure -- e.g. pgvector missing on CREATE EXTENSION."""
    statements = _split_statements(schema_sql_path.read_text(encoding="utf-8"))
    if dry_run:
        return statements
    for stmt in statements:
        conn.execute(stmt)
    return statements


def run(database_url: str, schema_sql_path: Path, dry_run: bool = False) -> dict:
    conn = psycopg.connect(database_url, autocommit=False)
    try:
        status_before = pgvector_extension_status(conn)
        # Commit this read-only check before starting the DDL transaction
        # below -- otherwise `with conn.transaction():` would nest INSIDE
        # the implicit transaction this SELECT already opened (psycopg
        # treats an already-open transaction's `with conn.transaction():`
        # as a SAVEPOINT, not the outer transaction), and its "commit" at
        # exit would only release that savepoint -- leaving the real outer
        # transaction (and every DDL statement in it) uncommitted, silently
        # discarded on conn.close().
        conn.commit()
        if not status_before["available"]:
            raise RuntimeError(PGVECTOR_MISSING_MESSAGE)

        if dry_run:
            statements = apply_schema(conn, schema_sql_path, dry_run=True)
        else:
            with conn.transaction():
                statements = apply_schema(conn, schema_sql_path, dry_run=False)

        status_after = pgvector_extension_status(conn)
        conn.commit()
        return {
            "dry_run": dry_run,
            "pgvector_available": status_after["available"],
            "pgvector_available_version": status_after["available_version"],
            "pgvector_installed": status_after["installed"],
            "pgvector_installed_version": status_after["installed_version"],
            "statements_executed": len(statements),
        }
    finally:
        conn.close()


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize the PostgreSQL + pgvector schema (Phase 12)")
    parser.add_argument("--database-url", type=str, default=None,
                         help="Defaults to config.database_url() (DATABASE_URL env var / .env / POSTGRES_* vars)")
    parser.add_argument("--schema-sql", type=Path, default=None,
                         help="Defaults to config.VECTOR_DB_SCHEMA_SQL")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be executed; change nothing")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    db_url = args.database_url or config.database_url()
    schema_sql_path = args.schema_sql or config.VECTOR_DB_SCHEMA_SQL
    try:
        result = run(db_url, schema_sql_path, dry_run=args.dry_run)
        logger.info(
            "pgvector available=%s (v%s) installed=%s (v%s); %d statement(s) %s.",
            result["pgvector_available"], result["pgvector_available_version"],
            result["pgvector_installed"], result["pgvector_installed_version"],
            result["statements_executed"], "would be executed (dry-run)" if args.dry_run else "executed",
        )
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
