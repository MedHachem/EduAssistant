"""
Phase 6 - Deterministic converter: validated reconstructed Markdown ->
KnowledgeItem JSON.

Implements the schema proposed in data/schema/knowledge_schema.md and
data/schema/knowledge_item.schema.json. Chapter 1 only ("Continuité et
limites", config.START_PAGE..END_PAGE); document/chapter identity is
fixed via config, not detected from headings -- deliberately out of
scope (see the design doc's open questions).

100% deterministic: no Claude/LLM call, no invented content. Every
field is either copied verbatim from the reconstructed Markdown or
derived by a documented, mechanical rule. Every produced item gets
"validation_status": "REVIEW_REQUIRED" -- nothing is ever marked
validated by this script.

---------------------------------------------------------------------
HEADING CLASSIFICATION (data-driven -- built by scanning every heading
that actually occurs across all 23 pages before writing this, not
guessed):

  - BANNER_HEADINGS: exact-text page banners/running headers that
    recur across many pages ("Cours", "Exercices et problèmes",
    "Continuité et limites", "Chapitre 1") plus one page-local banner
    identified by direct inspection ("QCM - VRAI - FAUX", page 23).
    These never become a Section/Subsection and never change the
    current section/subsection state.
  - LABEL_PREFIXES: headings that are just a redundant restatement of
    a bloc's own type ("Théorème", "Théorème (Rappel)", "Définition",
    ...) immediately before that bloc -- confirmed by inspection, not
    assumed. These become that item's `title` (a real, source-derived
    label) rather than a spurious section.
  - SUBSECTION_RE / SECTION_RE: Roman-numeral patterns, tolerant of the
    formatting inconsistencies actually observed in this corpus
    (space-or-not before the sub-number: "III.2" vs "V. 1"). A known,
    NOT silently corrected, limitation: one heading in the source reads
    "1.2 Continuité sur un intervalle" (digit instead of roman "I.2")
    and will not match SUBSECTION_RE -- it falls through to the
    generic bucket below rather than being guessed into "I.2".
  - Anything else non-banner, non-label, non-Roman (e.g. "Problème
    résolu", "QCM", "VRAI - FAUX", the "1.2 ..." heading above) becomes
    an ad-hoc Subsection under the current Section, using its own text
    verbatim as both label and title -- information-preserving, not
    invented.

QUESTION PARSING: intentionally FLAT, not recursively nested. A
"question paragraph" is any paragraph whose first line starts with a
roman/digit/letter marker at the true start of the paragraph. Compound
markers on one line (e.g. "I. 1. Soit la fonction...") are only split
at the first ("I."); the rest stays in that unit's text. This is a
deliberate simplification: a fragile nested parser that guesses wrong
is worse than an honest flat list that's always fully cross-checkable
against `original_content` (which is always preserved verbatim,
unabridged, regardless of how well the flat split works).

FIGURE LINKING: every <figure id="..."> found is recorded with
candidate_id=None, match_status="unresolved" -- this script does NOT
attempt to match a reconstruction's figure id to a visual-elements
candidate_id, even in cases a human has already manually verified
(e.g. page 24's fig-ex7 / page_024_candidate_02), because doing so
automatically here would be an invented link, not a derived one.

Usage:
    python convert_to_knowledge.py
    python convert_to_knowledge.py --start 5 --end 27 --output ../output/knowledge/chapter_01_continuite_limites.json
"""

import argparse
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

import config
from validate_reconstruction import parse_frontmatter

logger = logging.getLogger("convert_to_knowledge")

# --- heading classification (see module docstring) ---------------------

# Pure no-ops: recur across many pages, never a meaningful transition
# within the lesson's own Roman-numeral structure.
BANNER_HEADINGS = {
    "Cours",
    "Continuité et limites",
    "Chapitre 1",
}

# Also recurring banners, but ones that mark a genuine transition out of
# the numbered-lesson structure into an unrelated block of exercises --
# found by inspection: without this, items on the page(s) following one
# of these inherited the previous ad-hoc subsection (e.g. page 24's
# exercises inheriting page 23's "VRAI - FAUX" subsection/concept,
# purely because nothing had reset it). These become real top-level
# Sections (deduped like any other) and reset current_subsection.
PART_HEADINGS = {
    "Exercices et problèmes",
    "QCM - VRAI - FAUX",
}

