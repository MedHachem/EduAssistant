"""
Phase 13 - Semantic Search (read-only query layer over embeddings_1024).

query text -> BGE-M3 query embedding -> PostgreSQL/pgvector cosine
similarity -> ranked chunks. Strictly per data/schema/semantic_search_design.md
-- see that document for the full rationale behind every decision below.

Reuses, never reimplements: SentenceTransformerBackend and l2_normalize
(embed_knowledge.py) for the query embedding, and table_dimension
(import_embeddings.py) for the dimension-compatibility check. Never
regenerates document embeddings, never writes to embeddings_1024, never
modifies chunks/enrichment/relations/normalization/figures/associations/
backend/frontend.

The vector similarity computation happens entirely inside PostgreSQL
(ORDER BY embedding <=> query_vector) -- this module never loads candidate
vectors into Python or computes a dot product itself.

Chunk text is NEVER stored in Postgres -- it is resolved, per search call,
from the chapter's own authoritative data/output/<chapter_id>/chunks/
knowledge_chunks.json (config.chunks_json(chapter_id)).

Architectural boundary (semantic_search_design.md §13): this module
ends at returning ranked (chunk_id, score, metadata, text) results. It
never constructs a prompt, never calls an LLM, never exposes an HTTP
endpoint. Those are a distinct, later phase.

Usage:
    python search_embeddings.py --chapter-id <chapter_id> --query "..."
    python search_embeddings.py --chapter-id <chapter_id> --query "..." --top-k 10 --json
    python search_embeddings.py --chapter-id <chapter_id> --query "..." --filter-section-id sec-i-rappels
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

import config
from embed_knowledge import EmbeddingBackend, SentenceTransformerBackend, l2_normalize
from import_embeddings import table_dimension

logger = logging.getLogger("search_embeddings")

ALLOWED_FILTER_KEYS = {
    "section_id", "subsection_id", "concepts", "topics", "item_types",
    "content_role", "pdf_pages", "has_uncertain_content",
}


class SearchValidationError(ValueError):
    """A malformed request -- never reaches the embedding backend or
    PostgreSQL (see semantic_search_design.md §2 step 1)."""


class SearchIncompatibleModelError(RuntimeError):
    """The requested (embedding_model, model_revision) is structurally
    incompatible with the target table/chapter -- a dimension mismatch, or
    a (chapter_id, model, revision) combination that has never been
    indexed at all, while OTHER combinations exist for that chapter. This
    is deliberately distinct from a legitimate zero-relevant-results
    search (see semantic_search_design.md §9/§10): the former is
    a caller misconfiguration that will never self-resolve; the latter is
    returned as a normal, possibly-empty result list."""


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------

def validate_request(query: str, chapter_id: str, top_k: int, filters: dict | None) -> None:
    if not isinstance(query, str) or not query.strip():
        raise SearchValidationError("query must be a non-empty string")
    if not isinstance(chapter_id, str) or not chapter_id.strip():
        raise SearchValidationError("chapter_id must be a non-empty string")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not (1 <= top_k <= config.SEARCH_MAX_TOP_K):
        raise SearchValidationError(f"top_k must be an integer in 1..{config.SEARCH_MAX_TOP_K}, got {top_k!r}")
    if filters is None:
        return
    if not isinstance(filters, dict):
        raise SearchValidationError("filters must be a dict")
    unknown = set(filters) - ALLOWED_FILTER_KEYS
    if unknown:
        raise SearchValidationError(f"unknown filter key(s): {sorted(unknown)}")
    _validate_filter_types(filters)


def _validate_filter_types(filters: dict) -> None:
    for key in ("section_id", "subsection_id", "content_role"):
        if key in filters and filters[key] is not None and not isinstance(filters[key], str):
            raise SearchValidationError(f"filters.{key} must be a string or null")
    for key in ("concepts", "topics", "item_types"):
        if key in filters and filters[key] is not None:
            value = filters[key]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise SearchValidationError(f"filters.{key} must be a list of strings")
    if filters.get("pdf_pages") is not None:
        value = filters["pdf_pages"]
        if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            raise SearchValidationError("filters.pdf_pages must be a list of integers")
    if filters.get("has_uncertain_content") is not None and not isinstance(filters["has_uncertain_content"], bool):
        raise SearchValidationError("filters.has_uncertain_content must be a boolean")


def _safe_table_identifier(table: str) -> str:
    """Defensive check before this value is ever interpolated into a SQL
    string -- table names always originate internally from
    config.vector_table_name(dimension) (an int-derived, non-user-supplied
    value), never from raw request input, but this guard costs nothing and
    fails clearly if that invariant is ever broken."""
    if not re.fullmatch(r"embeddings_\d+", table):
        raise SearchValidationError(f"invalid table identifier: {table!r}")
    return table


# --------------------------------------------------------------------------
# Metadata filter -> SQL translation (semantic_search_design.md §4)
# --------------------------------------------------------------------------

def _build_filter_sql(filters: dict | None) -> tuple[list[str], dict]:
    clauses: list[str] = []
    params: dict = {}
    if not filters:
        return clauses, params

    if filters.get("section_id") is not None:
        clauses.append("filter_metadata->>'section_id' = %(f_section_id)s")
        params["f_section_id"] = filters["section_id"]
    if filters.get("subsection_id") is not None:
        clauses.append("filter_metadata->>'subsection_id' = %(f_subsection_id)s")
        params["f_subsection_id"] = filters["subsection_id"]
    if filters.get("content_role") is not None:
        clauses.append("filter_metadata->>'content_role' = %(f_content_role)s")
        params["f_content_role"] = filters["content_role"]
    if filters.get("has_uncertain_content") is not None:
        clauses.append("(filter_metadata->>'has_uncertain_content')::boolean = %(f_has_uncertain_content)s")
        params["f_has_uncertain_content"] = filters["has_uncertain_content"]

    for key in ("concepts", "topics", "item_types"):
        if filters.get(key):
            clauses.append(f"filter_metadata->'{key}' ?| %(f_{key})s::text[]")
            params[f"f_{key}"] = list(filters[key])

    if filters.get("pdf_pages"):
        clauses.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(filter_metadata->'pdf_pages') p "
            "WHERE p::int = ANY(%(f_pdf_pages)s::int[]))"
        )
        params["f_pdf_pages"] = list(filters["pdf_pages"])

    return clauses, params


# --------------------------------------------------------------------------
# Model/revision compatibility (semantic_search_design.md §9)
# --------------------------------------------------------------------------

def _check_model_revision_available(conn: psycopg.Connection, table: str, chapter_id: str,
                                     embedding_model: str, model_revision: str) -> None:
    available = conn.execute(
        f"SELECT DISTINCT embedding_model, model_revision FROM {table} "
        f"WHERE chapter_id = %s AND status = 'active'",
        (chapter_id,),
    ).fetchall()
    if not available:
        logger.info(
            "chapter_id=%r has no active embeddings under any model/revision -- "
            "returning an empty result set", chapter_id,
        )
        return
    if (embedding_model, model_revision) not in {tuple(r) for r in available}:
        raise SearchIncompatibleModelError(
            f"chapter_id={chapter_id!r} has no rows under embedding_model={embedding_model!r} "
            f"model_revision={model_revision!r}. Available (model, revision) pairs for this "
            f"chapter: {available}"
        )


# --------------------------------------------------------------------------
# Chunk text resolution (semantic_search_design.md §6 -- never stored
# in PostgreSQL; resolved from the authoritative chunks file)
# --------------------------------------------------------------------------

def _load_chunk_lookup(chunks_path: Path) -> dict[str, dict]:
    if not Path(chunks_path).exists():
        return {}
    doc = json.loads(Path(chunks_path).read_text(encoding="utf-8"))
    return {c["chunk_id"]: c for c in doc["chunks"]}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def search(
    query: str,
    chapter_id: str,
    top_k: int = config.SEARCH_DEFAULT_TOP_K,
    filters: dict | None = None,
    embedding_model: str = config.EMBEDDING_MODEL_NAME,
    model_revision: str = config.EMBEDDING_MODEL_REVISION,
    database_url: str | None = None,
    chunks_path: Path | None = None,
    backend: EmbeddingBackend | None = None,
    table: str | None = None,
) -> list[dict]:
    """Returns a list of SearchResult dicts (search_result.schema.json),
    ranked descending by cosine similarity. Empty list for a legitimate
    zero-match outcome (empty chapter, over-narrow filters, top_k=0 rows
    available) -- see module docstring and §9/§10 of the design
    for when this raises instead (dimension mismatch; a genuinely
    unindexed model/revision for a chapter that HAS other indexed data)."""
    validate_request(query, chapter_id, top_k, filters)

    database_url = database_url or config.database_url()
    chunks_path = chunks_path or config.chunks_json(chapter_id)
    backend = backend or SentenceTransformerBackend(model_name=embedding_model, model_revision=model_revision)

    conn = psycopg.connect(database_url)
    try:
        register_vector(conn)
        target_table = _safe_table_identifier(table or config.vector_table_name(backend.dimension))

        dim = table_dimension(conn, target_table)
        if dim is None:
            raise SearchIncompatibleModelError(
                f"table {target_table!r} does not exist -- run init_vector_db_schema.py first"
            )
        if dim != backend.dimension:
            raise SearchIncompatibleModelError(
                f"embedding backend dimension {backend.dimension} does not match table "
                f"{target_table!r}'s column width {dim}"
            )

        _check_model_revision_available(conn, target_table, chapter_id, embedding_model, model_revision)

        raw_vector = backend([query])[0]
        query_vector = l2_normalize(np.asarray(raw_vector, dtype=np.float32).reshape(1, -1))[0]

        filter_clauses, filter_params = _build_filter_sql(filters)
        where_sql = " AND ".join([
            "chapter_id = %(chapter_id)s",
            "embedding_model = %(embedding_model)s",
            "model_revision = %(model_revision)s",
            "status = 'active'",
            *filter_clauses,
        ])
        sql = (
            "SELECT chunk_id, chapter_id, filter_metadata, embedding_model, model_revision, "
            "1 - (embedding <=> %(query_vector)s) AS score "
            f"FROM {target_table} "
            f"WHERE {where_sql} "
            "ORDER BY embedding <=> %(query_vector)s ASC, embedding_id ASC "
            "LIMIT %(top_k)s"
        )
        params = {
            "chapter_id": chapter_id, "embedding_model": embedding_model, "model_revision": model_revision,
            "query_vector": query_vector, "top_k": top_k, **filter_params,
        }
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    chunk_lookup = _load_chunk_lookup(chunks_path)
    results = []
    for chunk_id, chp_id, filter_metadata, model_name, revision, score in rows:
        chunk = chunk_lookup.get(chunk_id)
        if chunk is None:
            logger.warning(
                "chunk_id=%r returned by search has no matching entry in %s -- excluding from results",
                chunk_id, chunks_path,
            )
            continue
        results.append({
            "chunk_id": chunk_id,
            "chapter_id": chp_id,
            "score": float(score),
            "section_id": filter_metadata.get("section_id"),
            "subsection_id": filter_metadata.get("subsection_id"),
            "content_role": filter_metadata.get("content_role"),
            "pdf_pages": filter_metadata.get("pdf_pages", []),
            "topics": filter_metadata.get("topics", []),
            "concepts": filter_metadata.get("concepts", []),
            "item_types": filter_metadata.get("item_types", []),
            "has_uncertain_content": filter_metadata.get("has_uncertain_content", False),
            "embedding_model": model_name,
            "model_revision": revision,
            "text": chunk["text"],
        })
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Semantic search over embeddings_1024 (Phase 13)")
    parser.add_argument("--chapter-id", type=str, default=config.CHAPTER_01_ID)
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--top-k", type=int, default=config.SEARCH_DEFAULT_TOP_K)
    parser.add_argument("--model", type=str, default=config.EMBEDDING_MODEL_NAME)
    parser.add_argument("--revision", type=str, default=config.EMBEDDING_MODEL_REVISION)
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--filter-section-id", type=str, default=None)
    parser.add_argument("--filter-subsection-id", type=str, default=None)
    parser.add_argument("--filter-content-role", type=str, default=None, choices=["statement", "correction"])
    parser.add_argument("--filter-concepts", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-topics", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-item-types", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-pdf-pages", type=str, default=None, help="comma-separated integers")
    parser.add_argument("--filter-has-uncertain-content", type=str, default=None, choices=["true", "false"])
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a human-readable summary")
    return parser.parse_args()


def _filters_from_args(args: argparse.Namespace) -> dict | None:
    filters: dict = {}
    if args.filter_section_id:
        filters["section_id"] = args.filter_section_id
    if args.filter_subsection_id:
        filters["subsection_id"] = args.filter_subsection_id
    if args.filter_content_role:
        filters["content_role"] = args.filter_content_role
    if args.filter_concepts:
        filters["concepts"] = [s.strip() for s in args.filter_concepts.split(",") if s.strip()]
    if args.filter_topics:
        filters["topics"] = [s.strip() for s in args.filter_topics.split(",") if s.strip()]
    if args.filter_item_types:
        filters["item_types"] = [s.strip() for s in args.filter_item_types.split(",") if s.strip()]
    if args.filter_pdf_pages:
        filters["pdf_pages"] = [int(s.strip()) for s in args.filter_pdf_pages.split(",") if s.strip()]
    if args.filter_has_uncertain_content is not None:
        filters["has_uncertain_content"] = args.filter_has_uncertain_content == "true"
    return filters or None


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        backend = SentenceTransformerBackend(model_name=args.model, model_revision=args.revision, device=args.device)
        results = search(
            query=args.query, chapter_id=args.chapter_id, top_k=args.top_k,
            filters=_filters_from_args(args), embedding_model=args.model, model_revision=args.revision,
            database_url=args.database_url or config.database_url(),
            chunks_path=args.chunks or config.chunks_json(args.chapter_id),
            backend=backend,
        )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            logger.info("%d result(s) for %r in chapter %s", len(results), args.query, args.chapter_id)
            for r in results:
                snippet = r["text"][:120].replace("\n", " ")
                logger.info("  score=%.4f chunk_id=%s section=%s :: %s",
                            r["score"], r["chunk_id"], r["section_id"], snippet)
    except (SearchValidationError, SearchIncompatibleModelError) as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception:
        logger.exception("search_embeddings failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
