"""
Phase 14 - RAG Context Assembly (deterministic, rule-based).

Strictly per the approved data/schema/rag_context_design.md. Transforms
the ranked results search_embeddings.search() already returns into a
bounded, ordered, provenance-carrying context for a future LLM.

    User query -> search_embeddings.search() -> candidates
        -> seed selection (diversity)
        -> deterministic expansion (correction pairing, concept support)
        -> deduplication
        -> cluster creation
        -> ordering
        -> context budget
        -> RagContext

This module calls the existing, unmodified search() function -- it NEVER
queries PostgreSQL directly, never regenerates embeddings, never
duplicates chunk text into a new store. Chunk fields not already returned
by search() (related_chunk_ids, figure_refs, review_status, order) are
read from the exact same data/output/<chapter_id>/chunks/knowledge_chunks.json
file search() already resolves `text` from -- a second, independent read
of an already-open, read-only file, not a new artifact or schema change.

Human Review confirmation for figures is read from the existing
knowledge_relations.json 'illustrates' edges (generation_method ==
"human_confirmed", confidence == "high" -- the exact encoding
relate_knowledge.py already produces for a real CONFIRMED decision, see
that module's _HUMAN_CONFIRMED_STATUSES). No new review mechanism, no
live connection to the Java backend's MySQL database.

Usage:
    python rag_context.py --chapter-id <chapter_id> --query "..."
    python rag_context.py --chapter-id <chapter_id> --query "..." --top-k 20 --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config
from embed_knowledge import SentenceTransformerBackend, file_hash
from search_embeddings import (
    EmbeddingBackend, SearchIncompatibleModelError, SearchValidationError, search,
)

logger = logging.getLogger("rag_context")

CONCEPT_ITEM_TYPES = {"theorem", "property", "definition"}
NON_CONCEPT_ITEM_TYPES = {"activity", "exercise"}


# --------------------------------------------------------------------------
# Auxiliary data loading (all read-only; nothing here is new -- the same
# files earlier phases already produce and validate)
# --------------------------------------------------------------------------

def load_chunks_lookup(chunks_path: Path) -> dict[str, dict]:
    doc = json.loads(Path(chunks_path).read_text(encoding="utf-8"))
    return {c["chunk_id"]: c for c in doc["chunks"]}


def load_confirmed_figure_lookup(relations_path: Path | None) -> dict[str, str]:
    """Maps a knowledge_item id -> its figure_id, ONLY for an 'illustrates'
    relation with generation_method == 'human_confirmed' AND confidence ==
    'high' -- exactly relate_knowledge.py's own encoding of a real
    ReviewStatus.CONFIRMED decision (see _HUMAN_CONFIRMED_STATUSES there).
    An algorithmic AUTO_MATCH-sourced 'high' confidence illustrates
    relation has generation_method 'rule_based', not 'human_confirmed',
    and is deliberately excluded here -- the design requires Human Review
    confirmation, not just algorithmic confidence."""
    if relations_path is None or not Path(relations_path).exists():
        return {}
    doc = json.loads(Path(relations_path).read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for rel in doc.get("relations", []):
        if rel.get("type") != "illustrates":
            continue
        if rel.get("generation_method") != "human_confirmed":
            continue
        if rel.get("confidence") != "high":
            continue
        result[rel["target_id"]] = rel["source_id"]
    return result


# --------------------------------------------------------------------------
# Step: seed selection (diversity applied to candidates -> seeds)
# --------------------------------------------------------------------------

def select_seeds(candidates: list[dict], chunks_lookup: dict[str, dict],
                  max_chunks_per_section: int, max_chunks_per_subsection: int) -> tuple[list[dict], list[dict]]:
    """Single greedy pass over `candidates` (already in Semantic Search's
    own deterministic order -- never re-sorted here). A candidate is
    rejected only if admitting it would violate a cap; an already-accepted
    higher-scoring chunk is never evicted. Returns (seeds, rejected), each
    rejected entry carrying 'rejection_reason'."""
    seeds: list[dict] = []
    rejected: list[dict] = []
    per_section: dict[str, int] = {}
    per_subsection: dict[str, int] = {}

    for cand in candidates:
        chunk = chunks_lookup.get(cand["chunk_id"])
        if chunk is None:
            # search() already excludes true orphans; defensive only.
            rejected.append({**cand, "rejection_reason": "missing_chunk_artifact"})
            continue
        if chunk.get("review_status") == "HUMAN_REJECTED":
            rejected.append({**cand, "rejection_reason": "human_rejected"})
            continue

        section_id = cand.get("section_id")
        subsection_id = cand.get("subsection_id")

        if section_id is not None and per_section.get(section_id, 0) >= max_chunks_per_section:
            rejected.append({**cand, "rejection_reason": "section_cap"})
            continue
        # A null subsection is not a meaningful grouping key -- it does
        # NOT share a global bucket with every other null-subsection chunk;
        # it is simply never capped by subsection at all.
        if subsection_id is not None and per_subsection.get(subsection_id, 0) >= max_chunks_per_subsection:
            rejected.append({**cand, "rejection_reason": "subsection_cap"})
            continue

        seeds.append(cand)
        if section_id is not None:
            per_section[section_id] = per_section.get(section_id, 0) + 1
        if subsection_id is not None:
            per_subsection[subsection_id] = per_subsection.get(subsection_id, 0) + 1

    return seeds, rejected


# --------------------------------------------------------------------------
# Step: deterministic expansion (E1 correction-pairing, E2 concept-support)
# --------------------------------------------------------------------------

def _find_correction_statement(chunk: dict, chunks_lookup: dict) -> dict | None:
    for rel_id in chunk.get("related_chunk_ids", []):
        related = chunks_lookup.get(rel_id)
        if related is not None and related.get("content_role") == "statement":
            return related
    return None


def _find_concept_expansion(chunk: dict, chunks_lookup: dict) -> dict | None:
    """At most one qualifying theorem/property/definition related chunk --
    the one with the smallest `order` when several qualify (deterministic;
    never depends on related_chunk_ids' own, unspecified list order)."""
    qualifying = []
    for rel_id in chunk.get("related_chunk_ids", []):
        related = chunks_lookup.get(rel_id)
        if related is not None and set(related.get("item_types", [])) & CONCEPT_ITEM_TYPES:
            qualifying.append(related)
    if not qualifying:
        return None
    return min(qualifying, key=lambda c: c["order"])


def expand_seeds(seeds: list[dict], chunks_lookup: dict[str, dict],
                  max_expansion_per_seed: int) -> list[dict]:
    """Returns a list of {"seed_chunk_id", "chunk", "reason"} -- at most
    one per seed (E1 and E2 never both fire for the same seed; E1 is
    checked first). Never expands recursively (an expansion's own
    related_chunk_ids are never followed). Never expands
    theorem/property/definition -> exercise (E2 is one-directional, only
    triggered by an activity/exercise seed)."""
    included_ids = {s["chunk_id"] for s in seeds}
    expansions: list[dict] = []

    for seed in seeds:
        if max_expansion_per_seed < 1:
            break
        chunk = chunks_lookup.get(seed["chunk_id"])
        if chunk is None:
            continue

        target = None
        reason = None
        if chunk.get("content_role") == "correction":
            target = _find_correction_statement(chunk, chunks_lookup)
            if target is not None:
                reason = "expansion:correction_pair"

        if target is None and set(chunk.get("item_types", [])) & NON_CONCEPT_ITEM_TYPES:
            target = _find_concept_expansion(chunk, chunks_lookup)
            if target is not None:
                reason = "expansion:applies_concept"

        if target is None or target["chunk_id"] in included_ids:
            continue
        if target.get("review_status") == "HUMAN_REJECTED":
            continue

        included_ids.add(target["chunk_id"])
        expansions.append({"seed_chunk_id": seed["chunk_id"], "chunk": target, "reason": reason})

    return expansions


# --------------------------------------------------------------------------
# Step: cluster creation + within-cluster ordering
# --------------------------------------------------------------------------

def build_clusters(seeds: list[dict], expansions: list[dict], chunks_lookup: dict[str, dict]) -> list[list[dict]]:
    """One cluster per seed, in the SAME order `seeds` is already in (that
    order is search()'s own deterministic score-desc + embedding_id-asc
    order -- never re-sorted here, which is exactly 'seed semantic score
    descending, deterministic tie-break inherited from Semantic Search').
    Within a cluster, members are ordered by their own `order` field
    ascending."""
    expansions_by_seed: dict[str, list[dict]] = {}
    for exp in expansions:
        expansions_by_seed.setdefault(exp["seed_chunk_id"], []).append(exp)

    clusters = []
    for seed in seeds:
        members = [{
            "chunk_id": seed["chunk_id"], "score": seed["score"],
            "inclusion_reason": "semantic_match", "expanded_from_chunk_id": None,
        }]
        for exp in expansions_by_seed.get(seed["chunk_id"], []):
            members.append({
                "chunk_id": exp["chunk"]["chunk_id"], "score": None,
                "inclusion_reason": exp["reason"], "expanded_from_chunk_id": seed["chunk_id"],
            })
        members.sort(key=lambda m: chunks_lookup[m["chunk_id"]]["order"])
        clusters.append(members)
    return clusters


# --------------------------------------------------------------------------
# Step: context budget
# --------------------------------------------------------------------------

def apply_budget(clusters: list[list[dict]], chunks_lookup: dict[str, dict],
                  max_chunks: int, max_chars: int) -> tuple[list[list[dict]], int, int, str | None]:
    """Whole-clusters-only, walked in the already-correct cluster order.
    The first cluster that would exceed either limit stops the walk --
    later, possibly-smaller clusters are never back-filled. The single
    highest-scoring (first) cluster always survives in full, even if it
    alone exceeds the budget."""
    included: list[list[dict]] = []
    total_chunks = 0
    total_chars = 0
    overflow_note = None

    for i, cluster in enumerate(clusters):
        cluster_chars = sum(len(chunks_lookup[m["chunk_id"]]["text"]) for m in cluster)
        cluster_count = len(cluster)
        fits = (total_chunks + cluster_count <= max_chunks) and (total_chars + cluster_chars <= max_chars)

        if i == 0:
            included.append(cluster)
            total_chunks += cluster_count
            total_chars += cluster_chars
            if not fits:
                overflow_note = (
                    f"top-scoring cluster alone totals {cluster_chars} char(s)/{cluster_count} chunk(s), "
                    f"exceeding the configured budget ({max_chars} chars/{max_chunks} chunks) -- included "
                    f"in full anyway per the design's top-cluster-always-survives exception"
                )
            continue

        if not fits:
            break
        included.append(cluster)
        total_chunks += cluster_count
        total_chars += cluster_chars

    return included, total_chunks, total_chars, overflow_note


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def _build_provenance(member: dict, chunks_lookup: dict[str, dict], confirmed_figure_by_item: dict[str, str],
                       embedding_model: str, model_revision: str) -> dict:
    chunk = chunks_lookup[member["chunk_id"]]
    figure_refs = chunk.get("figure_refs", [])
    has_potential_figure = bool(figure_refs)
    reconstructed_figure_id = figure_refs[0]["reconstructed_figure_id"] if figure_refs else None

    resolved_figure_id = None
    for source_item_id in chunk.get("source_item_ids", []):
        if source_item_id in confirmed_figure_by_item:
            resolved_figure_id = confirmed_figure_by_item[source_item_id]
            break

    return {
        "chunk_id": chunk["chunk_id"],
        "chapter_id": chunk["chapter_id"],
        "score": member["score"],
        "inclusion_reason": member["inclusion_reason"],
        "expanded_from_chunk_id": member["expanded_from_chunk_id"],
        "section_id": chunk.get("section_id"),
        "subsection_id": chunk.get("subsection_id"),
        "content_role": chunk.get("content_role"),
        "item_types": chunk.get("item_types", []),
        "pdf_pages": chunk.get("pdf_pages", []),
        "topics": chunk.get("topics", []),
        "concepts": chunk.get("concepts", []),
        "has_uncertain_content": chunk.get("has_uncertain_content", False),
        "review_status": chunk.get("review_status"),
        "has_potential_figure": has_potential_figure,
        "reconstructed_figure_id": reconstructed_figure_id,
        "figure_id": resolved_figure_id,
        "embedding_model": embedding_model,
        "model_revision": model_revision,
        "text": chunk["text"],
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def assemble_context(
    query: str,
    chapter_id: str,
    candidate_top_k: int = config.RAG_CANDIDATE_TOP_K,
    filters: dict | None = None,
    embedding_model: str = config.EMBEDDING_MODEL_NAME,
    model_revision: str = config.EMBEDDING_MODEL_REVISION,
    database_url: str | None = None,
    chunks_path: Path | None = None,
    relations_path: Path | None = None,
    backend: EmbeddingBackend | None = None,
    table: str | None = None,
    max_context_chunks: int = config.RAG_MAX_CONTEXT_CHUNKS,
    max_context_chars: int = config.RAG_MAX_CONTEXT_CHARS,
    max_expansion_per_seed: int = config.RAG_MAX_EXPANSION_PER_SEED,
    max_chunks_per_subsection: int = config.RAG_MAX_CHUNKS_PER_SUBSECTION,
    max_chunks_per_section: int = config.RAG_MAX_CHUNKS_PER_SECTION,
) -> dict:
    """The full pipeline, exactly per rag_context_design.md:

    candidate_top_k -> seed diversity -> expansion -> deduplication ->
    cluster creation -> ordering -> final context budget.

    max_context_chunks/max_context_chars are a FINAL CONTEXT budget --
    never a seed-selection limit; the seed set is never truncated to this
    size before expansion.

    Raises SearchIncompatibleModelError / SearchValidationError unchanged
    -- this function never swallows or reinterprets them. An empty
    Semantic Search result (no matching chapter, over-narrow filters) is
    NOT an error -- it produces a valid, empty RagContext.
    """
    chunks_path = chunks_path or config.chunks_json(chapter_id)
    relations_path = relations_path or config.relations_json(chapter_id)

    candidates = search(
        query=query, chapter_id=chapter_id, top_k=candidate_top_k, filters=filters,
        embedding_model=embedding_model, model_revision=model_revision,
        database_url=database_url, chunks_path=chunks_path,
        backend=backend, table=table,
    )

    source_hash = file_hash(chunks_path) if Path(chunks_path).exists() else None

    result: dict = {
        "chapter_id": chapter_id,
        "query": query,
        "embedding_model": embedding_model,
        "model_revision": model_revision,
        "candidate_count": len(candidates),
        "seed_count": 0,
        "rejected_seeds": [],
        "expansions": [],
        "context": [],
        "context_chunk_count": 0,
        "context_char_count": 0,
        "clusters_total": 0,
        "clusters_included": 0,
        "budget_overflow_note": None,
        "source_chunks_hash": source_hash,
        "diagnostics": [],
    }

    if not candidates:
        result["diagnostics"].append(
            f"Semantic Search returned zero candidates for chapter_id={chapter_id!r} "
            f"(no matching chapter/model/revision, or filters excluded everything)."
        )
        return result

    chunks_lookup = load_chunks_lookup(chunks_path)
    confirmed_figure_by_item = load_confirmed_figure_lookup(relations_path)

    seeds, rejected_seeds = select_seeds(candidates, chunks_lookup, max_chunks_per_section, max_chunks_per_subsection)
    result["seed_count"] = len(seeds)
    result["rejected_seeds"] = [
        {"chunk_id": r["chunk_id"], "score": r.get("score"), "rejection_reason": r["rejection_reason"]}
        for r in rejected_seeds
    ]

    expansions = expand_seeds(seeds, chunks_lookup, max_expansion_per_seed)
    result["expansions"] = [
        {"chunk_id": e["chunk"]["chunk_id"], "expanded_from_chunk_id": e["seed_chunk_id"], "reason": e["reason"]}
        for e in expansions
    ]

    clusters = build_clusters(seeds, expansions, chunks_lookup)
    result["clusters_total"] = len(clusters)

    included_clusters, total_chunks, total_chars, overflow_note = apply_budget(
        clusters, chunks_lookup, max_context_chunks, max_context_chars,
    )
    result["clusters_included"] = len(included_clusters)
    result["budget_overflow_note"] = overflow_note

    context = [
        _build_provenance(member, chunks_lookup, confirmed_figure_by_item, embedding_model, model_revision)
        for cluster in included_clusters for member in cluster
    ]
    result["context"] = context
    result["context_chunk_count"] = total_chunks
    result["context_char_count"] = total_chars

    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Context Assembly over Semantic Search (Phase 14)")
    parser.add_argument("--chapter-id", type=str, default=config.CHAPTER_01_ID)
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--top-k", type=int, default=config.RAG_CANDIDATE_TOP_K,
                         help="candidate_top_k passed to Semantic Search (NOT the final context size)")
    parser.add_argument("--model", type=str, default=config.EMBEDDING_MODEL_NAME)
    parser.add_argument("--revision", type=str, default=config.EMBEDDING_MODEL_REVISION)
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--relations", type=Path, default=None)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--filter-section-id", type=str, default=None)
    parser.add_argument("--filter-subsection-id", type=str, default=None)
    parser.add_argument("--filter-content-role", type=str, default=None, choices=["statement", "correction"])
    parser.add_argument("--filter-concepts", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-topics", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-item-types", type=str, default=None, help="comma-separated")
    parser.add_argument("--filter-pdf-pages", type=str, default=None, help="comma-separated integers")
    parser.add_argument("--filter-has-uncertain-content", type=str, default=None, choices=["true", "false"])
    parser.add_argument("--json", action="store_true", help="print the full context as raw JSON")
    return parser.parse_args()


