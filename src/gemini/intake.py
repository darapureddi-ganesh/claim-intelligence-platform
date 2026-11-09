"""Multimodal, multilingual FNOL intake with Gemini.

Accepts any mix of: free text in any Indian language, photos of damage, scanned
or PDF hospital bills / discharge summaries / FIRs, and voice notes. Returns an
`ExtractedFNOL` (facts + evidence) and can be converted to the core `FNOLData`,
so it slots in behind the existing `IDocumentParser` port — the "Phase 1d
multilingual OCR layer" the original design left a hole for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.claimiq.intake.normalizer import normalize_claim_type
from src.core.domain.models import FNOLData
from src.core.domain.ports import IDocumentParser
from src.gemini.client import GoogleAIUnavailableError, get_client
from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt
from src.gemini.schemas import ExtractedFNOL

logger = structlog.get_logger(__name__)

SUPPORTED_MIME_PREFIXES = ("image/", "application/pdf", "audio/", "text/")
MAX_INLINE_BYTES = 18 * 1024 * 1024  # stay under the 20 MB inline request limit


@dataclass
class Attachment:
    data: bytes
    mime_type: str
    filename: str = ""


class GeminiFNOLExtractor(IDocumentParser):
    def __init__(self, client: Any | None = None, settings: GoogleAISettings | None = None) -> None:
        self._client = client
        self._settings = settings or get_google_ai_settings()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_client()
        return self._client

    def extract(
        self,
        text: str = "",
        attachments: list[Attachment] | None = None,
        today: date | None = None,
    ) -> ExtractedFNOL:
        from google.genai import types

        attachments = attachments or []
        total = sum(len(a.data) for a in attachments)
        if total > MAX_INLINE_BYTES:
            raise ValueError("Attachments exceed 18 MB; upload fewer or smaller files.")
        for a in attachments:
            if not a.mime_type.startswith(SUPPORTED_MIME_PREFIXES):
                raise ValueError(f"Unsupported file type: {a.mime_type} ({a.filename})")
        if not text.strip() and not attachments:
            raise ValueError("Provide a description or at least one document/photo/voice note.")

        parts: list[Any] = []
        for a in attachments:
            parts.append(types.Part.from_text(text=f"[Attachment: {a.filename or a.mime_type}]"))
            parts.append(types.Part.from_bytes(data=a.data, mime_type=a.mime_type))
        parts.append(
            types.Part.from_text(
                text=(
                    f"Today's date: {(today or date.today()).isoformat()}\n"
                    f"Claimant's message:\n{text.strip() or '(none — use the attachments)'}"
                )
            )
        )

        try:
            response = self.client.models.generate_content(
                model=self._settings.gemini_model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=load_prompt("fnol_intake"),
                    response_mime_type="application/json",
                    response_schema=ExtractedFNOL,
                    temperature=0.1,
                ),
            )
        except GoogleAIUnavailableError:
            raise
        except Exception as exc:  # SDK raises several error types
            raise GoogleAIUnavailableError(f"Gemini FNOL extraction failed: {exc}") from exc

        extracted = _parsed_or_validate(response, ExtractedFNOL)
        logger.info(
            "gemini_fnol_extracted",
            claim_type=extracted.claim_type.value,
            language=extracted.detected_language,
            documents=len(extracted.documents),
            flags=len(extracted.consistency_flags),
        )
        return extracted

    # IDocumentParser port ---------------------------------------------------
    def parse(self, raw: bytes | str, mime_type: str) -> FNOLData:
        if isinstance(raw, str):
            extracted = self.extract(text=raw)
        else:
            extracted = self.extract(attachments=[Attachment(data=raw, mime_type=mime_type)])
        return to_fnol_data(extracted)


def _parsed_or_validate(response: Any, model: type) -> Any:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, model):
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise GoogleAIUnavailableError("Gemini returned an empty response.")
    return model.model_validate_json(text)


def to_fnol_data(x: ExtractedFNOL, today: date | None = None) -> FNOLData:
    """Map Gemini's extraction onto the core domain. Deterministic code from here on."""
    today = today or date.today()
    incident = _safe_date(x.incident_date) or today
    reported = _safe_date(x.reported_date) or today
    if reported < incident:
        reported = incident

    metadata: dict[str, Any] = {
        "intake_channel": "gemini-multimodal",
        "incident_location": x.incident_location,
        "narrative_original": x.narrative_original,
        "documents": [d.model_dump() for d in x.documents],
        "damage": x.damage.model_dump(),
        "ai_consistency_flags": [f.model_dump(mode="json") for f in x.consistency_flags],
        "missing_information": x.missing_information,
    }
    # Facts consumed by PolicyLens exclusion rules — only set when evidenced.
    if x.pre_existing_condition.value is not None and x.pre_existing_condition.evidence:
        metadata["pre_existing_condition"] = x.pre_existing_condition.value
        metadata["pre_existing_evidence"] = x.pre_existing_condition.evidence
    if x.alcohol_or_drugs_involved.value is not None and x.alcohol_or_drugs_involved.evidence:
        metadata["alcohol_or_drugs_involved"] = x.alcohol_or_drugs_involved.value
        metadata["alcohol_or_drugs_evidence"] = x.alcohol_or_drugs_involved.evidence

    # Waiting period is computed by code, never asked of the model.
    start = _safe_date(x.policy_start_date)
    if start:
        metadata["policy_start_date"] = start.isoformat()
        metadata["within_waiting_period"] = (incident - start).days < 30

    return FNOLData(
        policy_id=x.policy_id.strip() or "UNKNOWN",
        claim_type=normalize_claim_type(x.claim_type.value),
        amount_claimed=Decimal(str(round(x.amount_claimed_inr, 2))),
        incident_date=incident,
        reported_date=reported,
        insured_name=x.insured_name,
        raw_text=x.narrative_english or x.narrative_original,
        detected_language=(x.detected_language or "en")[:5],
        metadata=metadata,
    )


def _safe_date(value: str) -> date | None:
    """Strict parse: unlike normalize_date, never falls back to today."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None
