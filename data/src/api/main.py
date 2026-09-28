"""
FastAPI app entrypoint (Phase 16).

Run from data/src (matching this project's own established convention --
every existing script assumes that working directory for its flat
`import config`-style imports; this package is no exception):

    cd data/src
    python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

Then:
    GET  http://127.0.0.1:8000/health
    GET  http://127.0.0.1:8000/docs
    POST http://127.0.0.1:8000/api/v1/ask
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes.ask import router as ask_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(
    title="EduAssistant API",
    description="Thin HTTP layer over the validated Semantic Search / RAG Context Assembly / Gemini Answer Generation pipeline.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.api_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(ask_router)


@app.get("/health")
def health() -> dict:
    """Process-liveness only -- never touches Gemini, PostgreSQL, BGE-M3,
    or Semantic Search."""
    return {"status": "ok"}
