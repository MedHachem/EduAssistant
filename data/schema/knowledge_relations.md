# Knowledge Relations — Design Document

Status: **proposal, not implemented**. No relations code exists yet. This
document and `knowledge_relations.schema.json` are the full deliverable for
this design phase (Phase 9). Nothing here modifies the normalized
knowledge, the enrichment file, the source knowledge JSON, figure
detection, the Human Review UI/database, or implements Chunking,
Embeddings, a Vector DB, or Semantic Search.

## 0. What was inspected before designing this

- **`links.definitions/theorems/properties/formulas/methods/exercises`**
  (the cross-item reference arrays already present in every normalized
  item, per `knowledge_item.schema.json`): confirmed **empty on all 100
  items** — zero cross-item links exist anywhere in the current data. Only
  `links.figures` has real content (19 entries, the reconstruction's own
  `<figure id="...">` references — a different mechanism from the
  figure↔knowledge association pipeline, as already noted in
  `knowledge_enrichment.md`). This confirms Relations is genuinely
  greenfield: nothing to migrate, nothing already computed to reconcile.
- **The real enrichment `concepts` field**: 27 distinct concepts across
  100 items. The three most common — "continuité" (31 items), "exercices
  et problèmes" (31 — the coarse bucket topic, not a real concept for
  linking purposes), "intervalles" (30) — confirm concept-sharing is
  common enough to be useful, but naive all-pairs linking within a shared
  concept would be noisy (see §1).
- **A real, fully-traced concept cluster** (`concept = "branches
  infinies"`, 12 items, sorted by `order`):
  `act-008(11), act-009(12), act-010(13), prop-001(14), act-011(15),
  act-012(16), prop-002(17), qst-007(67), exo-008(75), exo-012(79),
  exo-014(81), exo-015(82)`.
  Reading `act-008`'s content (a graphed function with described
  asymptotes) against `prop-001`'s content (the general branches-infinies
  property) confirms this is a REAL pedagogical link, not a coincidental
  keyword match — `act-008` is exactly the kind of guided activity that
  leads into `prop-001`'s formal statement. This cluster is used as the
  worked example throughout (§2) precisely because it exposes the real
  design problem: items 67-82 are 50+ reading positions away from the
  nearest theorem/property — still the same nominal concept, but a much
  weaker, more speculative link (§3, confidence tiers).
- **The figure↔knowledge association output**
  (`data/output/<chapter_id>/associations/figure_knowledge.json`) and the
  **persisted Human Review model** (`backend/.../FigureKnowledgeReview`):
  re-confirmed as the intended source for the `illustrates` relation type
  (§1). Checked the actual current state: **0/19 Chapter 1 figures are
  AUTO_MATCH, and no human review session has persisted any CONFIRMED/
  REASSIGNED decision yet** — so `illustrates` would currently produce
  **zero relations** for Chapter 1 until a human actually reviews the 19
  figures. This is reported honestly (§10) rather than papered over.

## 1. What "Relations" means here, and what was deliberately excluded

A **directed edge** between two knowledge graph nodes (a knowledge item, or
a figure), typed, scored, and — like every other semi-automatic field in
this project — carrying its own provenance and review status. Two types
made the v1 cut; three candidates were considered and rejected:

