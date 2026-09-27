# Semantic Search design (Phase 13 — design only, nothing implemented)

Design proposal, not yet implemented. Describes a read-only query layer on
top of the existing `embeddings_1024` PostgreSQL+pgvector table (Phase 12)
and the existing embedding pipeline (Phase 11). No code is written in this
phase — see `vector_db_design.md` and `embedding_design.md` for the two
prior approved designs this one builds directly on, and does not
contradict.

Scope, restated precisely: **query text → BGE-M3 query embedding →
PostgreSQL/pgvector cosine similarity → ranked chunk_ids + scores +
metadata + resolved text.** No RAG, no LLM answer generation, no FastAPI,
no chat endpoint, no Spring Boot search endpoint, no frontend integration.
Those are explicitly out of scope and deferred to a later phase (see §13's
"boundary" section).

---

## 1. Inspected repository state (evidence this design is built on)

- **`embeddings_1024` table** (`data/schema/vector_db_schema.sql`,
  confirmed live via `\d embeddings_1024`): columns `embedding_id` (PK),
  `chunk_id`, `chapter_id`, `embedding_model`, `model_revision`,
  `content_hash`, `pipeline_version`, `normalization_strategy`, `status`
  (`active`/`stale`), `filter_metadata` (jsonb), `created_at`,
  `imported_at`, `embedding` (`vector(1024)`). Indexes already present:
  `embeddings_1024_chapter_id_idx`, `embeddings_1024_model_revision_idx`,
  `embeddings_1024_status_idx`, `embeddings_1024_filter_metadata_gin_idx`,
  and — most relevant here — **`embeddings_1024_embedding_cosine_idx`**
  (`USING hnsw (embedding vector_cosine_ops)`), built in Phase 12
  specifically to "prepare future retrieval only" (its own comment in
  `vector_db_schema.sql`). This phase is that future retrieval.
- **`filter_metadata`'s real shape** (confirmed against live rows and
  `_filter_metadata()` in `embed_knowledge.py`): exactly `section_id`,
  `subsection_id`, `topics` (array), `concepts` (array), `item_types`
  (array), `content_role` (`"statement"`/`"correction"`), `pdf_pages`
  (array of int), `has_uncertain_content` (bool). No other fields exist —
  confirmed both from the schema and from live Chapter 1 rows.
  `filter_metadata` deliberately does **not** include `text`,
  `figure_refs`, or `related_chunk_ids` — those stay chunk-file-only.
- **`SentenceTransformerBackend`** (`embed_knowledge.py:96`): already the
  exact reusable query-embedding mechanism — `backend([texts]) ->
  np.ndarray`, exposing `.dimension`, `.model_name`, `.model_revision`
  after construction. Constructed via
  `SentenceTransformerBackend(model_name, model_revision, device)`. No
  second embedding implementation needs to exist; this phase's query
  embedding is a call to this exact same class with a one-item list.
- **`l2_normalize()`** (`embed_knowledge.py:198`): already the exact
  normalization function applied to stored vectors; reused as-is for the
  query vector (see §3 for why this doesn't change ranking but is applied
  anyway for consistency).
- **`build_embedding_id()`/`content_hash()`** (`embed_knowledge.py`): not
  needed here — those are identity/caching concerns for *stored*
  embeddings; a query embedding is transient, never persisted, never
  cached, never given an `embedding_id`.
- **`import_embeddings.table_dimension()`** (`import_embeddings.py:83`):
  already the exact reusable "introspect the real vector column width from
  Postgres itself" helper — reused as-is for the dimension-compatibility
  check in §3/§10, rather than re-deriving it.
- **Chapter-scoped chunk text** (`config.chunks_json(chapter_id)` →
  `data/output/<chapter_id>/chunks/knowledge_chunks.json`): the
  authoritative source for `chunk.text`, confirmed to be the one place
  `text` has ever lived across every phase (normalization → enrichment →
  relations → chunking → embedding → import all treat it as read-only,
  never copied into Postgres). This phase continues that same rule.
- **Config/CLI conventions** (`config.py`, `import_embeddings.py`,
  `validate_embeddings.py`): chapter-generic path helpers, plain-constant
  config (no settings framework), `argparse`-based CLI with a
  `--chapter-id` default (never mandatory), machine-readable JSON reports,
  `unittest`-only tests with injectable-backend fakes so no real model
  download is required for most tests. This design follows all of these
  unchanged.

