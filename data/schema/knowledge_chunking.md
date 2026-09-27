# Knowledge Chunking — Design Document

Status: **proposal, not implemented**. No chunking code exists yet. This
document and `knowledge_chunk.schema.json` are the full deliverable for
this design phase (Phase 10). Nothing here modifies normalized knowledge,
enrichment, relations, figures, the Human Review system, or implements
Embeddings, a Vector DB, or Semantic Search. Zero LLM calls anywhere in
this design.

## 0. What was inspected before designing this

- **Item length distribution** (measured directly, character counts of
  `content` + `proof` + full `exercise_details` text, across all 100
  Chapter 1 items): median 460 chars, p90 1096, only **3 items exceed
  1500 chars**, only **1 exceeds 3000** (`exo-001`, 8126 chars, spanning
  pages 20-22). This is the central empirical fact the whole design rests
  on: **the overwhelming majority of items are already chunk-sized**;
  splitting is the rare exception, not the rule.
- **`exo-001`'s own structure**: 2 top-level `exercise_details.questions`
  ("I", "II"), 6 total leaf sub-questions, plus a `correction` with
  `present_in_source: true` (3022 chars) — the ONLY item in the whole
  chapter with a real correction. A natural, structurally-justified split
  point already exists (§4) without inventing one.
- **A real, concrete "same source exercise split across two items" case**,
  found by checking every `(type, section_id, bloc_numero)` group for
  duplicates: `exo-009` (bloc_numero "8", "Dans chacun des cas suivants,
  étudier la limite de la fonction f. ... 1. ... 2. ... 3. ...") and
  `exo-010` (bloc_numero **also** "8", content is only "4. $f: x \mapsto
  ...$ en 1.", page 25 immediately following `exo-009`'s page 24, `order`
  76 immediately followed by `order` 77) are genuinely two fragments of
  ONE source exercise, not two independent ones — confirmed by reading
  both items' content, not guessed. 9 OTHER `(type, bloc_numero)`
  collisions were also found and checked; all 9 turned out to be ordinary
  numero-reuse across **different** subsections (e.g. "Activité 1" exists
  once under section III.1 and again, independently, under III.2) with
  `order` gaps of 3-12 — never adjacent. This directly grounds the merge
  rule in §3: **same type + same bloc_numero + section_id + immediately
  consecutive `order` (difference of exactly 1)** isolates the one real
  case and excludes all 9 false positives, tested against the actual
  data, not assumed.
- **`links.definitions/theorems/properties/formulas/methods/exercises`**:
  confirmed still empty on all 100 items (per `knowledge_relations.md`
  §0) — chunking does not depend on them being populated.
- **`knowledge_relations.json`**: 67 real `applies_concept` edges, 0
  `illustrates` edges (Chapter 1 has no AUTO_MATCH figures or completed
  human reviews yet, per `knowledge_relations.md`). Chunking's figure/
  relation metadata is designed against this honest current state, not a
  hoped-for one (§6, §7).
- **`links.figures`**: 19 items carry a reconstruction-era figure
  reference (`reconstructed_figure_id`, `candidate_id: null`,
  `match_status: "unresolved"`) — a different, currently-unresolved
  mechanism from the association pipeline's own `figure_id` space (§6).

## 1. What should constitute a chunk?

The smallest unit that is **(a) pedagogically self-contained** (a student
or retrieval system reading it alone gets a complete thought — a full
theorem statement, a full activity, a full exercise statement) and **(b)
traceable to exact source item(s) and page(s)**. A chunk is defined by
`source_item_ids` (1 or more normalized item ids) + `content_role`
(`statement` or `correction`) + an optional `part_index` — never by a
character/token count. Size is only ever a trigger for considering a
split (§4), never the boundary itself.

## 2. Should one item normally map to one chunk?

**Yes — the default, and (per §0) true for 96-97 of Chapter 1's 100
items.** A definition, theorem, property, remark, or an activity/exercise
short enough to need no split, becomes exactly one `statement` chunk. This
is the simplest possible rule and matches the data: median item is 460
chars, comfortably one coherent, retrievable unit.

## 3. When should multiple items be grouped into one chunk?

**Only for a confirmed fragmentation repair, never for merely "related"
items.** Concept-sharing alone (`applies_concept`, §7) is surfaced as
**metadata** (`related_chunk_ids`), not a merge — merging `act-008`
through `act-012` and `prop-001`/`prop-002` (all sharing "branches
infinies", per `knowledge_relations.md`) into one chunk would destroy
their individual page/item traceability for no real benefit; each is
already a complete, retrievable unit on its own (§0, §2).

The ONE merge case with real evidence (§0): two items are merged when ALL
of — same `type`, same `section_id`, same `provenance.bloc_numero`,
`order` differs by exactly 1 — hold. In Chapter 1 this fires exactly
once (`exo-009` + `exo-010`). `source_item_ids` then lists both, in
`order`; `pdf_pages` is their union; `review_status` is forced to
`REVIEW_REQUIRED` (a merge is a judgment call, never `NOT_REQUIRED`).

## 4. When must an item be split into multiple chunks?

Only when **both** hold: total text exceeds a size threshold (proposed:
1500 characters — chosen because exactly 3 Chapter 1 items cross it, and
inspecting all 3 confirmed each has genuine internal structure to split
on, never a threshold picked to hit a target chunk count) **and** the item
has 2+ top-level `exercise_details.questions` entries to split along. Each
top-level question (with its own sub-questions) becomes one `statement`
chunk, `part_index`/`part_count` set, `source_item_ids` unchanged (still
the one original item — a split is not a merge in reverse; the item
itself was never fragmented upstream, only large). If NO structural split
point exists on an oversized item, it is NOT force-split by character
count (no such case exists in Chapter 1 to even test, honestly — see §13)
— the design leaves it as one (large) chunk rather than cutting
mid-sentence, and flags `review_status: REVIEW_REQUIRED` so a human can
judge if the chapter-specific case actually needs a manual split.

A `correction` (§0: only `exo-001` has one) is **always** its own
separate chunk, regardless of whether its parent item was also split by
question (§5, §12).

## 5. Definitions, properties, theorems, examples, activities, exercises

- **Definition / theorem / property / remark**: always exactly one
  `statement` chunk (never split — none exceeded the threshold in
  Chapter 1; these are inherently short, self-contained statements).
- **Activity / exercise / example**: one `statement` chunk by default;
  split only per §4; a `correction` (when `present_in_source: true`)
  always becomes its own separate chunk, `related_chunk_ids` pointing
  back to its statement part(s) so a consumer can choose to include or
  withhold the solution.
- `content_role` is the only field distinguishing these — no separate
  chunk "types" per item type, keeping the schema uniform (§ — see
  `knowledge_chunk.schema.json`'s single `Chunk` shape).

## 6. How figures are referenced from chunks

Two sources, both explicit about their own reliability (never conflated):

1. **`links.figures`** (from the source item, always available): copied
   through as `{source: "links.figures", reconstructed_figure_id, figure_id:
   null, confidence: null}` — honestly `null` for `figure_id`/`confidence`
   today, since `candidate_id` is always `null`/`unresolved` in the current
   data (§0). Still useful provenance (a human knows a figure belongs here
   even before it's resolved to a real image).
2. **`relation:illustrates`** (from `knowledge_relations.json`, when it
   exists): `{source: "relation:illustrates", figure_id: "<real
   final_figures id>", confidence: "high"|"medium", reconstructed_figure_id:
   null}` — a real, renderable image reference. **Currently zero for
   Chapter 1** (§0) — reported honestly, not worked around.
An unreviewed, low-confidence association candidate (`REVIEW_REQUIRED`/
`NO_MATCH` decisions never reviewed by a human) is **never** surfaced in
`figure_refs` — only an `AUTO_MATCH` or human-confirmed relation qualifies,
same trust boundary `knowledge_relations.md` already established.

## 7. How relations influence chunk boundaries or metadata

**Metadata only — relations never change chunk boundaries** (§3). Every
`knowledge_relations.json` edge (`applies_concept` or `illustrates`) whose
`source_id`/`target_id` matches one of a chunk's `source_item_ids` is
resolved to the chunk NOW containing that id and added to
`related_chunk_ids`. This keeps chunk granularity purely structural
(§1-§4) while still exposing the pedagogical graph for a future retrieval
step to walk (e.g. "also show the theorem this exercise applies").

## 8. How section/subsection hierarchy is preserved

Every chunk carries `section_id`/`subsection_id` (from its source item(s),
required to agree for a merge, §3) **and** the denormalized
`section_title`/`subsection_title` — same convenience pattern already
established by Enrichment's `topics` field, so a consumer never needs a
second lookup into the normalized JSON just to display a human-readable
location.

## 9. How source pages and original item IDs are preserved

`source_item_ids` (never regenerated, always the normalized item's own
stable id) and `pdf_pages` (the union of every source item's own
`provenance.pdf_pages`, ascending) are **required** fields on every chunk
— this is the chunk's entire reason for existing as a separate,
independently-schema'd file rather than being folded into normalization:
provenance must survive chunking exactly as well as it survived
normalization and enrichment.

## 10. How chunk IDs remain stable and deterministic

`chunk-<chapter_id>-<source_item_ids joined by "+">[-part<N>|-correction]`
— fully content-derived, no counter, so re-running chunking on unchanged
inputs reproduces byte-identical ids. A merge's id
(`...-exo-009+exo-010`) is still deterministic regardless of merge
detection order, since `source_item_ids` is always sorted by `order`
before joining.

## 11. How chunks support future RAG/semantic search

`text` is the exact string a future embedding step would consume — but
**this design does not choose an embedding model, a token limit, or a
vector store** (explicitly out of scope). What it DOES provide, ready for
that future phase: a stable `chunk_id` to key any embedding by; `topics`/
`concepts` as retrieval filters; `figure_refs`/`related_chunk_ids` so a
retrieved chunk can pull in its supporting figure or linked
theorem/correction; `has_uncertain_content` so a consumer can down-rank or
flag chunks whose source had OCR/reconstruction uncertainty.

## 12. How to avoid duplicated information between chunks

- A `correction` is never duplicated inside its statement chunk's `text`
  (§4/§5) — one `content_role` per concept, not copy-pasted into both.
- A merged chunk's `text` is assembled ONCE from both source items in
  order — never each item separately AND a merged copy.
- `related_chunk_ids` are references (chunk_id strings), never
  duplicated `text` from the related chunk.
- Enrichment's `concepts`/`topics` are **unioned and deduplicated**
  across `source_item_ids` for a merged chunk — a shared concept isn't
  listed twice just because both source items independently carried it.

## 13. Very short and very long items

- **Very short** (§0's minimum: 53 chars, `prop-003`, "La composée de
  deux fonctions continues est continue."): kept as its own full chunk,
  never merged with a neighbor purely for size — inspecting the actual
  shortest items in Chapter 1 found every one of them is already a
  complete, self-contained mathematical statement, not a truncated
  fragment (unlike the genuine `exo-009`/`exo-010` fragmentation, which
  was detected structurally in §3, not by length). Short is not, by
  itself, evidence of incompleteness.
- **Very long** (§0/§4): split when structural evidence exists; otherwise
  kept whole and flagged `REVIEW_REQUIRED` — no chapter in this design
  actually exercises the "long with no structure" case, so the rule is
  defined for genericity but honestly unverified against real data (see
  §14 risks).

## 14. Multi-page items

`pdf_pages` already carries every page an item (or merged pair) spans —
no special handling needed beyond what normalization already tracked
(§0: `exo-001` spans pages 20-22, `exo-009`+`exo-010` spans 24-25, both
handled by the union rule in §9 with no extra logic).

## 15. Uncertainty/provenance from previous phases

`has_uncertain_content` is a plain OR of every source item's
`uncertainty.has_uncertain_markers`/`has_gap_markers` (currently always
`false` in Chapter 1 — honestly reported, not fabricated evidence of
uncertainty that isn't there). Full provenance (`source_item_ids`,
`pdf_pages`, section/subsection) is carried at the chunk level precisely
so a chunk can never be traced back LESS precisely than its source
item(s) already were.

## Field-by-field classification

| Field | Class | Why |
|---|---|---|
| `chunk_id` | DETERMINISTIC | Pure string template over already-decided fields. |
| `order`, `pdf_pages`, `section_id`/`subsection_id`(+titles), `source_item_ids`, `item_types` | DETERMINISTIC | Direct lookups/unions from normalized data. |
| `content_role`, `part_index`/`part_count` | RULE_BASED | Decided by the split/merge/correction rules in §3-§5. |
| `text` | DETERMINISTIC | Concatenation of already-existing fields, in a fixed order, never rewritten. |
| `topics`, `concepts` | RULE_BASED | Direct union of Enrichment's own already-rule_based fields (no new inference here, just aggregation across `source_item_ids`). |
| `figure_refs` | DETERMINISTIC (links.figures) / carries through Relations' own classification (relation:illustrates) | Pure lookup either way — see §6. |
| `related_chunk_ids` | RULE_BASED | Resolving a Relations edge's item-id endpoint to "whichever chunk now contains it" is a small but real rule (item-to-chunk lookup), not a raw copy. |
| `has_uncertain_content` | DETERMINISTIC | Boolean OR over already-existing fields. |
| `review_status` | RULE_BASED | Forced to `REVIEW_REQUIRED` for any merge, split, or low/medium-confidence figure ref; `NOT_REQUIRED` otherwise. |
| generation_methods themselves | DETERMINISTIC | The classification is fixed by which rule produced each field, not computed per-chunk. |

**Nothing in this design is LLM_REQUIRED.** No field here needs semantic
interpretation beyond the explicit, evidenced rules above — consistent
with the strong deterministic-first preference and every prior phase in
this project.

## Representative chunks (Chapter 1)

See `knowledge_chunk.schema.json`; all 5 below were validated against it
directly (`jsonschema.Draft202012Validator`, zero errors):

1. **`chunk-math-4eme-tome1-ch01-math-4eme-tome1-ch01-act-008`** — a plain
   whole-item chunk (activity, one figure_ref from `links.figures`, one
   `related_chunk_ids` entry pointing at `prop-001` via the real
   `applies_concept` edge from `knowledge_relations.json`).
2. **`chunk-math-4eme-tome1-ch01-math-4eme-tome1-ch01-prop-001`** — the
   theorem-like counterpart `act-008` applies, linked back symmetrically.
3. **`chunk-math-4eme-tome1-ch01-math-4eme-tome1-ch01-exo-009+math-4eme-tome1-ch01-exo-010`**
   — the one real merge case, `pdf_pages: [24, 25]`, `review_status:
   REVIEW_REQUIRED`.
4. **`chunk-math-4eme-tome1-ch01-math-4eme-tome1-ch01-exo-001-part0`** —
   one split part of the chapter's only oversized item, `part_index: 0`,
   `part_count: 2`, linked to its sibling part and its correction.
5. **`chunk-math-4eme-tome1-ch01-math-4eme-tome1-ch01-exo-001-correction`**
   — the chapter's only real `correction` chunk.

## Expected chunk count for Chapter 1

100 source items → **-1** (the one merge, §3) → **+2** (`exo-001` splits
into 2 statement parts, §4) → **+1** (`exo-001`'s correction, §5) → **+2
to +4** (`act-029` and `exo-031`, the other two items over the 1500-char
threshold, split into 2-3 parts each if the threshold/rule from §4 is
applied uniformly) ≈ **approximately 104-108 chunks**. Reported as a
range, not a precise figure, since the exact split count for `act-029`/
`exo-031` depends on threshold tuning not yet locked in (this is a design
document, not a run).

## Risks / edge cases

- **Threshold tuning is untested beyond Chapter 1.** The 1500-char split
  threshold and the exactly-3-item split count are specific to this
  chapter's actual content; a future chapter with denser exercises could
  see a very different split rate. Recommend re-measuring length
  distribution per chapter before implementation, not hardcoding 1500.
- **The merge rule is narrow by design** (order-difference-of-exactly-1)
  and would miss a fragmentation spanning 3+ items, or one with a
  non-adjacent order due to an intervening banner/decorative element —
  none observed in Chapter 1, but worth a follow-up check on a denser
  future chapter.
- **`figure_refs` is currently thin** for Chapter 1 (`links.figures` only,
  zero `illustrates` edges) — a future chunking RUN (not this design)
  should re-derive `figure_refs` after Chapter 1's human review is
  actually completed, not rely on this design-time snapshot.
- **No chapter has yet exercised the "long item with no structural split
  point" case** (§4/§13) — the rule for it is defined but genuinely
  untested against real data; flag for re-validation once a chapter with
  such an item is processed.

## Explicitly out of scope (this phase and beyond)

Embeddings, vector store, semantic search, chunk size/token-limit tuning
for any specific embedding model, LLM-based semantic chunking or
summarization, modifying normalized knowledge/enrichment/relations,
figure detection/completeness, and the Human Review system.