| Candidate | Included? | Why |
|---|---|---|
| `illustrates` (figure → item) | **Yes** | Already has a real, validated confidence signal to build on: the figure↔knowledge association's own decision/score, refined further by actual human review once it happens. Not a new inference — a formalization of a decision that already exists (or will exist) elsewhere. |
| `applies_concept` (exercise/activity → theorem/property/definition) | **Yes** | Directly grounded in the real "branches infinies" cluster (§0): a deterministic reading-order + shared-concept rule reconstructs the genuine pedagogical structure (activity leads into theorem; exercises practice it afterward) without inventing anything not already in `concepts`/`order`. |
| `shares_concept` (item ↔ item, symmetric) | **No** | Would require materializing up to C(12,2)=66 pairwise edges for the "branches infinies" cluster alone, purely restating information the enrichment `concepts` field *already* provides as a queryable index. An edge list adds cost (storage, validation, staleness) without adding information over "filter items where `'branches infinies' in concepts`". Recommendation: query `concepts` directly; do not materialize this as a relation. |
| `prerequisite_of` (concept ↔ concept, or item ↔ item) | **No — deferred, LLM_REQUIRED** | Checked directly whether chapter/section ordering alone could safely proxy for prerequisite structure: sections ARE roughly sequential ("Rappels" before "Continuité et limite d'une fonction composée"), but a section boundary is an exposition order, not a verified dependency graph — asserting "concept A is a prerequisite of concept B" is a curriculum judgment, not a structural fact. Explicitly excluded from v1, same reasoning as `knowledge_enrichment.md`'s exclusion of `prerequisites` from Enrichment. A future, separate, human-curated concept-dependency table (not inferred from text) is the recommended path, not an LLM guess either. |

## 2. Example relations (real Chapter 1 data)

Using the "branches infinies" cluster from §0.

**`applies_concept`** — `act-008` (order 11) is 3 positions before `prop-001`
(order 14), the nearest item after it sharing the concept:

```json
{
  "relation_id": "rel-math-4eme-tome1-ch01-applies_concept-math-4eme-tome1-ch01-act-008-math-4eme-tome1-ch01-prop-001",
  "type": "applies_concept",
  "source_id": "math-4eme-tome1-ch01-act-008",
  "source_kind": "knowledge_item",
  "target_id": "math-4eme-tome1-ch01-prop-001",
  "target_kind": "knowledge_item",
  "confidence": "high",
  "generation_method": "rule_based",
  "review_status": "NOT_REQUIRED",
  "signals": { "shared_concepts": ["branches infinies"], "reading_order_distance": 3, "source_review_status": null }
}
```

Contrast with `exo-015` (order 82), 65 positions past the nearest
reference item `prop-002` (order 17) — same rule, much weaker evidence:

```json
{
  "relation_id": "rel-math-4eme-tome1-ch01-applies_concept-math-4eme-tome1-ch01-exo-015-math-4eme-tome1-ch01-prop-002",
  "type": "applies_concept",
  "source_id": "math-4eme-tome1-ch01-exo-015",
  "target_id": "math-4eme-tome1-ch01-prop-002",
  "confidence": "low",
  "generation_method": "rule_based",
  "review_status": "REVIEW_REQUIRED",
  "signals": { "shared_concepts": ["branches infinies"], "reading_order_distance": 65, "source_review_status": null }
}
```

**`illustrates`** — cannot be populated with a real Chapter 1 example yet
(§0): once a human confirms, say, `figure_012` → `math-4eme-tome1-ch01-thm-017`
in the review UI, the relation would be:

```json
{
  "relation_id": "rel-math-4eme-tome1-ch01-illustrates-figure_012-math-4eme-tome1-ch01-thm-017",
  "type": "illustrates",
  "source_id": "figure_012",
  "source_kind": "figure",
  "target_id": "math-4eme-tome1-ch01-thm-017",
  "target_kind": "knowledge_item",
  "confidence": "high",
  "generation_method": "human_confirmed",
  "review_status": "HUMAN_APPROVED",
  "signals": { "shared_concepts": [], "reading_order_distance": null, "source_review_status": "CONFIRMED" }
}
```

## 3. Field-by-field explanation

