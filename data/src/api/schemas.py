"""
Pydantic request/response models for the FastAPI API layer (Phase 16).

The response models are a field-for-field mirror of
data/schema/answer_result.schema.json (already confirmed, by direct
inspection, to match generate_answer.py's own real AnswerResult dict
shape exactly) -- NOT a second, incompatible format. They exist so
FastAPI can validate the dict generate_answer() returns before
serializing it, and so /docs and /openapi.json are accurate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AnswerStatus = Literal["ANSWERED", "INSUFFICIENT_CONTEXT", "CONFLICTING_CONTEXT", "VALIDATION_FAILED"]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)

    @field_validator("chapter_id", "query")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v  # returned UNCHANGED -- never silently modified (e.g. never .strip()'d)


class SupportingChunk(BaseModel):
    chunk_id: str
    chapter_id: str
    section_id: str | None
    subsection_id: str | None
    pdf_pages: list[int]


class Grounding(BaseModel):
    context_chunk_count: int
    cited_chunk_count: int
    has_uncertain_source: bool
    has_review_required_source: bool


class Provenance(BaseModel):
    chapter_id: str
    source_chunks_hash: str | None


class ModelMetadata(BaseModel):
    provider: str
    model: str
    model_revision: str | None


class GenerationConfigMetadata(BaseModel):
    temperature: float
    max_output_tokens: int
    seed: int | None = None


class GenerationMetadata(BaseModel):
    prompt_version: str
    generation_config: GenerationConfigMetadata
    generated_at: str


class AnswerResultResponse(BaseModel):
    """Mirrors answer_result.schema.json / generate_answer.py's AnswerResult
    dict exactly -- see this module's own docstring."""

    answer: str
    status: AnswerStatus
    supporting_chunks: list[SupportingChunk]
    warnings: list[str]
    grounding: Grounding
    provenance: Provenance
    model_metadata: ModelMetadata
    generation_metadata: GenerationMetadata
