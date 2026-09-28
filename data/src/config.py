"""Configuration for the PDF OCR ingestion pipeline (Phase 1).

Plain constants on purpose: no settings framework needed for a single
script. Override on the command line (see extract_pdf_text.py --help)
if you need a different PDF, page range, or output folder.
"""

from pathlib import Path

# data/
DATA_DIR = Path(__file__).resolve().parent.parent

# Input PDF
PDF_PATH = DATA_DIR / "math-4eme-tome1" / "source" / "source.pdf"

# Output folder for raw, page-per-file text
OUTPUT_DIR = DATA_DIR / "output" / "raw"

# Output folder for mechanically-cleaned (whitespace-only) page text
CLEANED_DIR = DATA_DIR / "output" / "cleaned"

# Page range to process, 1-indexed and inclusive, matching the page
# numbers as shown in a normal PDF viewer.
# Chapter 1 of math-4eme-tome1 = pages 5-27.
START_PAGE = 5
END_PAGE = 27

# OCR settings
OCR_LANGUAGE = "fra"  # Tesseract language code for French
OCR_DPI = 300  # rasterization resolution used before OCR

# A page is treated as having "usable" native text when the extracted
# text (after stripping whitespace) has at least this many characters.
# Below this threshold we fall back to OCR (page is likely a scanned
# image with no embedded text layer).
MIN_NATIVE_TEXT_CHARS = 20

# Only needed on Windows if tesseract.exe is not on PATH, e.g.:
# r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD = None

# --- Phase 3: LLM reconstruction (Claude) ---

# Output folder for reconstructed page Markdown
RECONSTRUCTED_DIR = DATA_DIR / "output" / "reconstructed"

# Folder for cached page images: rendered once, sent to Claude, and
# reused for side-by-side human review against the reconstructed output
PAGE_IMAGES_DIR = DATA_DIR / "output" / "page_images"

# Rendering resolution for reconstruction images (reuses OCR_DPI: already
# proven legible in Phase 1)
RECONSTRUCTION_IMAGE_DPI = OCR_DPI

# Claude model used for reconstruction, called through the locally
# authenticated Claude Code CLI (`claude -p`) -- no API key involved
CLAUDE_MODEL = "claude-sonnet-5"

# How many neighboring pages of cleaned text (each side) to include as
# read-only context, so Claude can recognize content that spans a page
# break without reconstructing those neighboring pages itself
CONTEXT_WINDOW_PAGES = 1

# Timeout (seconds) for a single `claude -p` reconstruction call
RECONSTRUCTION_TIMEOUT_SECONDS = 300

# --- Phase 3b: deterministic post-reconstruction validation ---

RECONSTRUCTION_REPORT_JSON = DATA_DIR / "output" / "reconstruction_report.json"
RECONSTRUCTION_REPORT_TXT = DATA_DIR / "output" / "reconstruction_report.txt"

# --- Phase 3c: Claude-based visual/semantic validation ---

# Output folder for per-page Claude validation results
VALIDATION_DIR = DATA_DIR / "output" / "validation"

# Combined Layer 1 (deterministic) + Layer 2 (Claude) report
FINAL_QUALITY_REPORT_JSON = DATA_DIR / "output" / "final_quality_report.json"
FINAL_QUALITY_REPORT_TXT = DATA_DIR / "output" / "final_quality_report.txt"

# --- Phase 4: deterministic visual-element candidate detection ---

VISUAL_ELEMENTS_REPORT_JSON = DATA_DIR / "output" / "visual_elements_report.json"

# Minimum width/height (PDF points) for an embedded image fragment to be
# considered at all. Measured against every fragment actually present in
# Chapter 1: the book's decorative hairline borders are built from a
# consistent ~3.85pt grid unit (3.8, 7.7, 11.5, 15.4, 19.2pt...), and a
# genuine (small) piece of a figure -- e.g. a thin axis/tick fragment the
# scan pipeline split out on its own -- can legitimately be exactly as
# thin as the border grid's 2nd step (~7.7pt; this previously being
# filtered out is what caused part of a graph on page 13 to go missing
# at the seed stage, before pixel-based refinement compensated for it).
# Only the finest (~3.8pt) hairline step is unambiguous border noise, so
# the floor sits just above it -- see VISUAL_ELEMENT_MAX_RULE_LENGTH_RATIO
# below for the actual defense against long decorative rule/border bars,
# which thinness alone can't safely distinguish from real thin fragments.
VISUAL_ELEMENT_MIN_FRAGMENT_PT = 5

