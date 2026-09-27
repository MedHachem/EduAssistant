"""
Phase 9 - Knowledge relations v1 (chapter-generic, deterministic only).

Reads a chapter's NORMALIZED knowledge JSON (Phase 7) and ENRICHMENT
file (Phase 8), plus optionally the figure<->knowledge ASSOCIATION file
(Phase 5b) and an exported Human Review decisions file, and produces
typed, directed relations between items (and, for `illustrates`,
between a figure and an item) -- see knowledge_relations.schema.json.
Purely additive: reads all of the above, modifies none of them, and
writes to a SEPARATE per-chapter output directory
(data/output/<chapter_id>/relations/knowledge_relations.json).

100% deterministic/rule-based. NO Claude/LLM call anywhere in this
module -- see knowledge_relations.md for the full classification and
why `shares_concept`/`prerequisite_of` were considered and excluded.

TWO RELATION TYPES (see knowledge_relations.md §1 for why these two
and not more):
  - applies_concept: an activity/exercise/example -> the nearest
    theorem/property/definition (by normalized `order`, either
    direction) sharing at least one enrichment `concept`. Confidence
    decays with reading-order distance (thresholds in config.py,
    derived from the real "branches infinies" cluster -- see the
    design doc's worked example).
  - illustrates: a figure -> a knowledge item, sourced from an actual
    human review decision when one exists (an exported list of
    {figureId, knowledgeItemId, status, ...} records -- see
    backend/.../FigureKnowledgeReview; this module has NO database/HTTP
    dependency, it only reads a plain JSON export), falling back to the
    association pipeline's own AUTO_MATCH decision when no human review
    exists yet for that figure. A human REJECTED decision is final --
    it is never overridden by falling back to AUTO_MATCH.

Usage:
    python relate_knowledge.py
    python relate_knowledge.py --normalized <path> --enrichment <path> \
        --associations <path> --reviews <path> --output <path>
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path

import config

logger = logging.getLogger("relate_knowledge")

# An "application" item practices/uses a concept; a "reference" item
# states it. Only these two buckets participate in applies_concept --
# a reference item is never linked to another reference item (e.g. two
# theorems sharing a concept are not "applying" one another).
APPLICATION_TYPES = {"activity", "exercise", "example"}
REFERENCE_TYPES = {"theorem", "property", "definition"}

# A human CONFIRMED decision is a full confirmation. REASSIGNED means
# the admin picked a different candidate than the algorithm's own
# suggestion but has NOT (yet) clicked Validate to confirm it (see
# backend ReviewStatus.REASSIGNED's own docstring) -- still real human
# signal, better than a bare algorithm guess, but deliberately not
# given the same trust level as an explicit CONFIRMED.
_HUMAN_CONFIRMED_STATUSES = {"CONFIRMED": ("high", "HUMAN_APPROVED"), "REASSIGNED": ("medium", "REVIEW_REQUIRED")}


def _relation_id(chapter_id: str, relation_type: str, source_id: str, target_id: str) -> str:
    return f"rel-{chapter_id}-{relation_type}-{source_id}-{target_id}"


def _build_relation(chapter_id, relation_type, source_id, source_kind, target_id, target_kind,
                     confidence, generation_method, review_status, signals) -> dict:
    return {
        "relation_id": _relation_id(chapter_id, relation_type, source_id, target_id),
        "type": relation_type,
        "source_id": source_id,
        "source_kind": source_kind,
        "target_id": target_id,
        "target_kind": target_kind,
        "confidence": confidence,
        "generation_method": generation_method,
        "review_status": review_status,
        "signals": signals,
    }


def _confidence_from_distance(distance: int) -> str:
    if distance <= config.RELATIONS_HIGH_CONFIDENCE_MAX_DISTANCE:
        return "high"
    if distance <= config.RELATIONS_MEDIUM_CONFIDENCE_MAX_DISTANCE:
        return "medium"
    return "low"


def _applies_concept_relations(chapter_id: str, normalized: dict, enrichment: dict) -> list[dict]:
    order_by_id = {item["id"]: item["order"] for item in normalized["items"]}
    type_by_id = {item["id"]: item["type"] for item in normalized["items"]}
    concepts_by_id = {record["item_id"]: record["concepts"] for record in enrichment["items"]}

    # Iterate the ALREADY-ordered items lists (not dict values) so
    # ties are broken deterministically by that fixed order, never by
    # incidental dict/hash iteration order.
    reference_items = [
        item["id"] for item in normalized["items"] if type_by_id[item["id"]] in REFERENCE_TYPES
    ]

    relations = []
    for item in normalized["items"]:
        item_id = item["id"]
        if type_by_id[item_id] not in APPLICATION_TYPES:
            continue
        concepts = concepts_by_id.get(item_id, [])
        if not concepts:
            continue

        my_order = order_by_id[item_id]
        best_distance = None
        best_target = None
        best_shared: list[str] = []
        for ref_id in reference_items:
            if ref_id == item_id:
                continue
            shared = [c for c in concepts if c in concepts_by_id.get(ref_id, [])]
            if not shared:
                continue
            distance = abs(order_by_id[ref_id] - my_order)
            # Strict '<' only: on an exact tie, the FIRST reference item
            # encountered (in fixed items[] order, i.e. the earlier one
            # in the chapter) keeps priority -- deterministic and never
            # depends on dict/hash ordering.
            if best_distance is None or distance < best_distance:
                best_distance, best_target, best_shared = distance, ref_id, shared

        if best_target is None:
            continue

        confidence = _confidence_from_distance(best_distance)
        review_status = "NOT_REQUIRED" if confidence == "high" else "REVIEW_REQUIRED"
        relations.append(_build_relation(
            chapter_id, "applies_concept", item_id, "knowledge_item", best_target, "knowledge_item",
            confidence, "rule_based", review_status,
            {"shared_concepts": best_shared, "reading_order_distance": best_distance, "source_review_status": None},
        ))

    return relations


def _illustrates_relations(chapter_id: str, associations: dict | None, reviews: list[dict] | None) -> list[dict]:
    if not associations:
        return []

    reviews_by_figure = {r["figureId"]: r for r in (reviews or [])}
    relations = []

    for assoc in associations["associations"]:
        figure_id = assoc["figure_id"]
        review = reviews_by_figure.get(figure_id)

        if review is not None:
            # A human decision exists for this figure -- it is final.
            # REJECTED (or any other status) means no relation, and we
            # NEVER fall through to the algorithm's own AUTO_MATCH
            # guess once a human has actually looked at this figure.
            tier = _HUMAN_CONFIRMED_STATUSES.get(review["status"])
            if tier and review.get("knowledgeItemId"):
                confidence, review_status = tier
                relations.append(_build_relation(
                    chapter_id, "illustrates", figure_id, "figure",
                    review["knowledgeItemId"], "knowledge_item",
                    confidence, "human_confirmed", review_status,
                    {"shared_concepts": [], "reading_order_distance": None, "source_review_status": review["status"]},
                ))
            continue

        if assoc["decision"] == "AUTO_MATCH" and assoc.get("chosen_item_id"):
            relations.append(_build_relation(
                chapter_id, "illustrates", figure_id, "figure",
                assoc["chosen_item_id"], "knowledge_item",
                "high", "rule_based", "REVIEW_REQUIRED",
                {"shared_concepts": [], "reading_order_distance": None, "source_review_status": None},
            ))

    return relations


def relate(normalized: dict, enrichment: dict, associations: dict | None = None,
           reviews: list[dict] | None = None) -> dict:
    """Pure, deterministic transform: normalized + enrichment (+
    optional associations/reviews), already parsed -> relations file
    (already a plain dict, not yet written to disk). No chapter_id/
    page/item-id branching -- every identifier comes from the input."""
    chapter_id = normalized["chapter"]["id"]

    relations = _applies_concept_relations(chapter_id, normalized, enrichment)
    relations += _illustrates_relations(chapter_id, associations, reviews)

    return {
        "schema_version": "relations-1.0",
        "algorithm_version": config.RELATIONS_ALGORITHM_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chapter_id": chapter_id,
        "relations": relations,
    }


def _load(path: Path | None) -> dict | list | None:
    if path is None or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(normalized_path: Path, enrichment_path: Path, associations_path: Path | None,
        reviews_path: Path | None, output_path: Path | None = None) -> dict:
    normalized = json.loads(Path(normalized_path).read_text(encoding="utf-8"))
    enrichment = json.loads(Path(enrichment_path).read_text(encoding="utf-8"))
    associations = _load(associations_path)
    reviews = _load(reviews_path)

    result = relate(normalized, enrichment, associations, reviews)

    out_path = output_path or config.relations_json(result["chapter_id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)
    return result


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                         handlers=[logging.StreamHandler(sys.stdout)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge relations v1 (Phase 9)")
    parser.add_argument("--normalized", type=Path, default=config.NORMALIZED_CHAPTER_01_JSON)
    parser.add_argument("--enrichment", type=Path, default=config.enrichment_json(config.CHAPTER_01_ID))
    parser.add_argument("--associations", type=Path, default=config.associations_json(config.CHAPTER_01_ID),
                         help="Figure<->knowledge association file (optional; omit to skip 'illustrates')")
    parser.add_argument("--reviews", type=Path, default=None,
                         help="Optional exported Human Review decisions JSON "
                              "(list of {figureId, knowledgeItemId, status, ...}, "
                              "see GET /api/chapters/{chapterId}/reviews)")
    parser.add_argument("--output", type=Path, default=None,
                         help="Defaults to data/output/<chapter_id>/relations/knowledge_relations.json")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    try:
        result = run(args.normalized, args.enrichment, args.associations, args.reviews, args.output)
        counts = {}
        for r in result["relations"]:
            counts[r["type"]] = counts.get(r["type"], 0) + 1
        logger.info("Chapter %s: %d relations (%s).", result["chapter_id"], len(result["relations"]), counts)
    except Exception:
        logger.exception("relate_knowledge failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
