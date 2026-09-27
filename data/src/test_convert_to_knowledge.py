"""
Unit tests for the recursive question/sub-question parser in
convert_to_knowledge.py (parse_questions). Deterministic, no LLM, no
file I/O -- pure function tests against synthetic text mirroring real
patterns confirmed in Chapter 1 (see convert_to_knowledge.py's
parse_questions docstring and the conversation history for the real
source pages these patterns were found on).

Run:
    python test_convert_to_knowledge.py
    python -m unittest test_convert_to_knowledge
"""

import unittest

from convert_to_knowledge import parse_questions


class TestParseQuestionsHierarchy(unittest.TestCase):

    def test_digit_then_letters_no_own_text(self):
        """1. (no text) -> a./b./c. -- the exact bug report case."""
        text = "1.\na. Determine ...\nb. Show that ...\nc. Deduce ..."
        statement, questions = parse_questions(text)
        self.assertIsNone(statement)
        self.assertEqual(len(questions), 1)
        top = questions[0]
        self.assertEqual(top["label"], "1")
        self.assertIsNone(top["text"])
        self.assertEqual([q["label"] for q in top["sub_questions"]], ["a", "b", "c"])
        self.assertEqual(top["sub_questions"][0]["text"], "Determine ...")
        self.assertEqual(top["sub_questions"][1]["text"], "Show that ...")
        self.assertEqual(top["sub_questions"][2]["text"], "Deduce ...")
        for sub in top["sub_questions"]:
            self.assertEqual(sub["sub_questions"], [])

    def test_digit_with_own_text_then_letters(self):
        """1. has its own text AND sub-questions a./b./c."""
        text = "1. Soit f une fonction.\na. Determine ...\nb. Show that ...\nc. Deduce ..."
        statement, questions = parse_questions(text)
        self.assertEqual(len(questions), 1)
        top = questions[0]
        self.assertEqual(top["label"], "1")
        self.assertEqual(top["text"], "Soit f une fonction.")
        self.assertEqual([q["label"] for q in top["sub_questions"]], ["a", "b", "c"])

    def test_three_level_hierarchy_digit_letter_roman(self):
        """1. -> a. -> i./ii."""
        text = "1.\na.\ni. First.\nii. Second.\nb. Show that ..."
        statement, questions = parse_questions(text)
        self.assertEqual(len(questions), 1)
        top = questions[0]
        self.assertEqual(top["label"], "1")
        self.assertIsNone(top["text"])
        self.assertEqual(len(top["sub_questions"]), 2)

        a_node = top["sub_questions"][0]
        self.assertEqual(a_node["label"], "a")
        self.assertIsNone(a_node["text"])
        self.assertEqual([q["label"] for q in a_node["sub_questions"]], ["i", "ii"])
        self.assertEqual(a_node["sub_questions"][0]["text"], "First.")
        self.assertEqual(a_node["sub_questions"][1]["text"], "Second.")

        b_node = top["sub_questions"][1]
        self.assertEqual(b_node["label"], "b")
        self.assertEqual(b_node["text"], "Show that ...")
        self.assertEqual(b_node["sub_questions"], [])

    def test_multiple_top_level_questions(self):
        """1., 2., 3. -- flat siblings, no nesting."""
        text = "1. First question.\n2. Second question.\n3. Third question."
        statement, questions = parse_questions(text)
        self.assertEqual([q["label"] for q in questions], ["1", "2", "3"])
        self.assertEqual(questions[0]["text"], "First question.")
        self.assertEqual(questions[1]["text"], "Second question.")
        self.assertEqual(questions[2]["text"], "Third question.")
        for q in questions:
            self.assertEqual(q["sub_questions"], [])

    def test_question_with_no_sub_questions(self):
        """A single flat question, no markers at all beneath it."""
        text = "1. Etudier la continuité de f sur son ensemble de définition."
        statement, questions = parse_questions(text)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["label"], "1")
        self.assertEqual(questions[0]["text"], "Etudier la continuité de f sur son ensemble de définition.")
        self.assertEqual(questions[0]["sub_questions"], [])

    def test_mixed_some_with_subquestions_some_without(self):
        """1. has a/b children; 2. is flat; 3. has its own text AND children."""
        text = (
            "1.\na. First part.\nb. Second part.\n"
            "2. A standalone question.\n"
            "3. Setup text.\na. Sub one.\nb. Sub two."
        )
        statement, questions = parse_questions(text)
        self.assertEqual([q["label"] for q in questions], ["1", "2", "3"])

        q1 = questions[0]
        self.assertIsNone(q1["text"])
        self.assertEqual([s["label"] for s in q1["sub_questions"]], ["a", "b"])

        q2 = questions[1]
        self.assertEqual(q2["text"], "A standalone question.")
        self.assertEqual(q2["sub_questions"], [])

        q3 = questions[2]
        self.assertEqual(q3["text"], "Setup text.")
        self.assertEqual([s["label"] for s in q3["sub_questions"]], ["a", "b"])

    def test_compound_markers_on_a_single_line(self):
        """Real corpus pattern: "1. a. Text..." on ONE line (not two),
        confirmed on page 9 ("1. a. Déterminer $\\lim...$"). Must still
        split into a parent "1" (no text of its own) with child "a"."""
        text = "1. a. Déterminer la limite.\nb. Conclure."
        statement, questions = parse_questions(text)
        self.assertEqual(len(questions), 1)
        top = questions[0]
        self.assertEqual(top["label"], "1")
        self.assertIsNone(top["text"])
        self.assertEqual([s["label"] for s in top["sub_questions"]], ["a", "b"])
        self.assertEqual(top["sub_questions"][0]["text"], "Déterminer la limite.")
        self.assertEqual(top["sub_questions"][1]["text"], "Conclure.")

    def test_statement_before_first_marker_is_preserved(self):
        text = "Soit f une fonction continue.\n\n1. Montrer que...\n2. En déduire..."
        statement, questions = parse_questions(text)
        self.assertEqual(statement, "Soit f une fonction continue.")
        self.assertEqual([q["label"] for q in questions], ["1", "2"])

    def test_no_markers_at_all_becomes_pure_statement(self):
        text = "Cette activité ne contient aucune numérotation explicite."
        statement, questions = parse_questions(text)
        self.assertEqual(statement, "Cette activité ne contient aucune numérotation explicite.")
        self.assertEqual(questions, [])

    def test_ambiguous_roman_letter_as_plain_letter_when_no_letter_parent(self):
        """A bare "i." with NO open 'letter' level is just the letter i,
        not a roman-lower level -- e.g. "1." -> "i." directly (skipping
        the letter level) should NOT be misread as roman_lower."""
        text = "1.\ni. Uses letter i directly, not nested under a letter."
        statement, questions = parse_questions(text)
        top = questions[0]
        self.assertEqual(len(top["sub_questions"]), 1)
        self.assertEqual(top["sub_questions"][0]["label"], "i")


if __name__ == "__main__":
    unittest.main()
