"""
The entire orchestration logic for POST /api/v1/ask (Phase 16).

Exactly two calls to already-validated, unchanged pipeline functions --
no vector similarity, no BGE-M3 embedding, no RAG selection/expansion/
diversity/budget logic, no Gemini prompt construction or response
validation is reimplemented here. This is the one seam tests patch to
verify the route delegates to the real pipeline functions rather than
duplicating them.
"""

from __future__ import annotations

from embed_knowledge import EmbeddingBackend
from generate_answer import LLMProvider, generate_answer
from rag_context import assemble_context


def answer_question(chapter_id: str, query: str, embedding_backend: EmbeddingBackend,
                     gemini_provider: LLMProvider) -> dict:
    rag_context = assemble_context(query=query, chapter_id=chapter_id, backend=embedding_backend)
    return generate_answer(rag_context, gemini_provider)
