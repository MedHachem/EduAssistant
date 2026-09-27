# Vector DB design (Phase 12 — design only, nothing implemented)

Design proposal, not yet implemented. Describes how a future Vector DB layer
would consume the Phase 11 embedding artifacts
(`data/output/<chapter_id>/embeddings/<model_id>/{manifest.json,vectors.npy,records.json}`).
No Vector DB is installed, no Docker container is started, no data is
inserted anywhere, and no semantic-search/RAG code exists yet. This document
is the approved-design counterpart to `embedding_design.md` for the next
phase — see that document (§10 "Future Vector DB compatibility") for the
contract this design builds on.

---

## 1. Actual current architecture (inspected directly, nothing invented)

### 1.1 The real Chapter 1 embedding artifacts

`data/output/math-4eme-tome1-ch01/embeddings/bge-m3-5617a9f61b02/`:

- **`manifest.json`**: `schema_version="embedding-manifest-1.0"`,
  `pipeline_version="embed-v1"`, `chapter_id="math-4eme-tome1-ch01"`,
  `embedding_model={name: "BAAI/bge-m3", revision: "5617a9f61b028...", framework: "sentence-transformers", dimension: 1024}`,
  `normalization_strategy="l2"`, `vector_dtype="float32"`, `vector_count=102`,
  `source_chunks_hash="sha256:c78e47b8...`.
- **`vectors.npy`**: inspected directly — shape **(102, 1024)**, dtype
  **float32**, and every row's L2 norm measured **exactly 1.0** (confirmed
  L2-normalized, not merely labeled as such).
- **`records.json`**: 102 entries, one per row. Fields present on every
  record: `embedding_id`, `chunk_id`, `chapter_id`, `row_index`,
  `content_hash` (`sha256:<64 hex>`), `embedding_model`, `model_revision`,
  `embedding_dimension`, `normalization_strategy`, `created_at`,
  `pipeline_version`, `filter_metadata`, `status` (`"active"` on all 102
  today — no stale records exist yet in this fixture).
  `filter_metadata` itself contains exactly: `section_id`, `subsection_id`,
  `topics[]`, `concepts[]`, `item_types[]`, `content_role`, `pdf_pages[]`,
  `has_uncertain_content` — **no more, no less** than
  `embedding_manifest.schema.json`'s `EmbeddingRecord.filter_metadata`
  definition. Records do **not** carry the chunk's own `text`.

### 1.2 The real Chapter 1 chunk data (`chunks/knowledge_chunks.json`)

Per `knowledge_chunk.schema.json`, every one of the 102 real chunks has:
`chunk_id`, `chapter_id`, `order`, `content_role` (real values seen:
`"statement"`, `"correction"`), `part_index`/`part_count` (non-null for only
**3** of 102 chunks — real oversized-item splits), `source_item_ids[]`,
`item_types[]`, `section_id`/`section_title`, `subsection_id`/
`subsection_title`, `pdf_pages[]`, `topics[]`, `concepts[]`, `text` (the
verbatim assembled string — this is the only field the embedding pipeline
reads for its input), `figure_refs[]` (present, non-empty on **19 of 102**
chunks — each entry has `source` (`"links.figures"` or
`"relation:illustrates"`), `reconstructed_figure_id`, `figure_id` (**often
`null`** — many figure refs are not yet resolved to a real
`final_figures` id), `confidence`), `related_chunk_ids[]` (other chunk_ids,
e.g. a correction pointing at its statement, or an `applies_concept`/
`illustrates` edge from `knowledge_relations.json`), `has_uncertain_content`
(bool, propagated from normalization), `generation_methods` (object),
`review_status` (real values seen: `"NOT_REQUIRED"`, `"REVIEW_REQUIRED"`).

Two facts matter directly for Vector DB design:

- **`figure_refs` and `related_chunk_ids` are graph-shaped, not scalar
  filters** — a Vector DB payload should carry enough to resolve them
  (via `chunk_id`), never inline their full content.
- **`text` is intentionally absent from `records.json` and from
  `filter_metadata`** — the embedding pipeline's own author already drew
  the "never duplicate the authoritative content" line at the chunk-text
  boundary. This Vector DB design continues that same line.

### 1.3 Upstream provenance (normalized knowledge — read for completeness)

`normalized/knowledge.json` items additionally carry `uncertainty`
(`has_uncertain_markers`, `has_gap_markers`, `uncertain_spans[]`) and
`provenance` (`source_item_id`, `document_id`, `pdf_pages[]`,
`reconstructed_sources[]`, `bloc_type`, `bloc_numero`,
`continues_from_previous_page`/`continues_on_next_page`,
`original_content`). **None of this reaches the chunk or the embedding
record directly** — only `has_uncertain_content` (a boolean summary) and
`pdf_pages` are propagated down to chunk → `filter_metadata`. A Vector DB
must not invent access to fields that don't survive to the chunk level.

### 1.4 The existing Spring Boot / MySQL backend (inspected, not assumed)

- Spring Boot **3.3.4**, Java **17**, Maven, port **8081** (not 8080 — a
  documented local port conflict). Dependencies: `spring-boot-starter-web`,
  `spring-boot-starter-data-jpa`, `spring-boot-starter-validation`,
  `mysql-connector-j`, `h2` (local dev profile only). **No Spring Security,
  no CORS config** — the Angular dev server reaches the backend through
  `frontend/proxy.conf.json`, not cross-origin headers.
