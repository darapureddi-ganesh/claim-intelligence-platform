"""Google AI configuration.

Every model ID is an environment variable, so a newer model from Google AI Studio
can be swapped in without a code change. Run `python scripts/list_models.py` to
see what your key or project can call.

Auth, in priority order:
1. Vertex AI (recommended on Cloud Run): GOOGLE_GENAI_USE_VERTEXAI=true plus
   GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION. Uses the service account, no key.
2. Gemini API key from Google AI Studio: GEMINI_API_KEY (or GOOGLE_API_KEY).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleAISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # --- Auth -------------------------------------------------------------
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    use_vertexai: bool = Field(
        default=False, validation_alias=AliasChoices("GOOGLE_GENAI_USE_VERTEXAI", "USE_VERTEXAI")
    )
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    # Live models on Vertex are regional, not served from "global".
    live_location: str = "us-central1"

    # --- Models (defaults are IDs from the google-genai 3.x model catalog) --
    # Gemini: multimodal FNOL intake, policy clause extraction, verdict letters
    gemini_model: str = "gemini-3.8-flash"
    # Larger reasoning model for long policy wordings (optional upgrade)
    gemini_reasoning_model: str = "gemini-3.8-flash"
    # Gemini Live: real-time multilingual voice FNOL
    gemini_live_model: str = "gemini-3.8-live"
    gemini_live_voice: str = "Kore"
    # Nano Banana: annotated damage-photo copies for adjusters
    nano_banana_model: str = "gemini-nano-banana-2.1"
    # Gemma: open-weights PII redaction (can be self-hosted inside the insurer's VPC)
    gemma_model: str = "gemma-4-26b-a4b-it"
    # Optional OpenAI-compatible endpoint for a self-hosted Gemma (vLLM / Ollama on
    # Cloud Run GPU or GKE). When empty, Gemma is called through the Gemini API.
    gemma_endpoint: str = ""

    # --- Feature switches -------------------------------------------------
    enable_gemma_redaction: bool = True
    request_timeout_s: float = 60.0

    @property
    def is_configured(self) -> bool:
        if self.use_vertexai:
            return bool(self.google_cloud_project)
        return bool(self.gemini_api_key)

    def public_summary(self) -> dict:
        """Safe to show in the UI: never includes the key."""
        return {
            "configured": self.is_configured,
            "backend": "vertex-ai" if self.use_vertexai else "gemini-api",
            "project": self.google_cloud_project or None,
            "models": {
                "gemini": self.gemini_model,
                "gemini_reasoning": self.gemini_reasoning_model,
                "gemini_live": self.gemini_live_model,
                "nano_banana": self.nano_banana_model,
                "gemma": self.gemma_model,
            },
            "gemma_self_hosted": bool(self.gemma_endpoint),
        }


@lru_cache(maxsize=1)
def get_google_ai_settings() -> GoogleAISettings:
    return GoogleAISettings()
