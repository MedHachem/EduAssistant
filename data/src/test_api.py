"""
Phase 16 - tests for the FastAPI API layer (data/src/api/).

No test calls Gemini or a real database:
- api.dependencies.get_embedding_backend / get_gemini_provider are
  replaced via app.dependency_overrides with trivial fakes (so no BGE-M3
  load, no GEMINI_API_KEY requirement at test-collection time).
- api.services.ask_service.assemble_context / generate_answer are
  replaced via unittest.mock.patch with deterministic canned
  returns/exceptions -- the same seam that lets a test assert the real
  functions WERE called (proving the route delegates to the existing
  pipeline rather than reimplementing it).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import config
from api.dependencies import get_embedding_backend, get_gemini_provider
from api.main import app
from generate_answer import GenerationError
from search_embeddings import SearchIncompatibleModelError

FAKE_HASH = "sha256:" + "0" * 64


def make_answer_result(status="ANSWERED", answer="Reponse.", supporting_chunks=None) -> dict:
    return {
        "answer": answer,
        "status": status,
        "supporting_chunks": supporting_chunks or [],
        "warnings": [],
        "grounding": {
            "context_chunk_count": 1, "cited_chunk_count": len(supporting_chunks or []),
            "has_uncertain_source": False, "has_review_required_source": False,
        },
        "provenance": {"chapter_id": "math-4eme-tome1-ch01", "source_chunks_hash": FAKE_HASH},
        "model_metadata": {"provider": "gemini", "model": "gemini-3.7-flash", "model_revision": None},
        "generation_metadata": {
            "prompt_version": "llm-answer-prompt-v1",
            "generation_config": {"temperature": 0.1, "max_output_tokens": 1024, "seed": None},
            "generated_at": "2026-01-01T00:00:00+00:00",
        },
    }


FAKE_RAG_CONTEXT = {"chapter_id": "math-4eme-tome1-ch01", "query": "q", "context": [{"chunk_id": "c1"}],
                    "context_chunk_count": 1, "source_chunks_hash": FAKE_HASH}


class ApiTestCase(unittest.TestCase):
    """Overrides the two expensive/stateful dependencies for every test
    in this suite -- no real BGE-M3 load, no real Gemini client init."""

    def setUp(self):
        app.dependency_overrides[get_embedding_backend] = lambda: object()
        app.dependency_overrides[get_gemini_provider] = lambda: object()
        # raise_server_exceptions=False: matches a real deployment's
        # actual behavior (an unhandled exception, including a
        # ResponseValidationError, becomes a real 500 response) rather
        # than TestClient's default debug-convenience re-raise.
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# 1. Valid request / 7. Successful ANSWERED response
# --------------------------------------------------------------------------

class TestValidRequestAnswered(ApiTestCase):
    def test_valid_request_returns_answered(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT) as m_search, \
             patch("api.services.ask_service.generate_answer",
                   return_value=make_answer_result(status="ANSWERED")) as m_generate:
            response = self.client.post("/api/v1/ask", json={
                "chapter_id": "math-4eme-tome1-ch01",
                "query": "Comment étudier les variations d'une fonction ?",
            })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ANSWERED")
        self.assertEqual(body["answer"], "Reponse.")
        # 14. existing pipeline functions are actually invoked, not duplicated
        m_search.assert_called_once()
        self.assertEqual(m_search.call_args.kwargs["chapter_id"], "math-4eme-tome1-ch01")
        m_generate.assert_called_once()


# --------------------------------------------------------------------------
# 2-6. Request validation
# --------------------------------------------------------------------------

class TestRequestValidation(ApiTestCase):
    def test_missing_chapter_id(self):
        response = self.client.post("/api/v1/ask", json={"query": "q"})
        self.assertEqual(response.status_code, 422)

    def test_empty_chapter_id(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "", "query": "q"})
        self.assertEqual(response.status_code, 422)

    def test_missing_query(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1"})
        self.assertEqual(response.status_code, 422)

    def test_empty_query(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": ""})
        self.assertEqual(response.status_code, 422)

    def test_whitespace_only_query(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "   \n\t "})
        self.assertEqual(response.status_code, 422)

    def test_whitespace_only_chapter_id(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "  ", "query": "q"})
        self.assertEqual(response.status_code, 422)

    def test_unrelated_field_rejected(self):
        response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q", "extra": "nope"})
        self.assertEqual(response.status_code, 422)

    def test_user_input_never_silently_modified(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT) as m_search, \
             patch("api.services.ask_service.generate_answer", return_value=make_answer_result()):
            self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "  Comment ca marche ?  "})
        self.assertEqual(m_search.call_args.kwargs["query"], "  Comment ca marche ?  ")


# --------------------------------------------------------------------------
# 8. INSUFFICIENT_CONTEXT / 9. CONFLICTING_CONTEXT
# --------------------------------------------------------------------------

class TestOtherAnswerStatuses(ApiTestCase):
    def test_insufficient_context_is_200(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer",
                   return_value=make_answer_result(status="INSUFFICIENT_CONTEXT", answer="")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "INSUFFICIENT_CONTEXT")

    def test_conflicting_context_is_200(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer",
                   return_value=make_answer_result(status="CONFLICTING_CONTEXT")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "CONFLICTING_CONTEXT")

    def test_validation_failed_is_200(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer",
                   return_value=make_answer_result(status="VALIDATION_FAILED", answer="")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "VALIDATION_FAILED")


# --------------------------------------------------------------------------
# 10. LLM provider failure -> 502
# --------------------------------------------------------------------------

class TestProviderFailure(ApiTestCase):
    def test_generation_error_is_502(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer", side_effect=GenerationError("Gemini API call failed: 503")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 502)
        # never fabricate an ANSWERED result on provider failure
        self.assertNotEqual(response.json().get("status"), "ANSWERED")

    def test_search_incompatible_model_error_is_500(self):
        with patch("api.services.ask_service.assemble_context",
                   side_effect=SearchIncompatibleModelError("dimension mismatch")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 500)


# --------------------------------------------------------------------------
# 11. Unexpected internal failure -> 500, no leaked internals
# --------------------------------------------------------------------------

class TestUnexpectedFailure(ApiTestCase):
    def test_unexpected_exception_is_500_generic(self):
        with patch("api.services.ask_service.assemble_context", side_effect=RuntimeError("boom, secret_path=/etc/passwd")):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 500)
        body_text = response.text
        self.assertNotIn("secret_path", body_text)
        self.assertNotIn("Traceback", body_text)


# --------------------------------------------------------------------------
# 12. Response conforms to AnswerResult
# --------------------------------------------------------------------------

class TestResponseSchemaConformance(ApiTestCase):
    def test_response_matches_answer_result_shape(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer",
                   return_value=make_answer_result(supporting_chunks=[
                       {"chunk_id": "c1", "chapter_id": "math-4eme-tome1-ch01", "section_id": "sec-a",
                        "subsection_id": None, "pdf_pages": [6]},
                   ])):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        body = response.json()
        for key in ("answer", "status", "supporting_chunks", "warnings", "grounding",
                    "provenance", "model_metadata", "generation_metadata"):
            self.assertIn(key, body)
        self.assertEqual(body["supporting_chunks"][0]["chunk_id"], "c1")

    def test_malformed_pipeline_dict_fails_response_validation(self):
        # A response dict missing a required AnswerResult field must be
        # caught (surfaced as a 500), never silently passed through.
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer", return_value={"answer": "x"}):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        self.assertEqual(response.status_code, 500)


# --------------------------------------------------------------------------
# 13. No secret/API key appears in the response
# --------------------------------------------------------------------------

class TestNoSecretsExposed(ApiTestCase):
    def test_no_gemini_api_key_in_response(self):
        with patch("api.services.ask_service.assemble_context", return_value=FAKE_RAG_CONTEXT), \
             patch("api.services.ask_service.generate_answer", return_value=make_answer_result()):
            response = self.client.post("/api/v1/ask", json={"chapter_id": "ch-1", "query": "q"})
        real_key = config.gemini_api_key()
        if real_key:
            self.assertNotIn(real_key, response.text)
        self.assertNotIn("GEMINI_API_KEY", response.text)
        self.assertNotIn("POSTGRES_PASSWORD", response.text)


# --------------------------------------------------------------------------
# 15. CORS behavior
# --------------------------------------------------------------------------

class TestCors(ApiTestCase):
    def test_allowed_origin_gets_cors_header(self):
        allowed_origin = config.api_cors_origins()[0]
        response = self.client.options("/api/v1/ask", headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(response.headers.get("access-control-allow-origin"), allowed_origin)

    def test_disallowed_origin_gets_no_cors_header(self):
        response = self.client.options("/api/v1/ask", headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        })
        self.assertNotIn("access-control-allow-origin", response.headers)


# --------------------------------------------------------------------------
# /health
# --------------------------------------------------------------------------

class TestHealth(ApiTestCase):
    def test_health_returns_ok_without_touching_pipeline(self):
        with patch("api.services.ask_service.assemble_context") as m_search, \
             patch("api.services.ask_service.generate_answer") as m_generate:
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        m_search.assert_not_called()
        m_generate.assert_not_called()


class TestOpenApiDocs(ApiTestCase):
    def test_openapi_schema_includes_ask_endpoint(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/v1/ask", response.json()["paths"])

    def test_docs_page_available(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
