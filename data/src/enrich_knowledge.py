"""
Phase 8 - Knowledge enrichment v1 (chapter-generic, deterministic only).

Reads a chapter's NORMALIZED knowledge JSON (Phase 7 output, see
normalized_knowledge.schema.json) and produces one enrichment record per
item (see knowledge_enrichment.schema.json): topics, keywords,
mathematical_entities, exercise_type, reasoning_types, concepts. Purely
additive: reads the normalized JSON, never modifies it, and writes to a
SEPARATE per-chapter output directory
(data/output/<chapter_id>/enrichment/knowledge_enrichment.json).

100% deterministic/rule-based. NO Claude/LLM call anywhere in this
module -- see knowledge_enrichment.md for the full field-by-field
deterministic/rule_based/llm_required classification and why every
field implemented here landed in the first two categories only.

WHERE EACH RULE COMES FROM (grounded in the real Chapter 1 normalized
output, not assumed -- see knowledge_enrichment.md §0):
  - topics: item's own section/subsection titles (already a clean,
    human-authored topic taxonomy).
  - keywords / concepts / reasoning_types: matched against
    math_glossary_fr.json, an EXPLICIT external controlled vocabulary
    file (never a hardcoded Python literal) -- every entry in it was
    confirmed present in real Chapter 1 content before being added.
  - mathematical_entities: conservative regexes over already-validated
    LaTeX (functions restricted to a small allow-list of conventional
    French textbook function letters -- f/g/h/u/v/w -- specifically to
    avoid misreading algebraic products like "x(1-x)" as a function
    named "x", a false positive confirmed by direct inspection).
  - exercise_type: purely structural, from exercise_details' own
    already-parsed shape (qcm_choices / questions / statement
    presence) -- never re-reads original_content.

Usage:
    python enrich_knowledge.py
    python enrich_knowledge.py --normalized <path> --output <path>
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
from pathlib import Path

import config

logger = logging.getLogger("enrich_knowledge")

# Conventional French-textbook function-name letters. Deliberately an
# ALLOW-list, not a stoplist of variable letters: a stoplist would need
# to anticipate every variable name a future chapter might use (x, y,
# t, n, a, b, k, m, ...), which is an open set, whereas the set of
# letters actually used to NAME a function in this corpus (and
# French secondary-school convention generally) is small and stable.
# Confirmed against real content: "x(" in exo-001 is "x times (1-x)",
# not a function -- excluding it here is not a guess, it's a measured
# false-positive fix.
FUNCTION_NAME_LETTERS = {"f", "g", "h", "u", "v", "w"}
FUNCTION_RE = re.compile(r"(?<!\\)\b([a-zA-Z])\(")

# Bracket-delimited interval notation: "]a,b[", "[a,b]", "[a,b[", etc.
# Deliberately excludes '{', '}', '$' from the inner content so this
# can never swallow an unrelated brace group or cross a math-mode
# delimiter -- conservative by construction, not just by testing.
INTERVAL_RE = re.compile(r"[\[\]][^,\[\]{}$]{1,30},[^,\[\]{}$]{1,30}[\[\]]")

# Short "symbol=value" assignments (e.g. "x=-1", "y=-x-3"), NOT
# arbitrary equations spanning a whole LaTeX expression -- the 20-char
# cap and comma/semicolon/period/whitespace/'$' stop-set keep this from
# ever capturing a multi-clause sentence as one "equation".
EQUATION_RE = re.compile(r"\b([a-zA-Z])\s*=\s*([^,;.\s$]{1,20})")

# A curated subset of LaTeX macros that denote a specific mathematical
# operation/relation -- deliberately excludes purely typographic macros
# (\dfrac, \left, \right, \mapsto, \text, \mathbb, \vec, ...) and bare
# Greek-letter variable names (\alpha, \beta, \pi), which name symbols
# rather than operations. Confirmed present in real Chapter 1 content
# before inclusion (see knowledge_enrichment.md §0); trig macros
# included since they unambiguously signal trigonometric content.
NOTATION_MACROS = [
    "lim", "sqrt", "circ", "infty", "leq", "geq", "neq", "in",
    "Rightarrow", "Leftrightarrow", "subset", "cup", "cap",
    "forall", "exists", "sin", "cos", "tan",
]
# A negative lookahead (not \b) on purpose: LaTeX commonly follows a
# macro directly with '_' or '{' (e.g. "\lim_{x \to 1}"), and '_' is a
# \w character, so \b would never fire there and silently miss every
# such occurrence -- confirmed by a failing test on "\lim_{...}"
# before this fix. The lookahead only rules out this macro name being
# a PREFIX of a longer one (so "in" never matches inside "infty").
NOTATION_RES = {m: re.compile(r"\\" + m + r"(?![a-zA-Z])") for m in NOTATION_MACROS}


def load_glossary(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _all_item_texts(item: dict) -> list[str]:
    """Every text field worth scanning for keywords/reasoning verbs --
    content, proof, and (recursively) exercise_details' own text
    fields. Never original_content (content is its already-cleaned
    counterpart, see normalize_knowledge.py)."""
    texts = [item["content"]]
    if item.get("proof"):
        texts.append(item["proof"])

    details = item.get("exercise_details")
    if details:
        if details.get("statement"):
            texts.append(details["statement"])

        def walk(questions):
            for q in questions or []:
                if q.get("text"):
                    texts.append(q["text"])
                walk(q.get("sub_questions"))

        walk(details.get("questions"))
        for choice in details.get("qcm_choices") or []:
            if choice.get("text"):
                texts.append(choice["text"])
        correction = details.get("correction") or {}
        if correction.get("content"):
            texts.append(correction["content"])

    return texts


def _topics(item: dict, sections_by_id: dict, subsections_by_id: dict) -> list[str]:
    topics = []
    section = sections_by_id.get(item.get("section_id"))
    if section:
        topics.append(section["title"])
    subsection = subsections_by_id.get(item.get("subsection_id"))
    if subsection and subsection["title"] not in topics:
        topics.append(subsection["title"])
    return topics


def _keywords_and_concepts(combined_text: str, glossary: dict) -> tuple[list[str], list[str]]:
    keywords: list[str] = []
    concepts: list[str] = []
    lowered = combined_text.lower()
    for entry in glossary["keywords"]:
        term = entry["term"]
        # 's?' tolerates plain French plurals (asymptote/asymptotes,
        # limite/limites, ...) while keeping the trailing word boundary,
        # so e.g. "continue" still never matches inside an unrelated
        # longer word like "continuellement". Gender-agreement variants
        # (borne/bornee/bornes/bornees) are NOT covered -- a deliberate,
        # documented conservative limitation (see math_glossary_fr.json).
        if re.search(r"\b" + re.escape(term.lower()) + r"s?\b", lowered):
            keywords.append(term)
            concept = entry.get("concept")
            if concept and concept not in concepts:
                concepts.append(concept)
    return keywords, concepts


def _reasoning_types(combined_text: str, glossary: dict, applicable: bool) -> list[str]:
    """`applicable` is whether this item is exercise-shaped at all
    (has exercise_details) -- "reasoning type" is a meaningless
    question for a theorem/property/definition/remark STATEMENT, so
    those get an empty list (not_populated), never "unclassified".
    "unclassified" is reserved for an exercise-shaped item where no
    glossary verb matched -- an honest "we expected one and didn't
    find it", never a guess at which one it might be."""
    if not applicable:
        return []
    lowered = combined_text.lower()
    tags: list[str] = []
    for entry in glossary["reasoning_verbs"]:
        if re.search(r"\b" + re.escape(entry["verb"]) + r"\b", lowered):
            if entry["tag"] not in tags:
                tags.append(entry["tag"])
    return tags or ["unclassified"]


