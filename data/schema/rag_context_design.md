# RAG Context Assembly / Retrieval Strategy design (Phase 14 — design only, nothing implemented)

Design proposal, not yet implemented. Describes how the ranked results
`search_embeddings.search()` already returns (Phase 13) would be
transformed into a coherent, bounded, source-grounded context for a
future educational LLM. No code is written in this phase. Every example
in §17 uses real Chapter 1 data and real, actually-executed
`search_embeddings.py` queries — nothing hypothetical.

Scope, restated precisely:

```
User question
    ↓
Semantic Search (existing, unchanged)
    ↓
candidate chunks
    ↓
context selection / expansion   <-- this phase designs these steps
    ↓
context ordering
    ↓
context budget
    ↓
final RAG context
    ↓
future LLM (NOT this phase)
```

Not designed or implemented here: the LLM itself, prompt construction,
FastAPI, Spring Boot/Angular integration, chat state, answer generation,
or any ML/LLM-based reranking. Where a deterministic post-retrieval
selection mechanism *is* proposed (§4–§6), it is explicitly rule-based —
no ranking model, no LLM call, anywhere in this design.

---

## 1. Scope

This phase designs the layer between Semantic Search's `SearchResult` list
and a bounded, ordered, provenance-carrying `RagContext` a future LLM
phase would consume. It is a pure transformation: candidate chunks in,
a smaller curated set out, using only deterministic rules over data that
already exists in `knowledge_chunks.json`, `knowledge_relations.json`, and
`SearchResult` itself. No new embeddings, no new database table, no new
LLM call.

## 2. Inputs (real, inspected — nothing assumed)

**From `search_embeddings.search()`** (`data/src/search_embeddings.py`,
confirmed by reading the actual return-dict construction): `chunk_id`,
`chapter_id`, `score`, `section_id`, `subsection_id`, `content_role`,
`pdf_pages`, `topics`, `concepts`, `item_types`, `has_uncertain_content`,
`embedding_model`, `model_revision`, `text`. Exactly the task's own list —
confirmed against the real source, not assumed.

**From `knowledge_chunks.json`** (`config.chunks_json(chapter_id)` — the
exact same file `search_embeddings.py` already reads for `text`
resolution; this phase reads a few more of its already-existing fields
from that same file, requiring no new field and no schema change):
`related_chunk_ids`, `figure_refs` (each entry: `source`,
`reconstructed_figure_id`, `figure_id`, `confidence`), `review_status`
(`NOT_REQUIRED` / `REVIEW_REQUIRED` / `HUMAN_APPROVED` / `HUMAN_REJECTED`),
`order` (global reading-position integer), `part_index`/`part_count`,
`source_item_ids`.

**From `knowledge_relations.json`**: relation type enum is exactly
`["illustrates", "applies_concept"]`
(`knowledge_relations.schema.json`). **Inspected directly against the
real Chapter 1 file: 100% of the 27 real relations are `applies_concept`
— zero `illustrates` relations exist.** This is a load-bearing fact for
§8/§9, reported transparently rather than assumed away.

**From `data/output/math-4eme-tome1-ch01/associations/figure_knowledge.json`**
(figure↔item candidate associations, inspected directly): 19 figures,
`summary = {auto_match: 0, review_required: 19, no_match: 0}`,
`pipeline_status = "ASSOCIATION_REVIEW_REQUIRED"` — **every single figure
association is still `REVIEW_REQUIRED`/`PENDING`; none is human-confirmed
yet.** Every chunk-level `figure_refs` entry inspected has `figure_id:
null` and `confidence: null` — the reconstruction's own raw
`reconstructed_figure_id` (e.g. `"fig-act1"`) is the *only* real signal
available today.

**From `backend/src/main/java/com/eduassistant/review/ReviewStatus.java`**
(the real Human Review enum, read directly): `CONFIRMED`, `REJECTED`,
`REASSIGNED`. `PENDING` is **not** a stored value — it's the absence of a
row for `(chapterId, figureId)` (per that file's own Javadoc). This is the
authority §10/§9 defer to.

**From `data/output/final_figures/index.json`**: 19 real, validated figure
*images* exist (`figure_id`, `image` filename, `status`, `source_page`) —
the images themselves are confirmed-real; only their *association to a
specific chunk* is unconfirmed. This distinction matters throughout §9.

**Real corpus statistics** (computed directly against the 102 real
Chapter 1 chunks, used to ground every numeric default below rather than
guessing): `content_role` is `statement` on 101 chunks and `correction` on
exactly 1 (`exo-001-correction`); `item_types` distribution: exercise 41,
activity 38, theorem 19, property 3, definition 1, remark 1 (**no
`"example"` item_type exists in this schema/corpus** — content-role
design in §7 is grounded in the item_types that actually exist, not an
invented `"example"` category); `subsection_id` is `null` on 49 of 102
chunks (48%); `related_chunk_ids` length distribution: 12 chunks have 0,
73 have exactly 1, and a long tail up to **16** (chunk `thm-019` has 16
related chunks — see §5 for why this makes "expand to all related chunks"
untenable); `has_uncertain_content` is `false` on all 102 chunks today
(the field/schema is exercised by design, but the real corpus doesn't
currently contain a positive case); chunk text length: min 53, max 3022,
average 357 characters.

---

## 3. Candidate retrieval strategy

**One retrieval pass, not several.** No separate passes for
"concepts/exercises/definitions" — the task itself says to keep v1 simple
absent strong evidence otherwise, and nothing in the real corpus (102
chunks, one chapter) justifies the added complexity and nondeterminism of
query-type classification (which would require classifying free-text
queries — itself a non-deterministic, unrequested capability). A single
call to the existing `search()` with a generous `top_k` is the entire
retrieval step.

**`candidate_top_k` > final context size**, always — retrieval must
over-fetch so that selection (§4), expansion (§5), diversity (§6), and
budget (§12) have real material to choose between. Concretely,
`RAG_CANDIDATE_TOP_K` defaults to **20** (§16), well above
`RAG_MAX_CONTEXT_CHUNKS`'s default of 8 — evidenced directly in Example B
(§17): the raw top-10 candidates alone already contained 4 chunks from one
section and 3 from a shared subsection, so a candidate pool *larger* than
the final context is what makes diversity/expansion filtering meaningful
rather than a no-op.

**Fewer candidates than requested**: inherited unchanged from Semantic
Search's own already-designed behavior (`vector_db_design.md` §10 /
`semantic_search_design.md` §8/§10) — `LIMIT` simply returns fewer rows;
this phase never treats that as an error, never pads, never re-queries
with a relaxed filter.

