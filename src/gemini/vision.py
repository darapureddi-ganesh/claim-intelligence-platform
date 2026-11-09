"""Nano Banana: annotated copies of damage photos for adjusters.

The original upload is evidence and is never altered: we store its SHA-256 and
return a *separate*, clearly labelled annotated copy that circles and labels
visible damage so an adjuster can triage a photo set in seconds.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import structlog

from src.gemini.client import GoogleAIUnavailableError, get_client
from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt

logger = structlog.get_logger(__name__)


@dataclass
class AnnotatedImage:
    original_sha256: str
    image_base64: str | None
    mime_type: str
    notes: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_sha256": self.original_sha256,
            "annotated_image": (
                f"data:{self.mime_type};base64,{self.image_base64}" if self.image_base64 else None
            ),
            "notes": self.notes,
            "model": self.model,
            "label": "AI-annotated copy for adjuster triage. Not evidence; original preserved.",
        }


class DamageAnnotator:
    def __init__(self, client: Any | None = None, settings: GoogleAISettings | None = None) -> None:
        self._client = client
        self._settings = settings or get_google_ai_settings()

    def annotate(self, data: bytes, mime_type: str, claim_type: str = "motor") -> AnnotatedImage:
        from google.genai import types

        if not mime_type.startswith("image/"):
            raise ValueError("Nano Banana annotation needs an image.")
        digest = hashlib.sha256(data).hexdigest()
        client = self._client or get_client()
        try:
            response = client.models.generate_content(
                model=self._settings.nano_banana_model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    load_prompt("damage_annotation").replace("{claim_type}", claim_type),
                ],
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
        except Exception as exc:
            raise GoogleAIUnavailableError(f"Nano Banana annotation failed: {exc}") from exc

        image_b64, out_mime, notes = None, "image/png", []
        for cand in getattr(response, "candidates", None) or []:
            for part in getattr(cand.content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    raw = inline.data
                    image_b64 = base64.b64encode(raw).decode() if isinstance(raw, bytes) else raw
                    out_mime = inline.mime_type or out_mime
                elif getattr(part, "text", None):
                    notes.append(part.text)
            break
        logger.info("damage_annotated", sha256=digest, image=bool(image_b64))
        return AnnotatedImage(
            original_sha256=digest,
            image_base64=image_b64,
            mime_type=out_mime,
            notes="\n".join(notes).strip(),
            model=self._settings.nano_banana_model,
        )