LABEL_PREFIXES = (
    "Théorème", "Définition", "Propriété", "Remarque", "Exemple", "Corollaire", "Méthode", "Formule",
)

# "III.2 ..." or "V. 1 ..." (tolerant of the space-before-digit variance
# actually observed in this corpus)
SUBSECTION_RE = re.compile(r"^([IVXLC]+)\.\s*(\d+)\s+(.*)$")
# "III. Continuité..." (no digit immediately following the dot)
SECTION_RE = re.compile(r"^([IVXLC]+)\.\s+(.*)$")

HEADING_LINE_RE = re.compile(r"^(#{1,3})[ \t]+(.*)$", re.MULTILINE)

BLOC_RE = re.compile(r'<bloc\b([^>]*)>(.*?)</bloc>', re.DOTALL)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
FIGURE_RE = re.compile(r'<figure\b([^>]*)>(.*?)</figure>', re.DOTALL)
UNCERTAIN_RE = re.compile(r'<uncertain\b([^>]*)>(.*?)</uncertain>', re.DOTALL)
GAP_RE = re.compile(r'<gap\b[^>]*/>')

# Question-outline marker levels, fixed precedence: roman_upper > digit
# > letter > roman_lower (e.g. "I." > "1." > "a." > "i."). "\s*" (not
# "\s+") deliberately, so a bare "1." with nothing else on its line
# still matches (rest="").
QUESTION_ROMAN_UPPER_RE = re.compile(r"^([IVXLC]+)\.\s*(.*)$")
QUESTION_DIGIT_RE = re.compile(r"^(\d+)\.\s*(.*)$")
QUESTION_ROMAN_LOWER_MULTI_RE = re.compile(r"^([ivxlc]{2,})\.\s*(.*)$")
QUESTION_LETTER_RE = re.compile(r"^([a-z])\.\s*(.*)$")
QUESTION_LEVELS = ("roman_upper", "digit", "letter", "roman_lower")
QUESTION_LEVEL_ORDER = {level: i for i, level in enumerate(QUESTION_LEVELS)}
# Only "i" is genuinely ambiguous in practice: a roman-lower sequence
# always STARTS at "i." (then "ii.", "iii." -- already unambiguous via
# QUESTION_ROMAN_LOWER_MULTI_RE). Letters that are ALSO valid roman
# numerals but would never plausibly start such a sequence (v, x, l, c,
# d, m) must stay plain letters -- otherwise a real a/b/c/d... sequence
# gets its "c" or "l" wrongly reclassified as a new nesting level and
# silently misrouted (found via a failing test, not by inspection).
AMBIGUOUS_ROMAN_LOWER_LETTERS = {"i"}

SQUARE_RE = re.compile(r"\$?\\square\$?")
SOLUTION_HEADING_RE = re.compile(r"^#{1,3}\s*(Solution|Correction)\s*$", re.IGNORECASE | re.MULTILINE)
DEMONSTRATION_RE = re.compile(r"^\s*D[ée]monstration\b", re.IGNORECASE)

BLOC_TYPE_TO_ITEM_TYPE = {
    "definition": "definition",
    "theoreme": "theorem",
    "propriete": "property",
    "remarque": "remark",
    "exemple": "example",
    "activite": "activity",
    "exercice": "exercise",
    "question": "exercise",
}

ID_PREFIX = {
    "definition": "def",
    "theoreme": "thm",
    "propriete": "prop",
    "remarque": "rem",
    "exemple": "exm",
    "activite": "act",
    "exercice": "exo",
    "question": "qst",
}


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug


def parse_attrs(attr_string: str) -> dict:
    return dict(ATTR_RE.findall(attr_string))


# --- heading/hierarchy state --------------------------------------------