| Field | Why it's needed | Source / rule |
|---|---|---|
| `relation_id` | Stable, content-derived identity so a rerun with unchanged inputs is idempotent (no duplicate edges, no drifting IDs) — same principle as every other stable ID in this project. | `rel-<chapter_id>-<type>-<source_id>-<target_id>` string template. |
| `type` | Distinguishes the two structurally different kinds of edge this project actually has evidence for (§1). | Enum, fixed at v1: `illustrates`, `applies_concept`. |
| `source_id`/`source_kind`, `target_id`/`target_kind` | A relation can point from a figure OR a knowledge item; making the kind explicit avoids ever needing to guess which ID space an id belongs to. | `source_kind`/`target_kind` are always known from which rule produced the relation (illustrates always figure→item; applies_concept always item→item). |
| `confidence` | Admin-facing, three-tier — never a raw number — mirrors the figure-association reviewer's own vocabulary exactly, so one review UI's conventions extend naturally to relations. | Derived from `reading_order_distance` (applies_concept) or from the source review's own status (illustrates) — see §4. |
| `generation_method` | Same auditability principle as Enrichment. `human_confirmed` is a genuinely new category here (not present in Enrichment) because `illustrates` can be sourced directly from a human's own review decision, not just an algorithm. | One of `deterministic`/`rule_based`/`human_confirmed`/`llm`/`not_populated`. |
| `review_status` | Nothing is silently trusted; mirrors every prior phase's convention. | `NOT_REQUIRED` for high-confidence rule_based relations; `REVIEW_REQUIRED` for low/medium confidence; a `human_confirmed` relation is already `HUMAN_APPROVED`. |
| `signals` | Explainable evidence, never hidden in one opaque score — same design choice as `associate_figures_knowledge.py`'s own `signals` object. | `shared_concepts`, `reading_order_distance`, `source_review_status` (only populated per relation type, `null` otherwise). |

## 4. Deterministic vs. rule-based vs. LLM classification