def _filters_from_args(args: argparse.Namespace) -> dict | None:
    filters: dict = {}
    if args.filter_section_id:
        filters["section_id"] = args.filter_section_id
    if args.filter_subsection_id:
        filters["subsection_id"] = args.filter_subsection_id
    if args.filter_content_role:
        filters["content_role"] = args.filter_content_role
    if args.filter_concepts:
        filters["concepts"] = [s.strip() for s in args.filter_concepts.split(",") if s.strip()]
    if args.filter_topics:
        filters["topics"] = [s.strip() for s in args.filter_topics.split(",") if s.strip()]
    if args.filter_item_types:
        filters["item_types"] = [s.strip() for s in args.filter_item_types.split(",") if s.strip()]
    if args.filter_pdf_pages:
        filters["pdf_pages"] = [int(s.strip()) for s in args.filter_pdf_pages.split(",") if s.strip()]
    if args.filter_has_uncertain_content is not None:
        filters["has_uncertain_content"] = args.filter_has_uncertain_content == "true"
    return filters or None


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        backend = SentenceTransformerBackend(model_name=args.model, model_revision=args.revision, device=args.device)
        result = assemble_context(
            query=args.query, chapter_id=args.chapter_id, candidate_top_k=args.top_k,
            filters=_filters_from_args(args), embedding_model=args.model, model_revision=args.revision,
            database_url=args.database_url or config.database_url(),
            chunks_path=args.chunks or config.chunks_json(args.chapter_id),
            relations_path=args.relations or config.relations_json(args.chapter_id),
            backend=backend,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        logger.info("Query: %r (chapter=%s)", result["query"], result["chapter_id"])
        logger.info("Candidates: %d | Seeds: %d | Rejected seeds: %d | Expansions: %d",
                     result["candidate_count"], result["seed_count"], len(result["rejected_seeds"]),
                     len(result["expansions"]))
        for r in result["rejected_seeds"]:
            logger.info("  rejected seed %s (score=%s): %s", r["chunk_id"], r["score"], r["rejection_reason"])
        for e in result["expansions"]:
            logger.info("  expansion %s <- %s (%s)", e["chunk_id"], e["expanded_from_chunk_id"], e["reason"])
        logger.info("Clusters: %d total, %d included in final budget%s",
                     result["clusters_total"], result["clusters_included"],
                     f" ({result['budget_overflow_note']})" if result["budget_overflow_note"] else "")
        logger.info("Final context: %d chunk(s), %d character(s), source_chunks_hash=%s",
                     result["context_chunk_count"], result["context_char_count"], result["source_chunks_hash"])
        for c in result["context"]:
            snippet = c["text"][:100].replace("\n", " ")
            logger.info("  [%s] score=%s reason=%s section=%s figure=%s :: %s",
                         c["chunk_id"], c["score"], c["inclusion_reason"], c["section_id"],
                         c["reconstructed_figure_id"], snippet)
        for d in result["diagnostics"]:
            logger.info("  diagnostic: %s", d)
    except (SearchValidationError, SearchIncompatibleModelError) as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception:
        logger.exception("rag_context failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