# A thin fragment (either dimension < VISUAL_ELEMENT_MIN_FRAGMENT_PT * 3,
# i.e. still clearly "thin") is excluded as a decorative rule/border bar
# -- not a figure fragment -- if its LONG dimension exceeds this fraction
# of the corresponding page dimension. Real figure fragments in this
# chapter are always small in both dimensions (observed up to ~65pt
# long); the book's box-border and page-margin rules run 100-457pt,
# i.e. a large fraction of the page. This is deliberately independent of
# (and a backstop for) the recurring-xref page-furniture check: that
# check only catches a rule that repeats across 2+ pages, not a one-off
# thin bar unique to a single page.
VISUAL_ELEMENT_MAX_RULE_LENGTH_RATIO = 0.15

# A single fragment, or a cluster of merged fragments, covering at least
# this fraction of the page area is treated as (part of) the full-page
# scan background, never a candidate figure.
VISUAL_ELEMENT_BACKGROUND_AREA_RATIO = 0.5

# A merged cluster covering less than this fraction of the page area is
# treated as icon/fragment noise, not a plausible figure.
VISUAL_ELEMENT_MIN_AREA_RATIO = 0.005

# Max gap (PDF points) between two fragment bboxes for them to be merged
# into one candidate region. 0 = only merge on actual overlap/touch --
# this scanned PDF renders unrelated same-page content (running header,
# colored callout boxes, an actual figure) as many separate raster tiles
# positioned close together, so any positive tolerance here chains
# unrelated regions into one meaningless page-spanning blob.
VISUAL_ELEMENT_CLUSTER_GAP_PT = 0

# --- Phase 5: figure candidate extraction (deterministic PNG crops) ---

FIGURE_CANDIDATES_DIR = DATA_DIR / "output" / "figure_candidates"
FIGURE_CANDIDATES_INDEX_JSON = FIGURE_CANDIDATES_DIR / "index.json"

# Margin added around each candidate bbox before cropping, in the SAME
# pixel space as the bbox itself (pixels at RECONSTRUCTION_IMAGE_DPI) --
# not raw PDF points, so it composes directly with the bbox with no unit
# conversion surprise. Keeps labels/axes/legends from being cut off.
FIGURE_CROP_MARGIN_PX = 20

# --- Phase 4b: pixel-based candidate bbox refinement ---

VISUAL_ELEMENTS_REFINED_REPORT_JSON = DATA_DIR / "output" / "visual_elements_report_refined.json"

# Search window margin (pixels, same pixel space as bbox) around a seed
# candidate within which pixel-based growth is allowed to look for
# missing figure content (thin lines/labels not captured as their own
# PDF image object). Growth that reaches this window's edge is treated
# as an untrustworthy runaway merge into unrelated content, not a real
# whitespace boundary.
FIGURE_REFINEMENT_SEARCH_MARGIN_PX = 400

# A pixel counts as "ink" (not blank page) if it deviates from pure
# white by more than this amount in at least one channel.
FIGURE_REFINEMENT_INK_THRESHOLD = 40

# Binary dilation radius (pixels) applied to the ink mask before
# connected-component labeling, so a figure's thin lines/labels that are
# physically separate but nearby (e.g. an axis digit sitting just off
# the curve) get bridged into the same connected region.
FIGURE_REFINEMENT_DILATION_RADIUS_PX = 20

# A region's dominant background color is considered "tinted" (i.e. a
# colored callout/reminder box rather than plain white page) if its
# max-channel/min-channel spread exceeds this. Empirically, real figure
# backgrounds measured ~0-2; tinted callout boxes measured ~48-64.
FIGURE_TEXT_BOX_COLOR_SPREAD_THRESHOLD = 20