- **Exactly one** JPA entity exists today: `FigureKnowledgeReview`
  (`chapterId`, `figureId`, `knowledgeItemId`, `relation`, `status`,
  `reviewedAt`, `reviewedBy`). There is **no** `Chunk`, `KnowledgeItem`, or
  `Embedding` entity in the backend — every knowledge/figure/chunk artifact
  is owned by the Python pipeline's JSON files on disk, and the backend
  only ever references them by plain string ID.
- REST convention: `/api/chapters/{chapterId}/reviews[...]`, no `/v1`
  segment.
- MySQL config: `jdbc:mysql://localhost:3306/eduassistant`,
  `hibernate.ddl-auto=update` (no Flyway/Liquibase yet).

### 1.5 A decision that already exists in this repo — must not be ignored

Three pieces of evidence, all present **since the very first commit**
(`5e387d1 chore: init repo structure`, confirmed via `git log`), show the
project already anticipated a Vector DB and had started planning for it:

- **`docker-compose.yml`** (repo root): a single `db` service,
  `image: pgvector/pgvector:pg16`, reading `.env`, mapping
  `${POSTGRES_PORT}:5432`. Comment (French, verbatim): *"Squelette Phase 1
  — l'implementation complete (init pgvector, volumes, healthcheck) arrive
  en Phase 2. Ne pas lancer encore."* ("Phase 1 skeleton — the full
  implementation (pgvector init, volumes, healthcheck) arrives in Phase 2.
  Don't launch it yet.")
