-- Phase 12 -- Vector DB schema (PostgreSQL + pgvector).
--
-- Applied idempotently by data/src/init_vector_db_schema.py -- every
-- statement below is safe to re-run (IF NOT EXISTS everywhere). This file
-- is the versioned source of truth for the schema -- init_vector_db_schema.py
-- is only the reproducible runner (kept deliberately separate from
-- data/src/import_embeddings.py's own data-import logic -- see
-- data/schema/vector_db_design.md §12).
--
-- One table PER EMBEDDING DIMENSION (never per chapter, never per model
-- name) -- pgvector's vector(N) column type is fixed-width, so a future
-- differently-dimensioned model gets its OWN table (embeddings_768, ...),
-- never a column added here. chapter_id / embedding_model / model_revision
-- are plain filter columns *within* this table -- see
-- data/schema/vector_db_design.md §5/§8 and
-- data/schema/vector_db_payload.schema.json for the full field-by-field
-- rationale.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embeddings_1024 (
    embedding_id           text PRIMARY KEY,
    chunk_id               text NOT NULL,
    chapter_id             text NOT NULL,
    embedding_model        text NOT NULL,
    model_revision         text NOT NULL,
    content_hash           text NOT NULL,
    pipeline_version       text NOT NULL,
    normalization_strategy text NOT NULL,
    status                 text NOT NULL DEFAULT 'active',
    filter_metadata        jsonb NOT NULL,
    created_at             timestamptz NOT NULL,
    imported_at            timestamptz NOT NULL DEFAULT now(),
    embedding              vector(1024) NOT NULL,
    CONSTRAINT embeddings_1024_status_check
        CHECK (status IN ('active', 'stale')),
    CONSTRAINT embeddings_1024_normalization_check
        CHECK (normalization_strategy IN ('l2', 'none')),
    CONSTRAINT embeddings_1024_content_hash_format
        CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$')
);

-- Natural key mirroring embedding_id's own deterministic derivation
-- (chunk_id + model + revision) -- a defensive constraint, not the primary
-- upsert key (that's embedding_id itself); see vector_db_design.md §5.
CREATE UNIQUE INDEX IF NOT EXISTS embeddings_1024_chunk_model_revision_key
    ON embeddings_1024 (chunk_id, embedding_model, model_revision);

CREATE INDEX IF NOT EXISTS embeddings_1024_chapter_id_idx
    ON embeddings_1024 (chapter_id);

CREATE INDEX IF NOT EXISTS embeddings_1024_model_revision_idx
    ON embeddings_1024 (embedding_model, model_revision);

CREATE INDEX IF NOT EXISTS embeddings_1024_status_idx
    ON embeddings_1024 (status);

CREATE INDEX IF NOT EXISTS embeddings_1024_filter_metadata_gin_idx
    ON embeddings_1024 USING gin (filter_metadata);

-- Cosine similarity index -- see vector_db_design.md §9: robust even
-- if a future row's normalization_strategy is legitimately 'none', unlike
-- a raw inner-product index. Prepares future retrieval only -- no search
-- query/endpoint exists yet (out of scope for this phase).
CREATE INDEX IF NOT EXISTS embeddings_1024_embedding_cosine_idx
    ON embeddings_1024 USING hnsw (embedding vector_cosine_ops);