# --- Phase 4c: soft figure/text-only/ambiguous classification hints ---
# (evaluate_visual_elements.py -- deliberately kept separate from the
# detection/refinement pipeline; see that module's docstring for the
# known failure modes of this classifier)

VISUAL_ELEMENTS_EVALUATION_JSON = DATA_DIR / "output" / "visual_elements_evaluation.json"
VISUAL_ELEMENTS_EVALUATION_TXT = DATA_DIR / "output" / "visual_elements_evaluation.txt"

# --- Phase 5b: refined-bbox crops (separate experiment directory from
# the original FIGURE_CANDIDATES_DIR, per instruction to keep refined
# outputs isolated) ---

FIGURE_CANDIDATES_REFINED_DIR = DATA_DIR / "output" / "figure_candidates_refined"
FIGURE_CANDIDATES_REFINED_INDEX_JSON = FIGURE_CANDIDATES_REFINED_DIR / "index.json"

# --- Phase 4d: human-review preparation ---

VISUAL_ELEMENTS_REVIEW_JSON = DATA_DIR / "output" / "visual_elements_review.json"
VISUAL_ELEMENTS_REVIEW_TXT = DATA_DIR / "output" / "visual_elements_review.txt"

# --- Phase 4e: V2 multi-signal classification + text-margin bbox
# trimming (classify_visual_elements_v2.py / detect_visual_elements_v2.py)
# -- reads the Phase 4b refined report, writes a SEPARATE report/crop
# directory so V1 results are never overwritten (V1 vs V2 comparison) ---

VISUAL_ELEMENTS_REPORT_V2_JSON = DATA_DIR / "output" / "visual_elements_report_v2.json"
FIGURE_CANDIDATES_V2_DIR = DATA_DIR / "output" / "figure_candidates_v2"
FIGURE_CANDIDATES_V2_INDEX_JSON = FIGURE_CANDIDATES_V2_DIR / "index.json"
VISUAL_DETECTION_V2_EVALUATION_JSON = DATA_DIR / "output" / "visual_detection_v2_evaluation.json"
VISUAL_DETECTION_V2_REPORT_TXT = DATA_DIR / "output" / "visual_detection_v2_report.txt"

# --- Phase 4g (V3): connected-component figure-completeness refinement
# (figure_completeness_v3.py / refine_completeness_for_v3.py) -- reads
# the Phase 4e V2 report, writes a SEPARATE report/crop directory; V2's
# own report/crops are never modified or re-run ---

VISUAL_ELEMENTS_REPORT_V3_JSON = DATA_DIR / "output" / "visual_elements_report_v3.json"
FIGURE_CANDIDATES_V3_DIR = DATA_DIR / "output" / "figure_candidates_v3"
FIGURE_CANDIDATES_V3_INDEX_JSON = FIGURE_CANDIDATES_V3_DIR / "index.json"
VISUAL_DETECTION_V3_EVALUATION_JSON = DATA_DIR / "output" / "visual_detection_v3_evaluation.json"
VISUAL_DETECTION_V3_REPORT_TXT = DATA_DIR / "output" / "visual_detection_v3_report.txt"

# --- Phase 4j (V4): FIGURE/NOT_FIGURE/FIGURE_REVIEW classification
# (classify_visual_elements_v4.py / detect_visual_elements_v4.py) --
# reads the V3 report (completeness-refined bboxes), writes a SEPARATE
# report/crop directory; V3's own report/crops are never modified ---

VISUAL_ELEMENTS_REPORT_V4_JSON = DATA_DIR / "output" / "visual_elements_report_v4.json"
FIGURE_CANDIDATES_V4_DIR = DATA_DIR / "output" / "figure_candidates_v4"
FIGURE_CANDIDATES_V4_INDEX_JSON = FIGURE_CANDIDATES_V4_DIR / "index.json"
VISUAL_DETECTION_V4_EVALUATION_JSON = DATA_DIR / "output" / "visual_detection_v4_evaluation.json"
VISUAL_DETECTION_V4_EVALUATION_TXT = DATA_DIR / "output" / "visual_detection_v4_evaluation.txt"
VISUAL_DETECTION_V4_FEATURES_JSON = DATA_DIR / "output" / "visual_detection_v4_features.json"

