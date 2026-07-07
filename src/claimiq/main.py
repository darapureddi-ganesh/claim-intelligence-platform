"""ClaimIQ FastAPI application."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.claimiq.api.routes.claims import router as claims_router
from src.claimiq.api.routes.health import router as health_router

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ClaimIQ",
        description=(
            "FNOL intake, ML scoring, and intelligent routing for Indian mid-market insurers. "
            "Every decision is justified by PolicyLens — no black-box routing."
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

    app.include_router(health_router)
    app.include_router(claims_router)

    @app.on_event("startup")
    async def startup() -> None:
        logger.info("claimiq_starting")

    return app


app = create_app()