class HierarchyState:
    """Tracks the current Section/Subsection as pages are scanned in
    order, plus every Section/Subsection created so far. A single
    mutable state object -- deliberately not thread-safe or reusable
    across chapters, this converter processes one chapter in one pass.

    Deliberately does NOT track Concepts: an earlier version of this
    converter auto-generated one Concept per Section/Subsection title,
    which turned out to include clearly non-conceptual structural
    labels ("Solution", "QCM", "Problème résolu", "Exercices et
    problèmes") -- mechanical heading reuse, not curation, and a
    violation of the explicit "no automatic concept inference, Chapter
    1 concepts are manual/curated only" decision. Removed rather than
    filtered, since there is no curated concept list yet to fall back
    to -- see knowledge_schema.md for how concepts should be populated
    once one exists."""

    def __init__(self, chapter_id: str):
        self.chapter_id = chapter_id
        self.sections: dict = {}       # key -> Section dict
        self.subsections: dict = {}    # key -> Subsection dict
        self.current_section_key = None
        self.current_subsection_key = None
        self.pending_title = None      # from a LABEL_PREFIXES heading

    def _touch_page(self, entity: dict, page: int) -> None:
        entity["pdf_page_start"] = min(entity["pdf_page_start"], page)
        entity["pdf_page_end"] = max(entity["pdf_page_end"], page)

    def handle_heading(self, text: str, page: int) -> None:
        text = text.strip()
        if not text:
            return

        if text in BANNER_HEADINGS:
            return

        if text.startswith(LABEL_PREFIXES):
            self.pending_title = text
            return

        if text in PART_HEADINGS:
            key = text
            if key not in self.sections:
                self.sections[key] = {
                    "id": f"{self.chapter_id}-sec-{slugify(text)}",
                    "chapter_id": self.chapter_id,
                    "label": text,
                    "title": text,
                    "pdf_page_start": page,
                    "pdf_page_end": page,
                }
            self._touch_page(self.sections[key], page)
            self.current_section_key = key
            self.current_subsection_key = None
            return

        sub_match = SUBSECTION_RE.match(text)
        if sub_match:
            roman, digit, title = sub_match.groups()
            label = f"{roman}.{digit}"
            key = label
            if key not in self.subsections:
                section_id = self.sections[self.current_section_key]["id"] if self.current_section_key else None
                self.subsections[key] = {
                    "id": f"{self.chapter_id}-sec-{slugify(self.current_section_key or roman)}-sub-{digit}",
                    "section_id": section_id,
                    "label": label,
                    "title": title.strip(),
                    "pdf_page_start": page,
                    "pdf_page_end": page,
                }
            self._touch_page(self.subsections[key], page)
            self.current_subsection_key = key
            return

        sec_match = SECTION_RE.match(text)
        if sec_match:
            roman, title = sec_match.groups()
            key = roman
            if key not in self.sections:
                self.sections[key] = {
                    "id": f"{self.chapter_id}-sec-{slugify(roman + '-' + title)}",
                    "chapter_id": self.chapter_id,
                    "label": roman,
                    "title": title.strip(),
                    "pdf_page_start": page,
                    "pdf_page_end": page,
                }
            self._touch_page(self.sections[key], page)
            self.current_section_key = key
            self.current_subsection_key = None
            return

        # Generic ad-hoc subsection under whatever section is current
        # (e.g. "Problème résolu", "QCM", "VRAI - FAUX") -- verbatim,
        # not invented, not silently mapped to a Roman-numeral slot.
        key = text
        if key not in self.subsections:
            section_id = self.sections[self.current_section_key]["id"] if self.current_section_key else None
            self.subsections[key] = {
                "id": f"{self.chapter_id}-sub-{slugify(text)}",
                "section_id": section_id,
                "label": text,
                "title": text,
                "pdf_page_start": page,
                "pdf_page_end": page,
            }
        self._touch_page(self.subsections[key], page)
        self.current_subsection_key = key

    def touch_current(self, page: int) -> None:
        """Extend the current section/subsection's page span to cover a
        bloc found on this page, even if no new heading appeared."""
        if self.current_section_key:
            self._touch_page(self.sections[self.current_section_key], page)
        if self.current_subsection_key:
            self._touch_page(self.subsections[self.current_subsection_key], page)

    def current_ids(self) -> tuple:
        section_id = self.sections[self.current_section_key]["id"] if self.current_section_key else None
        subsection_id = self.subsections[self.current_subsection_key]["id"] if self.current_subsection_key else None
        return section_id, subsection_id

    def take_pending_title(self) -> str:
        title = self.pending_title
        self.pending_title = None
        return title


# --- per-page tokenization ------------------------------------------------