# --- Phase 4i: human-review preparation for V3 (third verification round) ---

VISUAL_ELEMENTS_REVIEW_V3_JSON = DATA_DIR / "output" / "visual_elements_review_v3.json"
VISUAL_ELEMENTS_REVIEW_V3_TXT = DATA_DIR / "output" / "visual_elements_review_v3.txt"

# --- Phase 6: structured knowledge JSON conversion ---
# See data/schema/knowledge_schema.md and knowledge_item.schema.json for the
# full design. Document/chapter identity is fixed via config rather than
# detected from headings -- deliberately out of scope for this first
# converter (see that doc's "open questions" section).

KNOWLEDGE_DIR = DATA_DIR / "output" / "knowledge"
KNOWLEDGE_SCHEMA_JSON = DATA_DIR / "schema" / "knowledge_item.schema.json"

DOCUMENT_ID = "math-4eme-tome1"
DOCUMENT_TITLE = "Mathématiques 4ème année secondaire — Tome 1"
DOCUMENT_SUBJECT = "Mathématiques"
DOCUMENT_LEVEL = "4ème année secondaire"
DOCUMENT_COUNTRY = "Tunisia"

CHAPTER_NUMBER = 1
CHAPTER_TITLE = "Continuité et limites"
KNOWLEDGE_CHAPTER_01_JSON = KNOWLEDGE_DIR / "chapter_01_continuite_limites.json"

# --- Phase 5a: final figure dataset (build_final_figures.py /
# crop_correction.py) -- finalizes the 19 human-confirmed-real figures
# (13 VALIDATED unchanged from V4 + 6 NEEDS_CORRECTION crop-corrected)
# into their own directory. Additive only: V3/V4 reports and crops are
# never modified or re-run here. ---

FINAL_FIGURES_DIR = DATA_DIR / "output" / "final_figures"
FINAL_FIGURES_INDEX_JSON = FINAL_FIGURES_DIR / "index.json"
FINAL_FIGURES_REVIEW_JSON = FINAL_FIGURES_DIR / "review.json"
FINAL_FIGURES_CONTACT_SHEET_PNG = FINAL_FIGURES_DIR / "contact_sheet.png"
FINAL_FIGURES_VALIDATION_REPORT_JSON = FINAL_FIGURES_DIR / "validation_report.json"

# --- Phase 5b: figure <-> knowledge association
# (associate_figures_knowledge.py) -- chapter-generic by design: the
# chapter_id is read from the knowledge JSON's own "chapter.id" field
# at runtime, never hardcoded. Output lives under a PER-CHAPTER
# directory computed from that id (see associations_dir/associations_json
# below), not a fixed Chapter-1-only constant like the ones above --
# this is the one part of config.py meant to generalize to future
# chapters without edits. Chapter 1's own knowledge/figures inputs
# (KNOWLEDGE_CHAPTER_01_JSON, FINAL_FIGURES_INDEX_JSON above) are still
# used as this project's only current CLI defaults. ---


def associations_dir(chapter_id: str) -> Path:
    return DATA_DIR / "output" / chapter_id / "associations"


def associations_json(chapter_id: str) -> Path:
    return associations_dir(chapter_id) / "figure_knowledge.json"


# Score (0-1) at/above which a figure's top candidate is accepted
# automatically, PROVIDED it also clears ASSOCIATION_AUTO_MATCH_MARGIN
# over the runner-up (see associate_figures_knowledge.py:decide). Not
# chapter- or content-tuned -- derived from the scoring weights below,
# which are documented at their own definition site.
ASSOCIATION_AUTO_MATCH_THRESHOLD = 0.72

# Score (0-1) at/above which a figure's top candidate is at least
# offered to human review, even if not confident enough for
# AUTO_MATCH. Below this, the figure is NO_MATCH (no plausible
# candidate found at all).
ASSOCIATION_REVIEW_THRESHOLD = 0.40

