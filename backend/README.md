# backend

First backend for EduAssistant. Scope, deliberately: **persist the admin's
Human Review decisions for the Figure ↔ Knowledge association page** — that
UI already exists on the frontend (`frontend/src/app/features/admin/figure-association/`)
and was, until now, storing decisions in localStorage only.

Nothing else is implemented here (no auth system, no Normalization /
Enrichment / Relations / Chunking / Embeddings / Vector DB / Semantic
Search) — see "Ready for later" below for how this stays extensible without
those being built prematurely.

## Stack

Java 17, Spring Boot 3.3 (Web, Data JPA, Validation), MySQL (production),
Maven. No existing backend technology was configured, so this follows the
brief's fallback stack exactly.

## Domain model

**One entity: `FigureKnowledgeReview`.** No separate `Figure` or
`KnowledgeItem` JPA entities — both are already owned and generated
elsewhere (the Python pipeline's `data/output/final_figures/index.json` and
`data/output/knowledge/*.json`, synced into the Angular app as static
assets). This table only stores the *decision*, referencing those IDs as
plain strings. Duplicating them into this database would be a second, easily
out-of-sync source of truth for data this backend doesn't own or need to
query by any field other than the ID.

```
FigureKnowledgeReview
  id              Long        surrogate PK
  chapterId       String      e.g. "math-4eme-tome1-ch01"
  figureId        String      e.g. "figure_012" -- NOT globally unique alone
  knowledgeItemId String?     null when status == REJECTED
  relation        String?     e.g. "illustrates" -- optional context, copied
                               from the chosen candidate at review time
  status          enum        CONFIRMED | REJECTED | REASSIGNED
  reviewedAt      Instant
  reviewedBy      String?     no admin identity/auth system yet
```

Unique constraint on `(chapterId, figureId)` — one row is "the current
decision for this figure in this chapter". `figureId` is only unique
*within* a chapter (Chapter 2 will also have a `figure_001`), so `chapterId`
is part of the key, not optional.

**Why not `documentId` or `pipelineRunId` too** (brief §6): every
`chapterId` already embeds document identity (e.g.
`math-4eme-tome1-ch01`), so a separate `documentId` would be redundant with
the one thing that exists today — add it only if that naming convention
ever stops holding. `pipelineRunId` was rejected on purpose: a human
decision must outlive the algorithm being rerun (that's the whole point of
persisting it), so tying reviews to a specific run would fragment review
state across reruns instead of protecting it.

**Why `PENDING` is not a stored value**: "no decision yet" is the *absence*
of a row for `(chapterId, figureId)`, not a status — `GET` simply omits
that figure, and the frontend already defaults to `PENDING` when nothing is
returned (unchanged from its previous localStorage-only logic).

