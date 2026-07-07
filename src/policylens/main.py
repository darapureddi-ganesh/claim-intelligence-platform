"""PolicyLens FastAPI application."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.policylens.api.routes.policies import router as policies_router
from src.policylens.api.routes.query import router as query_router

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="PolicyLens",
        description=(
            "Rule-based policy knowledge graph for IRDAI-audit-defensible claims justification. "
            "Zero LLM — every answer traces to a specific policy clause."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(policies_router)
    app.include_router(query_router)

    @app.get("/health", tags=["Health"])
    def health() -> dict:
        return {"status": "ok", "service": "policylens"}

    return app


app = create_app()