# Minimum score margin the top candidate must hold over the runner-up
# to be accepted as AUTO_MATCH outright -- guards against auto-picking
# one of two nearly-equally-plausible same-page candidates; a genuine
# tie is exactly the case that should go to human review instead.
ASSOCIATION_AUTO_MATCH_MARGIN = 0.12

ASSOCIATION_ALGORITHM_VERSION = "assoc-v1"

# --- Phase 7: knowledge normalization (normalize_knowledge.py) --
# chapter-generic, same pattern as associations_dir/associations_json
# above: output lives under a PER-CHAPTER directory computed from the
# chapter_id found in the knowledge JSON at runtime, never a fixed
# Chapter-1-only constant. The reconstructed/converted knowledge JSON
# (KNOWLEDGE_CHAPTER_01_JSON above) is read-only input here, never
# modified or regenerated. ---

NORMALIZED_SCHEMA_JSON = DATA_DIR / "schema" / "normalized_knowledge.schema.json"
NORMALIZATION_ALGORITHM_VERSION = "normalize-v1"


def normalized_dir(chapter_id: str) -> Path:
    return DATA_DIR / "output" / chapter_id / "normalized"


def normalized_json(chapter_id: str) -> Path:
    return normalized_dir(chapter_id) / "knowledge.json"


def normalized_validation_report_json(chapter_id: str) -> Path:
    return normalized_dir(chapter_id) / "validation_report.json"


# This project's only current chapter -- the one hardcoded place this
# id may appear (as a CLI default), same convention as
# KNOWLEDGE_CHAPTER_01_JSON/FINAL_FIGURES_INDEX_JSON above. Production
# modules (normalize_knowledge.py, enrich_knowledge.py, ...) must only
# ever reference this constant, never the literal string themselves.
CHAPTER_01_ID = "math-4eme-tome1-ch01"
NORMALIZED_CHAPTER_01_JSON = normalized_json(CHAPTER_01_ID)


# --- Phase 8: knowledge enrichment (enrich_knowledge.py) -- same
# chapter-generic pattern as normalized_dir/normalized_json above.
# Reads the normalized JSON (read-only), writes a SEPARATE per-chapter
# enrichment file; never modifies normalization, the source knowledge
# JSON, figures, associations, or the Human Review model. v1 is 100%
# deterministic/rule-based (see knowledge_enrichment.md) -- no LLM call
# exists yet, so MATH_GLOSSARY_FR_JSON is the only external input
# besides the normalized JSON itself. ---

ENRICHMENT_SCHEMA_JSON = DATA_DIR / "schema" / "knowledge_enrichment.schema.json"
MATH_GLOSSARY_FR_JSON = DATA_DIR / "schema" / "math_glossary_fr.json"
ENRICHMENT_ALGORITHM_VERSION = "enrich-v1"


def enrichment_dir(chapter_id: str) -> Path:
    return DATA_DIR / "output" / chapter_id / "enrichment"


def enrichment_json(chapter_id: str) -> Path:
    return enrichment_dir(chapter_id) / "knowledge_enrichment.json"


def enrichment_validation_report_json(chapter_id: str) -> Path:
    return enrichment_dir(chapter_id) / "validation_report.json"


# --- Phase 9: knowledge relations (relate_knowledge.py) -- same
# chapter-generic pattern as enrichment_dir/enrichment_json above.
# Reads the normalized JSON, the enrichment file, and (optionally) the
# figure<->knowledge association file + an exported Human Review
# decisions file (read-only); writes a SEPARATE per-chapter relations
# file. Never modifies any of its inputs. Zero LLM calls (see
# knowledge_relations.md). ---

RELATIONS_SCHEMA_JSON = DATA_DIR / "schema" / "knowledge_relations.schema.json"
RELATIONS_ALGORITHM_VERSION = "relations-v1"