| Relation type | Class | Why |
|---|---|---|
| `applies_concept` | **RULE_BASED** | Explicit, documented rule: for each activity/exercise/example item, find the nearest theorem/property/definition (by `order`, either direction) sharing at least one `concepts` entry; `confidence` is a rule over `reading_order_distance` (`<=10` -> high, `<=30` -> medium, else low, thresholds chosen from the real cluster's own 3/50-65 distance spread in §0/§2, not guessed). Deterministic matching, not a raw lookup — hence rule_based, not deterministic. |
| `illustrates` (from AUTO_MATCH) | **RULE_BASED** | Directly reuses `associate_figures_knowledge.py`'s own existing decision — no new inference, just a format conversion into a Relation record. `confidence: "high"`, `review_status: "REVIEW_REQUIRED"` still (an AUTO_MATCH is algorithmically confident but not yet a human decision). |
| `illustrates` (from Human Review) | **HUMAN_CONFIRMED** (not really "generated" at all) | The relation's target IS a human's own decision (`FigureKnowledgeReview.status IN (CONFIRMED, REASSIGNED)`) — recorded, not inferred. `review_status: "HUMAN_APPROVED"` immediately. |
| `shares_concept` | *(excluded, §1)* | — |
| `prerequisite_of` | **LLM_REQUIRED** (deferred, not in v1) | Requires genuine curriculum/didactic judgment beyond structural ordering (§1). |

## 5. How to minimize Claude/LLM usage

Both v1 relation types are **fully deterministic/rule-based — zero LLM
calls** for all of Chapter 1's 100 items and 19 figures. The only deferred,
potentially-LLM-touching relation type (`prerequisite_of`) is explicitly
NOT scheduled (§1) until a concrete downstream need is confirmed, and even
then the recommended path is a small human-curated concept-dependency
table, not a per-chapter LLM call — the same "smallest justified subset,
cached, batched" philosophy from `knowledge_enrichment.md` §5 would apply
if that recommendation changes.

## 6. How relations remain generic for future chapters

- `applies_concept`'s rule operates purely on already-chapter-generic
  fields (`order`, `concepts`, `item_type`) — no chapter-specific
  vocabulary, section name, or item ID appears in the rule itself.
- `illustrates` operates purely on `figure_id`/`item_id` pairs already
  produced by the (already chapter-generic) association pipeline.
- The confidence-tier distance thresholds (10/30) are a property of
  "how far apart is too far to trust an unreviewed link", not of Chapter
  1's specific page count — reusable as-is; a future chapter with a
  different item density can revisit the constants without touching the
  rule's logic, exactly like `ASSOCIATION_AUTO_MATCH_THRESHOLD` etc. in
  `config.py`.
- Output path follows the exact established per-chapter convention:
  `data/output/<chapter_id>/relations/knowledge_relations.json`.

## 7. How Relations connects to Chunking (and stays bounded there)

- Chunking (future, not implemented) could use `applies_concept` edges to
  avoid separating an exercise from the theorem it applies when both fall
  near a chunk boundary, and `illustrates` edges to guarantee a figure and
  the item it illustrates are never split into different chunks/retrieval
  units.
- Relations does NOT itself decide chunk boundaries, embed anything, or
  touch a vector store — it only produces the typed edge list Chunking
  would later consume, same additive-only boundary every phase in this
  project has kept.

## 8. What should NOT be related

- **`shares_concept`** — excluded entirely (§1); query `concepts` instead.
- **Any pair of items whose only connection is the same coarse bucket
  section** ("Exercices et problèmes", "QCM - VRAI - FAUX") **without a
  shared concept** — section co-membership alone is not evidence of a real
  relationship (an exercise about limits and one about branches infinies
  both living in "Exercices et problèmes" are not related just because of
  that).
- **`prerequisite_of`** — deferred (§1), not modeled at all in v1, not even
  as a low-confidence field.
- **Figures with no chosen knowledge item** (`decision: NO_MATCH` or a
  human `REJECTED` review) — never produce an `illustrates` relation; the
  absence of a link is the correct, honest representation, not something
  to fill in with a low-confidence guess.
- **The normalized JSON's own `links.*` arrays** — Relations produces its
  own separate file; it does not write back into
  `data/output/<chapter_id>/normalized/knowledge.json`, preserving the
  established "normalized knowledge stays untouched" boundary. (A later,
  separate, explicitly-approved step could choose to materialize
  high-confidence relations into those existing empty arrays — not part
  of this design.)

## 9. Validation strategy

Mirrors `validate_enrichment.py` directly:

1. **Structural**: JSON Schema validation against
   `knowledge_relations.schema.json` (required fields, enum membership).
2. **Referential integrity**: every `source_id`/`target_id` of kind
   `knowledge_item` must exist in the normalized JSON; every `source_id` of
   kind `figure` must exist in `final_figures/index.json`; no relation may
   reference a figure whose association decision is `NO_MATCH` or whose
   human review is `REJECTED`.
3. **No duplicate relations**: `relation_id` uniqueness (their deterministic
   construction already prevents accidental duplicates on rerun, but a
   validator still checks it, same defense-in-depth as every prior
   validator in this project).
4. **Method/review consistency**: same hard rule as Enrichment — any
   `generation_method: "llm"` forces `review_status` away from
   `NOT_REQUIRED`; additionally, `generation_method: "human_confirmed"`
   requires `review_status: "HUMAN_APPROVED"` (never anything else — a
   human confirmation cannot be "pending review" of itself).
5. **Confidence/review consistency**: `confidence: "low"` must never carry
   `review_status: "NOT_REQUIRED"`.
6. Produces a `validation_report.json`, same shape/spirit as every prior
   phase's.

## 10. Recommended implementation plan

1. **`applies_concept` first** (`relate_knowledge.py`, when implementation
   is requested): fully self-contained within the normalized + enrichment
   files already on disk, zero dependency on the Human Review system
   actually having been used yet. Immediately testable against the real
   "branches infinies" cluster in §0/§2 as a regression fixture.
2. **`illustrates` second**, with an honest caveat already known before
   writing a line of code: **Chapter 1 currently has zero AUTO_MATCH
   figures and zero completed human reviews**, so this relation type would
   emit `[]` for Chapter 1 today. Implementing it is still worthwhile
   (chapter-generic, and future chapters — or a completed Chapter 1 review
   pass — would populate it immediately), but it should not be reported as
   "broken" if Chapter 1's own output is empty; that is the correct,
   current, honest state, not a bug.
3. Validate both against `knowledge_relations.schema.json` + the checks in
   §9 before considering this phase "done" — same review checkpoint every
   prior phase has used.
4. Do not schedule `prerequisite_of` (or reconsider `shares_concept`) until
   a concrete downstream feature (e.g. a "what should I review before this
   exercise" UI) is actually being built and needs it.