- **`.env.example`**: a section explicitly titled `# PostgreSQL (+
  pgvector)` (`POSTGRES_HOST/PORT/DB/USER/PASSWORD`), separate from the
  backend's own MySQL config (which isn't even in `.env.example` at all —
  MySQL is configured purely through `application.properties` defaults).
  It also lists an **`# AI/RAG service (Python FastAPI)`** block
  (`AI_SERVICE_PORT=8000`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`).
- **`ai-service/`**: an existing (currently empty-scaffold) directory with
  `app/` and `ingestion/` subfolders. Its `README.md` was just deleted in
  the working tree (`git status`: `D ai-service/README.md`), but its
  last-committed content (read via `git show HEAD:ai-service/README.md`)
  says: *"Service Python (FastAPI): RAG + connexion Claude. `ingestion/`:
  pipeline PDF → pages.json → ... → embeddings → pgvector (Phases 3-7).
  `app/`: service RAG + endpoint appelé par le backend (Phases 9-10)."*

**This must be reported transparently, not silently overridden**: the
project's original plan was a *third* architecture — a dedicated Python
FastAPI `ai-service` owning both the ingestion pipeline and the RAG/pgvector
layer, called by the Spring Boot backend. **That is not what actually got
built.** The real, working, tested, 216-test-covered pipeline lives
entirely in `data/src/` (this repo's `DATA_DIR`), writes to
`data/output/<chapter_id>/...`, and has zero relationship to `ai-service/`
today (empty folders only). `ai-service/README.md`'s own deletion in the
current working tree suggests this original plan is itself being
reconsidered, not settled. Sections 3 and 4 below address this honestly
rather than assuming either the original plan or the as-built reality is
"correct."

What *is* settled, and should be treated as a real prior decision rather
than re-litigated from scratch: **pgvector was already chosen** as the
vector storage engine, before this design task began. Section 2 evaluates
it on its merits anyway (per the task's "do not choose based on popularity
alone" instruction) rather than assuming it's right just because it's
already scaffolded — but that scaffold is real, relevant evidence, not a
tie-breaker to be ignored.

---

## 2. Vector DB technology comparison

| Criterion | FAISS | Qdrant | **pgvector** |
|---|---|---|---|
| Vector similarity search | Yes (library, in-process) | Yes (server, native) | Yes (Postgres extension: `<=>` cosine, `<#>` inner product, `<->` L2) |
| Metadata filtering | None built-in — must hand-roll an external ID→metadata store | Strong: indexed "payload" fields, rich filter DSL | Native SQL `WHERE` — arbitrary combinations, joins with other tables for free |
| Persistence | Manual (save/load index file yourself) | Built-in (WAL + snapshots) | Built-in (it's Postgres — WAL, standard backup tooling) |
| Local development | Trivial (`pip install faiss-cpu`), but no server/API | `docker run qdrant/qdrant` | Already scaffolded in this repo's `docker-compose.yml` |
| Production deployment | Requires building your own service around it | Docker image, mature single-node story; clustering exists but adds ops | Same Postgres you already know how to run/back up (already `docker-compose.yml`-scaffolded here) |
| Docker support | N/A (library) | First-class official image | First-class official image (`pgvector/pgvector:pg16`, already referenced) |
| Python integration | Native (it's a Python/C++ library) | Official `qdrant-client` | `psycopg`/`SQLAlchemy` + `pgvector` Python adapter — same stack already used for `jsonschema`-style tooling |
| Spring Boot / Java integration | No maintained JVM binding in common use — would force a Python service in front of it regardless | Java client exists, less commonly paired with Spring Data | **Spring Data JPA already works today against this exact Postgres instance** if the backend ever needs direct access — same JDBC/Hibernate stack, just a second datasource |
| REST API | None (must build one) | Built-in REST + gRPC | None built-in — but trivial to expose through the existing Spring Boot or a thin FastAPI layer, consistent with option in §3 |
| Scalability (this project's realistic scale) | Fine in-process up to the size that fits in one process's RAM | Purpose-built to shard past single-node RAM | Comfortably handles the realistic scale here: **102 vectors for one chapter today**; even a full multi-book, multi-subject Tunisian Bac corpus is realistically low thousands to tens of thousands of chunks — far inside single-node Postgres+pgvector capability |
| Incremental upsert | Manual (rebuild or use `IDMap` + remove/add, fragile) | Native `upsert` | Native SQL `INSERT ... ON CONFLICT ... DO UPDATE` |
| Deletion | Manual, index-rebuild-prone | Native | Native SQL `DELETE`/soft-delete via a status column |
| Collection/index management | None — you are the index manager | Native collections API | SQL tables + `CREATE INDEX` (HNSW/IVFFlat) |
| Operational complexity | Lowest to start, highest to operate correctly at scale (no server, no persistence, no filtering — all hand-built) | Medium (one more service, one more thing to monitor/back up) | Low if Postgres operations are already familiar (they will be, since MySQL operations already are, and Postgres is already scaffolded) — but does mean **two different relational database engines** (MySQL for Human Review, Postgres for vectors) in the same project |
| Memory/storage for 1024-dim vectors | In-RAM only unless hand-persisted; 1024×4 bytes ≈ 4 KB/vector, trivial at this project's scale | Disk-backed, indexed | Disk-backed (regular Postgres storage), same trivial per-vector footprint |
| Compatibility with 1024-dim BGE-M3 | Yes (arbitrary fixed dim) | Yes (dimension set per collection) | Yes (`vector(1024)` column type) |
| Future multi-chapter corpus | Requires a metadata layer built from scratch first | Native payload filters handle it directly | Native `WHERE chapter_id = ...` handles it directly |
| Future RAG architecture | Needs a wrapping service anyway | Fits directly | Fits directly, and can share a transaction/connection with other relational data if ever useful |
| Backup/recovery | Manual (you own the index file) | Snapshot API | Standard `pg_dump`/`pg_basebackup` — well-understood, no new tooling to learn |
| Observability | None built-in | Built-in metrics endpoint | Standard Postgres observability (`pg_stat_*`) — same tooling as any other Postgres instance |

---

## 3. Recommended Vector DB: **pgvector (Postgres)**

Justification, on the merits (not "because it's already scaffolded" alone,
though that is one real factor among several):

1. **Matches the project's actual scale.** 102 vectors today, realistically
   low-thousands at full multi-chapter/multi-book scale. Qdrant's
   distributed-scale strengths solve a problem this project doesn't have
   yet; FAISS's raw speed solves a problem (huge in-RAM corpora with no
   persistence/filtering need) this project also doesn't have.
2. **Matches the explicit MVP constraint** ("should not require an
   expensive managed cloud service... practical local-first architecture").
   A single self-hosted Postgres+pgvector container satisfies this
   directly.
3. **Native metadata filtering via plain SQL** is exactly what
   `filter_metadata`'s fields (§5) need — no separate filter-index
   configuration step, no DSL to learn, and it composes for free with any
   future relational metadata (e.g. a future `chapters` or `documents`
   table) without a cross-database join.
4. **Already a real, committed decision in this repo** — the
   `docker-compose.yml` skeleton and `.env.example`'s `PostgreSQL (+
   pgvector)` block predate this design task. Recommending something else
   would mean discarding existing project planning without a technical
   reason strong enough to justify it, and none of Qdrant's advantages
   (distributed scale, a dedicated payload-filter engine) are load-bearing
   at this project's real size.
5. **Reduces net-new operational surface.** The project already runs one
   relational database (MySQL) for the backend. Adding Postgres is "a
   second familiar kind of thing" (SQL, standard backup tools, JDBC-
   compatible if ever needed from Spring Boot) rather than "a wholly new
   category of infrastructure" (Qdrant) on top of an already-multi-service
   project (Spring Boot + MySQL + Angular + Python pipeline).

**Named limitation, reported honestly**: this does mean **two different
database engines** in one project (MySQL for `FigureKnowledgeReview`,
Postgres for vectors) rather than one. This was already true in the
project's own plan before this task (see §1.5) — not a new cost introduced
by this recommendation — but is worth the team re-confirming rather than
silently inheriting.

---

## 4. Where the Vector DB fits in the architecture

Three real options, given what's actually in the repo (not two — the
originally-planned `ai-service` is a genuine third option, see §1.5):

**A. Python pipeline → Vector DB directly.**
The existing `data/src/` pipeline (unchanged) gains one more phase: a
Python import/sync script (not yet written) that reads
`manifest.json`/`records.json`/`vectors.npy` and upserts rows into
Postgres/pgvector, using the exact same chapter-generic, `config.py`-driven
conventions as every phase from Normalization through Embeddings.

**B. Python pipeline → Spring Boot → Vector DB.**
The Java backend would gain a second `DataSource` (Postgres) and own the
import/sync + future query logic in Java.

**C. Python pipeline → Vector DB ← `ai-service` (FastAPI) → Spring Boot / Angular.**
The originally-planned shape: a dedicated Python RAG service (`ai-service`)
owns both ingestion-to-pgvector and query-time retrieval + the Claude call,
and the Java backend calls *it*, not Postgres directly.

**Recommendation for this phase: A now, with C as the intended eventual
runtime shape, B not recommended.**

- The import/sync step should be written as a `data/src/` Python script
  (Option A), because that is where the *real, working* pipeline lives
  today, and it can reuse `config.py`'s path helpers, the manifest schema,
  and the project's established validation/testing conventions immediately
  — with zero dependency on `ai-service` (currently just two empty
  folders) being built first.
- **B is not recommended**: it would duplicate Python's `sentence-
  transformers` model-loading/embedding-input logic in Java just to
  *query* the Vector DB (a future user question still needs to be embedded
  with the *same* model before searching), which either means running
  Python from Java anyway or reimplementing embedding inference in Java —
  neither is justified when a Python-owned retrieval layer (C) already
  matches the project's own original plan.
- **C remains the right eventual home for query-time retrieval** (embed
  the question, search pgvector, apply filters, hand chunk_ids back) since
  it matches `ai-service/README.md`'s own stated intent ("RAG + connexion
  Claude... service RAG + endpoint appelé par le backend") and keeps the
  Claude/embedding-model dependency inside Python where it already lives.
  Spring Boot's role stays what it already is: relational app data
  (`FigureKnowledgeReview` today) and being the thing Angular actually
  talks to — it would call `ai-service` as a downstream retrieval API when
  that phase is built, not reimplement retrieval itself.
- This is explicitly **not** decided by this document to the level of
  "start building `ai-service` next" — that's a call for the team to make
  when the retrieval/RAG phase actually starts (out of scope here per the
  task's boundaries). This section only establishes that the *import*
  step (in scope for "next implementation step", §15) belongs in
  `data/src/` regardless of that later decision.

---

## 5. Collection / index design

Compared:

- **Option A — one collection per chapter.** Rejected as the *storage*
  granularity: it would force a fan-out query (or manual UNION) across N
  tables/collections the moment multi-chapter retrieval is needed (item 5
  of the stated objectives), which pgvector has no native way to do
  efficiently — SQL has no "search across N tables" primitive.
- **Option B — one collection per book.** Same problem, one level up —
  rejected for the same reason, and doesn't even align with this project's
  own chapter-scoped output convention (`data/output/<chapter_id>/...`).
- **Option C — one global collection/table with metadata filters.**
  **Recommended**, with one necessary refinement: pgvector requires a
  *fixed* vector column dimension per table (`vector(1024)` is a real,
  fixed-width Postgres column type) — **it cannot store 1024-dim and
  768-dim vectors in the same column**, so "one global collection" must
  really mean **one table per embedding dimension**, e.g.
  `embeddings_1024`, with `chapter_id` (and `embedding_model` /
  `model_revision`) as regular filter columns *within* that table — not
  one table per chapter and not one table per model. A future
  differently-dimensioned model gets its own new table
  (`embeddings_768`, etc. — see §7), never a column added to an existing
  one.

Recommended shape (illustrative, not a migration to run yet):

```sql
CREATE TABLE embeddings_1024 (
    embedding_id       text PRIMARY KEY,   -- reused verbatim from records.json
    chunk_id           text NOT NULL,
    chapter_id         text NOT NULL,
    embedding_model    text NOT NULL,
    model_revision     text NOT NULL,
    content_hash       text NOT NULL,       -- 'sha256:<64 hex>', drift/cache key
    pipeline_version   text NOT NULL,
    normalization_strategy text NOT NULL,
    status             text NOT NULL DEFAULT 'active',  -- 'active' | 'stale'
    filter_metadata    jsonb NOT NULL,       -- section_id/subsection_id/topics/concepts/item_types/content_role/pdf_pages/has_uncertain_content, copied verbatim
    created_at         timestamptz NOT NULL,
    imported_at        timestamptz NOT NULL DEFAULT now(),
    embedding           vector(1024) NOT NULL
);

CREATE INDEX ON embeddings_1024 (chapter_id);
CREATE INDEX ON embeddings_1024 (embedding_model, model_revision);
CREATE INDEX ON embeddings_1024 USING gin (filter_metadata);
CREATE INDEX ON embeddings_1024 USING hnsw (embedding vector_cosine_ops);
```

`(chunk_id, embedding_model, model_revision)` is a natural unique
constraint mirroring `embedding_id`'s own derivation — enforced via
`embedding_id` being the primary key (it's already deterministically
derived from exactly those three values, per `embedding_design.md` §4/§8),
so no separate uniqueness constraint duplicates that logic.

Similarity metric, distance function, normalization assumption: see §8
below — `vector_cosine_ops` (the `<=>` operator) is the recommended index
type, consistent with the table above.

---

## 6. Metadata payload design

**A. Required for retrieval (identity + positional integrity)** — carried
on every row, never optional: `embedding_id`, `chunk_id`, `chapter_id`,
`embedding_model`, `model_revision`, `embedding_dimension` (implicit via
table choice, §7), `normalization_strategy`, `content_hash`,
`pipeline_version`, `created_at`, `status`. These are exactly the
non-`filter_metadata` fields already required by
`embedding_manifest.schema.json`'s `EmbeddingRecord` — reused verbatim,
not re-derived.

**B. Useful for filtering** — exactly `records.json`'s existing
`filter_metadata` object, copied verbatim, never re-derived or expanded
with invented fields: `section_id`, `subsection_id`, `topics[]`,
`concepts[]`, `item_types[]`, `content_role`, `pdf_pages[]`,
`has_uncertain_content`. (A future `document_id`/`subject`/`level` filter,
useful once a second book/subject exists, is **not** invented here because
it does not exist in the current chunk-level `filter_metadata` contract —
it lives only on the *normalized* knowledge document object today. If
multi-book retrieval becomes a real near-term need, that's a change to
`knowledge_chunk.schema.json`/`embedding_manifest.schema.json` upstream
first, propagated down through chunking → embedding → import, not
something the Vector DB layer should patch over on its own.)

**C. Never duplicated — resolved via `chunk_id`** back to
`data/output/<chapter_id>/chunks/knowledge_chunks.json`: the chunk's own
`text`, `figure_refs[]` (full objects), `related_chunk_ids[]`,
`source_item_ids[]`, `generation_methods`, `part_index`/`part_count`,
`review_status`. This continues the boundary `embed_knowledge.py` already
drew (`records.json` itself never carries `text` either) rather than
introducing a new one. **The Vector DB row is a pointer plus a filter
index, never a second copy of the knowledge content.**

```
vector  →  chunk_id  →  data/output/<chapter_id>/chunks/knowledge_chunks.json  (authoritative)
```

---

## 7. Identity and synchronization

Reused verbatim from the embedding layer, never re-derived: `embedding_id`,
`chunk_id`, `content_hash`, `embedding_model`, `model_revision`,
`pipeline_version`. **Never vector floating-point equality** — this
mirrors `embed_knowledge.py`'s own caching rule (`embedding_design.md` §5)
one layer up.

| Event | Synchronization behavior |
|---|---|
| 1. New chunk created | Its (already-computed, per Phase 11) embedding row is inserted (`INSERT ... ON CONFLICT (embedding_id) DO NOTHING` — idempotent). |
| 2. Chunk changes | Phase 11 already produces a new `content_hash` + (same `embedding_id`, since it's chunk_id+model+revision-derived) row with fresh values. Import: `INSERT ... ON CONFLICT (embedding_id) DO UPDATE SET ... WHERE embeddings_1024.content_hash IS DISTINCT FROM excluded.content_hash` — a no-op if unchanged, an update if the hash moved. |
| 3. Chunk deleted | Mirrors Phase 11's own stale-record rule (never silently delete): row's `status` is set to `'stale'`, row itself is kept. Default retrieval queries filter `WHERE status = 'active'`. |
| 4. Embedding changes (re-run with same model/revision, different vector due to a chunk edit) | Same as row 2 — `embedding_id` is unchanged (content_hash changes; identity doesn't), so this is an `UPDATE`, not a new row. |
| 5. Embedding model changes | New `embedding_model`/`model_revision` → a genuinely different `embedding_id` (per `embedding_design.md` §4's derivation) → a **new row**, inserted into the table matching *that* model's dimension (§stays in `embeddings_1024` only if the new model is also 1024-dim; otherwise §8 applies). The old model's rows are untouched. |
| 6. Chapter reprocessed | Re-running the Phase 11 pipeline (already idempotent/cached) followed by re-running the import step is itself idempotent — unchanged chunks produce unchanged `embedding_id`+`content_hash` pairs, which are no-ops on `ON CONFLICT`. |
| 7. Chapter "published" again | No separate concept exists yet at the embedding layer (no `published`/`draft` status in `embedding_manifest.schema.json`) — if this becomes a real requirement, it should be added as a manifest-level field upstream first, not invented ad hoc in the Vector DB's own schema. |
| 8. Stale embedding exists | Already covered by row 3 — `status='stale'` rows persist, are importable/inspectable, and are excluded from default retrieval by the query layer's own filter, never by deleting data. |

**Idempotent by construction**: re-running the import step against an
unchanged `records.json`/`vectors.npy` performs zero writes (every
`ON CONFLICT` branch is a no-op), matching the exact "rerun without
unnecessary recomputation" discipline already proven in Phase 11's own
`test_rerun_with_no_changes_calls_backend_zero_times` /
`test_rerun_on_real_chapter_1_chunks_is_fully_cached` tests.

---

## 8. Multiple embedding models

BAAI/bge-m3 → 1024 dimensions today. A future model with a different
dimension (e.g. a hypothetical 768-dim model) **cannot share a vector
column** with 1024-dim vectors — pgvector's `vector(N)` type is fixed-width
by design, and there is no meaningful way to compare vectors of different
dimension for similarity in the first place (they aren't in the same
vector space).

**Design rule: isolation by dimension, not by mere model/version label.**

- Same dimension, different model name or revision → **same table**,
  distinguished by the `embedding_model`/`model_revision` filter columns
  (§5's schema already includes these) — a query must always pin a
  specific `(embedding_model, model_revision)` pair (§9) so scores are
  never compared across incompatible vector spaces even when the raw
  column type happens to match.
- Different dimension → **a new table** (`embeddings_768`, etc.), created
  once, when that model is actually adopted — never a schema migration
  that widens/repurposes an existing dimension's table.

This mirrors `embed_knowledge.py`'s own `_embedding_model_id()` design
(config.py) exactly one layer up: that function already namespaces the
*file-based* output directory by model+revision for precisely this reason
(a single manifest can only hold one `(model, revision)` pair) — the
Vector DB layer inherits the same discipline, adapted to SQL's own
constraint (fixed column width forces the dimension split; model/revision
alone doesn't need a table split since SQL columns can hold that as data).

---

## 9. Similarity metric

Given: BGE-M3 vectors are **L2-normalized before storage** (confirmed
directly — every real vector's norm measures 1.0, §1.1). For unit vectors
`a`, `b`:

- **Cosine similarity** = `(a · b) / (‖a‖ ‖b‖)` = `a · b` when `‖a‖ = ‖b‖ = 1`
  — i.e. cosine similarity and the raw dot product/inner product are
  **numerically identical** for L2-normalized vectors.
- **Euclidean (L2) distance**: `‖a − b‖² = ‖a‖² + ‖b‖² − 2(a·b) = 2 − 2(a·b)`
  for unit vectors — a strictly monotonically *decreasing* function of the
  dot product. Ranking by L2 distance (ascending) therefore produces the
  **exact same top-K ordering** as ranking by cosine similarity or inner
  product (descending) on this normalized corpus.

**Recommendation: cosine similarity** (pgvector's `vector_cosine_ops`,
operator `<=>`), despite the mathematical equivalence to inner product for
today's data, because:

1. It is self-documenting — a future maintainer reading `<=>` doesn't need
   to separately know "and by the way, these vectors happen to already be
   unit-norm" to trust the result is correct.
2. It is robust to any future vector that is *not* perfectly unit-norm —
   floating-point drift, or a future model whose `normalization_strategy`
   is legitimately `"none"` (a real enum value in
   `embedding_manifest.schema.json`) — where inner product alone (`<#>`)
   would silently produce wrong rankings, but cosine still normalizes at
   query time.
3. It matches the fact that `normalization_strategy` is stored **per
   record**, not assumed globally — cosine similarity is the metric that
   stays correct regardless of what that field says for a given row,
   which inner product is not.

---

## 10. Retrieval design (contract only — not implemented)

```
search(query_vector, top_k, filters) -> list[RetrievalResult]
```

**Required inputs**: `query_vector` (float array, dimension must match the
target table, i.e. the table selection itself is part of picking which
model produced the query embedding — never mixed across tables/dimensions,
§8), `embedding_model` + `model_revision` (**required**, not optional —
comparing scores across different models'/revisions' vector spaces is
meaningless, so a query must always pin exactly one), `top_k`.

**Optional filters** (drawn only from real, existing `filter_metadata`
fields, §6.B — nothing invented): `chapter_id`, `section_id`,
`subsection_id`, `topics` (any-of), `concepts` (any-of), `item_types`
(any-of), `content_role`, `has_uncertain_content`, `status` (defaulting to
`'active'` only — never surfacing `'stale'` rows unless explicitly asked
for), `min_score` (a similarity-score floor, applied after the ANN search).

**Returned fields per result**: `chunk_id` (the resolution key back to the
authoritative chunk, §6.C), `embedding_id`, `chapter_id`, `filter_metadata`
(as stored, §6.B — enough for a caller to display/filter further without a
second lookup), `embedding_model`, `model_revision`, and `score` (cosine
similarity, §9 — **never the raw chunk text**, which the caller resolves
itself via `chunk_id → knowledge_chunks.json`, keeping the Vector DB
non-authoritative per §6).

**Score semantics**: cosine similarity in `[-1, 1]`, practically close to
`[0, 1]` for this domain (text embeddings rarely produce strongly negative
similarity for related content) — documented as an approximate range, not
guaranteed bounds, since it depends on the embedding model's own behavior.

This section defines the shape of the contract only — no query execution,
no embedding-a-question step, and no ranking/re-ranking logic exists yet.
That is explicitly the next phase (Semantic Search / RAG), out of scope
here.

---

## 11. Persistence and deployment

**Development**: the `docker-compose.yml` skeleton already at the repo
root (`db` service, `pgvector/pgvector:pg16`, reading `.env`) is the
intended local dev path — its "Phase 2" (per its own comment) is exactly
"init pgvector, volumes, healthcheck", i.e. enabling `CREATE EXTENSION
vector`, adding a named volume for the Postgres data directory, and a
healthcheck (`pg_isready`). Nothing about this design changes that
skeleton's already-chosen shape — it fills in what its own comment already
says is coming next.

**Production**: same image, self-hosted (the project's own instruction:
avoid a managed cloud vector DB for the MVP), with:
- a persistent named volume (already the standard Docker pattern the
  skeleton anticipates),
- scheduled `pg_dump`/`pg_basebackup` backups (standard, well-understood
  tooling — no new backup mechanism to learn beyond what any Postgres
  deployment already needs),
- the same `.env`-driven credential pattern already used for `POSTGRES_*`
  variables (never hardcoded, never committed — already gitignored via the
  existing `.env`/`*.env.local` rules).

No managed cloud vector DB (e.g. a hosted Qdrant Cloud/Pinecone-style
service) is recommended for the MVP, consistent with the task's own
constraint and with the realistic scale established in §3.

---

## 12. Synchronization / import strategy

The Vector DB **never regenerates embeddings** — it only ever consumes the
three existing artifacts (`vectors.npy`, `records.json`, `manifest.json`)
that Phase 11 already produces and validates.

- **Initial import**: for a given `(chapter_id, model_id)` directory, read
  `manifest.json` (confirm `vector_dtype="float32"`, dimension, and that
  `validation_report.json` — if present — already passed, refusing import
  otherwise, mirroring Phase 11's own "fail clearly, never silently
  continue with corrupted data" discipline), then `records.json` +
  `vectors.npy` together (`records[i] ↔ vectors[i]`, the exact positional
  contract Phase 11 already validates), and upsert each row keyed by
  `embedding_id` (§7).
- **Incremental synchronization**: re-run the same import; every
  `ON CONFLICT` branch (§7) makes it a no-op for unchanged rows, an
  `UPDATE` for changed `content_hash`, and an `INSERT` for genuinely new
  `embedding_id`s.
- **Re-indexing**: rebuilding the HNSW/IVFFlat ANN index is a Postgres-
  native operation (`REINDEX`/`CREATE INDEX CONCURRENTLY`) — orthogonal to
  data import, never requires re-embedding.
- **Model migration**: importing a new model's artifacts is just another
  import run targeting either the same table (same dimension, §8) or a new
  one (different dimension) — the *old* model's rows are never touched,
  matching Phase 11's own "different model/revision never overwrites"
  rule one layer up.
- **Chapter publication**: importing a new chapter's directory is an
  independent import run (`chapter_id` is just another row value, not a
  separate table, §5) — no cross-chapter effect.
- **Rollback**: since `content_hash`/`embedding_id` identity is preserved
  and stale rows are kept (never deleted, §7), rolling back to a prior
  chunking/embedding run is a matter of re-importing that prior run's
  artifacts (which restores the old `content_hash` values via the same
  `ON CONFLICT DO UPDATE` path) — no destructive operation is required in
  the normal case. A hard rollback (removing rows introduced by a bad
  import entirely) would use `imported_at`/`created_at` as the audit trail
  already present in the schema (§5).

None of this is implemented in this phase — it is the specification the
next implementation step (§15) will follow.

---

## 13. Testing strategy (designed, not implemented)

Following this project's own established convention (`unittest`, synthetic
fixtures for unit coverage, exactly one real-Chapter-1 fixture reserved for
regression, machine-readable validation reports — see
`test_embeddings.py`), a future `test_vector_db_sync.py` would cover:

1. Vector dimension validation (reject a vector whose length doesn't match
   the target table).
2. Model/version compatibility (reject/route correctly when
   `embedding_model`/`model_revision`/dimension combinations differ).
3. Metadata mapping (`filter_metadata` round-trips exactly, no field
   dropped or invented).
4. `chunk_id` mapping (every imported row's `chunk_id` resolves back to a
   real chunk in the source `knowledge_chunks.json` — synthetic fixture:
   an intentionally dangling `chunk_id` should be caught, not imported).
5. `embedding_id` mapping (identity derivation matches Phase 11's own
   `build_embedding_id`, reused not reimplemented).
6. Initial import (empty table → N rows, exact vector-count match against
   `manifest.json`'s own `vector_count`).
7. Idempotent re-import (same artifacts twice → zero additional rows,
   zero updates — assert via `imported_at` unchanged, not just row count).
8. Changed chunk (different `content_hash`, same `embedding_id` → an
   `UPDATE`, verified via `imported_at` advancing and vector actually
   differing).
9. Deleted chunk (`chunk_id` absent from a later `records.json` →
   `status='stale'`, row retained, excluded from default search filters).
10. Stale embedding (a row already `'stale'` remains importable/inspectable
    and is never silently dropped by a later import run).
11. Metadata filtering (section/subsection/topic/concept/item_type/
    content_role/has_uncertain_content filters each independently verified
    against a synthetic multi-row fixture).
12. Similarity search (synthetic vectors with a known, hand-computed
    cosine ranking — never asserting exact floating-point score equality
    across environments, matching the discipline already used for the
    real embedding model in `test_embeddings.py`).
13. Chapter filtering (synthetic 2-chapter fixture — a query scoped to
    chapter A never returns chapter B's rows).
14. Section filtering (synthetic fixture, same pattern).
15. Multiple chapters (synthetic fixture — the table design in §5 is
    exercised precisely because it must NOT need one table per chapter).
16. Multiple models (synthetic fixture spanning two `(model, revision)`
    pairs in the same table, plus one synthetic differently-dimensioned
    model routed to a second table — §8's isolation rule verified
    directly).
17. Empty collection (search against a table with zero rows returns an
    empty result, not an error).
18. Duplicate IDs (attempting to import two rows with the same
    `embedding_id` but different vectors — must be rejected/merged per the
    `ON CONFLICT` rule, never silently duplicated).
19. Corrupted/missing embedding artifacts (missing `vectors.npy`,
    `records.json`/`vectors.npy` row-count mismatch, a `manifest.json`
    whose own `validation_report.json` shows failures — every case must
    refuse import with a clear error, never partially import).

**Tests must not depend exclusively on Chapter 1** — per items 15/16 above,
synthetic multi-chapter/multi-model fixtures are required for genuine
coverage of the collection design (§5) and multi-model isolation (§8),
since the real corpus is single-chapter/single-model today. **Chapter 1
remains the one real regression fixture** (its actual 102-row artifact,
imported end-to-end and re-validated), exactly mirroring
`TestChapter1Regression`'s role in `test_embeddings.py`.

---

## 14. Security and application boundaries

```
Angular  →  Spring Boot (or future ai-service)  →  Vector DB
```

- **Angular must never talk to the Vector DB directly** — same boundary
  already implicitly enforced today (Angular never talks to MySQL
  directly either; it only ever calls the Spring Boot REST API through
  the dev proxy). No new precedent is being set here, only continued.
- **Authentication/authorization boundary**: sits at whichever
  service-layer component ends up owning retrieval (§4 — Spring Boot or
  `ai-service`), not inside the Vector DB itself. Today's backend has **no
  Spring Security dependency at all** (confirmed, §1.4) — so this is a gap
  that already exists for the *current* `FigureKnowledgeReview` API, not
  something newly introduced by adding a Vector DB. Worth flagging to the
  team as a pre-existing gap rather than solving it here (out of scope).
- **The Vector DB (Postgres/pgvector) should never be publicly exposed** —
  it should sit on the same private/internal network as MySQL does today,
  reachable only from the backend/`ai-service` process, never from the
  public internet or directly from a browser.
- **Secrets/configuration**: `POSTGRES_*` credentials follow the exact
  pattern already established for MySQL/JWT/Anthropic credentials in
  `.env.example` / `.gitignore` (`.env` and `*.env.local` already
  gitignored) — no new secrets-handling mechanism needs inventing.

---

## 15. Operational considerations (MVP-appropriate, not over-built)

- **Health check**: `SELECT 1` (Postgres reachable) plus a per-chapter
  sanity check — `SELECT count(*) FROM embeddings_1024 WHERE chapter_id =
  ...` compared against that chapter's own `manifest.json.vector_count` —
  reusing data that already exists rather than inventing a new health
  concept.
- **Collection/index status**: row count per `(chapter_id, embedding_model,
  model_revision)` combination, directly queryable via the filter columns
  already in the schema (§5) — no separate status table needed at this
  scale.
- **Synchronization status / drift detection**: compare the *stored* rows'
  `content_hash` set for a given chapter+model against the *current*
  `manifest.json.source_chunks_hash` — reusing the hash Phase 11 already
  computes and stores, never re-hashing independently.
- **Logging**: the import step should log exactly the same shape of
  progress info Phase 11's own pipeline already logs (total rows, reused/
  no-op count, inserted count, updated count, stale count) — consistent
  operator experience across phases.
- **Backup/recovery, re-indexing**: standard Postgres tooling (§11/§12) —
  deliberately not a custom mechanism.
- **Monitoring**: standard `pg_stat_*`/container-level monitoring — no
  bespoke metrics system justified at this scale.

Kept deliberately simple: a single-node Postgres instance with a handful of
tables is the right amount of infrastructure for a project whose real
current corpus is 102 vectors, not a distributed system.

---

## Final report

1. **Actual current embedding/chunk architecture**: 102 real Chapter 1
   chunks (`knowledge_chunk.schema.json`-conformant), 102 real
   `bge-m3-5617a9f61b02` embeddings (1024-dim, float32, L2-normalized —
   norms measured, not assumed), manifest/records/vectors triple validated
   by Phase 11's own tooling. Backend is Spring Boot 3.3.4/Java 17/MySQL
   with exactly one entity (`FigureKnowledgeReview`) and zero
   knowledge/chunk/embedding entities — all knowledge data is file-owned by
   the Python pipeline. **A pre-existing project decision already targets
   pgvector** (`docker-compose.yml`, `.env.example`, `ai-service/`'s
   last-committed README) via a not-yet-built `ai-service` FastAPI layer —
   reported transparently in §1.5 rather than silently assumed or ignored.
2. **FAISS vs Qdrant vs pgvector**: compared in full in §2 across 19
   criteria; none of Qdrant's distributed-scale strengths or FAISS's raw
   in-process speed are load-bearing at this project's real (currently
   102-vector, realistically low-thousands at full scale) size.
3. **Recommended Vector DB**: **pgvector** (§3) — matches real scale, MVP/
   local-first constraint, native SQL metadata filtering, and continues
   rather than discards the project's own pre-existing infrastructure
   decision.
4. **Recommended collection/index strategy**: one table **per embedding
   dimension** (e.g. `embeddings_1024`), `chapter_id`/`embedding_model`/
   `model_revision` as filter columns within it — not one table per
   chapter or per book (§5).
5. **Vector metric**: cosine similarity (`vector_cosine_ops`, `<=>`) —
   numerically equivalent to inner product for today's L2-normalized
   vectors, but robust to any future non-unit-norm vector (§9).
6. **Metadata/payload structure**: required-identity fields + verbatim
   `filter_metadata` reused from `records.json`; chunk `text`/
   `figure_refs`/`related_chunk_ids`/etc. never duplicated, resolved via
   `chunk_id` (§6).
7. **Identity/synchronization strategy**: `embedding_id`/`chunk_id`/
   `content_hash`/model+revision reused verbatim; `ON CONFLICT`-based
   idempotent upsert; deletions become `status='stale'`, never a hard
   delete (§7).
8. **Multi-model strategy**: isolate by **dimension** (separate tables),
   distinguish same-dimension models/revisions by filter column, never mix
   incompatible vector spaces in one query (§8).
9. **Import strategy**: read-only consumption of
   `manifest.json`/`records.json`/`vectors.npy`, never regenerates
   embeddings, idempotent by `embedding_id` (§12).
10. **Future retrieval contract**: `search(query_vector, top_k, filters)`
    with `embedding_model`/`model_revision` required (never optional),
    returns `chunk_id` + metadata + score, never raw chunk text (§10) —
    contract only, not implemented.
11. **Development deployment**: the existing (currently dormant)
    `docker-compose.yml` `db` service, completing its own stated "Phase 2"
    (§11).
12. **Production deployment**: same self-hosted image, persistent volume,
    standard `pg_dump` backups — no managed cloud service for the MVP
    (§11).
13. **Testing strategy**: 19 categories (§13), synthetic fixtures for
    multi-chapter/multi-model coverage, Chapter 1's real artifact as the
    one regression fixture — mirroring `test_embeddings.py`'s own proven
    pattern.
14. **Risks and limitations**:
    - Two relational database engines (MySQL + Postgres) to operate,
      rather than one — a real, pre-existing cost (§1.5/§3), not newly
      introduced here.
    - No importer code exists yet — this entire design is unimplemented.
    - The backend has no Spring Security/auth layer today (§14) — a
      pre-existing gap this design doesn't create but doesn't solve
      either.
    - The `ai-service` scaffold is empty and its own README was just
      deleted in the working tree — the team's actual intent for who owns
      runtime retrieval (§4, Option C) is still genuinely open and should
      be confirmed before that later phase starts, not assumed from a
      partially-abandoned original plan.
    - HNSW index build cost grows with corpus size — irrelevant at 102
      rows, worth revisiting only if the corpus reaches the point where
      index build time becomes noticeable (not predictable from today's
      data).
15. **Exact next implementation step**: implement the Phase 12
    *import/sync* script as a new `data/src/` module (e.g.
    `sync_embeddings_to_vector_db.py`), following the exact conventions of
    every prior phase — chapter-generic CLI, `config.py` path helpers, a
    machine-readable validation report, and a `unittest` suite covering
    §13's 19 categories — targeting the `docker-compose.yml` skeleton's
    completed "Phase 2" (pgvector extension + schema init + healthcheck).
    This is the next task to scope, **not started in this phase** per the
    explicit "design only, stop after this phase" instruction.