Nothing here conflicts with `vector_db_design.md`'s own already-approved
§10 retrieval contract sketch (`search(query_vector, top_k, filters) ->
list[RetrievalResult]`, `embedding_model`/`model_revision` required,
`chunk_id`/`embedding_id`/`filter_metadata`/`score` returned, never raw
text) — this phase makes that sketch concrete.

---

## 2. Search contract

```
SearchRequest:
    query: str                          # required, non-empty after strip()
    chapter_id: str                     # required (see §12 for why global search is deliberately NOT this phase's default)
    top_k: int = config.SEARCH_DEFAULT_TOP_K   # validated 1..config.SEARCH_MAX_TOP_K
    embedding_model: str = config.EMBEDDING_MODEL_NAME       # optional override
    model_revision: str = config.EMBEDDING_MODEL_REVISION    # optional override
    filters: SearchFilters | None = None
```

```
SearchFilters (all optional; AND-combined with each other and with the
mandatory chapter_id/model/revision/status conditions):
    section_id: str | None
    subsection_id: str | None
    concepts: list[str] | None       # any-of match
    topics: list[str] | None         # any-of match
    item_types: list[str] | None     # any-of match
    content_role: str | None         # exact match ("statement"/"correction")
    pdf_pages: list[int] | None      # any-of match (page overlap)
    has_uncertain_content: bool | None
```

Every field name here is copied verbatim from the real, already-stored
`filter_metadata` shape (§1) — nothing invented, nothing renamed.

