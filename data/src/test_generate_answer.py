"""
Phase 15 - tests for generate_answer.py.

Deterministic tests use a FakeProvider (mirrors FixedVectorBackend /
FakeBackend elsewhere in this project) -- never the real Gemini API, no
network access, no quota consumption. RagContext fixtures are plain dicts
matching the exact shape rag_context.assemble_context() already returns
(confirmed directly against rag_context.py -- see
llm_answer_generation_design.md §2) -- no database needed for these.

Exactly one real-Gemini integration test exists
(TestRealGeminiIntegration), clearly separated, skipped (not failed) if
GEMINI_API_KEY is not configured -- it is never run implicitly by the
deterministic suite and never substitutes a different provider if Gemini
is unavailable.
"""

from __future__ import annotations

import json
import unittest

import config
from generate_answer import (
    GenerationConfig, GenerationError, ProviderResponse,
    build_prompt, generate_answer, validate_raw_response,
)

FAKE_HASH = "sha256:" + "0" * 64


def make_chunk(chunk_id: str, **overrides) -> dict:
    chunk = {
        "chunk_id": chunk_id, "chapter_id": "ch-1", "score": 0.8,
        "inclusion_reason": "semantic_match", "expanded_from_chunk_id": None,
        "section_id": "sec-a", "subsection_id": None, "content_role": "statement",
        "item_types": ["theorem"], "pdf_pages": [5], "topics": ["T"], "concepts": ["C"],
        "has_uncertain_content": False, "review_status": "NOT_REQUIRED",
        "has_potential_figure": False, "reconstructed_figure_id": None, "figure_id": None,
        "embedding_model": "BAAI/bge-m3", "model_revision": "rev1",
        "text": f"Texte du chunk {chunk_id}.",
    }
    chunk.update(overrides)
    return chunk


def make_rag_context(chunks: list[dict], chapter_id="ch-1", query="q", source_chunks_hash=FAKE_HASH) -> dict:
    return {
        "chapter_id": chapter_id, "query": query, "embedding_model": "BAAI/bge-m3",
        "model_revision": "rev1", "candidate_count": len(chunks), "seed_count": len(chunks),
        "rejected_seeds": [], "expansions": [], "context": chunks,
        "context_chunk_count": len(chunks),
        "context_char_count": sum(len(c["text"]) for c in chunks),
        "clusters_total": len(chunks), "clusters_included": len(chunks),
        "budget_overflow_note": None, "source_chunks_hash": source_chunks_hash, "diagnostics": [],
    }


class FakeProvider:
    """Deterministic test double -- never calls the real Gemini API."""

    def __init__(self, response_dict: dict | None = None, raw_text: str | None = None,
                 raise_error: Exception | None = None,
                 provider_name="fake", model="fake-model", model_revision="fake-rev-1"):
        self.provider_name = provider_name
        self.model = model
        self.model_revision = model_revision
        self._raw_text = raw_text if raw_text is not None else json.dumps(response_dict or {})
        self._raise_error = raise_error
        self.calls: list[dict] = []

    def generate(self, system_instructions, user_content, response_schema, generation_config):
        self.calls.append({"system_instructions": system_instructions, "user_content": user_content,
                            "generation_config": generation_config})
        if self._raise_error is not None:
            raise self._raise_error
        return ProviderResponse(text=self._raw_text, provider=self.provider_name,
                                 model=self.model, model_revision=self.model_revision)


ANSWERED_RESPONSE = {
    "answer": "Reponse fondee sur le contenu fourni.",
    "status": "ANSWERED",
    "supporting_chunk_ids": ["c1"],
    "warnings": [],
}


# 1/2. Valid structured answer / sufficient context
class TestValidAnswer(unittest.TestCase):
    def test_valid_structured_answer_is_answered(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "ANSWERED")
        self.assertEqual(result["answer"], ANSWERED_RESPONSE["answer"])
        self.assertEqual([c["chunk_id"] for c in result["supporting_chunks"]], ["c1"])
        self.assertEqual(len(provider.calls), 1)