**Why `CONFIRMED` / `REJECTED` / `REASSIGNED`, not the brief's example
`VALIDATED` / `NO_MATCH`**: the brief's conceptual model was explicitly a
suggestion ("Possible conceptual model") and step 1 says *"do not invent IDs
or structures if they already exist in the frontend."* Inspecting the real
UI (`figure-association.model.ts` / `figure-association-state.service.ts`,
written when that feature was built) found it already has this exact
3-state vocabulary and only two buttons (Validate, "Reject / No related
item" — there is no separate third "No Match" button). Reusing what's
already there, rather than introducing a second parallel status vocabulary
that would force a UI change, is what "do not rebuild or redesign the
existing Human Review UI" means in practice here.

## API

Chapter-generic by construction — `chapterId` is always a path variable,
read from the request, never hardcoded:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/chapters/{chapterId}/reviews` | Restore every saved decision for this chapter (page load) |
| `PUT` | `/api/chapters/{chapterId}/reviews/{figureId}` | Create-or-update the one review for this figure — Validate, Reject, and Choose-another all call this |
| `DELETE` | `/api/chapters/{chapterId}/reviews/{figureId}` | Undo |
| `DELETE` | `/api/chapters/{chapterId}/reviews` | Reset all reviews for the chapter |

`PUT` body: `{ status, knowledgeItemId?, relation?, reviewedBy? }`. Because
`chapterId`/`figureId` come from the URL, not the body, the two can never
disagree — and because the service always looks up the existing row by
`(chapterId, figureId)` before deciding whether to insert or update, saving
the same figure twice (e.g. "Figure 1 → Question 12" changed to "Figure 1 →
Question 13") updates the row in place; it never creates a second one (see
`FigureKnowledgeReviewServiceTest.updatingAnExistingReviewChangesTheKnowledgeItemInPlace`
/ `savingTheSameFigureTwiceNeverCreatesADuplicateRow`).

## Running it

**Real MySQL** (default profile): `CREATE DATABASE eduassistant;`, then set
`DB_URL` / `DB_USERNAME` / `DB_PASSWORD` env vars if not using
`localhost:3306` / `root` / (empty), and `mvn spring-boot:run`. Hibernate
creates the table on first start (`ddl-auto=update`) — there's no migration
tool yet (first backend; revisit with Flyway/Liquibase once the schema
needs to evolve carefully in production).

**No MySQL installed** (this sandbox had none, no Docker either): an
`application-local.properties` profile backs the same code with a
file-based H2 instance in MySQL-compatible mode:
`mvn spring-boot:run -Dspring-boot.run.profiles=local`. Data lives in
`backend/data/` (gitignored) and survives a restart exactly like the real
MySQL profile would — this is how the full flow below was actually
exercised end-to-end in this environment, not simulated.

The Angular dev server already proxies `/api/*` to `http://localhost:8081`
(`frontend/proxy.conf.json`) — no CORS configuration was needed for local
development. **Keep this port in sync with `server.port` below** — see the
next section for what happens when they drift apart.

## 404 regression: root cause and fix

**Symptom**: `GET`/`PUT /api/chapters/{chapterId}/reviews...` from the
Angular app returned 404, even though the controller mapping
(`FigureKnowledgeReviewController`) and the proxy's `/api` path prefix
(`proxy.conf.json`) were both individually correct.

**Root cause**: `server.port` (backend) and `proxy.conf.json`'s `/api`
target port had drifted apart. Concretely, on the machine this was
diagnosed on, port 8080 (this backend's original default) was permanently
bound by an unrelated local Apache `httpd` service — so the Spring Boot app
could never actually start on 8080 at all, while `proxy.conf.json` kept
forwarding every `/api` request there anyway. Apache answered with its own
404 for the unmapped path, which looked identical to "the Spring endpoint
doesn't exist," even though the real backend was never in the request path
to begin with. Diagnosis confirmed by testing each hop in isolation (see
task steps 1-4): the controller mapping was verified correct, the proxy
config was verified correct, a direct call to the configured backend port
failed *to even reach Spring Boot*, and the proxied call reproduced the
exact same 404 body as hitting that other service directly.

**Fix**: moved the backend's default `server.port` off the collision-prone
8080 to `8081` (`application.properties`), and updated `proxy.conf.json`'s
`/api`/`/ws` targets to match. No controller code, database model, or
frontend UI changed — the mapping and the proxy prefix were never the
problem.

**Regression guard**: `frontend/scripts/verify-proxy-config.mjs` parses
both files and fails loudly if their ports ever disagree again, regardless
of which file changes next. Wired into `npm run prestart` (fails before
`ng serve` starts with a broken proxy) and `npm run pretest` (fails on
every `npm test`) — see `package.json`.

## Frontend integration

`figure-association-state.service.ts` (the only file changed on the
frontend besides the component/spec) now calls the API above instead of
reading/writing `localStorage` — its public methods
(`use`/`statusOf`/`chosenItemIdOf`/`confirm`/`reassign`/`reject`/`clear`/`clearAll`)
kept the exact same shape, so `figure-association.ts` and its template
needed no changes beyond passing the candidate's `relation` string through
to `confirm`/`reassign` (extra context for later phases, not a UI change).
Writes update the in-memory signal immediately (optimistic UI) and fire the
HTTP call in the background; a failed call is logged, not silently
swallowed, but doesn't roll back the optimistic update — a fuller
retry/reconciliation story is future work, not needed for this first pass.

## Verified end-to-end (Chapter 1's real 19 figures)

1. `mvn test` — 20 tests (unit/service, MockMvc controller, and a
   deliberately **non**-transactional `@SpringBootTest` end-to-end class —
   see "A real bug this caught" below).
2. Started the packaged jar for real (`local` profile), and via `curl`
   against the running instance: Validate → Reject → Choose-another →
   changed one figure's decision to a different item (confirmed
   update-in-place, not a duplicate) → `GET` restored all 3 rows exactly.
3. Killed the process and restarted it — `GET` still returned the same 3
   rows: **decisions survive an application restart**.
4. Started the Angular dev server against the running backend through its
   real `/api` proxy (not calling the backend directly) and repeated
   Validate/`GET` through that exact path — confirms the browser-facing
   flow, not just the backend in isolation.
5. `ng test` — 52 tests (39 pre-existing + 13 for `figure-association`,
   rewritten to assert against `HttpTestingController` instead of
   `localStorage`).

### A real bug this caught

The first version of `FigureKnowledgeReviewService` had no `@Transactional`
on its write methods. Every automated test passed anyway, because the two
initial test classes are `@Transactional` themselves — the ambient test
transaction silently supplied what production code was missing. Manually
running the packaged jar and calling `DELETE /api/chapters/.../reviews`
surfaced `TransactionRequiredException` immediately. Fixed by adding
`@Transactional` (write) / `@Transactional(readOnly = true)` (read) to the
service, and added a **non**-`@Transactional` `@SpringBootTest` class
(`FigureKnowledgeReviewEndToEndTest`, real HTTP via `TestRestTemplate`)
specifically so this class of bug fails a future automated run instead of
only a manual one.

## Ready for later (not built now)

The package is `com.eduassistant.review` — a bounded, single-purpose
package on purpose, so `com.eduassistant.knowledge`,
`com.eduassistant.chunking`, etc. can be added independently later without
this one needing to change. `relation` and `reviewedBy` are already modeled
(nullable) so Relations and an admin-identity system can arrive without a
schema migration surprise. None of Normalization, Enrichment, Relations
(beyond this review link), Chunking, Embeddings, Vector DB, or Semantic
Search are implemented, per the brief.