# reading_order_distance thresholds for applies_concept's confidence
# tier -- derived from the real "branches infinies" cluster used
# throughout knowledge_relations.md (a genuine same-unit link measured
# distance 3; a same-nominal-concept but different-teaching-unit link
# measured distance 50-65), not guessed.
RELATIONS_HIGH_CONFIDENCE_MAX_DISTANCE = 10
RELATIONS_MEDIUM_CONFIDENCE_MAX_DISTANCE = 30


def relations_dir(chapter_id: str) -> Path:
    return DATA_DIR / "output" / chapter_id / "relations"


def relations_json(chapter_id: str) -> Path:
    return relations_dir(chapter_id) / "knowledge_relations.json"


def relations_validation_report_json(chapter_id: str) -> Path:
    return relations_dir(chapter_id) / "validation_report.json"


# --- Phase 10: knowledge chunking (chunk_knowledge.py) -- same
# chapter-generic pattern as relations_dir/relations_json above. Reads
# the normalized JSON, the enrichment file, and (optionally) the
# relations file + final figures index (read-only); writes a SEPARATE
# per-chapter chunks file. Never modifies any of them. Zero LLM calls
# (see knowledge_chunking.md). ---

CHUNK_SCHEMA_JSON = DATA_DIR / "schema" / "knowledge_chunk.schema.json"
CHUNKING_ALGORITHM_VERSION = "chunk-v1"

# An item is a split CANDIDATE only if both hold: its own statement-only
# text (content with any correction suffix already removed -- see
# chunk_knowledge.py's _find_correction_split; the correction is its own
# chunk and must not inflate this measurement) plus proof exceeds this
# length, AND it has >=2 top-level exercise_details.questions to split
# along (never a character-count split alone -- see
# knowledge_chunking.md §4). Measured directly against Chapter 1's real
# data once the correction text is correctly excluded: the next item
# below this line is 1280 chars (a property, which never has
# exercise_details anyway); the one real candidate (an activity) measures
# 1508 -- this sits cleanly above it, not tuned to hit a target count.
# (The chapter's one exercise with a correction, exo-001, looked like an
# 8126/4092-char item before its embedded correction was measured and
# excluded -- once excluded, its own statement is only 1068 chars and
# does not need splitting at all; a real, documented recalibration from
# this constant's first estimate in knowledge_chunking.md.)
CHUNK_SPLIT_MIN_CHARS = 1500


def chunks_dir(chapter_id: str) -> Path:
    return DATA_DIR / "output" / chapter_id / "chunks"


def chunks_json(chapter_id: str) -> Path:
    return chunks_dir(chapter_id) / "knowledge_chunks.json"


def chunks_validation_report_json(chapter_id: str) -> Path:
    return chunks_dir(chapter_id) / "validation_report.json"


# --- Phase 11: knowledge embeddings (embed_knowledge.py) -- same
# chapter-generic pattern as chunks_dir/chunks_json above. Reads the
# chunks JSON (read-only); writes a SEPARATE per-chapter, per-model
# output directory. Never modifies chunking, relations, enrichment,
# normalization, figures, associations, or the Human Review system.
# Model choice, template, and every design decision here follow
# data/schema/embedding_design.md exactly -- see that document for the
# full rationale (French/LaTeX-heavy corpus measurements, model
# comparison with cited sources, identity/caching/validation strategy).
# ---

EMBEDDING_SCHEMA_JSON = DATA_DIR / "schema" / "embedding_manifest.schema.json"
EMBEDDING_PIPELINE_VERSION = "embed-v1"

# Exact model + framework chosen in embedding_design.md §3 -- MIT
# license, 1024-dim (fixed), 8192-token context, multilingual/French
# benchmarks competitive with multilingual-e5-large, native
# sentence-transformers support. Never silently substituted.
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
# Exact HuggingFace repo commit SHA for BAAI/bge-m3's main branch,
# resolved via the HF API at design time (never a branch name/tag alone
# -- see embedding_design.md §4/§8: a model *name* is not by
# itself reproducible if the weights behind it ever change).
EMBEDDING_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EMBEDDING_FRAMEWORK = "sentence-transformers"
EMBEDDING_DIMENSION = 1024
EMBEDDING_NORMALIZATION = "l2"
EMBEDDING_DTYPE = "float32"
EMBEDDING_DEFAULT_BATCH_SIZE = 16


