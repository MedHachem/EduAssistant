"""
FastAPI dependency providers (Phase 16).

Lazy, process-wide singletons for the two expensive/stateful pipeline
resources -- the BGE-M3 embedding backend and the Gemini provider -- so
they are constructed ONCE per process, not once per HTTP request. Both
are ordinary FastAPI Depends() callables, which gives tests the
idiomatic override point (app.dependency_overrides[...]) without
touching route or service code.
"""

from __future__ import annotations

import config

_embedding_backend = None
_gemini_provider = None


def get_embedding_backend():
    global _embedding_backend
    if _embedding_backend is None:
        from embed_knowledge import SentenceTransformerBackend

        _embedding_backend = SentenceTransformerBackend()
    return _embedding_backend


def get_gemini_provider():
    global _gemini_provider
    if _gemini_provider is None:
        from generate_answer import GeminiProvider

        _gemini_provider = GeminiProvider(model=config.GEMINI_MODEL)
    return _gemini_provider
