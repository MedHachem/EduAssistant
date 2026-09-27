"""
Unit + regression tests for associate_figures_knowledge.py (Phase 5b).
Deterministic, no LLM.

Two test classes:
  - TestAssociationLogic: synthetic knowledge/figure fixtures, one per
    required case from the task brief (same-page candidate generation,
    multi-item same-page, vertical/ordinal proximity, reading-order
    fallback, same-section preference, neighboring-page fallback,
    no-match, ambiguous -> REVIEW_REQUIRED, confident -> AUTO_MATCH,
    determinism, stable IDs, malformed/missing geometry, multi-page
    items, figure with no matching item). All synthetic data uses
    made-up chapter/page/item ids specifically to prove nothing here
    is Chapter-1-specific.
  - TestChapter1Regression: runs the real module against the real
    Chapter 1 knowledge JSON + final_figures manifest, if present on
    disk. Chapter 1's own page/figure numbers appear ONLY in this test
    class's ground truth, never in associate_figures_knowledge.py
    itself (grepped for below).

Run:
    python test_associate_figures_knowledge.py
    python -m unittest test_associate_figures_knowledge
"""

import json
import re
import unittest
from pathlib import Path

import config
from associate_figures_knowledge import build_associations, decide, generate_candidates


def make_item(item_id, item_type, pages, section_id, subsection_id=None):
    return {
        "id": item_id,
        "type": item_type,
        "section_id": section_id,
        "subsection_id": subsection_id,
        "source": {"pdf_pages": pages},
    }


def make_section(section_id, start, end):
    return {"id": section_id, "pdf_page_start": start, "pdf_page_end": end}


def make_figure(figure_id, page, bbox, image=None):
    return {
        "figure_id": figure_id,
        "source_page": page,
        "final_bbox": bbox,
        "image": image or f"{figure_id}.png",
    }


def make_knowledge(chapter_id, sections, subsections, items):
    return {
        "chapter": {"id": chapter_id},
        "sections": sections,
        "subsections": subsections,
        "items": items,
    }


