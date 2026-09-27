# Figure ↔ Knowledge Association — Design Document

Status: **implemented** (`associate_figures_knowledge.py`, Phase 5b). Additive
only — never modifies the knowledge JSON, `final_figures/` PNGs or index, or
any V1-V4 detection output.

## 1. What was inspected before designing this

- **Knowledge JSON** (`data/output/knowledge/chapter_01_continuite_limites.json`):
  `document` → `chapter` → `sections` (8, each with `pdf_page_start/end`) →
  `subsections` (12, same shape) → `items` (100: activity/theorem/property/
  definition/remark/exercise). Each item carries `section_id`, `subsection_id`
  (nullable), and `source.pdf_pages` (a **list** — items can span multiple
  pages, e.g. one exercise spans pages 20-22). Items already exist in
  document reading order in the `items` array. **No item carries a pixel
  bounding box or any other in-page geometry.**
- **Final figure manifest** (`data/output/final_figures/index.json`, Phase
  5a): `figure_id`, `source_page`, `candidate_id` (a V4-era id, not stable
  across pipeline reruns), `status`, `original_bbox`/`final_bbox` (real
  pixel geometry, page-image space), `image`. 19 entries for Chapter 1.
- **Existing ID conventions**: knowledge item IDs
  (`math-4eme-tome1-ch01-thm-001`) are already deterministic, chapter-scoped,
  and content-derived (a type prefix + a running counter) — reused as-is.
  Figure IDs (`figure_001`) are deterministic within a chapter given a fixed
  input, but not globally unique on their own; every consumer already reads
  them alongside `chapter_id`, so no new global figure-ID scheme was
  introduced (see §4).
- **Frontend review pattern** (`frontend/src/app/features/admin/figure-review/`,
  `knowledge-review/`): generated JSON (read-only) + a `*-state.service.ts`
  overlay persisted to **localStorage**, explicitly documented in that code
  as "Prototype-only". This confirms the task brief's instruction: don't
  build this phase's persistence on localStorage, and don't redesign the
  frontend now — see §9 for the integration point this phase exposes instead.
- **config.py conventions**: one flat module of path constants, currently
  entirely Chapter-1-specific (`KNOWLEDGE_CHAPTER_01_JSON`, `DOCUMENT_ID`,
  etc.) — there is no existing multi-chapter path convention to reuse. This
  phase adds the first **chapter-parametric** path helpers
  (`associations_dir(chapter_id)` / `associations_json(chapter_id)`) rather
  than another `..._CH01_...` constant.

## 2. Core design decision: no item geometry is invented

The task brief explicitly says: *"Do not invent item bounding boxes. If
reliable geometry cannot be recovered for a particular item, mark the
geometry as unavailable and let the matcher fall back to other signals."*

Chapter 1's knowledge JSON has **no** per-item geometry at all today — only
`source.pdf_pages` and array order. Two consequences:

- No "vertical pixel distance" signal is computed (there is nothing to
  measure it against). If a future chapter's extraction pipeline starts
  persisting per-item bounding boxes, only the ordinal proxy below needs to
  be swapped for a real distance measurement — the rest of the scoring model
  is unaffected.
- Instead, a **reading-order ordinal proximity** signal substitutes for it:
  for a given page, items on that page keep their existing array order
  (a real fact — document reading order), and figures on that page are
  ordered by their own **real** `final_bbox` y0 (also a real fact). Each
  side is converted to a normalized ordinal fraction (`(index + 0.5) / count`)
  and compared. This is explicitly an **ordinal**, not a **pixel**, proximity
  — documented as such everywhere it appears (code + this doc), so it is
  never mistaken for real geometry.

A lightweight, generic geometry helper (`_page_range_map`) derives which
section/subsection a given *page* falls into from the sections'/subsections'
own authored `pdf_page_start/end` ranges — this is not invented; it is the
same range data the knowledge JSON already stores.

## 3. Layer separation

| Layer | Source of truth | Touched by this phase? |
|---|---|---|
| Knowledge | `data/output/knowledge/<chapter>.json` | Read-only |
| Figures | `data/output/final_figures/index.json` | Read-only |
| Provenance/geometry | `sections`/`subsections` page ranges (knowledge JSON) + figures' own `final_bbox` | Read-only, derived at runtime |
| **Associations** | `data/output/<chapter_id>/associations/figure_knowledge.json` | **Written** (new, additive) |

No figure image data is embedded into the knowledge JSON, and no knowledge
text is embedded into the figure manifest — the association file is the only
new artifact, and it references both sides by ID.

## 4. Stable IDs

