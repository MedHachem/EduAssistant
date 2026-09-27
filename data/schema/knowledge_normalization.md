# Knowledge Normalization — Design Document

Status: **implemented** (`normalize_knowledge.py`, `validate_normalized_knowledge.py`,
Phase 7). Additive only — never modifies the source knowledge JSON, the
figure↔knowledge association output, the persisted Human Review model, or
any figure/detection output.

## 1. What was inspected before designing this

- **The real Chapter 1 knowledge JSON** (`data/output/knowledge/chapter_01_continuite_limites.json`):
  100 items (activity 36, exercise 40, theorem 19, property 3, definition 1,
  remark 1), 8 sections, 12 subsections. Measured directly (not assumed):
  `title` set on 7/100, `proof` set on 2/100, `concepts` always empty,
  `extracted_from` always empty, `uncertainty` flags always `false` in this
  chapter, 3 multi-page items, `subsection_id` null on 50/100 (many items
  sit directly under a section with no subsection).
- **`knowledge_item.schema.json` / `knowledge_schema.md`**: the authoritative
  existing schema and its documented design rationale (proof-without-tag,
  banner-vs-section ambiguity, flat vs. nested question parsing history,
  formula/method extraction, QCM-as-independent-items).
- **`convert_to_knowledge.py`**: found `strip_tags_for_parsing()` — the
  converter's OWN existing function for removing inline `<figure>`/
  `<uncertain>`/`<gap>` markup, already used internally to derive
  statement/question text while keeping `original_content` verbatim.
  **Reused directly** rather than reimplemented, so normalization's tag
  handling can never drift from the converter's own.
- **`validate_reconstruction.py`**: found `check_latex_balance()`, the
  project's existing deterministic LaTeX sanity checker (balanced `$`/`$$`,
  `{}`, `\left`/`\right`, no empty math expressions). **Reused directly**
  for the normalized validator's math-content check — no new LaTeX
  validation logic was written.
- **A real, concrete inconsistency found by inspection, not assumption**:
  `original_content` for items with a `<figure>` reference still contains
  the raw inline tag verbatim (e.g. `...asymptotes.\n\n<figure id="fig-act1"
  status="described">Repère orthogonal avec...</figure>`), even though that
  same information is already captured structurally in `links.figures`.
  This is the clearest "reconstruction-specific inconsistency" bleeding
  into content text that normalization can safely remove without losing
  anything (see §2).
- **A real, concrete numbering irregularity found by inspection**: subsection
  `math-4eme-tome1-ch01-sub-1-2-continuite-sur-un-intervalle` has label
  `"1.2 Continuité sur un intervalle"`, sitting between siblings `"I.1"` and
  `"I.3"` under section `"I"` — a digit where every sibling uses a roman
  numeral. Already flagged as a known, deliberately-not-silently-corrected
  limitation in `convert_to_knowledge.py`'s own docstring. Normalization
  detects this class of irregularity generically (§7) and surfaces it
  explicitly rather than guessing "I.2".
- **The figure↔knowledge association output** (`data/output/<chapter_id>/associations/figure_knowledge.json`)
  and **the persisted Human Review model** (`backend/.../FigureKnowledgeReview`):
  inspected to confirm normalization does not need to (and must not) merge
  with either — they operate on `figure_id`/`item_id` pairs already, are
  already chapter-generic, and are out of scope here (§10 boundary).
- **Existing Python conventions**: `config.py`'s `associations_dir(chapter_id)` /
  `associations_json(chapter_id)` pattern (Phase 5b) — mirrored exactly for
  `normalized_dir(chapter_id)` / `normalized_json(chapter_id)` rather than
  inventing a new output-path convention.

## 2. What "normalization" means here, concretely

For each item, `original_content` (untouched) is preserved verbatim under
`provenance.original_content`. A new `content` field holds the same text
with inline `<figure>`/`<uncertain>`/`<gap>` markup removed (via the
converter's own `strip_tags_for_parsing`) and the whitespace gap that
removal leaves behind collapsed to a single paragraph break. **No
information is lost** — the figure reference is already in `links.figures`;
an uncertain span's own text is kept (only the wrapper tag is dropped,
exactly as the converter already does internally); a gap marker is, by
definition, marking an absence, not content.

Everything else (`links`, `exercise_details`, `uncertainty`, `title`,
`proof`) is copied through unchanged — inspection found no other
inconsistency to fix in this single-converter, uniformly-shaped source.
Two purely-recombinant additions, from fields that already exist:

- `order`: 0-based position in the source `items`/`sections`/`subsections`
  arrays, made explicit rather than implicit in array position.
- `display_label`: `"<Type label> <bloc_numero>"` (e.g. `"Activité 4"`),
  built ONLY when the source has a `bloc_numero` — a mechanical
  recombination of two already-present fields (item type + numero), never
  new text. `null` when `bloc_numero` is absent, never guessed.

## 3. Normalized schema

See `normalized_knowledge.schema.json` (JSON Schema draft 2020-12, same
style as `knowledge_item.schema.json`). Top level:

```
document → chapter → sections[] → subsections[] → items[]
```

Each `items[]` entry:

```
id, type, order, chapter_id, document_id, section_id, subsection_id,
title, display_label, content, proof, links, exercise_details,
uncertainty, provenance { source_item_id, document_id, pdf_pages,
reconstructed_sources, bloc_type, bloc_numero, continues_from_previous_page,
continues_on_next_page, original_content }
```

