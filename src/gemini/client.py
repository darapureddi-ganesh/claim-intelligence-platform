"""google-genai client factory (Gemini API key or Vertex AI)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from src.gemini.config import GoogleAISettings, get_google_ai_settings


class GoogleAIUnavailableError(RuntimeError):
    """Raised when no Gemini credentials are configured or a model call fails."""


def build_client(settings: GoogleAISettings, *, location: str | None = None) -> Any:
    from google import genai

    if not settings.is_configured:
        raise GoogleAIUnavailableError(
            "Google AI is not configured. Set GEMINI_API_KEY (from Google AI Studio) or "
            "GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT."
        )
    if settings.use_vertexai:
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=location or settings.google_cloud_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


@lru_cache(maxsize=1)
def get_client() -> Any:
    return build_client(get_google_ai_settings())


@lru_cache(maxsize=1)
def get_live_client() -> Any:
    settings = get_google_ai_settings()
    return build_client(settings, location=settings.live_location)


def parse_json_loose(text: str) -> Any:
    """Parse JSON that may be wrapped in a ```json fence (Gemma has no JSON mode)."""
    if text is None:
        raise ValueError("empty model response")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    return json.loads(cleaned)