def _mathematical_entities(content: str) -> dict:
    functions = sorted({m for m in FUNCTION_RE.findall(content) if m in FUNCTION_NAME_LETTERS})
    intervals = sorted(set(INTERVAL_RE.findall(content)))
    equations = sorted({f"{sym}={val}" for sym, val in EQUATION_RE.findall(content)})
    notations = sorted(m for m, pattern in NOTATION_RES.items() if pattern.search(content))
    return {
        "functions": functions,
        "intervals": intervals,
        "equations": equations,
        "notations": notations,
    }


def _exercise_type(item: dict) -> str | None:
    """Purely structural -- see module docstring. Returns None when the
    item's own type is never exercise-shaped, or when exercise_details
    exists but carries no structural evidence at all (should not occur
    in practice; a safe, non-guessing fallback for it if it ever does)."""
    details = item.get("exercise_details")
    if not details:
        return None
    if details.get("qcm_choices"):
        return "qcm"
    if details.get("questions"):
        return "structured_multi_question"
    if details.get("statement"):
        return "unstructured_statement"
    return None


def _enrich_item(item: dict, glossary: dict, sections_by_id: dict, subsections_by_id: dict) -> dict:
    combined_text = " ".join(_all_item_texts(item))

    topics = _topics(item, sections_by_id, subsections_by_id)
    keywords, glossary_concepts = _keywords_and_concepts(combined_text, glossary)
    entities = _mathematical_entities(item["content"])
    exercise_type = _exercise_type(item)
    is_exercise_shaped = item.get("exercise_details") is not None
    reasoning_types = _reasoning_types(combined_text, glossary, applicable=is_exercise_shaped)

    # Concepts are a lowercase-normalized controlled vocabulary, kept
    # separate from `topics` (which stay Title Case, verbatim section/
    # subsection titles) and from the raw `keywords` surface forms --
    # deduping case-insensitively here matters concretely: a topic
    # title and a glossary-mapped concept can name the same real-world
    # concept while differing only in case, and must collapse to one
    # entry rather than being kept as two differently-cased strings
    # (see knowledge_enrichment.md's worked example).
    concepts: list[str] = []
    for concept in [t.lower() for t in topics] + glossary_concepts:
        if concept not in concepts:
            concepts.append(concept)

    def method(populated: bool, always: str = "rule_based") -> str:
        return always if populated else "not_populated"

    entities_populated = any(entities.values())

    return {
        "item_id": item["id"],
        "item_type": item["type"],
        "topics": topics,
        "keywords": keywords,
        "mathematical_entities": entities,
        "exercise_type": exercise_type,
        "reasoning_types": reasoning_types,
        "concepts": concepts,
        "generation_methods": {
            "topics": method(bool(topics), "deterministic"),
            "keywords": method(bool(keywords)),
            "mathematical_entities": method(entities_populated, "deterministic"),
            "exercise_type": method(exercise_type is not None),
            "reasoning_types": method(is_exercise_shaped),
            "concepts": method(bool(concepts)),
        },
        "review_status": "NOT_REQUIRED",
    }


