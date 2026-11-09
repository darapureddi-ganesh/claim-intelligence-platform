"""PII redaction: deterministic regex pass + Gemma for names and addresses.

Why Gemma: it is open-weights, so an insurer can run it inside its own VPC
(Cloud Run GPU, GKE, or on-prem) and keep raw claimant PII out of every log,
audit row and analytics export — the data-minimisation duty under India's
DPDP Act, 2023. In the demo it is called through the Gemini API; set
GEMMA_ENDPOINT to point at a self-hosted OpenAI-compatible server instead.

The regex pass always runs first and its placeholders are re-checked after
Gemma, so a bad model output can never *un-redact* an Aadhaar or PAN.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt

logger = structlog.get_logger(__name__)

# Order matters: Aadhaar before generic phone numbers.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("BANK_ACCOUNT", re.compile(r"(?i)(?:a/c|account)\s*(?:no\.?|number)?[:\s]*\d{9,18}\b")),
]


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    engine: str = "regex"

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def regex_redact(text: str) -> RedactionResult:
    counts: dict[str, int] = {}
    out = text
    for label, pattern in _PATTERNS:
        out, n = pattern.subn(f"[{label}]", out)
        if n:
            counts[label] = n
    return RedactionResult(text=out, counts=counts, engine="regex")


class GemmaPIIRedactor:
    def __init__(self, client: Any | None = None, settings: GoogleAISettings | None = None) -> None:
        self._client = client
        self._settings = settings or get_google_ai_settings()

    def redact(self, text: str) -> RedactionResult:
        base = regex_redact(text)
        if not text.strip() or not self._settings.enable_gemma_redaction:
            return base
        has_backend = self._settings.is_configured or self._settings.gemma_endpoint
        if self._client is None and not has_backend:
            return base
        try:
            gemma_text = self._call_gemma(base.text)
        except Exception as exc:  # redaction must never block intake
            logger.warning("gemma_redaction_failed_using_regex", error=str(exc))
            return base

        if not _is_safe_rewrite(base.text, gemma_text):
            logger.warning("gemma_redaction_rejected_using_regex")
            return base

        counts = dict(base.counts)
        for label in ("NAME", "ADDRESS"):
            n = gemma_text.count(f"[{label}]") - base.text.count(f"[{label}]")
            if n > 0:
                counts[label] = n
        return RedactionResult(text=gemma_text, counts=counts, engine="regex+gemma")

    def _call_gemma(self, text: str) -> str:
        prompt = f"{load_prompt('pii_redaction')}\n\nTEXT:\n{text}"
        if self._settings.gemma_endpoint:
            return self._call_self_hosted(prompt)
        client = self._client
        if client is None:
            from src.gemini.client import get_client

            client = get_client()
        # Gemma on the Gemini API takes no system_instruction; inline the prompt.
        response = client.models.generate_content(
            model=self._settings.gemma_model, contents=prompt
        )
        return (response.text or "").strip()

    def _call_self_hosted(self, prompt: str) -> str:
        url = self._settings.gemma_endpoint.rstrip("/") + "/v1/chat/completions"
        resp = httpx.post(
            url,
            json={
                "model": self._settings.gemma_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=self._settings.request_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _is_safe_rewrite(before: str, after: str) -> bool:
    """Reject outputs that dropped regex placeholders, leaked PII, or rewrote the text."""
    if not after:
        return False
    for label, _ in _PATTERNS:
        if after.count(f"[{label}]") < before.count(f"[{label}]"):
            return False
    if regex_redact(after).total:
        return False
    # Redaction should shorten or keep length; large growth means the model chatted.
    return 0.4 * len(before) <= len(after) <= 1.3 * len(before) + 40