def tokenize_page(body: str, page: int, hierarchy: HierarchyState) -> list:
    """Walk a page's body top-to-bottom, updating hierarchy state on
    headings and yielding raw bloc records in document order, each
    tagged with the section/subsection/title active at that point and
    the prose immediately following it (for proof detection)."""
    matches = []
    for m in HEADING_LINE_RE.finditer(body):
        matches.append(("heading", m.start(), m.end(), m))
    for m in BLOC_RE.finditer(body):
        matches.append(("bloc", m.start(), m.end(), m))
    matches.sort(key=lambda t: t[1])

    raw_blocs = []
    for i, (kind, start, end, m) in enumerate(matches):
        if kind == "heading":
            hierarchy.handle_heading(m.group(2), page)
            continue

        attrs = parse_attrs(m.group(1))
        bloc_type = attrs.get("type", "")
        content = m.group(2)
        hierarchy.touch_current(page)
        section_id, subsection_id = hierarchy.current_ids()

        trailing_prose = body[end:matches[i + 1][1]] if i + 1 < len(matches) else body[end:]

        raw_blocs.append({
            "page": page,
            "bloc_type": bloc_type,
            "numero": attrs.get("numero"),
            "continues_from_previous_page": attrs.get("continues_from_previous_page") == "true",
            "continues_on_next_page": attrs.get("continues_on_next_page") == "true",
            "content": content.strip(),
            "section_id": section_id,
            "subsection_id": subsection_id,
            "title": hierarchy.take_pending_title(),
            "trailing_prose": trailing_prose,
        })

    return raw_blocs


# --- content-level extraction --------------------------------------------

def extract_figures(text: str) -> list:
    figures = []
    for m in FIGURE_RE.finditer(text):
        attrs = parse_attrs(m.group(1))
        figures.append({
            "pdf_page": None,  # filled in by the caller, which knows the item's primary page
            "reconstructed_figure_id": attrs.get("id"),
            "candidate_id": None,
            "figure_status_in_source": attrs.get("status"),
            "match_status": "unresolved",
        })
    return figures


def extract_uncertainty(text: str) -> dict:
    spans = []
    for m in UNCERTAIN_RE.finditer(text):
        attrs = parse_attrs(m.group(1))
        spans.append({"reason": attrs.get("reason", ""), "text": m.group(2).strip()})
    has_gap = bool(GAP_RE.search(text))
    return {
        "has_uncertain_markers": bool(spans),
        "has_gap_markers": has_gap,
        "uncertain_spans": spans,
    }


def strip_tags_for_parsing(text: str) -> str:
    """A working copy (figures/uncertain/gap markup removed) used only to
    derive statement/questions/correction text -- original_content keeps
    everything verbatim regardless."""
    text = FIGURE_RE.sub("", text)
    text = UNCERTAIN_RE.sub(lambda m: m.group(2), text)  # keep the text, drop the wrapper
    text = GAP_RE.sub("", text)
    return text


def split_correction(text: str) -> tuple:
    """Returns (before_solution, correction_content_or_None)."""
    m = SOLUTION_HEADING_RE.search(text)
    if not m:
        return text, None
    return text[:m.start()].rstrip(), text[m.end():].strip()


CHOICE_STRIP_CHARS = " .\n\t-"


def parse_qcm_choices(text: str) -> tuple:
    """Returns (statement_text, choices_or_None). Choices in the source
    are Markdown bullets ("- $\\square$ ..."), so both the statement and
    each split part need the list-item "-" stripped, not just
    whitespace/periods."""
    if not SQUARE_RE.search(text):
        return text, None
    first = SQUARE_RE.search(text)
    statement = text[:first.start()].strip(CHOICE_STRIP_CHARS)
    remainder = text[first.start():]
    parts = [p.strip(CHOICE_STRIP_CHARS) for p in SQUARE_RE.split(remainder)]
    parts = [p for p in parts if p]
    choices = [{"label": chr(ord("A") + i), "text": part, "marked_correct_in_source": None}
               for i, part in enumerate(parts)]
    return statement, choices