def enrich(normalized: dict, glossary: dict) -> dict:
    """Pure, deterministic transform: normalized knowledge (already
    parsed) -> enrichment file (already a plain dict, not yet written
    to disk). No chapter_id/page/item-id branching -- every identifier
    comes from the input."""
    sections_by_id = {s["id"]: s for s in normalized.get("sections", [])}
    subsections_by_id = {s["id"]: s for s in normalized.get("subsections", [])}

    items = [
        _enrich_item(item, glossary, sections_by_id, subsections_by_id)
        for item in normalized["items"]
    ]

    return {
        "schema_version": "enrichment-1.0",
        "algorithm_version": config.ENRICHMENT_ALGORITHM_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chapter_id": normalized["chapter"]["id"],
        "items": items,
    }


def load_normalized(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(normalized_path: Path, glossary_path: Path, output_path: Path | None = None) -> dict:
    normalized = load_normalized(normalized_path)
    glossary = load_glossary(glossary_path)
    result = enrich(normalized, glossary)

    out_path = output_path or config.enrichment_json(result["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return result


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge enrichment v1 (Phase 8)")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--glossary", type=Path, default=config.MATH_GLOSSARY_FR_JSON)
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/enrichment/knowledge_enrichment.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.normalized, args.glossary, args.output)
        logger.info("Chapter %s: %d items enriched.", result["chapter_id"], len(result["items"]))
    except Exception:
        logger.exception("enrich_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
