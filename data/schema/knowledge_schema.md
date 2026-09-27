# Structured Knowledge JSON — Design Document

Status: **proposal, not implemented**. No converter code exists yet. This
document, `knowledge_item.schema.json`, and the files under `examples/`
are the full deliverable for this design phase.

## 1. What was inspected before designing this

- **Reconstructed Markdown** (`data/output/reconstructed/page_*.md`, Phase 3
  output): YAML frontmatter (`pdf_page`, `source_image`, `cleaned_source`,
  `needs_review`, `uncertain_count`, `gap_count`) + a body using a closed tag
  vocabulary: `<bloc type="definition|theoreme|propriete|remarque|exemple|
  activite|exercice|question" numero="N" continues_from_previous_page="true"
  continues_on_next_page="true">`, `<figure id="..." status="described|
  reference_only|requires_verification">`, `<uncertain reason="...">`,
  `<gap reason="..."/>`, plus standard Markdown headings (`#`/`##`/`###`) and
  LaTeX (`$...$`, `$$...$$`).
- **Layer 1 / Layer 2 validation reports** (`reconstruction_report.json`,
  `final_quality_report.json`): per-page `status`/`issues`, Layer 2's
  `status: pass|review|error` + `confidence`. Confirms validation currently
  happens **per page**, not per knowledge item — this schema is what
  introduces item-level granularity.
- **Visual-elements review** (`visual_elements_review.json`, Phase 4d):
  per-candidate `candidate_id`, `pdf_page`, `classification_hint` (soft, not
  verified), `seed_bbox`/`bbox`, `image_path`, `needs_review: true` always.

Concrete findings from real Chapter 1 content that shaped this design:

1. **Theorems are often followed by an untagged proof.** Page 12: a
   `<bloc type="theoreme">` is immediately followed by plain prose starting
   "Démonstration" — not wrapped in any tag. The schema needs an optional
   place for this without inventing structure that isn't there.
