# Knowledge ingestion pipeline

Turns the scanned textbook PDF into structured data, one stage at a
time. Each stage only does the minimum it can do safely.

Currently configured to process only **Chapter 1** of
`math-4eme-tome1` (PDF pages 5–27). See `src/config.py` to change the
source PDF, page range, or output folders.

## Phase 1 — PDF → OCR → raw text (`extract_pdf_text.py`)

For each page:
1. Try native PDF text extraction.
2. If the page has no usable text (scanned/image page), render it and
   run Tesseract OCR (French).
3. Save the result exactly as extracted, named after the **original
   PDF page number** (e.g. `page_005.txt` = PDF page 5).

No cleaning, no structural parsing, no LLM, no JSON at this stage.

## Phase 2 — Mechanical text cleaning (`clean_text.py`)

Reads `output/raw/page_*.txt` and writes whitespace-normalized copies
to `output/cleaned/page_*.txt`: collapses repeated spaces/blank lines,
strips stray control characters, normalizes Unicode accent composition.
It never touches letters, digits, or math symbols, never deletes a
line (including page-number footers), and never attempts to correct
OCR or math errors — that requires the original page image and is
deferred to the LLM reconstruction stage.

## Phase 3 — Intelligent reconstruction with Claude (`reconstruct.py`)

For each page, sends the cleaned text plus the original page image
(rendered from the PDF, cached as PNG) to Claude, along with a small
window of neighboring pages' cleaned text as read-only context (so
content spanning a page break is recognized, not misread). Claude
corrects OCR errors, reconstructs multi-column/split expressions,
converts math to LaTeX, and preserves document structure (chapter/
section/theorem/exercise/... via a small closed tag vocabulary) — using
the image as the visual source of truth whenever the text is ambiguous.

Never invents missing content, never solves exercises unless the
solution is explicitly present, never changes mathematical meaning.
Genuinely ambiguous or illegible content is flagged inline with
`<uncertain reason="...">...</uncertain>` or `<gap reason="..."/>`
rather than silently guessed — never invented content that reads as if
it were confidently transcribed.

Output is Markdown with a YAML frontmatter (page number, source image
path, `needs_review` flag, uncertainty counts), one file per page — a
human-reviewable intermediate, not yet the final JSON structure.

**This stage calls Claude through the locally authenticated Claude
Code CLI (`claude -p`) — it does NOT use the Anthropic API directly and
does NOT require `ANTHROPIC_API_KEY`.** It reuses whatever session
`claude auth login` already set up (e.g. a Pro/Max/Team subscription),
so there's no separate API billing to configure. This also means usage
counts against your Claude Code plan's normal rate limits (the same
pool your interactive IDE usage shares) rather than pay-per-token API
billing — see step 5 below. Pages already reconstructed are skipped
unless `--force` is passed, so an interrupted or rate-limited run can
be resumed later without redoing finished pages.

## Phase 3b/3c — Reconstruction validation (`validate_reconstruction.py`, `validate_with_claude.py`)

Two independent layers check the reconstructed Markdown before it's
trusted: Layer 1 (`validate_reconstruction.py`) is deterministic —
malformed tags, empty math, suspicious QCM formatting, frontmatter
consistency. Layer 2 (`validate_with_claude.py`) asks Claude to compare
the reconstructed Markdown against the original page image for
*fidelity* (not mathematical correctness) — selectively, only on pages
flagged by Layer 1 or explicitly requested, never the whole chapter
blindly. See each script's docstring for details.

## Phase 4 — Visual element candidate detection (`detect_visual_elements.py`)

Scans the source PDF for regions that might be mathematical figures
(graphs, geometry, diagrams, tables), using only PyMuPDF structural
metadata — embedded images, vector drawings, `find_tables()`. No
rendering, no Claude, 100% deterministic. Explicitly excludes page
furniture (headers/footers/logos recurring across pages) and the
full-page scan background. Output: `visual_elements_report.json`.

## Phase 4b — Pixel-based bbox refinement (`refine_visual_elements.py`)

The PDF-object bboxes from Phase 4 are frequently incomplete — this
scanned PDF splits a figure's dense/colorful sub-regions into their own
image tiles but leaves thin axis lines, labels, and sparse curve
segments baked into the excluded background tile. This stage regrows
each candidate's true extent from the actual rendered pixels
(ink/background thresholding + connected-component analysis), with a
safety cap that falls back to the original bbox rather than risk a bad
guess. Output: `visual_elements_report_refined.json`.

## Phase 4c — Soft classification hint (`evaluate_visual_elements.py`)

Adds a **soft triage hint** — `figure` / `text_only` / `ambiguous` —
to help a human skim candidates faster. **This is not a ground-truth
classifier and must not be treated as one.** `needs_review` stays
`true` for every candidate regardless of hint; nothing is ever excluded
based on it. Known, confirmed-by-manual-inspection failure modes:

1. Dense, tightly-spaced two-line theorem statements can read as `figure`.
2. Decorative page banners ("Cours", "Exercices et problèmes" pill
   headers) can read as `figure`.
3. A real graph preceded by substantial intro text can read as
   `text_only`, hiding the figure.
4. Genuine tables currently read as `text_only` (not yet their own
   category).

See the module's docstring for the full validation history and exact
examples of each failure mode.

