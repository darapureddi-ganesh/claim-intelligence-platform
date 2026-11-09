"""Single Cloud Run service: ClaimIQ + PolicyLens + VerdictLens + Google AI.

    uvicorn src.platform.app:app --port 8080
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.claimiq.intake.normalizer import normalize_claim_type
from src.core.domain.models import FNOLData
from src.gemini.client import GoogleAIUnavailableError
from src.gemini.config import get_google_ai_settings
from src.gemini.intake import Attachment
from src.gemini.verdict import LANGUAGES
from src.platform.service import ClaimNotFoundError, PlatformService
from src.platform.store import InMemoryStore

logger = structlog.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
SAMPLE_POLICY = ROOT / "data" / "sample_policy.txt"
MAX_UPLOAD_BYTES = 18 * 1024 * 1024


class StructuredClaimRequest(BaseModel):
    policy_id: str
    insured_name: str = ""
    claim_type: str
    amount_claimed: Decimal = Field(gt=0)
    incident_date: date
    reported_date: date
    narrative: str = ""
    language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyTextRequest(BaseModel):
    policy_id: str
    policy_name: str
    wording_text: str
    extractor: str = Field("gemini", pattern="^(gemini|rules)$")


def build_store():
    backend = os.getenv("STORAGE_BACKEND", "memory").lower()
    if backend == "firestore":
        from src.platform.store import FirestoreStore

        return FirestoreStore(
            project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
    return InMemoryStore()


def create_app(service: PlatformService | None = None, seed: bool = True) -> FastAPI:
    app = FastAPI(
        title="ClaimSaathi — Claims Intelligence on Google AI",
        description=(
            "Gemini reads claims in any Indian language, Gemma redacts PII, a zero-LLM policy "
            "graph decides, and Gemini explains — with every sentence traced to a clause."
        ),
        version="1.0.0",
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    svc = service or PlatformService(store=build_store())
    app.state.service = svc
    if seed and SAMPLE_POLICY.exists() and not svc.graph.policy_exists("HC-STD-2024"):
        # Seed with the deterministic extractor so the demo works with no API key.
        svc.load_policy("HC-STD-2024", "Standard Health + Motor + Property (sample)",
                        SAMPLE_POLICY.read_text(), use_gemini=False)

    # ------------------------------------------------------------------ meta
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health", tags=["Meta"])
    def health() -> dict:
        return {"status": "ok", "google_ai": get_google_ai_settings().is_configured}

    @app.get("/api/config", tags=["Meta"])
    def config() -> dict:
        return {
            **get_google_ai_settings().public_summary(),
            "storage": os.getenv("STORAGE_BACKEND", "memory"),
            "languages": LANGUAGES,
        }

    # ------------------------------------------------------------------ policies
    @app.get("/api/policies", tags=["PolicyLens"])
    def list_policies() -> list[dict]:
        return list(svc.policies.values())

    @app.get("/api/policies/{policy_id}/clauses", tags=["PolicyLens"])
    def policy_clauses(policy_id: str) -> list[dict]:
        if not svc.graph.policy_exists(policy_id):
            raise HTTPException(404, "Policy not found.")
        return svc.policy_clauses(policy_id)

    @app.post("/api/policies", status_code=201, tags=["PolicyLens"])
    def load_policy_text(req: PolicyTextRequest) -> dict:
        return _guard(lambda: svc.load_policy(
            req.policy_id, req.policy_name, text=req.wording_text,
            use_gemini=req.extractor == "gemini"))

    @app.post("/api/policies/upload", status_code=201, tags=["PolicyLens"])
    async def load_policy_file(
        policy_id: str = Form(...),
        policy_name: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict:
        data = await _read(file)
        mime = file.content_type or "application/octet-stream"
        if mime.startswith("text/"):
            return _guard(lambda: svc.load_policy(policy_id, policy_name,
                                                  text=data.decode("utf-8", "replace")))
        return _guard(lambda: svc.load_policy(policy_id, policy_name,
                                              document=Attachment(data, mime, file.filename or "")))

    # ------------------------------------------------------------------ claims
    @app.get("/api/claims", tags=["ClaimIQ"])
    def list_claims(limit: int = 50) -> list[dict]:
        return svc.list_claims(limit)

    @app.get("/api/claims/{claim_id}", tags=["ClaimIQ"])
    def get_claim(claim_id: UUID) -> dict:
        try:
            return svc.claim_detail(claim_id)
        except ClaimNotFoundError:
            raise HTTPException(404, "Claim not found.")

    @app.post("/api/claims", status_code=201, tags=["ClaimIQ"])
    async def submit_structured(req: StructuredClaimRequest) -> dict:
        fnol = FNOLData(
            policy_id=req.policy_id, claim_type=normalize_claim_type(req.claim_type),
            amount_claimed=req.amount_claimed, incident_date=req.incident_date,
            reported_date=req.reported_date, insured_name=req.insured_name,
            raw_text=req.narrative, detected_language=req.language, metadata=req.metadata,
        )
        return await _aguard(svc.submit(fnol, channel="api"))

    @app.post("/api/intake/extract", tags=["Gemini intake"])
    async def intake_extract(
        text: str = Form(""), files: list[UploadFile] = File(default=[])
    ) -> dict:
        """Gemini reads text/photos/PDFs/voice notes and returns facts + evidence (no filing)."""
        attachments = [await _attachment(f) for f in files]
        result = _guard(lambda: svc.extract(text, attachments))
        result.pop("_fnol_obj", None)
        return result

    @app.post("/api/intake", status_code=201, tags=["Gemini intake"])
    async def intake_and_triage(
        text: str = Form(""), files: list[UploadFile] = File(default=[])
    ) -> dict:
        """Gemini reads → Gemma redacts → score → route → PolicyLens justifies."""
        attachments = [await _attachment(f) for f in files]
        return await _aguard(svc.intake_and_triage(text, attachments))

    @app.post("/api/claims/{claim_id}/verdict", tags=["VerdictLens"])
    def verdict(claim_id: UUID, language: str = "en") -> dict:
        try:
            return svc.verdict(claim_id, language)
        except ClaimNotFoundError:
            raise HTTPException(404, "Claim or decision not found.")

    @app.post("/api/vision/annotate", tags=["Nano Banana"])
    async def annotate(file: UploadFile = File(...), claim_id: str = Form("")) -> dict:
        data = await _read(file)
        cid = UUID(claim_id) if claim_id else None
        try:
            return _guard(lambda: svc.annotate(data, file.content_type or "", cid))
        except ClaimNotFoundError:
            raise HTTPException(404, "Claim not found.")

    # ------------------------------------------------------------------ voice
    @app.websocket("/api/live/fnol")
    async def live_fnol(ws: WebSocket) -> None:
        from src.gemini.client import get_live_client
        from src.gemini.live import run_live_bridge

        await ws.accept()
        try:
            client = get_live_client()
        except GoogleAIUnavailableError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close()
            return
        try:
            await run_live_bridge(ws, client, svc.submit_from_voice, svc.match_policy)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.exception("live_session_failed")
            try:
                await ws.send_json({"type": "error", "message": f"Live session ended: {exc}"})
            except Exception:
                pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    return app


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{file.filename} is larger than 18 MB.")
    return data


async def _attachment(file: UploadFile) -> Attachment:
    data = await _read(file)
    return Attachment(data=data, mime_type=file.content_type or "application/octet-stream",
                      filename=file.filename or "")


def _guard(fn):
    try:
        return fn()
    except GoogleAIUnavailableError as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


async def _aguard(coro):
    from src.claimiq.services.triage import JustificationRequiredError

    try:
        return await coro
    except GoogleAIUnavailableError as exc:
        raise HTTPException(503, str(exc))
    except JustificationRequiredError as exc:
        raise HTTPException(503, f"PolicyLens justification unavailable: {exc}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


app = create_app()