def _clean_block_text(lines: list) -> str:
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_question_marker(line: str, deepest_open_level: str):
    """Classify a single line (or line remainder) as a question-outline
    marker, if it starts with one. Returns (level, label, rest) or
    (None, None, None).

    Level precedence is fixed: roman_upper > digit > letter >
    roman_lower (e.g. "I." > "1." > "a." > "i."). A bare "i." is
    ambiguous in isolation (9th letter, or roman numeral 1 starting a
    new sub-level) -- resolved by context, not guessed semantically: if
    we're currently nested inside a 'letter' level, "i." starts a new
    'roman_lower' child (matching the "1. -> a. -> i." convention
    actually used in this corpus); otherwise it's just the letter i.
    Other letters that are technically also roman numerals (v, x, l, c,
    d, m) are NOT treated as ambiguous -- a roman-lower sequence always
    starts at "i." (then "ii.", "iii.", ... already unambiguous via
    QUESTION_ROMAN_LOWER_MULTI_RE), so a bare "c." or "l." appearing
    after a/b is always just the next letter, never a new level.
    Deterministic, no semantic/LLM judgment involved."""
    m = QUESTION_ROMAN_UPPER_RE.match(line)
    if m:
        return "roman_upper", m.group(1), m.group(2)
    m = QUESTION_DIGIT_RE.match(line)
    if m:
        return "digit", m.group(1), m.group(2)
    m = QUESTION_ROMAN_LOWER_MULTI_RE.match(line)
    if m:
        return "roman_lower", m.group(1), m.group(2)
    m = QUESTION_LETTER_RE.match(line)
    if m:
        letter = m.group(1)
        if letter in AMBIGUOUS_ROMAN_LOWER_LETTERS and deepest_open_level == "letter":
            return "roman_lower", letter, m.group(2)
        return "letter", letter, m.group(2)
    return None, None, None


def extract_marker_chain(line: str, deepest_open_level: str) -> tuple:
    """Repeatedly peel markers off the FRONT of `line` -- real source
    lines commonly compound multiple levels on one line (e.g.
    "1. a. Déterminer ...", confirmed across many real pages in this
    chapter, not just a hypothetical). Returns (chain, remaining_text)
    where chain is an ordered list of (level, label) tuples."""
    chain = []
    remaining = line
    current_deepest = deepest_open_level
    while remaining:
        level, label, rest = classify_question_marker(remaining, current_deepest)
        if level is None:
            break
        chain.append((level, label))
        current_deepest = level
        remaining = rest.strip()
    return chain, remaining


def parse_questions(text: str) -> tuple:
    """Returns (statement, questions[]) with a genuine recursive
    label/text/sub_questions hierarchy, built with a standard
    outline-stack algorithm over the text's lines:

    - Each line is checked for one or more leading markers (see
      extract_marker_chain -- handles both "1.\\na. ...\\nb. ..." style
      sources and "1. a. ..." compound-on-one-line style sources).
    - A new marker at level L closes (finalizes) any currently-open
      node at level >= L, attaching it as a sub_question of whatever
      remains open (or as a new top-level question if nothing does).
    - Non-marker lines are appended to whatever node is currently
      deepest-open (or to the statement, if nothing has opened yet).
    - A node's own `text` is whatever non-marker content appeared
      directly under it before either a sibling or a deeper child
      marker appeared; if none, `text` is null (never an invented
      empty string) -- e.g. "1." followed immediately by "a./b./c."
      with nothing of its own produces {"label": "1", "text": null,
      "sub_questions": [...]}.

    This never discards content: every line is either a statement line,
    a marker (label), or attached as some node's text -- original_content
    upstream of this function is untouched regardless of how well this
    structural split works out."""
    lines = text.split("\n")

    statement_lines = []
    top_level = []
    stack = []  # list of [level, node_dict] currently open, deepest last

    def close_to(min_level_index: int) -> None:
        while stack and QUESTION_LEVEL_ORDER[stack[-1][0]] >= min_level_index:
            _level, node = stack.pop()
            finalized = {
                "label": node["label"],
                "text": _clean_block_text(node["_text_lines"]) or None,
                "sub_questions": node["sub_questions"],
            }
            if stack:
                stack[-1][1]["sub_questions"].append(finalized)
            else:
                top_level.append(finalized)

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            # blank line: preserve as a paragraph break within whatever
            # is currently accumulating text
            if stack:
                stack[-1][1]["_text_lines"].append("")
            else:
                statement_lines.append("")
            continue

        deepest_open = stack[-1][0] if stack else None
        chain, remaining_text = extract_marker_chain(stripped, deepest_open)

        if not chain:
            if stack:
                stack[-1][1]["_text_lines"].append(raw_line)
            else:
                statement_lines.append(raw_line)
            continue

        for level, label in chain:
            close_to(QUESTION_LEVEL_ORDER[level])
            stack.append([level, {"label": label, "_text_lines": [], "sub_questions": []}])

        if remaining_text:
            stack[-1][1]["_text_lines"].append(remaining_text)

    close_to(0)

    statement = _clean_block_text(statement_lines) or None
    return statement, top_level


