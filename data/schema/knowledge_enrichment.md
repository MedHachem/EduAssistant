# Knowledge Enrichment — Design Document

Status: **proposal, not implemented**. No enrichment code exists yet. This
document and `knowledge_enrichment.schema.json` are the full deliverable for
this design phase (Phase 8). Nothing here modifies the normalized knowledge,
the source knowledge JSON, figure detection, the Human Review UI/database,
or implements Relations, Chunking, Embeddings, a Vector DB, or Semantic
Search.

## 0. What was inspected before designing this

The real normalized Chapter 1 output
(`data/output/math-4eme-tome1-ch01/normalized/knowledge.json`), not assumed:

- **Type distribution**: `exercise` 40, `activity` 36, `theorem` 19,
  `property` 3, `definition` 1, `remark` 1 — no `formula`/`method`/`example`
  actually occur in this chapter (consistent with `knowledge_schema.md`'s
  own finding #4).
- `display_label` is only ever non-null for `activity`/`exercise` items
  (they carry a `bloc_numero`; theorem/property/definition/remark never
  do in this source).
- **`proof`** is set on only 2/100 items (`thm-005`, `thm-014`) — one full
  derivation, one one-line "découle de..." reference.
- **`exercise_details.qcm_choices`** is real and populated (e.g.
  `math-4eme-tome1-ch01-qst-001`, choices A/B/C, `marked_correct_in_source`
  always `null` — the source never marks the answer).
- **Nested `questions`** go up to 3 levels deep in real data (e.g.
  `exo-001`: `I` → `1` → `a`/`b`), confirming the recursive `SubQuestion`
  shape is genuinely exercised, not just theoretical.
- **No difficulty markers exist in the source text** — checked directly for
  `(*)`/`**`-style markers (the common French-textbook convention); the two
  candidate matches found were false positives from `$\mathbb{R}^*$`, not
  difficulty stars. Confirms `difficulty` cannot be deterministic here (§4).
- **Sections are already a clean, human-authored topic taxonomy** (8 titles:
  "Rappels", "Branches infinies", "Continuité et limite d'une fonction
  composée", "Limites et ordre", "Image d'un intervalle par une fonction
  continue", "Image d'un intervalle par une fonction strictement monotone",
  "QCM - VRAI - FAUX", "Exercices et problèmes"). `activity` items map
  cleanly onto the first six (topic-specific). `exercise` items cluster
  overwhelmingly into the last two generic buckets (31 + 8 of 40) — these
  two sections are NOT specific enough to serve as a real topic tag for an
  individual exercise (§3, §4).
- **Real instruction verbs found in question/statement text** (counted, not
  guessed): "Montrer" (30), "Étudier" (9), "Tracer" (5), "Calculer" (4),
  "Justifier" (3), "Identifier" (2), "Donner"/"Trouver"/"Dresser"/
  "Expliciter"/"Lire" (1 each), plus "déduire" (as in "En déduire") appearing
  routinely. This grounds `reasoning_types` (§3) in actually-observed
  vocabulary, not an invented list.
- **The existing schema already has an unpopulated hook for exactly this
  kind of data**: `knowledge_item.schema.json`'s top-level `concepts: []`
  array and the `Concept` `$def` (`id`, `label`, `aliases`,
  `first_seen_item_id`) — currently always empty (0 concepts across all 100
  items). Enrichment's `concepts` field (§3) is designed to eventually feed
  that existing registry, not invent a parallel one.
- **The figure↔knowledge association output and the persisted Human Review
  model** were re-confirmed to operate purely on `figure_id`/`item_id`
  pairs and are untouched by anything proposed here.

## 1. Proposed enrichment schema (v1)

See `knowledge_enrichment.schema.json` for the full JSON Schema. Shape,
per normalized item:

```
{
  "item_id": "...",              // FK, reused verbatim
  "item_type": "...",            // denormalized copy, for readability
  "topics": [...],
  "keywords": [...],
  "mathematical_entities": { "functions": [...], "intervals": [...], "equations": [...], "notations": [...] },
  "exercise_type": "...",        // or null
  "reasoning_types": [...],
  "concepts": [...],
  "generation_methods": { <field>: "deterministic"|"rule_based"|"llm"|"not_populated" },
  "review_status": "NOT_REQUIRED" | "REVIEW_REQUIRED" | "HUMAN_APPROVED" | "HUMAN_REJECTED"
}
```

Stored **separately**, one file per chapter:
`data/output/<chapter_id>/enrichment/knowledge_enrichment.json` — mirroring
the exact convention already established for associations
(`.../associations/figure_knowledge.json`) and normalization
(`.../normalized/knowledge.json`). The normalized JSON is never modified;
an enrichment record is looked up by `item_id`, the same pattern the
figure↔knowledge association already uses to reference knowledge items
without merging into them.

**Fields considered and deliberately left OUT of v1** (see §4, §8):
`skills`, `pedagogical_intent`, `difficulty`, `learning_objectives` — no
justified deterministic or rule-based path exists for any of them in the
real data, and no concrete downstream consumer needs them yet. `difficulty`
and `learning_objectives` in particular were explicitly checked against the
source and found to have no textual anchor at all. They are documented as
future `OPTIONAL_LLM`/`LLM_REQUIRED` extensions (§4), not modeled as schema
fields today, so the schema doesn't carry structure nothing populates.
`prerequisites` is excluded entirely — it describes a relationship BETWEEN
items, which is explicitly the Relations phase's job, not Enrichment's (§7).

## 2. Example enriched item (real Chapter 1 data)

Source: `math-4eme-tome1-ch01-act-008` (already used as the normalization
example in `knowledge_normalization.md`, for continuity) — an activity in
section "Branches infinies", asking the reader to determine several limits
of a function whose graph (with asymptotes) is described in the linked
figure.

Normalized `content` (recap):
> "La courbe ci-contre est la représentation graphique d'une fonction f
> définie sur $]-\infty,-1[ \cup ]1,+\infty[$ . Les droites d'équations
> $x=-1$, $x=1$, $y=0$ et $y=-x-3$ sont des asymptotes à cette courbe.
> Déterminer $\lim_{x \to -\infty} f(x)$, ... et $\lim_{x \to +\infty} f(x)$."

Proposed enrichment record:

```json
{
  "schema_version": "enrichment-1.0",
  "algorithm_version": "enrich-v1",
  "generated_at": "2026-09-27T00:00:00Z",
  "chapter_id": "math-4eme-tome1-ch01",
  "item_id": "math-4eme-tome1-ch01-act-008",
  "item_type": "activity",
  "topics": ["Branches infinies"],
  "keywords": ["asymptote", "limite", "fonction"],
  "mathematical_entities": {
    "functions": ["f"],
    "intervals": ["]-\\infty,-1[", "]1,+\\infty["],
    "equations": ["x=-1", "x=1", "y=0", "y=-x-3"],
    "notations": ["\\lim", "\\infty"]
  },
  "exercise_type": "unstructured_statement",
  "reasoning_types": ["determine_limit"],
  "concepts": ["branches infinies"],
  "generation_methods": {
    "topics": "deterministic",
    "keywords": "rule_based",
    "mathematical_entities": "deterministic",
    "exercise_type": "rule_based",
    "reasoning_types": "rule_based",
    "concepts": "rule_based"
  },
  "review_status": "NOT_REQUIRED"
}
```

Every value above is directly traceable to either a structural fact
(`section_id` → title; `exercise_details.questions == []` and `statement`
non-null → `unstructured_statement`) or a literal substring match (the
glossary/regex sources are listed per field in §3) — nothing was inferred
semantically for this example, hence `review_status: "NOT_REQUIRED"`.

## 3. Field-by-field explanation

| Field | Why it's needed | Source / allowed values |
|---|---|---|
| `topics` | Directly useful for filtering/browsing by subject area; the sections already ARE a topic taxonomy authored by the textbook itself — reusing it costs nothing and invents nothing. | Controlled vocabulary = the chapter's own section + subsection titles (looked up via the item's `section_id`/`subsection_id`, already present). For coarse buckets ("Exercices et problèmes", "QCM - VRAI - FAUX") this is honestly coarse — flagged in §4/§9 as the one field with a real Phase B refinement path. |
| `keywords` | A lightweight, literal index of which established math vocabulary terms actually appear in an item — useful for search/filtering without semantic modeling. | Substring match against a maintained, versioned glossary file (French math vocabulary: "limite", "continuité", "asymptote", "intervalle", "fonction composée", "théorème des valeurs intermédiaires", "borne", "croissante", "décroissante", ...). Not free-text extraction — only terms in the glossary can ever appear. |
| `mathematical_entities` | Structured index of the actual mathematical objects/notations an item uses (function names, intervals, equations, key LaTeX macros) — useful later for Chunking (avoid splitting mid-expression) and Relations (link items sharing an entity) without reading the whole text again. | Regex over the LaTeX in `content` (already validated as balanced by normalization's own validator). Purely syntactic: an identifier immediately followed by `(` → function; `[`/`]`/`` ` `` bracket pairs with a comma → interval; short `symbol=expression` → equation; a fixed set of LaTeX macros (`\lim`, `\sqrt`, `\int`, `\circ`, ...) → notations. |
| `exercise_type` | Distinguishes QCM / multi-part / plain-statement items — directly useful for UI rendering and for any future selection logic ("give me a QCM") — without re-deriving it from `exercise_details` every time. | Purely structural, already-present fields: `qcm_choices` non-null → `"qcm"`; `questions` non-empty → `"structured_multi_question"`; `statement` non-null and `questions` empty → `"unstructured_statement"`; item type not exercise-shaped → `null`. |
| `reasoning_types` | Captures WHAT KIND of mathematical action an item asks for (prove vs. compute vs. plot vs. solve) — directly grounded in real, counted instruction verbs (see §0), useful for balancing exercise sets or later skill-tagging without needing to read full sentences. | Keyword match against a small, explicit French-verb-to-tag glossary (`Montrer`/`Démontrer`/`Vérifier`/`Justifier` → `prove`; `Calculer`/`Trouver` → `compute`; `Déterminer` + a limit/value target → `determine_limit`; `Étudier` → `study_variations`; `Tracer`/`Représenter`/`Construire`/`Dresser` → `represent_graphically`; `Résoudre` → `solve_equation`; `déduire` → `deduce`; `Identifier`/`Lire` → `identify_or_read`; anything else → `unclassified`), scanned across the statement and every question/sub-question text. |
| `concepts` | The field meant to eventually populate the EXISTING, currently-empty `concepts`/`Concept` registry hook already in `knowledge_item.schema.json` — real concept names (not just surface keywords) are valuable for Relations (§7) and any future retrieval filtering. | v1 (rule-based bootstrap): deduplicated union of the item's own `topics` and canonical concept labels mapped from its `keywords` hits (the glossary maps each surface term to one canonical concept, e.g. "asymptote"/"branche infinie" both → `"branches infinies"`). Phase B (§10) may refine this with an LLM ONLY for the coarse-bucket items where the rule-based bootstrap is too generic. |
| `generation_methods` | Makes every other field's provenance explicit and auditable — the whole point of the deterministic/rule-based/LLM classification the task requires isn't useful unless it's recorded alongside the data it describes, not just in this document. | One of `deterministic`/`rule_based`/`llm`/`not_populated` per field above. |
| `review_status` | Mirrors the project's existing `validation_status`/review-state pattern (knowledge items, figure review, figure↔knowledge association review) — nothing produced by an LLM is ever silently trusted. | `NOT_REQUIRED` while every `generation_methods` value is deterministic/rule_based/not_populated; forced to at least `REVIEW_REQUIRED` the moment any field's method becomes `llm`. |

## 4. Deterministic vs. rule-based vs. LLM classification

| Field | Class | Why |
|---|---|---|
| `topics` (structural bucket) | **DETERMINISTIC** | Pure lookup: `item.section_id`/`subsection_id` → that section/subsection's own `title`. No interpretation. |
| `topics` (coarse-bucket refinement) | **OPTIONAL_LLM** (Phase B, not v1) | Only needed for the ~48 items whose section is "Exercices et problèmes"/"QCM - VRAI - FAUX" — everywhere else the deterministic bucket is already specific enough. |
| `mathematical_entities` | **DETERMINISTIC** | Regex over already-validated LaTeX; no semantic judgment, purely syntactic pattern matching. |
| `exercise_type` | **RULE_BASED** | Requires an explicit, documented decision rule (which combination of already-structured fields maps to which label) — mechanical, but a rule, not a raw lookup. |
| `keywords` | **RULE_BASED** | Requires a maintained glossary (external knowledge, not derivable from the JSON alone) but the matching itself is deterministic substring search once that glossary exists. |
| `reasoning_types` | **RULE_BASED** | Same reasoning as `keywords`: an explicit verb→tag glossary, deterministic matching. |
| `concepts` (v1 bootstrap) | **RULE_BASED** | Deduplication of two already-computed rule-based fields (`topics` + glossary-mapped `keywords`) — no new semantic step beyond the glossary itself. |
| `concepts` (refinement for coarse-bucket items) | **LLM_REQUIRED** (Phase B, not v1) | Determining which specific concept(s) an individual exercise in the generic "Exercices et problèmes" bucket actually tests requires reading and understanding the mathematical content — genuinely semantic. |
| `skills` | **LLM_REQUIRED** (deferred, not in v1 schema) | "What competency does this exercise practice" is a didactic judgment call, not extractable from structure or keywords. |
| `pedagogical_intent` | **LLM_REQUIRED** (deferred, not in v1 schema) | Distinguishing "discovery activity leading into the next theorem" from "warm-up/review" requires reading the item in the context of its neighbors — semantic + relational, not a single-item deterministic fact. `type` itself already provides a coarse proxy (activity vs. theorem vs. exercise), which is why this wasn't promoted to a v1 field. |
| `difficulty` | **OPTIONAL_LLM** (deferred, not in v1 schema) | Confirmed by direct inspection: the source text contains NO difficulty markers at all in this chapter. Any value would be an LLM's own judgment call, not an extraction — explicitly the kind of thing the task says not to invent without justification. |
| `learning_objectives` | **LLM_REQUIRED** (deferred, not in v1 schema) | Phrasing a pedagogical goal in natural language is inherently generative, not extractive. |
| `prerequisites` | *(excluded — Relations phase, not Enrichment; see §7)* | — |

## 5. How to minimize Claude/LLM usage

1. **Phase A (this design's actual recommendation to implement first) uses
   zero LLM calls** and already covers `topics`, `mathematical_entities`,
   `exercise_type`, `keywords`, `reasoning_types`, and the rule-based
   `concepts` bootstrap for all 100 items.
2. **Scope any future LLM pass to the smallest justified subset**: of 100
   items, only the ~48 in the two generic sections ("Exercices et
   problèmes", "QCM - VRAI - FAUX") would ever need `concepts`/`topics`
   refinement — never re-run it on the other 52 whose section already
   gives a specific topic.
3. **Batch, don't call per-item**: send a batch of N items' `content` (plus
   their already-computed `keywords`/`topics` as hints) in a single request
   asking for a compact per-item concept-tag list, rather than one call per
   item — cuts call count by ~N×.
4. **Content-hash caching**: key any LLM result by a hash of the item's
   `content` (mirrors the fingerprint-skip pattern already used elsewhere
   in this pipeline, e.g. `detect_visual_elements_v4.py`'s
   `source_report_fingerprint`) — a chapter re-run with unchanged content
   never re-calls the LLM for items already enriched.
5. **Never implement the deferred fields (§4) until a concrete downstream
   consumer needs them** — the biggest cost saving is simply not building
   `skills`/`pedagogical_intent`/`difficulty`/`learning_objectives` at all
   until something actually reads them.

## 6. How enrichment remains generic for future chapters

- `topics`/`concepts` derive from THAT chapter's own section/subsection
  titles — no chapter-specific string ever appears in the enrichment code,
  only in the data it reads (same principle already enforced in
  `associate_figures_knowledge.py`/`normalize_knowledge.py` via a grep-based
  "no hardcoding" test, to be replicated here).
- The keyword/verb glossaries are **external data files**, not Python
  literals scattered through code — e.g.
  `data/schema/math_glossary_fr.json` (proposed, not created yet). A future
  Chapter 2 on a different topic (or a future non-French-language edition)
  extends the glossary file, never the enrichment script itself.
- `mathematical_entities`' regexes match generic LaTeX syntax (identifier
  before `(`, bracket-comma-bracket intervals, a fixed macro list) — not
  tied to continuity/limits specifically; the same patterns apply to
  derivatives, sequences, geometry, etc.
- `exercise_type`/`reasoning_types` operate purely on the ALREADY-generic
  normalized schema shapes (`exercise_details.questions`/`qcm_choices`),
  which are themselves chapter-agnostic.
- Same output-path convention as every prior phase:
  `data/output/<chapter_id>/enrichment/knowledge_enrichment.json`, computed
  from the chapter_id found in the normalized JSON at runtime.

## 7. How enrichment connects later to Relations and Chunking

- **Relations** (future, not implemented): would consume `concepts` and
  `mathematical_entities` to link items that share them — e.g. an exercise
  tagged `concepts: ["théorème des valeurs intermédiaires"]` could be
  linked to the theorem item stating it. This is exactly why `concepts` is
  designed to feed the EXISTING `Concept` registry (`first_seen_item_id`
  already anticipates cross-item linking) rather than being a closed,
  per-item-only field. `prerequisites` (excluded here, §1) is a Relations
  output, not an Enrichment input.
- **Chunking** (future, not implemented): would use `topics`/`concepts`/
  `keywords` as attached metadata for retrieval filtering, and
  `mathematical_entities` as a signal for where NOT to place a chunk
  boundary (e.g. never split between a function's definition and the
  equation naming it).
- Enrichment intentionally produces small, structured, machine-filterable
  tags rather than prose, specifically so a later Chunking/Embeddings phase
  can attach them as metadata without re-deriving anything.

## 8. What should NOT be enriched

- `original_content`/`provenance` (normalization's own preserved source) —
  immutable, never gains derived fields written into it.
- Individual QCM choice texts, or individual `sub_questions` nodes — only
  the parent item gets an enrichment record; a per-sub-question record
  would fragment the same information the item-level `reasoning_types`
  array already captures adequately.
- Any field with no real anchor in this corpus: `difficulty`,
  `learning_objectives`, `pedagogical_intent`, `skills` — see §4. Better to
  ship nothing than an LLM-invented value dressed up as data.
- `prerequisites` — belongs to Relations, not Enrichment (§7).
- Banner/decorative structural elements — there are none surviving into
  the normalized `items[]` array (already filtered out in earlier phases),
  so nothing to exclude in practice, but worth stating: enrichment only
  ever processes real normalized items, never section/subsection banners.

## 9. Validation strategy

Mirrors `validate_normalized_knowledge.py`'s approach directly:

1. **Structural**: JSON Schema validation against
   `knowledge_enrichment.schema.json` (required fields, enum membership for
   `exercise_type`/`reasoning_types`/`review_status`/`generation_methods`
   values).
2. **Referential integrity**: every `item_id` must exist in the normalized
   JSON it was generated from (no orphan enrichment records); every
   normalized item should have exactly one enrichment record (no
   duplicates, none silently missing — same "no loss" principle as
   normalization's own validator).
3. **Controlled-vocabulary enforcement**: every `topics` entry must be one
   of the chapter's own section/subsection titles (or `generation_methods.topics
   == "llm"` for a Phase-B-added entry, which must then also be
   `review_status != NOT_REQUIRED`); every `keywords`/`concepts` entry must
   trace back to the maintained glossary file (reject silent vocabulary
   drift).
4. **Method/review consistency**: if any `generation_methods` value is
   `"llm"`, `review_status` must NOT be `"NOT_REQUIRED"` — enforced as a
   hard validation error, not a convention.
5. **No LaTeX re-validation needed**: enrichment reads `content` but never
   rewrites it, so `check_latex_balance` (already run by normalization's
   validator) does not need to run again here.
6. Produces a machine-readable `validation_report.json`, same shape/spirit
   as the normalization phase's.

## 10. Recommended implementation plan (when this moves from design to code)

1. **Phase A — deterministic + rule-based, zero LLM** (`enrich_knowledge_deterministic.py`):
   `topics`, `mathematical_entities`, `exercise_type`, `keywords`,
   `reasoning_types`, `concepts` (bootstrap) for all 100 items. Requires
   creating the glossary data file(s) first (proposed:
   `data/schema/math_glossary_fr.json` — keyword→concept map + verb→tag
   map), reviewed once by a human before use, then reused deterministically
   forever after.
2. **Validate Phase A output** against `knowledge_enrichment.schema.json`
   + the referential/vocabulary checks above — ship and human-review this
   BEFORE considering Phase B at all, since Phase A alone likely already
   answers most practical filtering/search needs.
3. **Phase B — narrow, cached, batched LLM pass** (`enrich_knowledge_llm.py`,
   separate script, opt-in): ONLY for `concepts`/`topics` refinement on
   items whose section is one of the two generic buckets. Batches multiple
   items per call, caches by content hash, sets `review_status:
   "REVIEW_REQUIRED"` on every touched record. Not scheduled until Phase A
   is reviewed and a concrete need for finer-grained exercise concepts is
   confirmed.
4. **Do not schedule** `skills`/`pedagogical_intent`/`difficulty`/
   `learning_objectives` implementation until a specific downstream feature
   (e.g. exercise recommendation) is actually being built and needs them.