- **Chapter ID**: reused from `knowledge['chapter']['id']`.
- **Knowledge item ID**: reused from `item['id']` (already stable/deterministic).
- **Figure ID**: reused from `final_figures/index.json`'s `figure_id` (already
  deterministic given a fixed input; not the transient V1-V4 `candidate_id`).
- **Association ID** (new): `assoc-<chapter_id>-<figure_id>-<item_id>`, one
  per figure/candidate-item *pair* — deterministic, content-derived, and
  independently addressable (needed if a human reviewer picks a *different*
  candidate than the top automatic pick — that pair already has its own ID).

No candidate ID from any V1-V4 stage is used or stored anywhere in the
association output.

## 5. Candidate generation

1. Same PDF page: any item whose `source.pdf_pages` contains the figure's
   `source_page`.
2. If (and only if) that set is empty, fall back to the immediate
   neighboring pages (page−1, page+1) — e.g. a full-bleed figure whose
   accompanying text landed on the adjacent page during extraction. This
   never searches further than one page away, and every such candidate is
   flagged `neighboring_page: true` and penalized (see §6) — it can reach
   `REVIEW_REQUIRED` but never `AUTO_MATCH`.
3. No section/subsection *pre-filtering* is applied at the generation step
   (the brief allows it "when the available structure allows it", but
   Chapter 1's sections are page-range based, so a page is only ever in one
   section anyway — section match is a *scoring* signal, not a filter, so it
   still surfaces a cross-section candidate for review rather than silently
   dropping it).

This keeps candidate generation O(items on ≤3 pages) per figure, never O(all
100 items) — important for chapters with hundreds of items.

## 6. Deterministic scoring

```
score = 0.45 * same_page
      + 0.20 * same_section
      + 0.10 * same_subsection
      + 0.25 * reading_order_proximity      (ordinal, see §2)
      − 0.40 if not same_page (neighboring-page candidate)
```

Weights were chosen so a **perfect same-page, same-section, same-subsection,
ordinal-perfect** match sums to exactly `1.0` — a score is directly readable
as "fraction of available deterministic evidence satisfied". `same_page` is
weighted highest because it is the only binary, unambiguous, always-available
signal; `reading_order_proximity` is the primary tie-breaker among same-page
items sharing a section. These are **defaults, not per-chapter tuning** —
see `config.py`'s `ASSOCIATION_*` constants, which are the only place they're
defined.

Every score's `signals` dict is stored alongside it (`same_page`,
`same_section`, `same_subsection`, `reading_order_proximity`,
`neighboring_page`) — this is what makes a decision explainable to a human
reviewer without exposing any V1-V4 algorithm internals (see §9).

## 7. Confidence routing

Three states, thresholds in `config.py` (not hardcoded per chapter):

- `AUTO_MATCH`: top candidate's score ≥ `ASSOCIATION_AUTO_MATCH_THRESHOLD`
  (0.72) **and** beats the runner-up by ≥ `ASSOCIATION_AUTO_MATCH_MARGIN`
  (0.12). The margin check exists specifically so a genuine tie between two
  similarly-plausible same-page items is **not** silently resolved — it goes
  to review instead.
- `REVIEW_REQUIRED`: top candidate's score ≥ `ASSOCIATION_REVIEW_THRESHOLD`
  (0.40) but did not clear the bar above (or came from a neighboring page).
- `NO_MATCH`: no candidate reaches even the review threshold, or none exist.

## 8. Relation type

`relation` is derived deterministically from the candidate item's own `type`
(existing, authored field — not inferred from content):

| item type | relation |
|---|---|
| theorem / property / definition | `illustrates` |
| activity | `supports` |
| exercise | `belongs_to_exercise` |
| remark / anything else | `related_to` |

This is intentionally the minimum useful taxonomy (per the task brief) — no
attempt is made to detect e.g. "demonstrates" vs "illustrates" semantically
without real evidence; that is exactly the kind of refinement left to human
review or a future optional LLM pass (see §11).

## 9. Human review model / admin integration point

The output's per-figure record already contains everything a non-technical
review UI needs, with **zero** algorithm-internal vocabulary:

```json
{
  "figure_id": "figure_012",
  "decision": "REVIEW_REQUIRED",
  "review_status": "PENDING",
  "candidates": [
    {"item_id": "...", "relation": "illustrates", "score": 0.89},
    {"item_id": "...", "relation": "related_to", "score": 0.81}
  ]
}
```

**Implemented** (`frontend/src/app/features/admin/figure-association/`):
`Admin → Build AI Pipeline → Figure ↔ Knowledge`. Renders the figure image
(from `final_figures/`, synced by `scripts/sync-knowledge.mjs`), looks up
each candidate `item_id`'s `original_content`/`title` from the knowledge
JSON (reusing the existing `KnowledgeService`) for display text, and shows
only a `High`/`Medium`/`Low` confidence tier (`CONFIDENCE_BY_DECISION`) —
never a raw score or a signal name — alongside *Validate / Reject / Choose
another* actions, exactly as described in the brief.