def build_exercise_details(working_text: str, bloc_type: str) -> dict:
    before_solution, correction_content = split_correction(working_text)
    statement, choices = parse_qcm_choices(before_solution)

    if choices is not None:
        questions = []
    else:
        statement, questions = parse_questions(before_solution)

    return {
        "statement": statement,
        "questions": questions,
        "correction": {
            "present_in_source": correction_content is not None,
            "content": correction_content,
        },
        "qcm_choices": choices,
    }


# --- multi-page merging + item assembly -----------------------------------

def merge_continuations(all_raw_blocs: list) -> list:
    """Blocs are already in (page, position) order across the whole
    chapter. Merge any continues_on_next_page -> continues_from_previous_page
    chain of the same bloc_type into one logical bloc."""
    merged = []
    pending = None  # dict accumulating an in-progress multi-page bloc

    for raw in all_raw_blocs:
        if pending is not None and raw["continues_from_previous_page"] and raw["bloc_type"] == pending["bloc_type"]:
            pending["pages"].append(raw["page"])
            pending["content"] += "\n\n" + raw["content"]
            pending["trailing_prose"] = raw["trailing_prose"]
            pending["continues_on_next_page"] = raw["continues_on_next_page"]
            if not raw["continues_on_next_page"]:
                merged.append(pending)
                pending = None
            continue

        if pending is not None:
            # previous continuation chain ended without a matching
            # continuation bloc -- finalize what we have rather than
            # silently drop it
            logger.warning(
                "Page %d: expected a continues_from_previous_page bloc of type '%s', "
                "finalizing the chain as-is instead of guessing",
                raw["page"], pending["bloc_type"],
            )
            merged.append(pending)
            pending = None

        item = {
            "pages": [raw["page"]],
            "bloc_type": raw["bloc_type"],
            "numero": raw["numero"],
            "content": raw["content"],
            "section_id": raw["section_id"],
            "subsection_id": raw["subsection_id"],
            "title": raw["title"],
            "trailing_prose": raw["trailing_prose"],
            "continues_on_next_page": raw["continues_on_next_page"],
        }
        if raw["continues_on_next_page"]:
            pending = item
        else:
            merged.append(item)

    if pending is not None:
        logger.warning(
            "Chapter ended with an unresolved continues_on_next_page bloc of type '%s' "
            "(page %d) -- finalizing as-is", pending["bloc_type"], pending["pages"][-1],
        )
        merged.append(pending)

    return merged


def build_item(merged: dict, seq_counters: dict, chapter_id: str, hierarchy: HierarchyState) -> dict:
    bloc_type = merged["bloc_type"]
    item_type = BLOC_TYPE_TO_ITEM_TYPE.get(bloc_type, "remark")
    prefix = ID_PREFIX.get(bloc_type, "itm")
    seq_counters[prefix] = seq_counters.get(prefix, 0) + 1
    item_id = f"{chapter_id}-{prefix}-{seq_counters[prefix]:03d}"

    raw_content = merged["content"]
    working_text = strip_tags_for_parsing(raw_content)

    figures = extract_figures(raw_content)
    for fig in figures:
        fig["pdf_page"] = merged["pages"][0]

    uncertainty = extract_uncertainty(raw_content)

    proof = None
    if bloc_type in ("theoreme", "propriete") and DEMONSTRATION_RE.match(merged["trailing_prose"].strip()):
        proof = merged["trailing_prose"].strip()

    exercise_details = None
    if bloc_type in ("exercice", "activite", "exemple", "question"):
        exercise_details = build_exercise_details(working_text, bloc_type)

    # Deliberately empty: no automatic concept inference (see
    # HierarchyState's docstring). Populating this requires a curated
    # concept vocabulary, which doesn't exist yet for Chapter 1.
    concepts = []

    reconstructed_sources = [
        str((config.RECONSTRUCTED_DIR / f"page_{p:03d}.md")) for p in merged["pages"]
    ]

    return {
        "id": item_id,
        "type": item_type,
        "document_id": config.DOCUMENT_ID,
        "chapter_id": chapter_id,
        "section_id": merged["section_id"],
        "subsection_id": merged["subsection_id"],
        "title": merged["title"],
        "source": {
            "document_id": config.DOCUMENT_ID,
            "pdf_pages": merged["pages"],
            "reconstructed_sources": reconstructed_sources,
            "bloc_type": bloc_type,
            "bloc_numero": merged["numero"],
            # Both always False here: these describe the RAW bloc's own
            # continuation attributes, and by this point continuation
            # chains are already fully merged/resolved. A multi-page
            # item is instead signaled by len(pdf_pages) > 1.
            "continues_from_previous_page": False,
            "continues_on_next_page": False,
        },
        "original_content": raw_content,
        "proof": proof,
        "concepts": concepts,
        "links": {
            "definitions": [], "theorems": [], "properties": [], "formulas": [],
            "methods": [], "exercises": [], "figures": figures,
        },
        "exercise_details": exercise_details,
        "extracted_from": None,
        "uncertainty": uncertainty,
        "validation_status": "REVIEW_REQUIRED",
        "validation_history": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "1.0",
    }