Each `sections[]` / `subsections[]` entry adds `order` and `irregularities`
(array of human-readable strings, empty by default) to the source shape.

No chapter-specific IDs, page numbers, or special cases appear in the
schema or in `normalize_knowledge.py`/`validate_normalized_knowledge.py`
themselves — enforced by a dedicated test
(`test_no_chapter_specific_hardcoding_in_production_modules`) that greps
both modules' own source for Chapter-1 tokens.

## 4. Example normalized Chapter 1 item

(`math-4eme-tome1-ch01-act-008`, abridged — see
`data/output/math-4eme-tome1-ch01/normalized/knowledge.json` for the full
100-item file)

```json
{
  "id": "math-4eme-tome1-ch01-act-008",
  "type": "activity",
  "order": 11,
  "section_id": "math-4eme-tome1-ch01-sec-ii-branches-infinies",
  "subsection_id": null,
  "title": null,
  "display_label": "Activité 1",
  "content": "La courbe ci-contre est la représentation graphique d'une fonction f définie sur $]-\\infty,-1[ \\cup ]1,+\\infty[$ . ... et $\\lim_{x \\to +\\infty} f(x)$.",
  "links": { "figures": [{ "pdf_page": 9, "reconstructed_figure_id": "fig-act1", "candidate_id": null, "figure_status_in_source": "described", "match_status": "unresolved" }], "...": [] },
  "uncertainty": { "has_uncertain_markers": false, "has_gap_markers": false, "uncertain_spans": [] },
  "provenance": {
    "source_item_id": "math-4eme-tome1-ch01-act-008",
    "pdf_pages": [9],
    "bloc_type": "activite",
    "bloc_numero": "1",
    "original_content": "La courbe ci-contre ... et $\\lim_{x \\to +\\infty} f(x)$.\n\n<figure id=\"fig-act1\" status=\"described\">Repère orthogonal avec une courbe rose présentant des asymptotes...</figure>"
  }
}
```

Note `content` has no `<figure>` tag; `provenance.original_content` keeps
it verbatim; `links.figures` keeps the structured reference. LaTeX
(`$]-\infty,-1[ \cup ]1,+\infty[$`, `$\lim_{x \to +\infty} f(x)$`) is
byte-identical in both.

## 5. Determinism (no LLM)

100% Python transformations: tag stripping (reused converter function),
whitespace collapse (one regex), field copy-through, mechanical
recombination for `order`/`display_label`, and one generic structural
regex check for the roman-vs-digit subsection numbering pattern. No
Claude/LLM call anywhere in `normalize_knowledge.py`. An ambiguity that
cannot be resolved deterministically (the "1.2" numbering, or any future
chapter's equivalent) is preserved verbatim and flagged via
`irregularities`, never guessed — see §7 for the future LLM extension
point this leaves open, deliberately unimplemented now.

## 6. Validation

`validate_normalized_knowledge.py` checks, per the task's checklist:

| Requirement | Check |
|---|---|
| Required fields | JSON Schema validation against `normalized_knowledge.schema.json` |
| Unique IDs | `duplicate_ids` — across chapter/sections/subsections/items combined |
| Valid hierarchy | `hierarchy` — no item/subsection references a non-existent section/subsection; a subsection's own `section_id` must match its parent item's |
| Valid ordering | `section_ordering`/`subsection_ordering`/`item_ordering` — `order` values are exactly `0..N-1` in array order |
| Valid source references | `source_references` — `pdf_pages`/`reconstructed_sources` length match, `bloc_type` present |
| Valid page references | `page_references` — every page falls inside the chapter's own `[pdf_page_start, pdf_page_end]` |
| Valid mathematical content | `latex_balance` — reuses `validate_reconstruction.check_latex_balance` on every content/proof/question/QCM/correction text |
| No duplicated IDs | (same as unique IDs) |
| No orphan items | (same as hierarchy) |
| No loss of source items | `no_lost_items` — normalized item-ID set is compared against the source item-ID set; any difference (either direction) is reported, not silently accepted |

Produces a machine-readable report (`validation_report.json`) with a
`passed` boolean, `total_errors`, and per-check-group error lists.

## 7. Limitations / future optional LLM extension

- The digit-vs-roman subsection check is intentionally narrow (only
  fires when a roman-numeral convention is already established among
  siblings) — it will not catch every possible numbering slip, only the
  one class actually observed. Extending it to more patterns, if a future
  chapter needs it, is a mechanical addition to `_label_irregularities`,
  not a redesign.
- `display_label` covers 9 item types; a future chapter introducing a new
  `type` not in `ITEM_TYPE_DISPLAY_LABEL` simply gets `display_label: null`
  for that type rather than an error — safe degradation, not a crash.
- An optional future LLM pass could attempt genuinely semantic
  normalization (e.g. resolving whether "1.2" was meant as "I.2", or
  reconciling banner-vs-real-section ambiguity mentioned in
  `knowledge_schema.md`) for items where `irregularities` is non-empty —
  explicitly NOT implemented now, per the task brief, and would need to
  remain human-reviewable output, not an automatic rewrite.

## 8. Boundary respected

Does not modify: source knowledge JSON, final figure PNGs, figure
detection/completeness logic, the Human Review UI, the Human Review
database model, or the figure↔knowledge association algorithm. Does not
implement: Enrichment, Relations (beyond what's already in `links`),
Chunking, Embeddings, Vector DB, or Semantic Search.