def _embedding_model_id(model_name: str, model_revision: str = EMBEDDING_MODEL_REVISION) -> str:
    """Filesystem-safe slug namespacing the output directory -- e.g.
    'BAAI/bge-m3' + '5617a9f61b0...' -> 'bge-m3-5617a9f61b0'. Includes a
    short revision prefix (git-style, 12 hex chars) because
    manifest.json carries a SINGULAR (model, revision) pair (see
    embedding_manifest.schema.json) -- a different revision of the SAME
    model name must therefore get its own directory, never share one
    with (and silently overwrite) another revision's manifest (see
    embedding_design.md §5's 'different model or revision -> a
    separate, additional embedding' rule)."""
    name_part = model_name.rsplit("/", 1)[-1].lower()
    revision_part = (model_revision or "unknown")[:12]
    return f"{name_part}-{revision_part}"


def embeddings_dir(chapter_id: str, model_name: str = EMBEDDING_MODEL_NAME,
                    model_revision: str = EMBEDDING_MODEL_REVISION) -> Path:
    return DATA_DIR / "output" / chapter_id / "embeddings" / _embedding_model_id(model_name, model_revision)


def embeddings_manifest_json(chapter_id: str, model_name: str = EMBEDDING_MODEL_NAME,
                              model_revision: str = EMBEDDING_MODEL_REVISION) -> Path:
    return embeddings_dir(chapter_id, model_name, model_revision) / "manifest.json"


def embeddings_vectors_npy(chapter_id: str, model_name: str = EMBEDDING_MODEL_NAME,
                            model_revision: str = EMBEDDING_MODEL_REVISION) -> Path:
    return embeddings_dir(chapter_id, model_name, model_revision) / "vectors.npy"


def embeddings_records_json(chapter_id: str, model_name: str = EMBEDDING_MODEL_NAME,
                             model_revision: str = EMBEDDING_MODEL_REVISION) -> Path:
    return embeddings_dir(chapter_id, model_name, model_revision) / "records.json"


def embeddings_validation_report_json(chapter_id: str, model_name: str = EMBEDDING_MODEL_NAME,
                                       model_revision: str = EMBEDDING_MODEL_REVISION) -> Path:
    return embeddings_dir(chapter_id, model_name, model_revision) / "validation_report.json"


# --- Phase 12: Vector DB import (import_embeddings.py) -- reads the
# existing embedding artifacts (manifest.json/records.json/vectors.npy,
# read-only) and syncs them into a local PostgreSQL+pgvector table. Never
# regenerates embeddings, never modifies chunks/enrichment/relations/
# normalization/figures/associations/backend/frontend. Schema
# initialization (init_vector_db_schema.py) is a separate step from import
# (import_embeddings.py) by design -- see data/schema/vector_db_design.md
# / vector_db_payload.schema.json for the full rationale (one table PER
# DIMENSION, e.g. embeddings_1024, holding every chapter/model/revision
# that happens to share that dimension -- never one table per chapter). ---

VECTOR_DB_SCHEMA_SQL = DATA_DIR / "schema" / "vector_db_schema.sql"
VECTOR_DB_IMPORT_PIPELINE_VERSION = "import-v1"


def vector_table_name(dimension: int) -> str:
    """One table per embedding DIMENSION, never per chapter or model --
    pgvector's vector(N) column is fixed-width, so a differently-dimensioned
    future model gets its own table (embeddings_768, ...), never a column
    added to an existing one (see vector_db_design.md §5/§8)."""
    return f"embeddings_{dimension}"