## Phase 4d — Human review preparation (`prepare_review.py`)

Joins Phase 4b's bboxes, Phase 4c's hints, and Phase 5's cropped PNG
paths into one flat, review-friendly report — `visual_elements_review.json`
and `.txt`, grouped `figure` → `ambiguous` → `text_only` (review order,
not confidence order) with both the original and refined bbox, the
hint's plain-language explanation, and the crop's image path for every
candidate. Purely a read-only join; detects nothing new.

## Phase 5 — Figure candidate extraction (`extract_figure_candidates.py`)

Reads any visual-elements report and renders a cropped PNG (with
configurable margin) for every `candidate` element, ignoring
`full_page_scan` entries. Generic over report/page range — works
unchanged against either the Phase 4 or Phase 4b (refined) report, just
by pointing `--report` at it. Rerunnable with on-disk PNG caching.

## Structure

```
data/
├── math-4eme-tome1/source/source.pdf   # input (scanned PDF)
├── output/
│   ├── raw/                 # Phase 1 output
│   │   ├── page_005.txt
│   │   └── ...
│   ├── cleaned/              # Phase 2 output
│   │   ├── page_005.txt
│   │   └── ...
│   ├── page_images/          # Phase 3: cached rendered page images
│   │   ├── page_005.png
│   │   └── ...
│   └── reconstructed/        # Phase 3 output
│       ├── page_005.md
│       └── ...
├── src/
│   ├── config.py            # input/output paths, page range, OCR/cleaning/reconstruction settings
│   ├── pdf_render.py        # shared PDF -> image rendering (Phases 1 & 3)
│   ├── extract_pdf_text.py  # Phase 1: OCR extraction script
│   ├── clean_text.py        # Phase 2: mechanical whitespace cleaning
│   ├── prompts.py           # Phase 3: Claude system prompt + message building
│   └── reconstruct.py       # Phase 3: Claude-based reconstruction script
├── requirements.txt
└── README.md
```

## 1. Install Tesseract OCR (system dependency)

Tesseract itself is a native binary, not a Python package — install it
separately, **with the French language pack**:

- **Windows**: install from the
  [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki).
  During setup, check the "French" language under additional language
  data. Note the install path (typically
  `C:\Program Files\Tesseract-OCR\tesseract.exe`).
  If `tesseract` is not on your `PATH` afterwards, set
  `TESSERACT_CMD` in `src/config.py` to that path.
- **macOS**: `brew install tesseract tesseract-lang`
- **Linux (Debian/Ubuntu)**: `sudo apt install tesseract-ocr tesseract-ocr-fra`

Verify it works:

```bash
tesseract --version
tesseract --list-langs   # should list "fra"
```

## 2. Install Python dependencies

From the `data/` folder, using a virtual environment is recommended:

```bash
cd data
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## 3. Run the OCR extraction (Phase 1)

From `data/src/`:

```bash
cd src
python extract_pdf_text.py
```

This uses the defaults in `config.py` (Chapter 1, pages 5–27). To
override:

```bash
python extract_pdf_text.py --start 5 --end 27 --pdf ../math-4eme-tome1/source/source.pdf --output ../output/raw
```

Progress and any per-page errors are logged to the console. A page
that fails to process is skipped (logged) rather than aborting the
whole run. Output: `data/output/raw/page_005.txt` ... `page_027.txt`,
raw extracted/OCR'd text, unmodified — including any OCR noise or
uncertain characters.

## 4. Run the text cleaning (Phase 2)

From `data/src/`, after Phase 1 has produced `output/raw/`:

```bash
python clean_text.py
```

To override the input/output folders:

```bash
python clean_text.py --input ../output/raw --output ../output/cleaned
```

Output: `data/output/cleaned/page_005.txt` ... `page_027.txt`, same
content as Phase 1's output with whitespace normalized — no letters,
digits, or math symbols are changed or removed.

## 5. Run the reconstruction (Phase 3)

Requires [Claude Code](https://docs.claude.com/en/docs/claude-code) to
be installed and logged in — no `.env`, no `ANTHROPIC_API_KEY`, no
manually-provided credentials of any kind. Check you're logged in with:

```bash
claude auth status
```

`reconstruct.py` calls the `claude` CLI as a subprocess for each page
and fails fast with a clear error if it's missing from `PATH` or the
CLI itself reports an error (including rate-limit rejections — Claude
Code plans are rate-limited on a rolling window rather than metered
per token; a rejected page is logged as failed, not silently retried,
so you can resume later with `--force` once the window resets).

From `data/src/`, after Phase 2 has produced `output/cleaned/`, test on
a single page first:

```bash
python reconstruct.py --start 6 --end 6
```

Then run the full configured range:

```bash
python reconstruct.py
```

Re-running is safe and won't re-spend on already-done pages — add
`--force` to reprocess specific pages:

```bash
python reconstruct.py --start 6 --end 6 --force
```

Output: `data/output/reconstructed/page_005.md` ... `page_027.md`.
Each file's frontmatter includes `needs_review: true` when the page
contains any `<uncertain>`/`<gap>` marker — check those first. Cached
page images used as Claude's visual input are saved to
`data/output/page_images/page_NNN.png` for side-by-side review against
the corresponding `.md` file.