**Persistence**: consistent with the existing figure-review/knowledge-review
prototypes (both explicitly documented as such in their own code), review
decisions are kept in a **separate** localStorage key,
`edu.figure-association-review.v1.<chapter_id>`
(`figure-association-state.service.ts`) — never mixed with the other two
review states, and the generated `figure_knowledge.json` is never written
back to. This is a prototype, not the long-term mechanism: the real backend
data model is a small persisted-decision store keyed by `association_id`
(shape: `{status, chosen_item_id, reviewed_at}`, i.e. exactly what the
service already writes to localStorage), for a future `/api/associations`
endpoint once the Spring Boot backend exists (`backend/README.md` — Phase
11, not yet started). Swapping the state service's storage backend from
localStorage to that endpoint is the only change needed; the component and
templates are already written against the service's public method shapes
(`confirm`/`reassign`/`reject`/`clear`/`statusOf`/`chosenItemIdOf`), not
against localStorage directly.

**Pipeline status contract** (brief §20): top-level `pipeline_status` is
`ASSOCIATION_AUTO_COMPLETED` when zero figures need review, else
`ASSOCIATION_REVIEW_REQUIRED`. The eventual `ASSOCIATION_VALIDATED` state is
a human-driven transition once every `REVIEW_REQUIRED` figure has a stored
decision — also out of scope here, but the `review_status` field is exactly
what that future check would scan for `PENDING` entries.

## 10. Chapter 1 regression strategy

`test_associate_figures_knowledge.py` has two classes:

- `TestAssociationLogic`: 15 synthetic cases (one per required scenario in
  the brief), using made-up `doc-x-ch01`-style IDs specifically so nothing
  here depends on real Chapter 1 data.
- `TestChapter1Regression`: runs the real module against the real Chapter 1
  files (skipped, not failed, if they're absent) and checks structural
  invariants (every candidate item ID is real, every figure gets a
  candidate list, decisions are one of the three valid states, reruns are
  deterministic) — **not** a fixed expected AUTO_MATCH count, since that
  count is a property of real content density, not a constant the algorithm
  should be tuned to hit (see §11 for what Chapter 1 actually produced).

A dedicated test (`test_no_chapter_specific_hardcoding_in_production_module`)
greps the production module's own source for Chapter-1 tokens
(`math-4eme-tome1`, `ch01`, real page/candidate IDs) and fails if any appear
— the only place Chapter 1 identifiers may legitimately appear in code is
`config.py`'s CLI-default constants and the test file's ground truth.

## 11. Actual Chapter 1 result (reported, not hidden)

Running the module against the real Chapter 1 data currently yields:

```
total_figures: 19, auto_match: 0, review_required: 19, no_match: 0
```

This is **not a bug** — every one of Chapter 1's 27 pages that contains a
figure also contains ≥2 knowledge items (verified: only pages 21-22, which
have no figures, have exactly one item), so no figure in this chapter is
ever "alone" with a single unambiguous candidate. `AUTO_MATCH` is validated
by synthetic tests (§10) using a single-candidate scenario that does not
occur among Chapter 1's real figures. This is reported plainly rather than
loosening thresholds to manufacture auto-matches on this one chapter.

## 12. Limitations

- No per-item pixel geometry exists yet, so reading-order proximity is an
  ordinal approximation, not a real distance measurement (see §2).
- Neighboring-page fallback only looks one page in each direction.
- The relation taxonomy is intentionally coarse (§8) and does not attempt to
  distinguish e.g. "demonstrates" vs "represents" without real evidence.
- Candidate generation does not use section/subsection as a hard pre-filter,
  so a same-page item from a different logical section can still appear as
  a (typically low-scoring) reviewable candidate rather than being excluded
  outright — a deliberate choice per the brief ("when the available
  structure allows it"), open to revisiting once more chapters are observed.

## 13. Future optional LLM extension point

Per the brief, no LLM call is made anywhere in this phase. The natural,
narrow extension point (not implemented) is: for figures whose `decision`
is `REVIEW_REQUIRED` **and** whose top two candidates remain within a small
score band even after this deterministic pass, optionally send just that
figure's image + its small candidate shortlist (not all 100 items) to an LLM
for a semantic tie-break suggestion — still routed through human review, not
auto-applied. This would be a separate, explicitly-opt-in script, not a
change to `associate_figures_knowledge.py`'s deterministic core.
