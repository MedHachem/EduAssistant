# FastAPI API Layer design (Phase 16)

Design proposal for the first HTTP layer over the already-validated
EduAssistant pipeline. Minimal by design — a thin orchestration layer,
not a redesign of anything underneath it.

```
HTTP client / Postman
    ↓
FastAPI (this phase)
    ↓
search_embeddings.search()            (unchanged, called via rag_context)
    ↓
rag_context.assemble_context()        (unchanged)
    ↓
generate_answer.generate_answer()     (unchanged, Gemini 3.7 Flash)
    ↓
AnswerResult (unchanged dict shape)
    ↓
HTTP JSON response
```

---

## 1. API scope

Exactly one functional endpoint (`POST /api/v1/ask`) plus one operational
endpoint (`GET /health`). No chat, no history, no auth, no other resource
types. The API's only job is to accept `{chapter_id, query}`, call the
three already-validated pipeline functions in sequence, and return their
combined result as JSON — nothing computed here that isn't already
computed by `assemble_context()`/`generate_answer()`.

## 2. Technology choice

**FastAPI** + **uvicorn** (ASGI), per the task's explicit instruction —
not chosen for any reason beyond that instruction (no other framework is
evaluated here, since none is in scope). FastAPI is used specifically
for: automatic request validation via Pydantic (matching the task's own
"use Pydantic validation" requirement), automatic `/docs`/`openapi.json`
generation (task's own explicit requirement), and its dependency-injection
system (`Depends()`), which gives a clean, idiomatic seam for overriding
the embedding backend / Gemini provider in tests without touching route
code.

## 3. Project/module structure

```
data/src/api/
├── __init__.py
├── main.py              # FastAPI() app, CORS middleware, router mount, /health
├── schemas.py            # Pydantic request/response models
├── dependencies.py        # lazy-singleton providers: embedding backend, Gemini provider
├── routes/
│   ├── __init__.py
│   └── ask.py             # POST /api/v1/ask
└── services/
    ├── __init__.py
    └── ask_service.py       # answer_question(): the ONLY orchestration logic
```

`ask_service.py` is justified (not an unnecessary abstraction) precisely
because it is the one clean seam that lets tests patch
`assemble_context`/`generate_answer` directly, independent of FastAPI's
own request/response machinery — without it, tests would need to mock
inside the route handler itself, coupling test setup to HTTP framework
details it doesn't need to know about.

## 4. Endpoint contract

```
POST /api/v1/ask
Content-Type: application/json

{"chapter_id": "math-4eme-tome1-ch01", "query": "Comment étudier..."}

-> 200 application/json: AnswerResult (see §6)
-> 422 application/json: {"detail": [...]}      (FastAPI's own standard shape)
-> 500 application/json: {"detail": "..."}       (generic, no internals)
-> 502 application/json: {"detail": "..."}       (generic, no internals)
```

```
GET /health
-> 200 {"status": "ok"}   (no pipeline dependency touched at all)
```

## 5. Request schema

```python
class AskRequest(BaseModel):
    chapter_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
```

Both fields required (Pydantic's own default for a field with no
default value). A `field_validator` rejects a value that is
**whitespace-only** (`v.strip()` empty) but the validator **returns `v`
unchanged**, never `v.strip()` — per the explicit "do not silently
modify user input" instruction, the exact string the client sent is what
reaches `assemble_context()`/`generate_answer()`. No other fields are
accepted (`model_config = {"extra": "forbid"}` — matches "do not add
unrelated fields at this stage").

## 6. Response schema

Pydantic models in `schemas.py` that are a field-for-field mirror of
`data/schema/answer_result.schema.json` (already confirmed, by direct
inspection, to match `generate_answer.py`'s own real `AnswerResult` dict
shape exactly — `answer`, `status`, `supporting_chunks`, `warnings`,
`grounding`, `provenance`, `model_metadata`, `generation_metadata`, each
sub-object exactly as defined there). This is **not** a second,
incompatible format — it's the same JSON shape expressed as a Pydantic
model so FastAPI can (a) validate the dict `generate_answer()` returns
before serializing it (catching any accidental shape drift as a real,
tested guarantee) and (b) generate accurate `/docs`/`openapi.json`. The
route returns the plain dict from `generate_answer()` directly;
`response_model=AnswerResultResponse` does the validation/serialization.

## 7. HTTP status codes

| Condition | Code | Rationale |
|---|---|---|
| `generate_answer()` returns normally, **any** of `ANSWERED` / `INSUFFICIENT_CONTEXT` / `CONFLICTING_CONTEXT` / `VALIDATION_FAILED` | **200** | All four are the pipeline's own well-formed, already-handled outcomes — none is an HTTP-layer error. `VALIDATION_FAILED` in particular means "we caught a bad model output and safely reported it," which is the API layer working correctly, not failing. The response body's own `status` field is what distinguishes them — this is the single most coherent mapping given the existing four-status contract already approved in `llm_answer_generation_design.md` §10. |
| Pydantic request validation fails | **422** | FastAPI's own standard behavior for an invalid request body — no custom code needed. |
| `search_embeddings.SearchIncompatibleModelError` | **500** | A genuine local misconfiguration (dimension/model-revision mismatch) — not something the client's request can fix, and not an upstream provider failure either. |
| `generate_answer.GenerationError` | **502** | The upstream Gemini provider failed/was unavailable (auth, malformed response, or the transient 503/504 already observed in Phase 15) — a single, consistent "bad gateway" mapping, without inventing new exception subtypes inside the already-validated `generate_answer.py` to distinguish finer-grained provider-failure codes. |
| Any other unhandled exception | **500** | Generic, logged server-side in full, never leaked to the client. |

A chapter with no indexed data, or a query that legitimately retrieves
nothing, is **not** a special case here at all: Semantic Search already
returns an empty result list (never an exception) for that, RAG Context
Assembly already turns that into an empty `context`, and
`generate_answer()` already short-circuits to `INSUFFICIENT_CONTEXT`
without even calling Gemini — the API layer needs zero new code for this
path; it's already handled two phases upstream, unchanged.

## 8. Error handling

Three narrow `except` clauses in the route (mapping exactly the three
non-200 rows above), each: logs full diagnostic detail server-side
(`logger.error`/`logger.exception`), and raises `HTTPException` with a
short, generic, non-leaking `detail` string. **Never** a stack trace, a
DB connection string, or the Gemini API key in a response body. **Never**
a caught provider failure silently turned into `{"status": "ANSWERED"}`
— the exception propagates as a 502 with the real status visible only
in server logs, exactly the task's own explicit requirement.

## 9. Validation strategy

Entirely Pydantic, at the request boundary (`AskRequest`) and the
response boundary (`response_model=AnswerResultResponse`). No manual
`if not chapter_id` checks duplicating what Pydantic already does. The
*pipeline's own* validation (Semantic Search's own request validation,
`generate_answer`'s own deterministic `AnswerResult` validator) is
reused unchanged — the API layer adds no second, competing validation
layer over the same data.

## 10. Dependency/configuration management

Exactly one new config function is introduced —
`config.api_cors_origins()` — following the *exact* existing
`.env`-based pattern (`database_url()`, `gemini_api_key()`): reads
`API_CORS_ORIGINS` (comma-separated) from the environment, defaulting to
the Angular dev server's own already-established port
(`http://localhost:4200`, matching `frontend/proxy.conf.json`). **No
other new configuration is introduced** — search `top_k`, the Gemini
model/generation settings, and every RAG limit are already configurable
via existing `config.py` constants (`RAG_CANDIDATE_TOP_K`,
`GEMINI_MODEL`, `GEMINI_TEMPERATURE`, `RAG_MAX_CONTEXT_CHUNKS`, etc.) —
`assemble_context()`/`generate_answer()` already default to them; the API
layer never re-declares or duplicates them.

`api/dependencies.py` provides two lazy, process-wide singletons (built
once, on first use, not per request — loading BGE-M3 or initializing a
Gemini client on every HTTP call would be wasteful and slow):
`get_embedding_backend()` (a real `SentenceTransformerBackend`) and
`get_gemini_provider()` (a real `GeminiProvider`). Both are ordinary
FastAPI `Depends()` callables — the idiomatic override point for tests
(`app.dependency_overrides[...] = lambda: fake`).

## 11. Service/orchestration layer

`ask_service.answer_question(chapter_id, query, embedding_backend,
gemini_provider) -> dict` is the **entire** orchestration:

```python
def answer_question(chapter_id, query, embedding_backend, gemini_provider):
    rag_context = assemble_context(query=query, chapter_id=chapter_id, backend=embedding_backend)
    return generate_answer(rag_context, gemini_provider)
```

Two calls, both to already-validated, unchanged functions. Nothing else.

## 12. Mapping from HTTP request → Semantic Search → RAG → LLM

`AskRequest` (validated) → `answer_question(chapter_id, query, ...)` →
`assemble_context()` (which itself calls `search_embeddings.search()`
internally, unchanged) → `generate_answer()` (which calls the Gemini
provider, unchanged) → the resulting `AnswerResult` dict → FastAPI
serializes it through `AnswerResultResponse` → JSON body, HTTP 200.

## 13. Handling of `AnswerResult.status`

Not branched on by the API layer at all beyond the blanket "any status =
200" rule (§7) — the status is data the client reads, not a signal the
HTTP layer acts differently on. This keeps the API layer from encoding
any policy that `llm_answer_generation_design.md` already owns.

## 14. Logging strategy

Standard `logging`, matching every other module in this project
(`logging.basicConfig` + a named logger). Every caught
exception is logged with full detail (`logger.error(str(e))` /
`logger.exception(...)`) — server-side only. The Gemini API key is never
logged (already guaranteed by `generate_answer.py`'s own `GenerationError`
messages, which only ever wrap the SDK's own exception text — unchanged,
re-verified, not re-implemented here). Ordinary request/response bodies
are not logged wholesale by default (a future decision, per
`llm_answer_generation_design.md` §18's own unresolved
question-logging/privacy note — not resolved here either).

## 15. Security considerations

No authentication in this phase (explicitly out of scope). What *is* in
scope: never returning `GEMINI_API_KEY`, DB credentials, `.env` contents,
or a raw stack trace in any response body (§8); CORS restricted to
explicitly configured origins, never `allow_origins=["*"]` with
credentials; no secret ever hardcoded in `api/` source.

## 16. CORS strategy for this phase

`CORSMiddleware` configured from `config.api_cors_origins()` (§10) —
local development only, defaulting to the Angular dev server's port.
`allow_credentials=False` (no cookies/auth in this phase, so there's
nothing to carry credentialed CORS risk). No production origin is ever
hardcoded — a real deployment would set `API_CORS_ORIGINS` via its own
environment, the same `.env` mechanism already used for every other
secret/environment-specific value in this project.

## 17. Testing strategy

`data/src/test_api.py`, using FastAPI's `TestClient` (via `httpx`).
**No test calls Gemini or a real database** — `app.dependency_overrides`
replaces `get_embedding_backend`/`get_gemini_provider` with trivial fakes
(so no BGE-M3 load, no `GEMINI_API_KEY` requirement at test-collection
time), and `unittest.mock.patch` replaces
`api.services.ask_service.assemble_context` /
`api.services.ask_service.generate_answer` directly — the exact seam
that lets a test assert the real functions *were called* (proving no
reimplementation happened) while controlling their return value/exception
deterministically. One separate, explicitly optional real end-to-end
run (§18 of the task, not an automated test) exercises the genuine
pipeline once, manually.

## 18. CLI/local development strategy

```
cd data/src
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Run from `data/src` (matching this project's own established convention
— every existing script assumes that working directory for its own flat
`import config`-style imports; the `api/` package is no exception).
`/health` never touches the pipeline. `/docs` and `/openapi.json` are
FastAPI's own automatic output — no hand-maintained OpenAPI file.

## 19. Explicit non-goals

Angular integration, chat UI, conversation history, user accounts, JWT,
authentication, authorization, WebSockets, streaming, Server-Sent Events,
file upload API, PDF processing API, chapter-management API, Human
Review API, Spring Boot integration, Docker, Kubernetes, cloud
deployment, Redis, caching, any redesign of RAG/Semantic
Search/Gemini/`AnswerResult`, any second LLM provider.

## 20. Future extension points

A second endpoint (e.g. listing available chapters) would follow the
exact same route→service→existing-function pattern. Authentication would
slot in as FastAPI middleware/dependency ahead of the existing route,
without touching `ask_service.py`. A different LLM provider would only
ever require a new `LLMProvider` implementation (already an abstraction,
Phase 15) — `dependencies.py`'s `get_gemini_provider()` is the one place
that would change, never the route or service layer.