Processing order (matches the task's own 5-step list exactly):

1. **Validate the request** — non-empty query, `top_k` in range, filter
   keys/types recognized (§11's "invalid filters" case), `chapter_id`
   non-empty. All of this happens in Python, before any model load or DB
   connection — a malformed request must never reach pgvector.
2. **Generate a query embedding** using `SentenceTransformerBackend`
   constructed with the request's `embedding_model`/`model_revision`
   (defaulting to the current production model, §1).
3. **Verify dimension compatibility** — the backend's own `.dimension`
   (loaded from the real model) must equal `import_embeddings.
   table_dimension(conn, config.vector_table_name(dimension))`'s reported
   column width for the table this query would run against. A mismatch is
   a hard, clear failure (§10) — never a silent wrong-shape query.
4. **Perform cosine similarity search** in PostgreSQL/pgvector (§4) —
   never in Python.
5. **Return ranked chunks** (§7), with `text` resolved from the chapter's
   own `knowledge_chunks.json` (§7).

---

## 3. Query embedding strategy

Reuses `SentenceTransformerBackend` exactly as `import_embeddings.py` and
`embed_knowledge.py` already do — **no second embedding implementation**.
Concretely: construct `backend = SentenceTransformerBackend(model_name=
request.embedding_model, model_revision=request.model_revision, device=
...)`, then `raw_vector = backend([request.query])[0]`.

**Normalization**: apply `l2_normalize()` (the same function used for
stored vectors) to the query vector before sending it to Postgres. This is
worth being explicit about, because it is *not* mathematically required
for correct ranking: pgvector's `<=>` cosine operator already normalizes
both operands internally (cosine similarity is scale-invariant on both
sides), so ranking and the *relative* ordering of results would be
identical whether or not the query vector is pre-normalized. It's applied
anyway for two concrete reasons: (a) it matches every stored vector's own
`normalization_strategy = "l2"` convention, so a future person reading a
raw query vector never has to wonder whether it's normalized or not; (b)
it makes the returned score's absolute value (not just its ranking)
trustworthy as a genuine cosine similarity in a well-understood range,
rather than depending on incidental embedding-model output scale.

**Model/revision compatibility (the design's explicit, non-optional
handling of this)**: the query embedding is *always* generated with the
exact `(embedding_model, model_revision)` pair the search will filter
`embeddings_1024` by (§4) — never a different pair. There is no code path
that embeds a query with one model and searches vectors indexed under
another. See §10 for what happens when the requested pair has no indexed
rows for the target chapter.

**No document embeddings are ever regenerated by this phase.** This
module only ever calls the backend on the single query string; it never
touches `embed_knowledge.py`'s `run()`, never reads/writes
`vectors.npy`/`records.json`/`manifest.json`.

---

## 4. PostgreSQL/pgvector query strategy

The similarity computation happens entirely inside PostgreSQL — Python
never loads candidate vectors and never computes a dot product itself.
Conceptually:

```sql
SELECT
    chunk_id, chapter_id, filter_metadata, embedding_model, model_revision,
    1 - (embedding <=> %(query_vector)s) AS score
FROM embeddings_1024
WHERE chapter_id = %(chapter_id)s
  AND embedding_model = %(embedding_model)s
  AND model_revision = %(model_revision)s
  AND status = 'active'
  -- optional filter conditions appended here, see below
ORDER BY embedding <=> %(query_vector)s ASC, embedding_id ASC
LIMIT %(top_k)s
```

Notes on exactly why it's written this way:

- **`<=>` is pgvector's cosine *distance* operator** (`1 -
  cosine_similarity`), not similarity — ordering `ASC` on `<=>` is
  therefore ordering by similarity **descending** (most similar first),
  which is what "top-K" means here. The `1 - (...)` in the `SELECT` list
  is a trivial scalar transform of a value Postgres already computed,
  applied so the *returned* number is the intuitive "higher is better"
  cosine similarity (§9) — this is not "comparing vectors in Python", it's
  relabeling a scalar Postgres already produced.
- **`embedding_id ASC` as a secondary sort key**: real BGE-M3 output
  essentially never produces an exact tie, so this has no practical effect
  on production queries — but it makes ranking **deterministic** for
  hand-crafted synthetic test vectors that *can* tie exactly (task test
  item #14), without which two runs of the same test could observe
  Postgres return tied rows in a different (undefined) order.
- **`status = 'active'`** is always applied, never optional — a `'stale'`
  row (Phase 12's own never-delete convention) must never surface in
  search results, matching `vector_db_design.md` §7/§10's own rule.
- The HNSW index (`embeddings_1024_embedding_cosine_idx`) is reused
  as-is — no new index, no new index type, per the task's explicit
  instruction.

**Metadata filter translation** (only appended when the corresponding
`SearchFilters` field is provided):

| Filter field | JSONB shape | SQL strategy |
|---|---|---|
| `section_id` | scalar string/null | `filter_metadata->>'section_id' = %s` |
| `subsection_id` | scalar string/null | `filter_metadata->>'subsection_id' = %s` |
| `content_role` | scalar string | `filter_metadata->>'content_role' = %s` |
| `has_uncertain_content` | scalar bool | `(filter_metadata->>'has_uncertain_content')::boolean = %s` |
| `concepts` / `topics` / `item_types` (any-of) | JSONB array of strings | `filter_metadata->'concepts' ?\| %s` (pgvector-independent, plain jsonb "any of these strings is a top-level array element" operator — correct for string arrays) |
| `pdf_pages` (any-of) | JSONB array of integers | the `?\|` string-membership operator doesn't apply to a numeric array; strategy is `EXISTS (SELECT 1 FROM jsonb_array_elements_text(filter_metadata->'pdf_pages') p WHERE p::int = ANY(%s))` |

All filter conditions are **AND-combined** with each other and with the
mandatory `chapter_id`/`model`/`revision`/`status` conditions — they
narrow the *candidate set* before ranking; they never re-rank or
post-process the similarity order. Semantic similarity remains the sole
ranking mechanism, exactly as required.

---

## 5. Chapter isolation

`chapter_id` is a mandatory `WHERE` condition in every query this phase
issues — never a table name, never a code branch, never optional in this
phase's default contract (§12 discusses the *possibility* of dropping it
for a future global-search variant, without adopting it now). This is a
direct continuation of `embeddings_1024` already being one physical table
holding every chapter (`vector_db_design.md` §5) — search isolation is
free: it's the same `WHERE chapter_id = %s` the import layer already
relies on for its own per-chapter scoping.

---

## 6. Result contract

```
SearchResult:
    chunk_id: str
    chapter_id: str
    score: float                    # cosine similarity, see §9
    section_id: str | None
    subsection_id: str | None
    content_role: str
    pdf_pages: list[int]
    topics: list[str]
    concepts: list[str]
    item_types: list[str]
    has_uncertain_content: bool
    embedding_model: str
    model_revision: str
    text: str                       # resolved, see below -- NOT stored in Postgres
```

**Chunk text resolution strategy**: `embeddings_1024` deliberately never
stores `text` (§1, unchanged from Phase 11/12's own boundary). After the
SQL query returns its ranked `chunk_id`s, the search layer performs one
read of the chapter's own chunk artifact — `config.chunks_json(chapter_id)`
(the exact same helper `import_embeddings.py`/`validate_embeddings.py`
already use) — builds a `{chunk_id: chunk}` lookup **once per search
call**, and hydrates `text` (and nothing else the chunk file has that
`filter_metadata` doesn't already surface — no need to also re-fetch
`section_id`/`pdf_pages`/etc, since those already came back from Postgres
verbatim via `filter_metadata`). This keeps Postgres exactly as
non-authoritative as `vector_db_design.md` §6 already established — the
DB is a ranked-pointer index; the chunks file remains the one and only
source of prose content.

**Missing chunk artifact** (a `chunk_id` the query returns that no longer
exists in the *current* `knowledge_chunks.json` — should be rare, since
`status='active'` rows are supposed to always correspond to a real current
chunk per the import layer's own coverage invariant, but not provably
impossible if the chunks file and the DB ever drift out of band): that
result is **excluded from the returned list** with a logged warning,
rather than raising and failing the entire search over one stale pointer.
This mirrors the "never let one bad row corrupt/abort a whole batch"
posture already used throughout this project's validation code.

---

## 7. Score semantics (explicit, per the task's own requirement)

- **What it is**: cosine similarity between the query embedding and the
  stored chunk embedding, computed by PostgreSQL as `1 - (embedding <=>
  query_vector)` — never a Python-side computation, never a
  model-specific "confidence" or calibrated probability. It is called
  `score`, not `confidence`, precisely because nothing here justifies the
  word "confidence" (no calibration, no probability interpretation).
- **Direction**: **higher is better** — 1.0 means the two vectors point in
  exactly the same direction (maximally similar); the returned list is
  ordered descending by `score`.
- **Range**: mathematically `[-1, 1]` for arbitrary vectors. In practice,
  since both the query and every stored vector are L2-normalized
  embeddings from the same text model, scores for genuinely related
  educational text are expected to sit closer to `[0, 1]` — but this is an
  empirical expectation stated as such, **not a guaranteed bound and not a
  threshold**. No result is ever hidden or excluded for having a "low"
  score (§11) — the raw ranked scores are always returned as-is.
- **Ordering semantics**: strictly descending by `score`; ties broken by
  `embedding_id` ascending (§4) for deterministic, testable behavior.

---

## 8. Top-K

`top_k` is a required-but-defaulted request field, validated as an
integer in `1..config.SEARCH_MAX_TOP_K` (new config constants —
`config.SEARCH_DEFAULT_TOP_K` and `config.SEARCH_MAX_TOP_K` — not a bare
`5` hardcoded inline anywhere; both overridable, matching this project's
existing "plain constants, always named" convention). An out-of-range or
non-integer `top_k` is rejected during request validation (§2 step 1),
before any embedding or DB work happens.

Behavior by value, all handled by the exact same `LIMIT %(top_k)s` clause
(§4) — no special-casing per value:

- `top_k = 1` → single best match, or an empty list if the chapter/filters
  produce zero candidates (§11).
- `top_k = 5` (the proposed default) → up to 5 ranked results.
- `top_k = 10` against a chapter with fewer than 10 active, filter-
  matching rows (e.g. Chapter 1's real 102 rows, filtered down to say 6 by
  a narrow `section_id` filter) → returns exactly as many rows as exist
  (6), never an error, never padding with placeholder rows.

---

## 9. Model/revision compatibility (explicit handling)

Both the *query* embedding and the *search* `WHERE` clause are always
driven by the same `(embedding_model, model_revision)` pair (§3/§4) — the
design has no path where these could diverge. Two distinguishable failure
conditions:

1. **Requested pair genuinely incompatible with the loaded model's own
   reported dimension** (e.g. a caller asks for `model_revision="X"` but
   the *actual* model loaded under that revision reports a different
   embedding dimension than `embeddings_1024`'s column width) — caught by
   the same `table_dimension()`-based check `import_embeddings.py` already
   uses (§2 step 3) — a hard, clear error, never a silently-wrong-shape
   query.
2. **Requested pair has zero indexed rows for the target chapter** (a
   valid model/revision in general, just never imported for this
   chapter — e.g. Chapter 1 was only ever imported under
   `bge-m3@5617a9f...`, and a caller asks for a hypothetical
   `bge-m3@some-other-revision`) — distinguished from "chapter has no
   relevant results" (§11) by a cheap existence probe (`SELECT 1 FROM
   embeddings_1024 WHERE chapter_id=%s AND embedding_model=%s AND
   model_revision=%s LIMIT 1`) run once before the main ranked query;
   if it finds nothing, the response reports "no index for this
   model/revision" (optionally listing which `(model, revision)` pairs
   *do* exist for that chapter, via a `SELECT DISTINCT`) rather than a
   bare empty result list that looks identical to "nothing relevant was
   found."

---

## 10. Zero results / low relevance

No magic threshold anywhere in this design, per the explicit instruction.
Every case below returns the **actual** ranked results (possibly empty),
with a status/diagnostic distinguishing *why* the list might be empty:

- **No matching chapter** (chapter_id has zero rows under *any*
  model/revision): empty result list + a diagnostic ("no embeddings
  found for this chapter_id").
- **Empty chapter** (chapter_id valid, but zero `status='active'` rows —
  e.g. every chunk went stale): same empty-list + diagnostic path.
- **`top_k` larger than available rows**: `LIMIT` naturally returns fewer
  rows; not an error (§8).
- **No rows after filters**: a legitimate outcome (filters over-narrowed);
  empty list, no error, no automatic filter-relaxation.
- **Very low similarity for every result**: results are returned exactly
  as ranked, with their real (possibly low or even negative) scores — no
  hiding, no filtering, no rounding up. If a relevance threshold is ever
  wanted, it must be calibrated empirically against real query/result
  data later — explicitly deferred, not guessed at here.

---

## 11. Multi-chapter support

Searching Chapter 2 after Chapter 1 requires **zero implementation
changes** — `chapter_id` is a plain request parameter, and every chapter
already coexists in the same `embeddings_1024` table (`vector_db_design.md`
§5/§24 regression test). A future **global search** (no `chapter_id`
filter at all) is technically a one-line change (drop that `WHERE`
clause) and would still use the same HNSW index — but this phase
deliberately does **not** adopt it as part of the default contract:
nothing in the task's own use case needs it yet, chapter-scoping is a
meaningful pedagogical boundary (a Chapter 1 question shouldn't surface
Chapter 7 content), and leaving `chapter_id` required keeps the contract
minimal per the task's own "do not implement unless useful" instruction.
It's noted here only so a future phase doesn't have to re-derive that this
was a deliberate, easy-to-lift restriction rather than an architectural
limitation.

---

## 12. Performance

Current real scale: 102 rows (Chapter 1). At this size, Postgres' planner
may well choose a sequential scan over the HNSW index for some queries —
**this is expected and not a problem**, not a sign the index is
misconfigured; HNSW's approximate-nearest-neighbor advantage only becomes
load-bearing at a much larger row count. No new index, no new index type,
and explicitly no Redis/Elasticsearch/Qdrant/FAISS — the existing
`embeddings_1024_embedding_cosine_idx` (already built in Phase 12
specifically for this future use) is reused exactly as-is.

**How this scales without changing the design**: because every query is
already `chapter_id`-scoped (§5), real-world latency tracks a *single
chapter's* row count, not the whole corpus's — a future 20-chapter, several-
thousand-chunk corpus doesn't change per-query cost as long as chapter
scoping stays mandatory. The HNSW index becomes genuinely useful once a
single chapter (or a future global-search mode, §11) holds tens of
thousands of rows; nothing about this design needs to change when that
happens, since the query shape (`ORDER BY embedding <=> ... LIMIT
top_k`) is exactly what an HNSW index is built to accelerate.

---

## 13. Architectural boundary: Semantic Search vs. future RAG

This phase's deliverable is a **Python function/module + CLI** (no network
service), matching the exact placement/convention of `import_embeddings.py`:
`data/src/search_embeddings.py`, callable directly (`search(request) ->
list[SearchResult]`) or via a manual-testing CLI (`--chapter-id --query
--top-k --database-url --model --revision --filter-*`).

**In scope (this phase)**: request validation, query embedding (reusing
`SentenceTransformerBackend`), the cosine-similarity SQL query, metadata
filtering, chunk-text resolution, the result contract above.

**Explicitly out of scope, deferred to a later phase**: constructing an
LLM prompt from retrieved chunks, calling any LLM to synthesize an answer,
deciding *which* chunks fit a context-window budget, a FastAPI/Spring Boot
HTTP endpoint exposing this to the Angular frontend, authentication/
authorization for that endpoint, chat/conversation state, and any ranking
beyond plain cosine similarity (e.g. a future re-ranker model). The line
is exact: **this phase returns ranked chunks; it never reads their
meaning.**

---

## 14. Test strategy

Following this project's own established convention (`unittest`,
injectable-backend fakes so no real model download is required for most
tests, one real-model/real-Chapter-1 integration test, a dedicated
`ai_education_test` PostgreSQL database reused from
`test_import_embeddings.py`'s own setup):

For **ranking-specific tests**, synthetic fixtures insert **hand-crafted
vectors with an analytically known cosine similarity** directly into
`embeddings_1024` (bypassing the embedding pipeline and any `FakeBackend`
hashing entirely) — e.g. a query vector `q`, and stored vectors
constructed to have cosine similarity exactly `1.0`, `0.5`, and `0.0`
against `q` — so the expected ranked order and even the expected scores
are known constants, not just "semantically plausible."

| # | Test | Strategy |
|---|---|---|
| 1 | Query validation | Malformed request (non-string query, non-int top_k, missing chapter_id) rejected before any embedding/DB call |
| 2 | Empty query | `query=""` / whitespace-only rejected with a clear validation error |
| 3 | Valid query | End-to-end happy path against synthetic inserted rows via a `FakeBackend`-driven query embedding |
| 4 | Query embedding dimension | A fake backend reporting the wrong dimension is rejected via the reused `table_dimension()` check, before querying Postgres |
| 5 | Model compatibility | Query against a `(model, revision)` pair with zero rows for the chapter → distinguishable "no index for this model/revision" result (§9), not a bare empty list |
| 6 | Chapter isolation | Two chapters, same model/revision, synthetic vectors — search chapter A never returns chapter B's rows |
| 7 | top_k | `top_k=1/5/10` correct counts; `top_k=0`/negative/non-int rejected |
| 8 | Metadata filters | Each filter field (`section_id`, `content_role`, `concepts` any-of, `pdf_pages` any-of, etc.) independently narrows a synthetic multi-row fixture correctly |
| 9 | Cosine ranking | Hand-crafted known-similarity vectors (see above) — assert exact ranked order and scores (within floating-point tolerance) |
| 10 | Result ordering | Descending by score; exact tie broken deterministically by `embedding_id` (two hand-crafted identical vectors) |
| 11 | Zero results | Empty chapter / all filtered out → empty list, no exception, correct diagnostic |
| 12 | Fewer results than top_k | `top_k=10` against 3 available rows → exactly 3 returned, no error |
| 13 | Multiple chapters | 3+ synthetic chapters coexisting in `embeddings_1024`, each searched independently and correctly (mirrors `TestMultipleChaptersSameTable` from Phase 12) |
| 14 | Deterministic behavior | Same request run twice → identical order and scores (guaranteed by the `embedding_id` tiebreaker, §4) |
| 15 | Invalid filters | An unrecognized filter key or wrong-typed filter value rejected during request validation, never silently ignored or passed through to SQL |
| 16 | Missing chunk artifact | A synthetic DB row whose `chunk_id` doesn't exist in the (synthetic) chunks file → excluded from results with a logged warning, search doesn't crash |
| 17 | chunk_id → text resolution | Returned `text` matches the exact source chunk file content for that `chunk_id`, byte-for-byte (same style as Phase 12's `TestMetadataPreservation`) |
| 18 | Model/revision mismatch | Querying with a revision genuinely different from what's stored for that chapter never mixes/blends scores across the two — confirmed via a fixture with BOTH revisions present (mirrors Phase 12's `TestModelRevisionIsolation`) |

One real-model, real-Chapter-1 integration test (mirroring
`TestChapter1RealImportRegression`) exercises the actual BGE-M3 model
against the real 102 imported rows with a real French query, skipped (not
failed) if the model/DB aren't available in the running environment.

---

## 15. Files that would need to be created/modified (not created yet)

- **NEW** `data/src/search_embeddings.py` — the search function + CLI.
- **NEW** `data/src/test_search_embeddings.py` — the test suite (§14).
- **NEW** `data/schema/search_result.schema.json` — a JSON Schema for the
  `SearchResult` contract (§6), mirroring `vector_db_payload.schema.json`'s
  own convention of pairing a design doc with a schema file.
- **MODIFIED** `data/src/config.py` — additive only:
  `SEARCH_DEFAULT_TOP_K`, `SEARCH_MAX_TOP_K` constants (§8). No existing
  constant, helper, or behavior changes.
- **Not modified**: `embed_knowledge.py`, `import_embeddings.py`,
  `validate_embeddings.py`, `init_vector_db_schema.py`,
  `vector_db_schema.sql`, any chunk/enrichment/relations/normalization
  artifact, the backend, or the frontend. This phase is additive and
  read-only with respect to everything built so far.

---

## Final report

1. **Architecture**: a single new Python module (`search_embeddings.py`,
   no network service) sitting downstream of the existing
   `embeddings_1024` table and reusing `SentenceTransformerBackend`
   unchanged for query embedding.
2. **Data flow**: query text → validate request → embed query (reused
   backend) → verify dimension against the real table column width →
   cosine-similarity SQL query (Postgres-side ranking only) → resolve
   `chunk_id`s to `text` via the chapter's own `knowledge_chunks.json` →
   return ranked `SearchResult` list.
3. **Query embedding strategy**: exactly `SentenceTransformerBackend` +
   `l2_normalize()`, both reused verbatim from Phase 11/12 — no second
   embedding implementation, no document re-embedding.
4. **PostgreSQL/pgvector query strategy**: `ORDER BY embedding <=>
   query_vector ASC, embedding_id ASC LIMIT top_k`, `score = 1 -
   distance` computed in SQL, reusing the existing HNSW cosine index —
   never a Python-side vector comparison.
5. **Metadata filtering strategy**: optional, AND-combined `WHERE`
   conditions built only from the fields `filter_metadata` already has
   (§1/§6) — scalar equality for `section_id`/`subsection_id`/
   `content_role`/`has_uncertain_content`, `?|` any-of for the string
   arrays, an `EXISTS`/`jsonb_array_elements_text` any-of for the numeric
   `pdf_pages` array.
6. **Result contract**: `chunk_id`, `chapter_id`, `score`, the
   `filter_metadata` fields flattened, `embedding_model`/`model_revision`,
   and a resolved `text` — never storing/duplicating full chunk text in
   Postgres.
7. **Chunk text resolution strategy**: one read of
   `config.chunks_json(chapter_id)` per search call, building an in-memory
   lookup — the chunks file remains the sole authority for prose content.
8. **Model/revision compatibility**: query embedding and search `WHERE`
   clause always share the same `(model, revision)` pair; a dimension
   mismatch or a zero-rows-for-this-pair condition are both detected and
   reported distinctly, never silently producing a meaningless or
   wrong-shape comparison.
9. **Chapter isolation**: `chapter_id` mandatory in every query; free
   reuse of the same single-table design Phase 12 already proved supports
   multiple chapters cleanly.
10. **Error handling**: request validation before any model/DB work;
    distinguishable diagnostics for "no chapter", "no rows for this
    model/revision", "filtered to zero", and "dimension mismatch" — no
    invented relevance threshold anywhere.
11. **Test strategy**: 18 categories mapped to concrete test designs
    (§14), synthetic hand-crafted-similarity vectors for ranking
    correctness, one real-model/real-Chapter-1 regression test, reusing
    `test_import_embeddings.py`'s dedicated-test-database convention.
12. **Files to create/modify**: 3 new files, 1 additive config change,
    nothing else (§15).
13. **Boundary vs. future RAG**: this phase ends at ranked
    `(chunk_id, score, metadata, text)` tuples returned from a Python
    function/CLI — no prompt construction, no LLM call, no HTTP endpoint,
    no frontend/backend integration. Those remain a distinct, later phase.

No implementation has been written in this phase, per the explicit
instruction. Stopping here.
