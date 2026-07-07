"""VerdictLens FastAPI application (Phase 2 stub)."""

from __future__ import annotations

from fastapi import FastAPI

from src.verdictlens.api.routes.denials import router as denials_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="VerdictLens",
        description="Claims denial explanation & compliance documentation (Phase 2).",
        version="0.2.0-planned",
    )
    app.include_router(denials_router)

    @app.get("/health", tags=["Health"])
    def health() -> dict:
        return {"status": "ok", "service": "verdictlens", "phase": "2-planned"}

    return app


app = create_app()