---

## 4. Selection algorithm (deterministic)

Terminology used throughout: a **seed** is a chunk selected because it
independently appears among the semantic candidates (i.e., Semantic
Search itself ranked it). An **expansion** chunk is one added *because of*
a seed (§5), never independently scored. **Selected** = seed ∪ expansion,
after diversity (§6) and budget (§12) are applied.

Algorithm, in order:

1. Take the `RAG_CANDIDATE_TOP_K` candidates from `search()`, already
   sorted descending by score with the deterministic `embedding_id`
   tiebreak (inherited from Phase 13 — never re-derived here).
2. **Correction completion rule (deterministic, no cap needed — a
   correction has exactly one statement by construction)**: for every
   candidate whose `content_role == "correction"`, if its paired
   statement (found via `related_chunk_ids` — a correction's only
   related-chunk entry is its own statement, per
   `knowledge_chunk.schema.json`'s documented convention) is not itself
   already a candidate, add that statement chunk as a **mandatory
   expansion** (not subject to the `max_expansion_per_seed` cap in §5,
   since it is definitionally exactly one chunk). Rationale: a correction
   shown without the question it answers is meaningless to a reader.
3. **The reverse is deliberately not automatic**: selecting a *statement*
   chunk never automatically pulls in its correction (see §7 for the
   pedagogical reasoning — showing an unrequested answer key works
   against the product's educational purpose; a correction only appears
   when it, or its own statement being asked-about, earns its place on
   semantic merit or via step 2 above).
4. Apply concept-support expansion (§5, rule E2) to every remaining
   candidate.
5. Apply diversity caps (§6) to the seed set (expansions added by steps
   2/4 are **not** themselves re-filtered by diversity — see the worked
   justification in Example C, §17, where an expansion chunk
   [`prop-002`] is legitimately included even though its section already
   hit the diversity cap among *independent* seeds).
6. Apply the context budget (§12) to the final, ordered (§11) cluster
   list.

**Deduplication**: keyed by `chunk_id` (already globally unique per
`knowledge_chunk.schema.json`'s own derivation from `chapter_id` +
`source_item_ids`). If an expansion target is already present (as a seed
*or* an earlier expansion), it contributes nothing new — this is not an
edge case, it is the *common* case in the real data (Example B, §17: three
different seeds all independently want to expand to `thm-019`; only the
first one actually adds it).

**related_chunk_ids is never wholesale-included.** Per the task's
explicit instruction, and directly evidenced by `thm-019` having 16
related chunks (§2) — including all of them would both blow any
reasonable budget and dilute a conceptual answer with an arbitrary
grab-bag of unrelated exercises. Only the two narrow, directional rules in
§5 ever add a related chunk.

---

## 5. Context expansion rules (deterministic, capped)

**E1 — Correction completion.** Described in §4 step 2. Always exactly 1
chunk, mandatory, uncapped by `max_expansion_per_seed` (there is only ever
one statement per correction).

**E2 — Concept-support expansion.** If a *seed* chunk's own `item_types`
contains `"activity"` or `"exercise"` (i.e., it is *not itself* a
concept-defining chunk), and it has a `related_chunk_id` whose own
`item_types` contains `"theorem"`, `"property"`, or `"definition"`, add
**at most one** such chunk as an expansion (deterministic pick when more
than one qualifies: the one with the smallest `order`, i.e. the earliest
concept in reading order — sidesteps needing to trust
`related_chunk_ids`'s own list order, which chunking's own generation
method (`"rule_based"`) doesn't document as meaningfully sorted).

**E2 is asymmetric, deliberately.** A theorem/property/definition seed
never automatically pulls in its exercises — this is the direct, explicit
answer to the task's own "if a definition matches, should an associated
example be added?" question, and it is grounded in real data: `thm-019`
alone has 16 related exercises (§2); `prop-001` has 4 (§17, Example C).
Pulling even one or two would need its own principled selection rule this
design does not currently have evidence to justify, whereas the reverse
direction (exercise → its underlying concept) is both bounded (at most 1)
and directly useful (a student looking at an exercise benefits from the
rule it applies; a student looking at a rule does not need a
non-deterministically-chosen sample exercise thrust upon them).

**No adjacent/neighboring-chunk expansion in this design.** The task asks
whether "adjacent chunks from the same subsection" should be added.
Rejected for v1: 48% of real chunks have `subsection_id: null` (§2), so
"adjacent within the same subsection" is frequently undefined, and reading
order (`order` field) alone is not a reliable proxy for topical adjacency
in a text this densely mixed (theorems, remarks, activities, and
exercises interleave within a few `order` values — see `prop-001`
order=14, `act-008` order=11, `act-011` order=15, §17). Introducing
blanket adjacency expansion would add real complexity without an
evidenced benefit, which the task explicitly warns against.

**No figure-triggered chunk expansion**, because there is no such thing as
a separate "figure chunk" to expand *to* — a figure is metadata attached
to the chunk that already mentions it, never its own retrievable unit (see
§9 for the full figure-handling design, which is a metadata concern, not
an expansion concern).

**Cap: `max_expansion_per_seed = 1`** (E1 and E2 never both apply to the
same seed — a chunk is either a correction [E1-eligible] or a non-concept
statement [E2-eligible], never both). This single, low, real-data-grounded
number is what prevents the `thm-019`/16-related-chunks scenario from ever
reaching the context.

---

## 6. Diversity rules (deterministic, greedy, score-preserving)

Applied to the seed candidate list only (§4 step 5), in descending score
order, greedily: a candidate is **rejected** only if admitting it would
violate a cap — an already-accepted higher-scoring chunk is **never**
evicted to make room for a later one. This guarantees "preserve high
semantic score" exactly as the task requires, with a single, simple,
single-pass algorithm.

- **`max_chunks_per_section = 3`.** Grounded directly in the real
  section-size distribution (§2): sections range from 6 to 30 chunks; a
  cap of 3 keeps even the 30-chunk `"exercices-et-problemes"` section from
  dominating a context that should represent multiple sections when the
  query legitimately spans them (see Example A, §17, where this cap
  produces a context spanning two different, closely-related sections
  rather than one).
- **`max_chunks_per_subsection = 2`**, applied *only* when `subsection_id`
  is non-null. A `null` subsection is not a meaningful grouping key (it
  does not mean "these 49 chunks are all the same topic" — it means "no
  subsection was assigned"), so `null`-subsection chunks are governed by
  the section cap alone. Directly evidenced in Example A (§17): three
  real candidates (`rem-001`, `thm-014`, `act-027`) share the real
  subsection `sec-v-sub-1`; the cap keeps the top two and rejects the
  third even though it would otherwise have passed the (already-satisfied)
  section cap.
- **Duplicate item avoidance**: never include two chunks whose
  `source_item_ids` sets are identical — the practical case is a
  split item's multiple parts (`part_index`/`part_count`, 3 real chunks
  in the whole corpus). Both parts of a genuinely split item may
  legitimately coexist if independently relevant (they cover different
  text), but the same part is obviously never duplicated (guaranteed
  already by `chunk_id`-keyed dedup, §4).
- **Content-role diversity**: defined generically ("prefer not stacking
  many same-role candidates from one slot") but has essentially no
  real leverage in the *current* corpus, honestly reported: `content_role`
  is `statement` on 101 of 102 chunks — the one real differentiated case
  (the single correction) is already fully handled by E1, not by a
  separate diversity rule. Kept as a generic rule for forward-compatibility
  with a future chapter that has richer content_role variety, not tuned
  against data that doesn't yet exist.

**Diversity caps do not apply to expansion chunks.** An expansion is
already capped at exactly 1 per seed (§5) and is semantically justified
support, not a redundant near-duplicate — re-filtering it through the same
caps used for independent seed candidates would be double-counting a risk
that doesn't apply the same way. Example C (§17) shows this precisely:
`prop-002` is rejected as an independent seed by the section cap, then
legitimately included anyway as `act-012`'s E2 expansion.

---

## 7. Content-role / item-type handling

**Two separate real fields, not one — this must not be conflated.**
`content_role` (schema enum: `statement` / `correction`) is about whether
a chunk is a question or its answer. `item_types` (real values in this
corpus: `activity`, `exercise`, `theorem`, `property`, `definition`,
`remark` — **not** `"example"`, which does not exist as an item_type in
this schema or corpus) is about the pedagogical *kind* of content. The
task's own content-role list (definition/theorem/example/activity/
exercise/correction/explanation) mixes both axes — this design treats them
as the two real, distinct fields they are.

**No query-intent classification.** The task's own example ("How do I
study variations of a function?" should surface concept+method+example
rather than five exercises) is achieved *without* attempting to classify
the query's phrasing — which would require non-deterministic NLP on free
text, not requested and not justified. Instead, the desired blend emerges
structurally from E2 (§5): whenever the query's top semantic matches
happen to be exercise/activity chunks, their underlying
theorem/property/definition is pulled in automatically, for *any* query,
regardless of its wording. Example B (§17) demonstrates this directly: a
literal exercise-oriented query ("Comment étudier les variations...")
still surfaces `thm-019` and `prop-001` in the final context, purely
because the top-scoring exercises/activities happen to reference them —
no keyword or intent detection involved.

**Corrections are handled exclusively by E1** (§5) — no separate
content-role rule is needed beyond that, since it is the one real
differentiated case in the current corpus.

---

## 8. Relation handling

**`applies_concept`** (the only relation type with real data — 27 real
edges, all of this type): used **exclusively** to drive E2 expansion
(§5) — chunking's own `related_chunk_ids` field is already the
*resolved* form of this relation (per `knowledge_chunk.schema.json`:
`related_chunk_ids` includes "any `knowledge_relations.json` edge
(`applies_concept`/`illustrates`) touching one of this chunk's
`source_item_ids`, resolved to the chunk that now contains the target
item"), so this design reads `related_chunk_ids` directly rather than
re-deriving anything from `knowledge_relations.json` itself. `applies_concept`:

- **does** expand candidates (via E2, capped at 1, directional).
- **does** provide supporting context (the expansion chunk's own `text`
  is included, not just a reference).
- **does not** influence selection *scoring* — an `applies_concept` edge
  never boosts or overrides a chunk's semantic score; it only decides
  whether a *bounded, additional* chunk accompanies an already-selected
  seed. This is the literal, explicit answer to the task's "a relation
  should not automatically override semantic similarity" requirement.
- **does** influence ordering, specifically and only within a cluster
  (§11 — sorted by `order`, not by "relation-ness").

**`illustrates`**: defined in the schema (`NodeKind` enum
`["knowledge_item", "figure"]`, so an `illustrates` edge connects a
`figure` node to a `knowledge_item` node, generated with
`generation_method: "human_confirmed"` per
`knowledge_relations.schema.json`) but **zero instances exist in the real
data today** — directly inspected, confirmed. The most plausible
explanation, itself grounded in real evidence (not invented): `illustrates`
relations appear to be generated only from a *confirmed* Human Review
decision on a figure↔item association, and since all 19 real figure
associations are currently `REVIEW_REQUIRED`/`PENDING` (§2), none has been
promoted to a relation yet. This design specifies `illustrates`'s intended
future behavior (identical treatment to a concept-expansion signal — if a
selected chunk has a confirmed `illustrates` edge, surface the associated
figure's metadata per §9, never the image itself) so a future chapter with
confirmed associations needs no design change here — but reports plainly,
per the task's own request for "assumptions discovered," that this
relation type currently contributes **nothing** to real Chapter 1 context
assembly.

---

## 9. Figure handling (conservative, matching the real, unconfirmed state)

Real state, inspected directly (§2): figures themselves are validated,
real images (`final_figures/index.json`, 19 entries with real filenames
and corrected bounding boxes) — but **every** figure↔chunk association is
still `REVIEW_REQUIRED`/`PENDING`, and every chunk-level `figure_refs`
entry has `figure_id: null`, `confidence: null`. Only the reconstruction's
own raw `reconstructed_figure_id` string (e.g. `"fig-act1"`,
`"fig-activite4"`) is real, unconfirmed metadata available today.

Rules, deliberately conservative given this state:

- **F1**: A chunk's mere presence of a non-empty `figure_refs` does not,
  by itself, cause any *additional* chunk to be included — there is no
  separate figure-only chunk to expand to (§5).
- **F2**: When a chunk with `figure_refs` is already selected (seed or
  expansion), its provenance (§14) carries `has_potential_figure: true`
  and the raw `reconstructed_figure_id`, always — this is harmless,
  already-real metadata. The *resolved* `figure_id` is surfaced **only**
  if that specific `figure_refs` entry has a non-null `figure_id` **and**
  `confidence == "high"` (the schema's own `Confidence` enum). Given
  today's real data (§2), this condition is never met — the design is
  correct and ready for when it is, without any code path returning a
  false-confidence claim today.
- **F3**: No image path, filename, or binary is ever included in the
  context in this phase — the task explicitly defers image delivery, and
  a future multimodal-LLM phase would need its own separate, explicit
  decision about *whether and how* to attach images (a materially
  different, larger design question — not addressed here).
- **F4**: A figure association's confidence in this design is gated by
  Human Review status specifically (not the reconstruction-uncertainty
  gating in §10) — only `CONFIRMED` (per the real
  `ReviewStatus.java` enum: `CONFIRMED` / `REJECTED` / `REASSIGNED`, §2)
  would ever unlock F2's "resolved figure_id" branch; `REASSIGNED` (picked
  but not yet validated) and `REJECTED` never do. This is a stricter gate
  than uncertainty handling (§10) deliberately: an unconfirmed figure
  association is a specific, checkable *identity claim* ("this image IS
  the one this chunk refers to") that could be flatly wrong if surfaced
  prematurely — a categorically different risk than an imperfect OCR
  span, which is still the genuine source text either way.

Example C (§17) is built entirely around this real, unconfirmed state —
four selected chunks (`act-012`, `exo-008`, `act-008`, `exo-015`) each
carry a real `figure_refs` entry, and every one is reported with only its
raw `reconstructed_figure_id`, per F2/F4, since none is `CONFIRMED`.

---

## 10. Human-review / uncertainty handling (conservative, no new review system)

Two distinct, already-existing signals, not conflated:

- **`has_uncertain_content`** (chunk-level boolean, propagated from
  normalization's OCR/reconstruction-uncertainty markers) — real value is
  `false` on all 102 current chunks (§2), but the design must still handle
  `true` correctly for a future chapter.
- **`review_status`** (chunk-level enum from chunking's own boundary
  decisions: `NOT_REQUIRED` / `REVIEW_REQUIRED` / `HUMAN_APPROVED` /
  `HUMAN_REJECTED` — real values seen: `NOT_REQUIRED` and
  `REVIEW_REQUIRED` only) — about whether the *chunk's own boundaries*
  (a merge/split judgment call, or a low/medium-confidence figure ref)
  needed a human look, a different question from content uncertainty.

**Decision: included with explicit metadata, never excluded, never
score-penalized.** Per the task's own "be conservative... do not invent a
new review system" instruction:

- Outright exclusion is **not** adopted: it would silently discard
  otherwise-good chunks over what is often a small uncertain span (or a
  chunking judgment call already reviewed and NOT rejected), with no
  evidence that inclusion actually produces wrong answers.
- A score **penalty** is explicitly **not** adopted either — the task
  itself warns against inventing an uncalibrated adjustment, and a
  penalty is exactly that: an invented weighting with no empirical basis.
  Cosine similarity is not a confidence probability (Phase 13's own
  established position); layering an uncalibrated penalty on top would
  not fix that, only compound it.
- "Requires confirmed review before becoming context" is **not** adopted
  for ordinary chunk uncertainty — that bar is reserved specifically for
  figure *identity* claims (§9/F4), a different and stricter category of
  risk than an imperfect but genuine text span.
- **`HUMAN_REJECTED`** chunks (a real enum value, though none exist in
  the current corpus) are the one case this design *does* treat as
  exclusionary: a chunk a human has explicitly rejected must never appear
  in generated context — this isn't a new review system, it's honoring a
  decision the existing Human Review vocabulary already records.

Every included chunk's `has_uncertain_content` and `review_status` is
carried into provenance (§14) unconditionally, so a future LLM/product
layer can choose to caveat its answer — that decision is explicitly out
of scope here (§20).

---

## 11. Context ordering (deterministic algorithm)

1. Group selected chunks into **clusters**: each seed plus its at most one
   expansion (E1 or E2) forms one cluster. A pure seed with no expansion
   is a cluster of size 1.
2. Order clusters by **seed score descending** (the score that earned the
   cluster its place at all) — ties broken by the seed's `embedding_id`
   ascending (inherited from Phase 13's own deterministic tiebreak, never
   re-derived).
3. **Within a cluster**, order its members by their own `order` field
   ascending (the chunk's real, already-existing global reading-position
   integer) — not by "seed always first." This single rule, with no
   special-casing for "is the expansion a concept or a correction,"
   naturally produces coherent reading order in both real directions
   observed in the data: a concept chunk that precedes its exercise in the
   book (e.g. `thm-019`, order 58, before `exo-028`, order 95 — Example B)
   is placed first; a correction (whose `order` matches or follows its own
   statement) is placed after (Example B — not directly triggered there,
   but the same rule handles it identically, since `exo-001-correction`'s
   `order` (60) is never less than `exo-001`'s (60)). Even a genuinely
   *reversed* textbook order is handled correctly by this same rule without
   a special case: Example C shows `prop-001` (order 14) placed before its
   own semantic seed `act-008` (order 11) is *not* the case there since
   act-008 comes first — but the symmetric case *does* occur in that same
   example: `act-012` (order 16) is followed by its expansion `prop-002`
   (order 17), which comes right after it textually, again handled by the
   same single rule.

This produces a context that reads as a coherent sequence of
concept-then-application or question-then-answer pairs, ordered overall by
relevance — not a flat similarity-sorted dump.

---

## 12. Context budget

- **`max_context_chunks = 8`** (default, configurable, §16) — chosen as a
  round number comfortably above what `max_expansion_per_seed=1` combined
  with a handful of seeds typically produces, while still small enough
  to keep total context length manageable given the real average chunk
  size (357 characters).
- **`max_context_chars = 10000`** (default, configurable) — a
  **character** budget, deliberately **not** a token budget: no LLM or
  tokenizer has been chosen yet (explicitly out of scope, §20), and
  fabricating a token count without knowing the target model's tokenizer
  would itself be an uncalibrated, unjustified number — exactly what the
  task warns against. A character budget is honestly what can be
  justified today; converting it to a token budget later is a
  straightforward, separate calibration step once an LLM is chosen, not a
  redesign.
- **Overflow handling**: walk the final ordered cluster list (§11) and
  add **whole clusters** while the running character/chunk totals stay
  under budget. The **first** cluster that would exceed either limit is
  rejected, and processing **stops** there — later, possibly
  smaller-but-fitting clusters are deliberately **not** back-filled into
  the resulting gap. This keeps the algorithm simple and its behavior
  easy to reason about and test (a single linear scan, one stopping
  condition) at the cost of occasionally leaving a small amount of budget
  unused — an explicit, documented tradeoff (see Example C, §17, where a
  2-chunk cluster is rejected for exceeding the budget by exactly the
  chunk count, even though a later 1-chunk-only cluster might technically
  have fit).
- **Never split/truncate a chunk's `text` mid-string.** A partially cut
  mathematical statement or LaTeX expression can become actively
  *wrong*, not just incomplete — a categorically worse failure mode than
  simply omitting the chunk. Whole-chunk-in or whole-chunk-out, always.
- **Exception: the single highest-scoring cluster always survives in
  full**, even if it alone exceeds `max_context_chars` — a
  "high-score chunks always survive" guarantee (directly requested by the
  task). This is a deliberately narrow exception (only ever the very top
  cluster) rather than a general rule, precisely to avoid the
  alternative failure mode of returning an empty context for a
  well-matched query just because its single best chunk happens to be the
  3022-character outlier chunk (§2's real max length). Any such overshoot
  is reported in the context's own metadata, never silently hidden.

---

## 13. No-result / weak-result behavior

Mirrors Semantic Search's own already-established stance
(`semantic_search_design.md` §10/§11) at every point — this phase adds no
new threshold anywhere:

- **Zero search results** (empty chapter, `SearchIncompatibleModelError`,
  or filters excluding everything): the RAG context is empty, carrying a
  diagnostic explaining why (chapter has no data / model-revision
  mismatch / filters too narrow) — never a fabricated placeholder chunk,
  never a raised "confidence too low" error (no such threshold exists in
  this design).
- **Very low similarity scores**: results still flow through the exact
  same selection/expansion/diversity/ordering/budget pipeline, unchanged.
  This phase's job is to correctly *transform* whatever Semantic Search
  returned — not to second-guess whether the corpus actually contains a
  good answer (that judgment belongs to a future LLM/product layer, out
  of scope here, §20).
- **Only uncertain/flagged chunks available**: included with their flags
  (§10) rather than producing an empty context — an imperfect-but-present
  answer is preferred over silently returning nothing.
- **Only duplicated/near-duplicate information**: diversity (§6) legally
  thins this down; if fewer chunks survive than `max_context_chunks`
  allows, that is the **correct**, expected outcome — this design never
  backfills with lower-relevance chunks purely to reach a target count.
- **Filters producing no results**: identical, explicit non-behavior to
  Semantic Search's own stance — empty result, no error, no automatic
  filter loosening on the caller's behalf.

---

## 14. Provenance contract

Every chunk in the final context carries, at minimum (all sourced from
data that already exists — nothing invented):

- `chunk_id`, `chapter_id` (passthrough from `SearchResult`).
- `score`: the raw cosine similarity **only for a seed chunk** — an
  expansion chunk was never independently scored by Semantic Search, so
  its `score` field is `null`, paired with an explicit
  `inclusion_reason` instead (see below). Conflating an expansion chunk's
  "presence" with an implied score would misrepresent it as something the
  user's own query matched.
- `inclusion_reason`: one of `"semantic_match"`, `"expansion:correction_pair"`
  (E1), or `"expansion:applies_concept"` (E2) — plus, for an expansion,
  `expanded_from_chunk_id` naming the seed that pulled it in.
- `section_id`, `subsection_id`, `content_role`, `item_types`,
  `pdf_pages`, `topics`, `concepts`, `has_uncertain_content`,
  `embedding_model`, `model_revision` — passthrough from `SearchResult`
  (already resolved there; no re-fetch needed for these specific fields).
- `review_status` — read directly from `knowledge_chunks.json` (not
  currently part of `SearchResult`; see §2 — this is an *additional* read
  of the same already-open file, not a new field anywhere).
- Figure metadata per §9/F2: `has_potential_figure`,
  `reconstructed_figure_id` when present; a resolved `figure_id` only
  under F2/F4's confirmed-and-high-confidence condition (never met in the
  real data today).
- **Once per whole context** (not per chunk): `source_chunks_hash` —
  reusing the exact same hash `embed_knowledge.py`'s own manifest already
  computes (`file_hash()`) for the chapter's `knowledge_chunks.json` at
  the moment of assembly. This is the traceability anchor the task
  requires ("the future LLM answer should eventually be traceable back to
  source chunks") — reusing existing hash machinery, inventing no new
  field or mechanism.

---

## 15. Determinism guarantees

Same `(query, chapter_id, search configuration, knowledge version)` →
same final context, because every step in this pipeline is itself
deterministic and none introduces its own randomness:

- Semantic Search's own ranking is already deterministic (Phase 13:
  `ORDER BY ... ASC, embedding_id ASC`).
- Selection (§4) processes candidates in that same fixed order.
- E2's tie-break (§5, smallest `order` among qualifying expansion targets)
  is deterministic and does not depend on `related_chunk_ids`'s own
  (unspecified) list order.
- Diversity (§6) is a single greedy pass in a fixed (score, then
  `embedding_id`) order.
- Ordering (§11) and budget (§12) both process the same fixed cluster
  sequence.
- "Knowledge version" determinism is inherited, not reinvented: as long
  as the underlying `knowledge_chunks.json` and `embeddings_1024` rows
  are unchanged between two calls (already versioned via
  `content_hash`/`source_chunks_hash`, per Phases 11/12), this pipeline's
  output is bit-for-bit reproducible. No new versioning field is
  introduced here — `source_chunks_hash` (§14) is surfaced, not created.

---

## 16. Configuration

Only what earns its place — matching the task's own "do not create
configuration for every possible rule" instruction:

| Constant | Default | Justification |
|---|---|---|
| `RAG_CANDIDATE_TOP_K` | 20 | Must exceed `RAG_MAX_CONTEXT_CHUNKS` so diversity/expansion have real material (§3). |
| `RAG_MAX_CONTEXT_CHUNKS` | 8 | Bounds total chunk count (§12). |
| `RAG_MAX_CONTEXT_CHARS` | 10000 | Character (not token) budget, pending LLM/tokenizer choice (§12). |
| `RAG_MAX_EXPANSION_PER_SEED` | 1 | Directly prevents the real `thm-019`/16-related-chunks scenario (§5). |
| `RAG_MAX_CHUNKS_PER_SUBSECTION` | 2 | Grounded in real subsection sizes (§6). |
| `RAG_MAX_CHUNKS_PER_SECTION` | 3 | Grounded in real section sizes, e.g. the 30-chunk exercises section (§6). |

**Deliberately not configurable / not introduced**: a minimum-similarity
threshold (no empirical calibration exists, per the task's own explicit
instruction); an "allowed/blocked content roles" list (would configure a
2-value field with only one real differentiated instance in the whole
corpus — premature complexity); per-item_type expansion toggles (E2's
single rule already covers the real, evidenced need).

---

## 17. End-to-end examples (real Chapter 1 data, real executed queries)

### Example A — a conceptual question

**Query**: *"Quelle est l'image d'un intervalle par une fonction continue
et strictement monotone ?"*

**Real semantic search candidates** (`candidate_top_k=10`, actually
executed via `search_embeddings.py`):

| rank | chunk_id | score | section | subsection |
|---|---|---|---|---|
| 1 | `thm-019` | 0.7486 | sec-vi (…strictement-monotone) | — (null) |
| 2 | `rem-001` | 0.7056 | sec-v (…continue) | sec-v-sub-1 |
| 3 | `thm-014` | 0.6971 | sec-v | sec-v-sub-1 |
| 4 | `exo-001` | 0.6912 | sec-vi | sub-probleme-resolu |
| 5 | `act-036` | 0.6890 | sec-vi | — (null) |
| 6 | `act-027` | 0.6852 | sec-v | sec-v-sub-1 |
| 7 | `thm-018` | 0.6788 | sec-vi | — (null) |
| 8 | `act-035` | 0.6703 | sec-vi | — (null) |
| 9 | `exo-001-correction` | 0.6651 | sec-vi | sub-probleme-resolu |
| 10 | `thm-012` | 0.6633 | sec-v | sec-v-sub-1 |

**Diversity (§6)**: sec-vi has 6 candidates (cap 3) → keep `thm-019`,
`exo-001`, `act-036`; **reject** `thm-018`, `act-035`, `exo-001-correction`
(rank 4th–6th within that section). sec-v has 4 candidates (cap 3, and
all 4 additionally share subsection `sec-v-sub-1`, cap 2) → subsection cap
binds first: keep `rem-001`, `thm-014`; **reject** `act-027` and
`thm-012` (3rd/4th in that subsection).

**Selected seeds** (5): `thm-019`, `exo-001`, `act-036`, `rem-001`,
`thm-014`.

**Expansion (§5)**: `exo-001`'s related `thm-019` and `act-036`'s related
`thm-019` are both **already present** as an independent seed → deduped,
no new chunks added. `thm-019`, `rem-001`, `thm-014` are not
exercise/activity → E2 does not apply to them as triggers. **No
expansion chunks in this example** — a clean, real illustration that
concept chunks scoring well on their own merit need no artificial
support.

**Rejected candidates and why**: `thm-018`/`act-035`/`exo-001-correction`
— section-cap diversity; `act-027`/`thm-012` — subsection-cap diversity
(a stricter, earlier-binding cap than the section cap here).

**Final ordered context** (5 chunks, no clusters larger than 1, so
ordering is pure seed-score descending): `thm-019` (0.7486) → `rem-001`
(0.7056) → `thm-014` (0.6971) → `exo-001` (0.6912) → `act-036` (0.6890).

**Provenance** (illustrative for the top chunk): `{chunk_id:
"chunk-...-thm-019", score: 0.7486, inclusion_reason: "semantic_match",
section_id: "...sec-vi...", subsection_id: null, content_role:
"statement", item_types: ["theorem"], has_uncertain_content: false,
review_status: "NOT_REQUIRED", has_potential_figure: false}`.

---

### Example B — an exercise-oriented question

**Query**: *"Comment étudier les variations d'une fonction ?"* (the exact
query used in the Phase 13 completion report, re-run here with a wider
`top_k=10` for this example).

**Real semantic search candidates** (top 10, actually executed):

| rank | chunk_id | score | section | item_types | related |
|---|---|---|---|---|---|
| 1 | `exo-013` | 0.5924 | exercices-et-problemes | exercise | (none) |
| 2 | `exo-028` | 0.5921 | exercices-et-problemes | exercise | `thm-019` |
| 3 | `act-011` | 0.5816 | ii-branches-infinies | activity | `prop-001` |
| 4 | `exo-001` | 0.5734 | sec-vi | exercise | `exo-001-correction`, `thm-019` |
| 5 | `exo-029` | 0.5685 | exercices-et-problemes | exercise | `thm-019` |
| 6 | `act-032` | 0.5673 | sec-v | activity | `thm-017` |
| 7 | `exo-003` | 0.5639 | exercices-et-problemes | exercise | `thm-019` |
| 8 | `act-035` | 0.5618 | sec-vi | activity | `thm-018` |
| 9 | `exo-001-correction` | 0.5604 | sec-vi | exercise/correction | `exo-001` |
| 10 | `rem-001` | 0.5590 | sec-v | remark | (none) |

**Diversity (§6)**: `"exercices-et-problemes"` has 4 candidates
(`exo-013`, `exo-028`, `exo-029`, `exo-003`) — cap 3 → **reject** `exo-003`
(0.5639, 4th by score in that section). All other sections stay at or
under both caps.

**Selected seeds after diversity** (8 remain — already at
`max_context_chunks` before any expansion): `exo-013`, `exo-028`,
`act-011`, `exo-001`, `exo-029`, `act-032`, `act-035`,
`exo-001-correction`.

**Expansion (§5), processed in score order**:
- `exo-028` (exercise) → related `thm-019` (theorem), not yet present →
  **expand: add `thm-019`**.
- `act-011` (activity) → related `prop-001` (property), not yet present →
  **expand: add `prop-001`**.
- `exo-001` → related `thm-019` already present (just added above) →
  deduped, no new chunk.
- `exo-029` → related `thm-019` already present → deduped.
- `act-032` (activity) → related `thm-017` (theorem), not yet present →
  **expand: add `thm-017`**.
- `act-035` (activity) → related `thm-018` (theorem), not yet present →
  **expand: add `thm-018`**.
- `exo-001-correction` (correction) → E1 mandatory pair: its statement
  `exo-001` is already present → deduped, no new chunk.

**Budget (§12)**, walking clusters in seed-score order, whole-cluster-only,
`max_context_chunks=8`: `exo-013`(1, running 1) → `exo-028`+`thm-019`(2,
running 3) → `act-011`+`prop-001`(2, running 5) → `exo-001`(1, running 6)
→ `exo-029`(1, running 7) → `act-032`+`thm-017`(2, running **9 — exceeds
8**) → **cluster rejected, stop here.**

**Rejected candidates and why**: `exo-003` — section-cap diversity;
`act-035`+`thm-018` and `exo-001-correction` and `rem-001` — never
reached; the budget walk stops at the first over-limit cluster
(`act-032`+`thm-017`) per §12's explicit "no back-filling" rule, even
though the smaller, later `exo-001-correction` cluster (size 1) would
technically have fit in the single remaining slot.

**Final ordered context** (7 chunks): cluster order by seed score, members
within a cluster ordered by `order` ascending — `exo-013` → [`thm-019`
(order 58), `exo-028` (order 95)] → [`prop-001` (order 14), `act-011`
(order 15)] → `exo-001` → `exo-029`.

This example demonstrates the task's own target outcome directly and
without any query-text classification: a literal exercise-phrased query
still surfaces two concept chunks (`thm-019`, `prop-001`) that never
appeared in the raw top-10 semantic candidates at all — purely because
the actually-matched exercises reference them.

---

### Example C — a question involving a figure

**Query**: *"Comment étudier les branches infinies d'une courbe
représentative à partir de son graphique ?"*

**Real semantic search candidates** (top 10, actually executed):

| rank | chunk_id | score | section | item_types | figure_refs | related |
|---|---|---|---|---|---|---|
| 1 | `prop-001` | 0.5975 | ii-branches-infinies | property | no | `act-008`,`act-009`,`act-010`,`act-011` |
| 2 | `act-012` | 0.5969 | ii-branches-infinies | activity | **yes** (`fig-activite4`) | `prop-002` |
| 3 | `exo-008` | 0.5929 | exercices-et-problemes | exercise | **yes** (`fig-ex7`) | `thm-016` |
| 4 | `act-008` | 0.5908 | ii-branches-infinies | activity | **yes** (`fig-act1`) | `prop-001` |
| 5 | `exo-015` | 0.5891 | exercices-et-problemes | exercise | **yes** (`ex13-courbes`) | `thm-019` |
| 6 | `exo-014` | 0.5844 | exercices-et-problemes | exercise | no | `thm-016` |
| 7 | `exo-016` | 0.5765 | exercices-et-problemes | exercise | no | (none) |
| 8 | `prop-002` | 0.5756 | ii-branches-infinies | property | no | `act-012`,`qst-007` |
| 9 | `act-011` | 0.5623 | ii-branches-infinies | activity | no | `prop-001` |
| 10 | `act-029-part2` | 0.5535 | sec-v | activity | no | `thm-015` |

**Diversity (§6)**: `"ii-branches-infinies"` has 5 candidates (`prop-001`,
`act-012`, `act-008`, `prop-002`, `act-011`) — cap 3 → keep `prop-001`,
`act-012`, `act-008`; **reject** `prop-002` (0.5756) and `act-011`
(0.5623) *as independent seeds*. `"exercices-et-problemes"` has 4
(`exo-008`, `exo-015`, `exo-014`, `exo-016`) — cap 3 → keep `exo-008`,
`exo-015`, `exo-014`; **reject** `exo-016` (0.5765, 4th by score).

**Selected seeds after diversity** (7): `prop-001`, `act-012`, `exo-008`,
`act-008`, `exo-015`, `exo-014`, `act-029-part2`.

**Expansion (§5)**:
- `act-012` (activity) → related `prop-002` (property), not present →
  **expand: add `prop-002`** — note this is the *same* `prop-002` that
  was just rejected as an independent seed by the section cap; it is
  legitimately re-admitted here because diversity caps govern independent
  seeds, not expansions (§6's explicit rule).
- `exo-008` (exercise) → related `thm-016`, not present → **expand: add
  `thm-016`**.
- `act-008` (activity) → related `prop-001`, already present (top seed) →
  deduped.
- `exo-015` (exercise) → related `thm-019`, not present → **expand: add
  `thm-019`**.
- `exo-014` (exercise) → related `thm-016`, already present (from
  `exo-008`) → deduped.
- `act-029-part2` (activity) → related `thm-015`, not present → would
  expand, but never reached (see budget below).

**Budget**, walking in seed-score order: `prop-001`(1, running 1) →
`act-012`+`prop-002`(2, running 3) → `exo-008`+`thm-016`(2, running 5) →
`act-008`(1, running 6) → `exo-015`+`thm-019`(2, running **8 — exactly at
limit, fits**) → `exo-014`(1, running **9 — exceeds 8, cluster rejected,
stop**).

**Rejected candidates and why**: `act-011` — section-cap diversity;
`exo-016` — section-cap diversity; `exo-014` — own seed cut by budget
(despite surviving diversity); `act-029-part2`+`thm-015` — never reached.

**Final ordered context** (8 chunks): `prop-001` → [`act-012` (order 16),
`prop-002` (order 17)] → [`thm-016` (order — precedes `exo-008`),
`exo-008`] → `act-008` → [`thm-019` (order 58), `exo-015` (order 82)].

**Figure handling (§9), the point of this example**: four selected chunks
carry a real `figure_refs` entry — `act-012` (`fig-activite4`), `exo-008`
(`fig-ex7`), `act-008` (`fig-act1`), `exo-015` (`ex13-courbes`). **Every
one** is reported in provenance as `has_potential_figure: true,
reconstructed_figure_id: "<the string above>", figure_id: null` — never a
resolved `figure_id`, never an image path — because every real figure
association in this chapter is still `REVIEW_REQUIRED`/`PENDING` (§2/§9),
and F2/F4's confirmed-and-high-confidence condition is never met today.
This is the design working exactly as intended given the real, current
state of Human Review — conservative, not silently wrong.

---

## 18. Complexity considerations

The whole pipeline (§4–§12) is a handful of linear passes over at most
`RAG_CANDIDATE_TOP_K` (20) candidates — no iterative graph traversal, no
recursive expansion (expansion is exactly one level deep, capped at 1 per
seed, §5), no per-query classification model. At the current real scale
(102 chunks/chapter), every step completes in well under a millisecond of
pure Python work on top of the already-fast Semantic Search query. Nothing
in this design requires revisiting as the corpus grows to many chapters,
since every rule operates within a single chapter's candidate set
(`chapter_id` stays mandatory, inherited unchanged from Phase 13).

## 19. Failure modes

- A `chunk_id` present in a search/expansion candidate but missing from
  `knowledge_chunks.json` (the exact orphan case Phase 13 already
  handles at the search layer) — this phase inherits that same
  exclude-with-warning behavior for any additional field it reads from
  that file, never crashing over one bad pointer.
- `SearchIncompatibleModelError` (dimension/model-revision
  misconfiguration, Phase 13) propagates unchanged — this phase does not
  swallow or reinterpret it.
- A cluster whose single top-scoring member alone exceeds
  `max_context_chars` — handled by §12's explicit, narrow "top cluster
  always survives in full" exception, with the overshoot reported rather
  than hidden.
- All candidates diversity-rejected down to zero (a pathological, not yet
  observed case) — an empty context with a diagnostic, per §13, not an
  error.

## 20. Explicit out-of-scope items

LLM selection and invocation; prompt construction/templating; answer
generation; ML/LLM-based reranking (no evidence in this design justifies
one — every selection mechanism proposed is deterministic and rule-based,
per the task's own instruction); FastAPI; Spring Boot integration; Angular
integration; chat/conversation state; multi-turn context carryover; actual
image/figure delivery to a multimodal model (§9/F3); query-intent
classification (§7); token-budget calibration against a specific LLM's
tokenizer (§12); cross-chapter/global context assembly (Semantic Search
itself doesn't support this by default either, per
`semantic_search_design.md` §11 — inherited, not revisited here).

## 21. Recommended test strategy for the future implementation

Following this project's own established convention (`unittest`,
synthetic fixtures for deterministic unit coverage, the real Chapter 1
corpus reserved for one end-to-end regression test):

1. Selection: a seed with no expansion-eligible relation stays a
   1-chunk cluster.
2. E1: a correction candidate always pulls its statement; the reverse
   never happens automatically.
3. E2: an exercise/activity seed pulls at most one concept chunk, chosen
   deterministically by smallest `order` when multiple qualify.
4. E2 asymmetry: a theorem/property/definition seed never gains an
   automatic exercise expansion.
5. Dedup: an expansion target already present as an independent seed
   contributes no duplicate.
6. Diversity: section cap rejects the correct (lowest-scoring-over-cap)
   candidates, preserving higher scores.
7. Diversity: subsection cap binds correctly when `subsection_id` is
   non-null; `null`-subsection chunks are governed by the section cap
   only.
8. Diversity does not re-filter expansion chunks (the `prop-002` pattern
   from Example C, reproduced with a synthetic fixture).
9. Budget: whole-cluster-only inclusion; the first over-limit cluster
   stops the walk without back-filling a smaller later one.
10. Budget: the single top cluster always survives even when it alone
    exceeds the character budget.
11. Ordering: cluster order follows seed score descending; within-cluster
    order follows the `order` field ascending, verified in both the
    "concept precedes application" and "correction follows statement"
    real directions.
12. Figure handling: a `figure_refs` entry with `figure_id: null` never
    produces a resolved `figure_id` in provenance; a synthetic
    `CONFIRMED`+`"high"`-confidence fixture does.
13. Uncertainty: `has_uncertain_content: true` and `review_status:
    "REVIEW_REQUIRED"` chunks are included, correctly flagged, never
    excluded or score-adjusted; a synthetic `HUMAN_REJECTED` chunk is
    excluded.
14. No-result paths: empty chapter, over-narrow filters, and
    all-candidates-diversity-rejected each produce an empty context with
    a diagnostic, never an exception, never fabricated content.
15. Determinism: the same synthetic candidate set run twice produces a
    byte-identical final context (order, provenance, and all).
16. One real, real-Chapter-1 regression test reproducing Example B or C
    exactly, skipped (not failed) if the real model/DB aren't available
    in the running environment — mirroring
    `TestChapter1RealSearchIntegration`'s own established pattern.

---

## Final summary

1. **File created**: `data/schema/rag_context_design.md` (this document)
   — nothing else.
2. **Proposed architecture**: a single deterministic Python transformation
   layer, downstream of the existing, unchanged `search_embeddings.search()`
   — over-fetch candidates → apply two narrow, capped, directional
   expansion rules (correction-completion, concept-support) → apply
   greedy score-preserving diversity caps (per-section, per-subsection) →
   order into concept/application or question/answer clusters using the
   chunk's own existing `order` field → fill a character/chunk budget
   greedily by whole clusters only, with a narrow top-cluster-always-
   survives exception → attach full provenance (including a whole-context
   `source_chunks_hash`) to every chunk. No new database table, no new
   embedding model, no new LLM, no ML/LLM-based reranking.
3. **Assumptions discovered** (reported, not silently designed around):
   `illustrates` relations are fully defined in the schema but **zero
   real instances exist** — apparently gated on Human Review confirmation
   that hasn't happened yet for any of the 19 real figure associations,
   all still `REVIEW_REQUIRED`/`PENDING`. Every real chunk `figure_refs`
   entry has `figure_id: null` and `confidence: null` — only the raw,
   unconfirmed `reconstructed_figure_id` is real data today. Nearly half
   of real chunks (48%) have `subsection_id: null`. `content_role` is
   overwhelmingly `statement` (101/102) — the design's content-role
   handling is necessarily light on real differentiation today, by honest
   necessity, not oversight. `has_uncertain_content` is `false` on all 102
   real chunks — that branch of the design is unexercised by current data
   but specified for a future chapter that may need it.
4. **Missing information that would sharpen (not block) this design**: no
   real chapter currently has `has_uncertain_content: true`, so §10's
   metadata-flagging behavior is unverified against real positive cases;
   no figure association has ever reached `CONFIRMED`, so §9's F2/F4
   "resolved and high-confidence" branch is unverified against a real
   positive case; no second chapter exists yet, so cross-chapter
   corpus-scale assumptions in §18 rest on a single chapter's real
   distribution. None of these block this design — each rule is specified
   precisely enough to implement and test today (§21, items 12–13 use
   synthetic fixtures specifically because no real positive case exists
   yet).
5. **No implementation was performed.** No `rag_context.py`, no test file,
   no API endpoint, no LLM call, no prompt, no frontend or backend code
   was created. Only the design document above.
