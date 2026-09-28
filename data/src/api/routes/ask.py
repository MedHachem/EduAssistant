"""POST /api/v1/ask (Phase 16). See data/schema/fastapi_api_design.md §7
for the exact HTTP status mapping and its rationale."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_embedding_backend, get_gemini_provider
from api.schemas import AnswerResultResponse, AskRequest
from api.services.ask_service import answer_question
from generate_answer import GenerationError
from search_embeddings import SearchIncompatibleModelError

logger = logging.getLogger("api.ask")
router = APIRouter()


@router.post("/api/v1/ask", response_model=AnswerResultResponse)
def ask(request: AskRequest, embedding_backend=Depends(get_embedding_backend),
        gemini_provider=Depends(get_gemini_provider)) -> dict:
    try:
        return answer_question(request.chapter_id, request.query, embedding_backend, gemini_provider)
    except SearchIncompatibleModelError as e:
        logger.error("Search/model incompatibility for chapter_id=%r: %s", request.chapter_id, e)
        raise HTTPException(status_code=500, detail="Internal configuration error while retrieving context.")
    except GenerationError as e:
        logger.error("Gemini provider failure: %s", e)
        raise HTTPException(status_code=502, detail="The answer-generation provider is currently unavailable.")
    except Exception:
        logger.exception("Unexpected error in POST /api/v1/ask")
        raise HTTPException(status_code=500, detail="An unexpected internal error occurred.")