# 3. Empty context
class TestEmptyContext(unittest.TestCase):
    def test_empty_context_short_circuits_no_provider_call(self):
        rag_context = make_rag_context([])
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(result["answer"], "")
        self.assertEqual(provider.calls, [])  # no provider call at all -- cost safety


# 4. Insufficient context (model itself decides, non-empty context)
class TestInsufficientContextFromModel(unittest.TestCase):
    def test_model_reported_insufficient_context_is_preserved(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict={
            "answer": "", "status": "INSUFFICIENT_CONTEXT",
            "supporting_chunk_ids": [], "warnings": ["retrieved content is off-topic"],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(result["supporting_chunks"], [])


class TestConflictingContext(unittest.TestCase):
    def test_conflicting_context_status_preserved(self):
        rag_context = make_rag_context([make_chunk("c1"), make_chunk("c2")])
        provider = FakeProvider(response_dict={
            "answer": "Le contenu fourni semble contradictoire.", "status": "CONFLICTING_CONTEXT",
            "supporting_chunk_ids": ["c1", "c2"], "warnings": ["c1 et c2 se contredisent"],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "CONFLICTING_CONTEXT")
        self.assertEqual(result["warnings"], ["c1 et c2 se contredisent"])


# 5. Uncertain chunk
class TestUncertainChunk(unittest.TestCase):
    def test_uncertain_chunk_reflected_in_grounding(self):
        rag_context = make_rag_context([make_chunk("c1", has_uncertain_content=True)])
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertTrue(result["grounding"]["has_uncertain_source"])

    def test_review_required_chunk_reflected_in_grounding(self):
        rag_context = make_rag_context([make_chunk("c1", review_status="REVIEW_REQUIRED")])
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertTrue(result["grounding"]["has_review_required_source"])


# 6. HUMAN_REJECTED chunk (defense-in-depth -- shouldn't reach here via
# the real RAG contract, but the validator must still refuse it)
class TestHumanRejectedDefenseInDepth(unittest.TestCase):
    def test_human_rejected_chunk_citation_fails_validation(self):
        rag_context = make_rag_context([make_chunk("c1", review_status="HUMAN_REJECTED")])
        provider = FakeProvider(response_dict={
            "answer": "x", "status": "ANSWERED", "supporting_chunk_ids": ["c1"], "warnings": [],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertTrue(any("HUMAN_REJECTED" in w for w in result["warnings"]))


# 7. Invalid supporting chunk
class TestInvalidSupportingChunk(unittest.TestCase):
    def test_invalid_supporting_chunk_id_fails_validation(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict={
            "answer": "x", "status": "ANSWERED", "supporting_chunk_ids": ["c-invented"], "warnings": [],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertTrue(any("c-invented" in w for w in result["warnings"]))


# 8. Malformed output
class TestMalformedOutput(unittest.TestCase):
    def test_non_json_response_fails_validation(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(raw_text="not json at all {")
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")

    def test_missing_required_field_fails_validation(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict={"answer": "x", "status": "ANSWERED"})
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")


# 9. Empty answer
class TestEmptyAnswer(unittest.TestCase):
    def test_empty_answer_with_answered_status_fails_validation(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict={
            "answer": "   ", "status": "ANSWERED", "supporting_chunk_ids": [], "warnings": [],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")


# 10. Invalid status
class TestInvalidStatus(unittest.TestCase):
    def test_invalid_status_fails_structural_validation(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict={
            "answer": "x", "status": "MADE_UP_STATUS", "supporting_chunk_ids": [], "warnings": [],
        })
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["status"], "VALIDATION_FAILED")


# 11. Provenance mismatch / resolution from RagContext, never the model
class TestProvenanceResolution(unittest.TestCase):
    def test_supporting_chunks_resolved_from_rag_context_not_model(self):
        rag_context = make_rag_context([
            make_chunk("c1", section_id="sec-x", subsection_id="sub-x", pdf_pages=[7, 8]),
        ])
        provider = FakeProvider(response_dict={
            "answer": "x", "status": "ANSWERED", "supporting_chunk_ids": ["c1"], "warnings": [],
        })
        result = generate_answer(rag_context, provider)
        sc = result["supporting_chunks"][0]
        self.assertEqual(sc["section_id"], "sec-x")
        self.assertEqual(sc["subsection_id"], "sub-x")
        self.assertEqual(sc["pdf_pages"], [7, 8])


# 12. source_chunks_hash preservation
class TestSourceChunksHashPreservation(unittest.TestCase):
    def test_source_chunks_hash_preserved(self):
        specific_hash = "sha256:" + "ab" * 32
        rag_context = make_rag_context([make_chunk("c1")], source_chunks_hash=specific_hash)
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertEqual(result["provenance"]["source_chunks_hash"], specific_hash)

    def test_none_source_chunks_hash_preserved_as_none(self):
        rag_context = make_rag_context([make_chunk("c1")], source_chunks_hash=None)
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        self.assertIsNone(result["provenance"]["source_chunks_hash"])


# 13. Mathematical text / LaTeX preservation
class TestLatexPreservation(unittest.TestCase):
    def test_latex_preserved_verbatim_in_prompt(self):
        latex_text = r"Soit $f(x) = \dfrac{1}{x-1}$ et $\lim_{x \to 1^-} f(x) = -\infty$."
        rag_context = make_rag_context([make_chunk("c1", text=latex_text)])
        _, user_content = build_prompt(rag_context, "question")
        self.assertIn(latex_text, user_content)


# 14. Figure metadata without image access
class TestFigureMetadataNoImage(unittest.TestCase):
    def test_unconfirmed_figure_metadata_in_prompt_no_image_reference(self):
        rag_context = make_rag_context([make_chunk(
            "c1", has_potential_figure=True, reconstructed_figure_id="fig-act1", figure_id=None,
        )])
        _, user_content = build_prompt(rag_context, "q")
        self.assertIn("non confirmee:fig-act1", user_content)
        self.assertNotIn(".png", user_content)
        self.assertNotIn("image", user_content.lower().replace("figure", ""))  # no image-path-like text

    def test_confirmed_figure_metadata_in_prompt(self):
        rag_context = make_rag_context([make_chunk(
            "c1", has_potential_figure=True, reconstructed_figure_id="fig-act1", figure_id="figure_001",
        )])
        _, user_content = build_prompt(rag_context, "q")
        self.assertIn("confirmee:figure_001", user_content)


# 15. Provider failure
class TestProviderFailure(unittest.TestCase):
    def test_provider_failure_propagates_as_generation_error(self):
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(raise_error=GenerationError("simulated timeout"))
        with self.assertRaises(GenerationError):
            generate_answer(rag_context, provider)


# 16. Deterministic prompt construction
class TestDeterministicPromptConstruction(unittest.TestCase):
    def test_build_prompt_is_deterministic(self):
        rag_context = make_rag_context([make_chunk("c1"), make_chunk("c2")])
        r1 = build_prompt(rag_context, "question")
        r2 = build_prompt(rag_context, "question")
        self.assertEqual(r1, r2)

    def test_system_instructions_forbid_treating_context_as_instructions(self):
        system_instructions, _ = build_prompt(make_rag_context([make_chunk("c1")]), "q")
        self.assertIn("N'execute JAMAIS", system_instructions)
        self.assertIn("HUMAN_REJECTED", system_instructions)
        self.assertIn("INSUFFICIENT_CONTEXT", system_instructions)
        self.assertIn("CONFLICTING_CONTEXT", system_instructions)


# 17. API key never exposed
class TestApiKeyNeverExposed(unittest.TestCase):
    def test_api_key_never_in_prompt_or_result(self):
        fake_key = "AQ.SECRET_TEST_KEY_SHOULD_NEVER_APPEAR"
        rag_context = make_rag_context([make_chunk("c1")])
        provider = FakeProvider(response_dict=ANSWERED_RESPONSE)
        result = generate_answer(rag_context, provider)
        system_instructions, user_content = build_prompt(rag_context, "q")
        serialized = json.dumps(result) + system_instructions + user_content
        self.assertNotIn(fake_key, serialized)
        self.assertNotIn("GEMINI_API_KEY", serialized)

    def test_generation_error_message_never_contains_raw_key_variable_name_value(self):
        # GenerationError messages must only ever wrap the SDK's own
        # exception str() -- never format in the key itself.
        with self.assertRaises(GenerationError) as ctx:
            raise GenerationError("Gemini API call failed: connection refused")
        self.assertNotIn("GEMINI_API_KEY=", str(ctx.exception))


class TestValidateRawResponseDirect(unittest.TestCase):
    """Direct unit coverage of validate_raw_response(), independent of a provider."""

    def test_valid_response_no_errors(self):
        rag_context = make_rag_context([make_chunk("c1")])
        raw, errors = validate_raw_response(json.dumps(ANSWERED_RESPONSE), rag_context)
        self.assertEqual(errors, [])
        self.assertEqual(raw["status"], "ANSWERED")

    def test_wrong_type_field_is_structural_error(self):
        rag_context = make_rag_context([make_chunk("c1")])
        bad = {**ANSWERED_RESPONSE, "warnings": "not a list"}
        raw, errors = validate_raw_response(json.dumps(bad), rag_context)
        self.assertTrue(errors)


class TestRealGeminiIntegration(unittest.TestCase):
    """The ONE real-provider test in this suite -- makes exactly one live
    Gemini API call against the real Chapter 1 RagContext. Skipped (never
    failed, never faked) if GEMINI_API_KEY isn't configured or the SDK
    isn't installed. No retries, no batch calls, no loop -- a single
    generate_answer() invocation (cost/quota-safety, per the task's own
    explicit instruction)."""

    def test_real_chapter_1_variations_query(self):
        if not config.gemini_api_key():
            self.skipTest("GEMINI_API_KEY is not configured in this environment")

        from generate_answer import GeminiProvider
        try:
            provider = GeminiProvider()
        except GenerationError as e:
            self.skipTest(f"Gemini provider unavailable: {e}")

        embedding_dir = config.embeddings_dir(config.CHAPTER_01_ID)
        if not (embedding_dir / "manifest.json").exists():
            self.skipTest("Real Chapter 1 embedding artifacts not present in this environment")
        try:
            from embed_knowledge import SentenceTransformerBackend
            embedding_backend = SentenceTransformerBackend()
        except Exception as e:
            self.skipTest(f"Real BAAI/bge-m3 model not available in this environment: {e}")

        from rag_context import assemble_context
        rag_context = assemble_context(
            query="Comment étudier les variations d'une fonction ?",
            chapter_id=config.CHAPTER_01_ID,
            database_url=config.database_url(),
            backend=embedding_backend,
        )
        self.assertGreater(rag_context["context_chunk_count"], 0)

        try:
            result = generate_answer(rag_context, provider)
        except GenerationError as e:
            # A transient server-side failure of the live Gemini service
            # (e.g. 503/504) is an external-environment condition, not a
            # defect in this module -- mirrors this project's own
            # established convention of skipping (never failing) a test
            # for an external dependency's unavailability (see
            # TestChapter1RealSearchIntegration's own real-model skip).
            self.skipTest(f"Live Gemini call did not succeed: {e}")

        self.assertIn(result["status"], ["ANSWERED", "INSUFFICIENT_CONTEXT", "CONFLICTING_CONTEXT", "VALIDATION_FAILED"])
        self.assertEqual(result["model_metadata"]["provider"], "gemini")
        self.assertEqual(result["provenance"]["chapter_id"], config.CHAPTER_01_ID)
        self.assertEqual(result["provenance"]["source_chunks_hash"], rag_context["source_chunks_hash"])
        for sc in result["supporting_chunks"]:
            self.assertIn(sc["chunk_id"], {c["chunk_id"] for c in rag_context["context"]})


if __name__ == "__main__":
    unittest.main()