2. **A "Section" heading is not always a real section.** Page-banner text
   ("Cours", "Exercices et problèmes") is rendered as a Markdown heading
   (`# Cours`) on *many* pages because it's a recurring page-header graphic
   in the source PDF, not a new section each time. Genuine numbered sections
   ("## III. Continuité et limite d'une fonction composée", "### III.2
   Continuité d'une fonction composée") are also plain Markdown headings —
   **structurally indistinguishable from banner headings** without extra
   logic. This schema does not solve that; it's flagged in §6 as an open
   question for the converter, not silently resolved here.
3. **Exercises span multiple pages** via `continues_from_previous_page` /
   `continues_on_next_page`, and a solution, when present, lives **inside
   the same `<bloc type="exercice">`** under a `### Solution` sub-heading —
   it is not a separate tag. `exercise_details.correction` must therefore be
   optional and the converter will need to split on that heading text, not
   assume a dedicated tag exists.
4. **"Formula" and "Method" have no dedicated source tag** in this chapter —
   no `<bloc type="formule">` or `type="methode"` appears anywhere in
   Chapter 1 (checked: zero matches). A "méthode" is mentioned only as an
   inline phrase ("méthode de dichotomie") inside an exercise. The schema
   still needs to support these two types for other chapters / future
   content, but populating them here means **extracting** a formula/method
   out of a parent item's content — never inventing one — with explicit
   `extracted_from` provenance (see §4).
5. **QCM questions are independent items**, not sub-questions of one
   exercise: page 23 has three separate `<bloc type="question" numero="N">`
   blocks under `## QCM`, each with its own complete stem and choices.

## 2. Core design decision: one unified item shape, not nine

Instead of nine unrelated schemas (Definition, Theorem, Property, Formula,
Method, Example, Activity, Exercise, Remark), all knowledge items share **one
base shape** (`KnowledgeItem`) with a `type` discriminator, plus one optional
type-specific extension block (`exercise_details`) used only by
`exercise`/`activity`/`example` items that have questions and possibly a
correction. Rationale:

- **PostgreSQL**: maps directly to a single `knowledge_items` table (or
  single-table-inheritance) with a `type` column, rather than nine tables
  with duplicated provenance/link columns — provenance (`source`),
  `concepts`, `links`, and `validation_status` are identical in shape across
  every type, so keeping them unified avoids nine copies of the same join
  logic.
- **RAG**: a retriever wants one uniform "chunk" shape it can filter by
  `type`/`chapter_id`/`concepts` and embed `original_content` from,
  regardless of whether the chunk is a Theorem or an Exercise. Nine
  different shapes would mean nine different retrieval code paths.
- Every type-specific difference that actually exists in the source (an
  exercise's questions/correction, a theorem's optional proof) is still
  represented — just as optional fields on the shared shape, not a
  different shape per type.

## 3. Entities

### 3.1 `Document`, `Chapter`, `Section`, `Subsection` (hierarchy, small tables)

Structural containers, not content — one row each, referenced by id from
`KnowledgeItem`. `Section`/`Subsection` are nullable on the item (per finding
#2 above, not every item can be confidently placed under a real numbered
section yet).

### 3.2 `Concept` (small table, growing over time)

A lightweight controlled-vocabulary tag ("continuité en un point", "théorème
des valeurs intermédiaires", ...). `KnowledgeItem.concepts` is an array of
`Concept` ids. Per rule #1 (never invent content), concepts in this design
phase are meant to be **extracted from the source's own terminology**
(section titles, restated definitions) — concept *extraction* itself is a
separate, future converter concern; this schema only provides the slot to
store the link once extracted, plus `Concept.first_seen_item_id` so a
concept's origin is always traceable back to real content.

### 3.3 `KnowledgeItem` (the main, high-volume entity)

One row per Definition / Theorem / Property / Formula / Method / Example /
Activity / Exercise / Remark. Full field list in
`knowledge_item.schema.json`; summary:

| Field | Purpose |
|---|---|
| `id` | stable, deterministic (see §6 open question) |
| `type` | the 9 required types (enum) |
| `document_id`, `chapter_id`, `section_id`, `subsection_id` | hierarchy links (last two nullable) |
| `title` | short label if the source has one (e.g. "Théorème (admis)"), else `null` — never invented |
| `source` | `pdf_pages[]`, `reconstructed_sources[]`, `bloc_type`, `bloc_numero`, continuation flags |
| `original_content` | verbatim Markdown/LaTeX body, unmodified — the ground truth |
| `proof` | optional verbatim untagged proof text immediately following a theorem (finding #1) |
| `concepts` | array of `Concept` ids |
| `links` | typed arrays of related item ids (`definitions`, `theorems`, `properties`, `formulas`, `methods`, `exercises`) + `figures` (see §4) |
| `exercise_details` | present only for `exercise`/`activity`/`example`: `statement`, `questions[]` (recursive `label`+`text`+`sub_questions[]`), `correction` (`present_in_source` + `content`), `qcm_choices[]` |
| `extracted_from` | only for `formula`/`method` items derived out of a parent's content (finding #4): `{item_id, note}` |
| `uncertainty` | mirrors the reconstruction's own `<uncertain>`/`<gap>` markers, carried forward rather than dropped |
| `validation_status` | enum, **always `"REVIEW_REQUIRED"`** when first produced (rule #7) |
| `validation_history` | empty array initially; future human/automated review events append here |
| `schema_version` | `"1.0"` |

### 3.4 Figure references (rule #9)

`links.figures` is an array of lightweight reference objects, **never** an
embedded image or a re-derived description:

```json
{
  "pdf_page": 24,
  "reconstructed_figure_id": "fig-ex7",
  "candidate_id": "page_024_candidate_02",
  "figure_status_in_source": "described",
  "match_status": "manual"
}
```

Two figure-identification systems already exist independently and are not
yet auto-linked: the reconstructed Markdown's own `<figure id="...">` (a
Claude-authored semantic anchor, no bbox) and the visual-elements pipeline's
`candidate_id` (a pixel bbox + cropped PNG, no semantic description, and
explicitly a **soft hint** — see `evaluate_visual_elements.py`). This schema
stores both ids side by side with an explicit `match_status`
(`unresolved`/`manual`/`automated`) rather than silently assuming they refer
to the same figure — that assumption must be made explicitly by whoever (or
whatever) resolves it, never baked in by the converter.

## 4. Relationships (how the graph fits together)

```
Document 1──* Chapter 1──* Section 1──* Subsection
                                │             │
                                └──────┬──────┘
                                       │ (nullable, either level)
                                       ▼
                                 KnowledgeItem *──* Concept
                                       │
                          ┌────────────┼─────────────────┐
                          ▼            ▼                 ▼
                  links.theorems  links.exercises   links.figures
                  links.formulas  links.methods     (candidate_id /
                  links.definitions links.properties  reconstructed_figure_id)
```

- `KnowledgeItem ↔ KnowledgeItem` links are **directed but symmetric in
  intent** (a Theorem linking to an Exercise that uses it, an Exercise
  linking back to the Theorem it needs) — both directions are stored
  explicitly rather than inferred, since inferring the reverse edge safely
  requires knowing it's not accidentally a different-but-similar theorem
  (rule #5, don't silently merge separate concepts).
- No link is populated by the converter in the first pass unless it's
  unambiguous from the source itself (e.g. an exercise explicitly citing
  "d'après le théorème des valeurs intermédiaires" by name). Everything else
  stays an empty array — an empty `links.theorems: []` is honest; a guessed
  link is not.

## 5. PostgreSQL / RAG suitability (rule #10)

- `knowledge_items` table: most fields as real columns (`id`, `type`,
  `chapter_id`, `validation_status`, ...) for indexing/filtering; `source`,
  `exercise_details`, `uncertainty`, `links` as `JSONB` columns — structured
  enough to query (`links -> 'theorems'`) without needing five extra join
  tables for what's fundamentally sparse, type-varying data.
- `concepts` and `concept_links` (item_id, concept_id) as real join tables —
  this is the one relationship expected to be queried/joined constantly
  ("find all items about concept X"), so it belongs in normalized form, not
  buried in JSONB.
- `documents` / `chapters` / `sections` / `subsections` as small normalized
  tables.
- RAG: `original_content` (+ `title`, `concepts`, `type`, `chapter_id`,
  `pdf_pages`) is the natural embedding+metadata unit — one row in, one
  retrievable chunk out, with enough metadata to filter by chapter/type
  before ever touching a vector index. `validation_status` lets a RAG
  pipeline choose to exclude `REVIEW_REQUIRED` items until approved, without
  deleting them from storage.

## 6. Open questions (not resolved here, flagged for the converter design)

1. **Heading disambiguation** (finding #2): distinguishing a real numbered
   section/subsection heading from a recurring page-banner heading. Likely
   needs a small allowlist/pattern check (e.g. headings matching
   `^[IVX]+\.` or `^[IVX]+\.\d+` are real; bare words like "Cours" are not)
   — not designed here, since it's converter logic, not schema.
2. **Deterministic ID scheme.** Examples below use readable
   `{document}-ch{N}-{type-abbrev}-{seq}` ids for illustration. The real
   scheme (sequential per chapter+type vs. content-hash-based) should be
   decided when the converter is built, not guessed here.
3. **Splitting `exercise_details.correction`** out of `original_content`
   requires recognizing the `### Solution` heading convention (finding #3)
   — confirmed present in this chapter, not guaranteed identical wording in
   future chapters.
4. **QCM choice parsing** (finding #5): extracting `qcm_choices[]` from
   Markdown bullet lines reliably (this depends on the Phase 3 prompt fix
   already shipped for QCM formatting — not yet re-validated against freshly
   reconstructed QCM pages).

## 7. Files in this delivery

- `knowledge_schema.md` — this document
- `knowledge_item.schema.json` — formal JSON Schema (2020-12) for
  `KnowledgeItem` plus `Document`/`Chapter`/`Section`/`Subsection`/`Concept`
  as `$defs`
- `examples/theorem_composition_continuity.json` — Theorem, with a proof,
  linked Property, page 12
- `examples/exercise_probleme_resolu.json` — Exercise spanning pages 20-21,
  with an embedded solution
- `examples/exercise_with_figure.json` — Exercise (page 24) referencing a
  figure via both identification systems, `match_status: "manual"`