def _load_env_file_if_present() -> None:
    """Minimal .env loader (no new dependency, matching this file's own
    'plain constants on purpose' philosophy) -- reads DATA_DIR's repo-root
    .env if present, setting os.environ only for keys not already set
    (real environment variables always take precedence). Never raises if
    the file is absent (a real deployment may set POSTGRES_*/DATABASE_URL
    directly in its environment instead)."""
    import os

    env_path = DATA_DIR.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def database_url() -> str:
    """Reads DATABASE_URL from the environment (see .env.example) -- never
    hardcoded, never committed. Falls back to assembling one from the
    individual POSTGRES_* variables (same two-tier layout .env.example
    already documents) if DATABASE_URL itself isn't set."""
    import os

    _load_env_file_if_present()
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "ai_education")
    user = os.environ.get("POSTGRES_USER", "ai_education")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# --- Phase 13: Semantic Search (search_embeddings.py) -- read-only query
# layer over embeddings_1024. Reuses SentenceTransformerBackend/
# l2_normalize (embed_knowledge.py) and table_dimension (import_embeddings.py)
# as-is; never regenerates document embeddings, never modifies chunks/
# enrichment/relations/normalization/figures/associations/backend/frontend/
# the embeddings_1024 table's rows. See data/schema/semantic_search_design.md
# / search_result.schema.json for the full rationale. ---

SEARCH_DEFAULT_TOP_K = 5
# Generous sanity cap, not a tuned value -- guards against an accidental
# unbounded pull, never meant to be a realistic "normal" top_k.
SEARCH_MAX_TOP_K = 100


# --- Phase 14: RAG Context Assembly (rag_context.py) -- deterministic,
# rule-based transformation of Semantic Search results into a bounded,
# ordered, provenance-carrying context for a future LLM. Calls
# search_embeddings.search() unchanged; never queries PostgreSQL
# directly; never duplicates chunk text into a new store. Every constant
# below is grounded in the real Chapter 1 corpus -- see
# data/schema/rag_context_design.md for the full rationale. ---

RAG_CANDIDATE_TOP_K = 20
RAG_MAX_CONTEXT_CHUNKS = 8
RAG_MAX_CONTEXT_CHARS = 10000
RAG_MAX_EXPANSION_PER_SEED = 1
RAG_MAX_CHUNKS_PER_SUBSECTION = 2
RAG_MAX_CHUNKS_PER_SECTION = 3


# --- Phase 15: LLM Answer Generation (generate_answer.py) -- consumes an
# existing RagContext (rag_context.py, unchanged) and produces a
# structured, deterministically-validated AnswerResult via the Gemini
# API. Never re-runs semantic search, never re-assembles context, never
# queries PostgreSQL directly. See
# data/schema/llm_answer_generation_design.md for the full rationale --
# temperature fixed low (favors grounded, consistent phrasing over
# creative variation, design §13); model pinned explicitly, never a
# bare/movable alias (same discipline as EMBEDDING_MODEL_REVISION). ---

GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_TEMPERATURE = 0.1
GEMINI_MAX_OUTPUT_TOKENS = 1024
GEMINI_API_TIMEOUT_SECONDS = 30
LLM_ANSWER_PROMPT_VERSION = "llm-answer-prompt-v1"


def gemini_api_key() -> str | None:
    """Reads GEMINI_API_KEY from the environment (see .env) -- never
    hardcoded, never committed, never logged. Returns None (rather than
    raising) if unset, so callers can produce a clear, specific error at
    the point the key is actually needed."""
    import os

    _load_env_file_if_present()
    return os.environ.get("GEMINI_API_KEY")


# --- Phase 16: FastAPI API layer (data/src/api/) -- a thin HTTP
# orchestration layer over the already-validated Semantic Search / RAG
# Context Assembly / Gemini Answer Generation pipeline. Never
# reimplements any of their logic -- search top_k, Gemini settings, and
# every RAG limit are already configurable above; this phase introduces
# exactly one new setting. See data/schema/fastapi_api_design.md. ---

def api_cors_origins() -> list[str]:
    """Reads API_CORS_ORIGINS (comma-separated) from the environment --
    same .env convention as database_url()/gemini_api_key(). Defaults to
    the Angular dev server's own already-established port
    (frontend/proxy.conf.json) -- local development only, never a
    hardcoded production origin."""
    import os

    _load_env_file_if_present()
    raw = os.environ.get("API_CORS_ORIGINS", "http://localhost:4200")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