class TestAssociationLogic(unittest.TestCase):
    def test_same_page_candidate_generation(self):
        """1. Only items whose source.pdf_pages include the figure's
        page are considered (no neighbor fallback needed)."""
        items = [
            make_item("it-1", "theorem", [5], "sec-a"),
            make_item("it-2", "activity", [6], "sec-a"),
        ]
        by_page = {5: [0], 6: [1]}
        candidates, used_neighbor = generate_candidates(5, by_page)
        self.assertEqual(candidates, [0])
        self.assertFalse(used_neighbor)

    def test_multi_item_same_page_all_considered(self):
        """2. A page with several items produces a candidate for each."""
        items = [make_item(f"it-{i}", "activity", [7], "sec-a") for i in range(4)]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        self.assertEqual(len(result["associations"][0]["candidates"]), 4)

    def test_reading_order_ordinal_proximity_scores_closer_item_higher(self):
        """3. Among same-page/same-section candidates, the one whose
        ordinal (reading-order) position is closer to the figure's own
        ordinal position on that page scores higher."""
        items = [
            make_item("it-first", "activity", [7], "sec-a"),
            make_item("it-mid", "activity", [7], "sec-a"),
            make_item("it-last", "activity", [7], "sec-a"),
        ]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        # figure sits alone on the page -> its own ordinal frac is 0.5,
        # so the MIDDLE item (also ordinal frac 0.5) should score highest.
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        candidates = result["associations"][0]["candidates"]
        best = max(candidates, key=lambda c: c["score"])
        self.assertEqual(best["item_id"], "it-mid")

    def test_reading_order_fallback_with_multiple_figures_on_page(self):
        """4. Multiple figures on one page each get their OWN ordinal
        position (by real bbox y0), so an earlier figure prefers an
        earlier item and a later figure prefers a later item."""
        items = [
            make_item("it-a", "activity", [7], "sec-a"),
            make_item("it-b", "activity", [7], "sec-a"),
        ]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [
            make_figure("fig-top", 7, [0, 0, 10, 10]),
            make_figure("fig-bottom", 7, [0, 500, 10, 600]),
        ]}
        result = build_associations(knowledge, figures)
        by_fig = {a["figure_id"]: a for a in result["associations"]}
        top_best = max(by_fig["fig-top"]["candidates"], key=lambda c: c["score"])
        bottom_best = max(by_fig["fig-bottom"]["candidates"], key=lambda c: c["score"])
        self.assertEqual(top_best["item_id"], "it-a")
        self.assertEqual(bottom_best["item_id"], "it-b")

    def test_same_section_preferred_over_different_section(self):
        """5. Given equal page/ordinal standing, an item in the figure's
        own (page-derived) section scores higher than one that is not."""
        items = [
            make_item("it-same-sec", "activity", [7], "sec-a"),
            make_item("it-other-sec", "activity", [7], "sec-b"),
        ]
        knowledge = make_knowledge(
            "doc-x-ch01",
            [make_section("sec-a", 1, 10), make_section("sec-b", 11, 20)],
            [], items,
        )
        # figure's page (7) falls in sec-a's range
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        candidates = {c["item_id"]: c for c in result["associations"][0]["candidates"]}
        self.assertGreater(candidates["it-same-sec"]["score"], candidates["it-other-sec"]["score"])

    def test_neighboring_page_fallback_when_own_page_has_no_items(self):
        """6. A figure whose own page has zero items falls back to the
        immediate neighboring pages, flagged as such and penalized."""
        items = [make_item("it-1", "activity", [8], "sec-a")]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-1", 9, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        assoc = result["associations"][0]
        self.assertEqual(len(assoc["candidates"]), 1)
        self.assertTrue(assoc["candidates"][0]["signals"]["neighboring_page"])
        self.assertNotEqual(assoc["decision"], "AUTO_MATCH", "neighboring-page candidates must never auto-match")

    def test_no_match_when_no_candidates_anywhere(self):
        """7. A figure whose page and both neighbors have no items at
        all yields NO_MATCH with an empty candidate list."""
        items = [make_item("it-1", "activity", [1], "sec-a")]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-1", 50, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        assoc = result["associations"][0]
        self.assertEqual(assoc["decision"], "NO_MATCH")
        self.assertEqual(assoc["candidates"], [])
        self.assertIsNone(assoc["chosen_item_id"])

    def test_ambiguous_close_scores_route_to_review(self):
        """8. Two candidates with near-identical scores (no clear
        winner) must go to REVIEW_REQUIRED, not be force-picked."""
        items = [
            make_item("it-a", "activity", [7], "sec-a", "sub-a"),
            make_item("it-b", "activity", [7], "sec-a", "sub-a"),
        ]
        knowledge = make_knowledge(
            "doc-x-ch01",
            [make_section("sec-a", 1, 20)],
            [{"id": "sub-a", "pdf_page_start": 1, "pdf_page_end": 20}],
            items,
        )
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        self.assertEqual(result["associations"][0]["decision"], "REVIEW_REQUIRED")

    def test_confident_single_candidate_auto_matches(self):
        """9. A figure alone on a page with exactly one item in the
        same section+subsection, no competing candidates, reaches
        AUTO_MATCH."""
        items = [make_item("it-only", "theorem", [7], "sec-a", "sub-a")]
        knowledge = make_knowledge(
            "doc-x-ch01",
            [make_section("sec-a", 1, 20)],
            [{"id": "sub-a", "pdf_page_start": 1, "pdf_page_end": 20}],
            items,
        )
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        assoc = result["associations"][0]
        self.assertEqual(assoc["decision"], "AUTO_MATCH")
        self.assertEqual(assoc["chosen_item_id"], "it-only")
        self.assertEqual(assoc["review_status"], "AUTO_ACCEPTED")

    def test_deterministic_rerun_same_logical_output(self):
        """10. Running the same inputs twice produces identical
        associations (aside from the generated_at timestamp)."""
        items = [make_item(f"it-{i}", "activity", [7], "sec-a") for i in range(3)]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10]), make_figure("fig-2", 7, [0, 20, 10, 30])]}
        r1 = build_associations(knowledge, figures)
        r2 = build_associations(knowledge, figures)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_no_chapter_specific_hardcoding_in_production_module(self):
        """11. The production module never references Chapter 1's own
        identifiers (page numbers, candidate/figure/item IDs)."""
        source = Path(__file__).parent.joinpath("associate_figures_knowledge.py").read_text(encoding="utf-8")
        forbidden = ["math-4eme-tome1", "ch01", "page_018", "page_009", "candidate_0"]
        for token in forbidden:
            self.assertNotIn(token, source, f"production module must not reference {token!r}")

    def test_stable_ids_are_deterministic_and_content_derived(self):
        """12. association_id is derived from chapter/figure/item
        identity, not from array position or a random/uuid source."""
        items = [make_item("it-1", "activity", [7], "sec-a")]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-1", 7, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        assoc_id = result["associations"][0]["candidates"][0]["association_id"]
        self.assertEqual(assoc_id, "assoc-doc-x-ch01-fig-1-it-1")

    def test_missing_section_subsection_geometry_handled_gracefully(self):
        """13. A page not covered by any section/subsection range (a
        gap in authored data) must not crash -- same_section/
        same_subsection simply read as False rather than being invented."""
        items = [make_item("it-1", "activity", [99], None, None)]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 5)], [], items)
        figures = {"figures": [make_figure("fig-1", 99, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        candidate = result["associations"][0]["candidates"][0]
        self.assertFalse(candidate["signals"]["same_section"])
        self.assertFalse(candidate["signals"]["same_subsection"])

    def test_multi_page_item_matches_any_of_its_pages(self):
        """14. An item spanning several pdf_pages is a same-page
        candidate for a figure on ANY of those pages."""
        items = [make_item("it-spanning", "exercise", [20, 21, 22], "sec-a")]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 30)], [], items)
        figures = {"figures": [make_figure("fig-1", 21, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        candidate = result["associations"][0]["candidates"][0]
        self.assertTrue(candidate["signals"]["same_page"])

    def test_figure_with_no_matching_knowledge_item(self):
        """15. A figure on a page with no items and no populated
        neighbors is NO_MATCH (duplicate of case 7's scenario at the
        chapter level, kept separate since the task brief lists it
        explicitly)."""
        items = [make_item("it-1", "activity", [3], "sec-a")]
        knowledge = make_knowledge("doc-x-ch01", [make_section("sec-a", 1, 20)], [], items)
        figures = {"figures": [make_figure("fig-orphan", 15, [0, 0, 10, 10])]}
        result = build_associations(knowledge, figures)
        self.assertEqual(result["associations"][0]["decision"], "NO_MATCH")

    def test_decide_helper_directly(self):
        clear_winner = [
            {"score": 0.9, "item_id": "a", "signals": {"neighboring_page": False}},
            {"score": 0.5, "item_id": "b", "signals": {"neighboring_page": False}},
        ]
        decision, chosen = decide(clear_winner)
        self.assertEqual(decision, "AUTO_MATCH")
        self.assertEqual(chosen["item_id"], "a")

        close_tie = [
            {"score": 0.9, "item_id": "a", "signals": {"neighboring_page": False}},
            {"score": 0.85, "item_id": "b", "signals": {"neighboring_page": False}},
        ]
        decision, _ = decide(close_tie)
        self.assertEqual(decision, "REVIEW_REQUIRED")

        empty_decision, empty_chosen = decide([])
        self.assertEqual(empty_decision, "NO_MATCH")
        self.assertIsNone(empty_chosen)


class TestChapter1Regression(unittest.TestCase):
    """Real Chapter 1 data is used ONLY as ground truth/ fixture here --
    never inside associate_figures_knowledge.py itself (see
    test_no_chapter_specific_hardcoding_in_production_module above)."""

    @classmethod
    def setUpClass(cls):
        if not config.KNOWLEDGE_CHAPTER_01_JSON.exists() or not config.FINAL_FIGURES_INDEX_JSON.exists():
            raise unittest.SkipTest("Chapter 1 knowledge JSON / final_figures index not found")
        from associate_figures_knowledge import load_figures, load_knowledge
        cls.knowledge = load_knowledge(config.KNOWLEDGE_CHAPTER_01_JSON)
        cls.figures = load_figures(config.FINAL_FIGURES_INDEX_JSON)

    def test_all_19_figures_produce_an_association_record(self):
        result = build_associations(self.knowledge, self.figures)
        self.assertEqual(result["summary"]["total_figures"], len(self.figures["figures"]))
        self.assertEqual(len(result["associations"]), len(self.figures["figures"]))

    def test_every_candidate_item_id_exists_in_knowledge(self):
        result = build_associations(self.knowledge, self.figures)
        valid_ids = {item["id"] for item in self.knowledge["items"]}
        for assoc in result["associations"]:
            for cand in assoc["candidates"]:
                self.assertIn(cand["item_id"], valid_ids)

    def test_no_figure_left_without_at_least_a_candidate_list(self):
        # Every real Chapter 1 figure's page has at least one item
        # somewhere in the chapter, so none should be a bare NO_MATCH
        # with zero candidates (documents the current, real outcome --
        # see the task's final report for why 0 reach AUTO_MATCH).
        result = build_associations(self.knowledge, self.figures)
        for assoc in result["associations"]:
            self.assertGreater(len(assoc["candidates"]), 0, assoc["figure_id"])

    def test_deterministic_rerun_on_real_data(self):
        r1 = build_associations(self.knowledge, self.figures)
        r2 = build_associations(self.knowledge, self.figures)
        r1.pop("generated_at")
        r2.pop("generated_at")
        self.assertEqual(r1, r2)

    def test_decisions_are_one_of_the_three_valid_states(self):
        result = build_associations(self.knowledge, self.figures)
        for assoc in result["associations"]:
            self.assertIn(assoc["decision"], {"AUTO_MATCH", "REVIEW_REQUIRED", "NO_MATCH"})


if __name__ == "__main__":
    unittest.main()
