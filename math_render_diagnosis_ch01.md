# Math rendering diagnosis — Chapter 1 Knowledge Review

Scope: `frontend/src/app/shared/math-text/` (MathText/KaTeX integration) and its
two call sites in the Knowledge Review feature (`item-detail/`, `question-tree/`,
`knowledge-review.html`). No files in the reconstruction pipeline, `data/`, or the
generated JSON were modified. This is diagnosis only.

## 1. Root cause

There are **two separate things going on**, and they must not be conflated:

1. **The MathText/KaTeX rendering pipeline itself (used in the item-detail panel)
   is correct for Chapter 1's actual data.** Every math expression currently in
   `chapter_01_continuite_limites.json` is valid LaTeX, is correctly tokenized,
   and renders through KaTeX with zero errors (see §4, tests A/B/C).
2. **The list/sidebar row preview bypasses MathText/KaTeX entirely** and prints
   raw LaTeX source (dollar signs, backslash commands) as plain text. This is a
   real, confirmed code defect — **this is the actual root cause of reviewers
   seeing "malformed" math** while scanning the list, not a KaTeX or Unicode
   problem.

Concretely:
- `knowledge-format.ts:41-44` (`excerpt()`) strips HTML-like tags
  (`<[^>]+>`) but does nothing to `$…$` / `$$…$$` delimiters or LaTeX macros.
- `knowledge-review.html:83` binds this straight into the DOM as plain text:
  `<span class="preview">{{ r.preview }}</span>` — no `<app-math-text>`, no
  KaTeX pass at all.
- Result: every row in the list shows things like
  `Vérifier que pour tout réel $x \neq 1$, $f(x) = 2|x-1|$.` verbatim,
  backslashes and all. A reviewer scanning the list sees literal `\in`,
  `\neq`, `\mathbb{R}`, `\lim_{x \to a}`, `\circ`, `\ell`, etc. as raw text
  instead of typeset symbols — which reads as "the math symbols are broken,"
  even though nothing crashed and no data is corrupted.

This is **not** invalid LaTeX, **not** a Unicode-handling gap, **not** a KaTeX
config problem, **not** an HTML-escaping or Angular-sanitization bug, and
**not** a delimiter-parsing bug in `tokenize()`. It is a UI completeness gap:
one of the two rendering surfaces (the list) was never wired to the MathText
component that the other surface (the detail panel) already uses correctly.

## 2. Affected symbols

In the **list preview** (`knowledge-review.html:83`): every symbol in the
user's list is affected, because *none* of the math in the preview is
rendered at all — `∈ ∉ ≠ ≤ ≥ → ↔ ℝ ℕ ℤ ℚ ℓ`, composition, limits,
subscripts/superscripts, fractions, and Greek letters all show up as their
raw LaTeX source (e.g. `\in`, `\notin`, `\neq`, `\mathbb{R}`, `\ell`,
`v \circ u`, `\lim_{x \to a}`, `x_1`, `x^2`, `\frac{a}{b}`, `\alpha`).

In the **item-detail panel** (`item-detail.html`, `question-tree/`): confirmed
**not** affected for current Chapter 1 content — see §4 for the exhaustive
test against all 451 unique math expressions in the file.

## 3. Is the JSON itself correct or incorrect?

**Correct.** Confirmed by direct inspection and by a scripted sweep of the
entire `chapter_01_continuite_limites.json`:

- Zero occurrences of raw Unicode math symbols (`∈ ∉ ≠ ≤ ≥ → ↔ ℝ ℕ ℤ ℚ ℓ ∘` etc.)
  anywhere in the file — every math expression uses proper single-backslash
  LaTeX commands (`\in`, `\notin` never actually occurs, `\neq`, `\mathbb{R}`,
  `\ell`, `\circ`, `\lim_{x \to a}`, `\frac`, `\dfrac`, `\alpha`, …), correctly
  JSON-escaped (one backslash in LaTeX → `\\` in the JSON file, which decodes
  back to one backslash — verified, not double- or zero-escaped).
- The one Unicode character that *does* appear outside math delimiters is the
  Unicode MINUS SIGN `−` (U+2212, e.g. "continuité en −2 ?") in plain prose —
  this is inert plain text, not math, and isn't part of the symbol list the
  user asked about.
- The user's example pair ("x ∉ A" vs "x \notin A") does not currently occur
  in Chapter 1 in *either* form — `\notin`/∉ isn't used anywhere in this
  chapter's source content. It's worth keeping in mind for future chapters or
  for manually-typed corrections (see §7), but it isn't the cause of today's
  rejections.

## 4. Concrete examples (JSON → MathText → KaTeX → result)

**Test method:** a script (`frontend/diagnose_math.mjs`, run then deleted —
throwaway, not committed) replicated `tokenize()` + `renderMath()` from
`math-text.ts` verbatim against every `original_content` / `statement` /
`text` / `content` / `title` field in `chapter_01_continuite_limites.json`,
using the actual installed `katex` package (`0.18.9`, matching
`package.json`).

**Result: 1219 math segments found (451 unique), 0 KaTeX parse failures, 0
segments left un-tokenized (no stray `$` or LaTeX commands escaped into
plain-text segments).**

Worked examples:

- **A — `\neq`, `\lim_{x\to a}` (real item, `original_content`):**
  ```
  JSON:      "Vérifier que pour tout réel $x \\neq 1$, $f(x) = 2|x-1|$.\n2. En déduire $\\lim_{x \\to 1} f(x)$."
  tokenize:  [text] "Vérifier que pour tout réel "
             [inline] "x \neq 1"
             [text] ", "
             [inline] "f(x) = 2|x-1|"
             [text] ".\n2. En déduire "
             [inline] "\lim_{x \to 1} f(x)"
  KaTeX:     renders correctly, no errors → item-detail panel: OK
  list row:  excerpt() → "Vérifier que pour tout réel $x \neq 1$, $f(x) = 2|x-1|$. 2. En déduire $\lim_{x \to 1}…"
             bound via {{ r.preview }} → shown VERBATIM, dollar signs and
             backslashes visible as text → this is what looks "malformed"
  ```
- **B — `\mathbb{R}`, `\ell`, `\begin{cases}` (piecewise continuity item):**
  ```
  JSON:  "...la fonction f admet une limite finie $\\ell$ lorsque x tend vers a, alors la fonction g ... $g(x) = \\begin{cases} f(x) & \\text{si } x \\neq a, \\\\ \\ell & \\text{si } x = a. \\end{cases}$..."
  KaTeX: \ell -> ℓ, \begin{cases}...\end{cases} both render correctly (detail panel OK)
  list row: shows the raw "\ell", "\begin{cases}", "\\", "\text{si }" tokens as plain text
  ```
- **C — composition notation (real item):**
  ```
  JSON: "La fonction notée $v \\circ u$, définie sur I par $v \\circ u(x) = v(u(x))$..."
  KaTeX: \circ -> ∘, renders correctly (detail panel OK)
  list row: shows literal "v \circ u" as text
  ```
- **D — Unicode vs LaTeX equivalence check (isolated KaTeX test, not from the
  corpus since ∉/ℝ-as-Unicode don't occur in it):** rendering `\mathbb{R}`,
  `\notin`, `\ell`, `\leq`, `\circ` side-by-side against their literal Unicode
  equivalents (`ℝ`, `∉`, `ℓ`, `≤`, `∘`) through the exact installed KaTeX
  0.18.9 build produces **identical HTML output** for every pair tested —
  this KaTeX version has native Unicode-math support, so *if* raw Unicode
  ever ends up inside a `$…$` span (e.g. via a future manual correction typed
  with a Unicode symbol picker instead of LaTeX), it would render fine, not
  as an empty box. This isn't the current bug, but it means switching to
  Unicode-in-math is not a safe universal fix either — LaTeX commands remain
  the right target form.
- **E — KaTeX font/asset pipeline (build-level check, not just code
  inspection):** ran `npm run build` and inspected `dist/eduassistant/browser/`.
  `katex.min.css`'s `url(...)` references (including `KaTeX_AMS-Regular.*`,
  which backs `\mathbb`) are correctly resolved and copied to
  `dist/.../media/` by Angular's build, and `angular.json` already lists
  `node_modules/katex/dist/katex.min.css` in the global `styles` array. Font
  loading is not broken.

## 5. Exact file/function responsible

- **Real bug:** `frontend/src/app/features/admin/knowledge-review/knowledge-format.ts:41-44`
  (`excerpt()`) — produces a plain-text string with raw LaTeX still embedded,
  with no caller ever passing it through `renderToHtml`/`MathText`.
  Consumed at `frontend/src/app/features/admin/knowledge-review/knowledge-review.html:83`
  (`<span class="preview">{{ r.preview }}</span>`).
- **Confirmed correct, no change needed:**
  `frontend/src/app/shared/math-text/math-text.ts` (`tokenize`, `renderMath`,
  `renderToHtml`, the `MathText` component itself) and its use in
  `item-detail.html` / `question-tree/question-tree.ts`.

## 6. Minimal fix

Render the list preview through the same math pipeline the detail panel
already uses, instead of showing raw source text:

- Simplest option: replace `<span class="preview">{{ r.preview }}</span>` in
  `knowledge-review.html` with `<app-math-text class="preview" [text]="r.preview" />`
  (add `MathText` to the component's `imports`). `MathText` is already
  designed to be a drop-in, so this is a two-line change plus one import.
- One caveat to handle in the same change: `excerpt()` truncates at a fixed
  character count (`max = 90`), which can currently cut a `$…$` span in half
  (e.g. `"...$x \i"`). Once the preview is rendered through KaTeX, a
  mid-expression truncation would produce a visible KaTeX parse-error span
  instead of a clean ellipsis. `excerpt()` should stop at the nearest
  segment boundary from `tokenize()` rather than an arbitrary character
  offset (or fall back to truncating only within `text`-kind segments,
  never inside an `inline`/`display` segment). This keeps the fix contained
  to `knowledge-format.ts` + the one template line — no redesign of the
  review UI, no new component.

No other change is needed: `math-text.ts`'s tokenizer, KaTeX config, and the
detail-panel usages are already correct for this chapter's content.

## 7. Does the fix require regenerating the JSON?

**No.** The JSON is correct as-is (§3). This is purely a frontend rendering
fix confined to the list-row preview. `convert_to_knowledge.py`, the
reconstructed Markdown, and `chapter_01_continuite_limites.json` do not need
to change.

One forward-looking note for the *separate* correction/re-validation
workflow already discussed: if a human reviewer's typed correction ever
contains a raw Unicode math symbol (∈, ∉, ℝ, …) instead of the LaTeX form,
§4-D shows the installed KaTeX (0.18.9) renders it identically to the LaTeX
form when it's placed inside `$…$` — so it would still render correctly.
The only risk case is a correction where the symbol is typed *outside* any
`$…$` delimiter, where it would just show as plain Unicode text (harmless,
readable, not "broken" — browsers render these glyphs fine as regular text).