# --- top-level run ---------------------------------------------------------

def run(reconstructed_dir: Path, pdf_path: Path, start_page: int, end_page: int, output_path: Path) -> dict:
    chapter_id = f"{config.DOCUMENT_ID}-ch{config.CHAPTER_NUMBER:02d}"
    hierarchy = HierarchyState(chapter_id)

    all_raw_blocs = []
    for page in range(start_page, end_page + 1):
        page_path = reconstructed_dir / f"page_{page:03d}.md"
        if not page_path.exists():
            logger.warning("Page %d: reconstructed file not found (%s), skipping", page, page_path)
            continue
        _frontmatter, body = parse_frontmatter(page_path.read_text(encoding="utf-8"))
        all_raw_blocs.extend(tokenize_page(body, page, hierarchy))

    merged_blocs = merge_continuations(all_raw_blocs)

    seq_counters = {}
    items = [build_item(m, seq_counters, chapter_id, hierarchy) for m in merged_blocs]

    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
    finally:
        doc.close()

    document = {
        "id": config.DOCUMENT_ID,
        "title": config.DOCUMENT_TITLE,
        "subject": config.DOCUMENT_SUBJECT,
        "level": config.DOCUMENT_LEVEL,
        "country": config.DOCUMENT_COUNTRY,
        "source_pdf": str(pdf_path),
        "total_pages": total_pages,
    }
    chapter = {
        "id": chapter_id,
        "document_id": config.DOCUMENT_ID,
        "number": config.CHAPTER_NUMBER,
        "title": config.CHAPTER_TITLE,
        "pdf_page_start": start_page,
        "pdf_page_end": end_page,
    }

    output = {
        "document": document,
        "chapter": chapter,
        "sections": list(hierarchy.sections.values()),
        "subsections": list(hierarchy.subsections.values()),
        "concepts": [],  # no curated concept vocabulary exists yet for Chapter 1 -- see HierarchyState docstring
        "items": items,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def validate_output(output: dict, schema_path: Path) -> int:
    """Best-effort self-check against knowledge_item.schema.json. Logs
    violations but never blocks writing the file -- REVIEW_REQUIRED
    content failing schema validation is exactly the kind of thing a
    human reviewer needs visibility into, not a silent crash."""
    try:
        import jsonschema
    except ImportError:
        logger.warning("jsonschema not installed, skipping self-validation (pip install jsonschema)")
        return 0

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    error_count = 0
    for item in output["items"]:
        errors = list(validator.iter_errors(item))
        for e in errors:
            logger.error("Schema violation in %s: %s (at %s)", item["id"], e.message, list(e.path))
            error_count += 1
    return error_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconstructed Markdown -> KnowledgeItem JSON converter (Phase 6)")
    parser.add_argument("--reconstructed-dir", type=Path, default=config.RECONSTRUCTED_DIR)
    parser.add_argument("--pdf", type=Path, default=config.PDF_PATH)
    parser.add_argument("--start", type=int, default=config.START_PAGE)
    parser.add_argument("--end", type=int, default=config.END_PAGE)
    parser.add_argument("--output", type=Path, default=config.KNOWLEDGE_CHAPTER_01_JSON)
    parser.add_argument("--schema", type=Path, default=config.KNOWLEDGE_SCHEMA_JSON)
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        output = run(args.reconstructed_dir, args.pdf, args.start, args.end, args.output)
        error_count = validate_output(output, args.schema)
        logger.info(
            "Done. %d item(s), %d section(s), %d subsection(s), %d concept(s) -> %s",
            len(output["items"]), len(output["sections"]), len(output["subsections"]),
            len(output["concepts"]), args.output,
        )
        if error_count:
            logger.warning("%d item(s) failed schema self-validation -- see errors above", error_count)
    except Exception:
        logger.exception("Conversion failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
