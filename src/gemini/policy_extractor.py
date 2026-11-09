"""Gemini policy-wording extractor with a verbatim grounding check.

Replaces the keyword/spaCy heuristics with Gemini's reading of the wording
(including scanned PDFs), while keeping PolicyLens's audit guarantee:

    every clause node stored in the graph is a character-for-character
    substring of the source document.

Any clause Gemini paraphrases or invents is rejected before it reaches the
graph. The reasoning engine itself stays zero-LLM and unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.gemini.client import GoogleAIUnavailableError, get_client
from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt
from src.gemini.schemas import GroundedClause, PolicyExtraction
from src.policylens.graph.models import NodeType
from src.policylens.nlp.extractor import ExtractedClause

logger = structlog.get_logger(__name__)

# Vocabulary the zero-LLM reasoning engine actually matches on.
ALLOWED_TAGS = {
    "coverage", "exclusion", "condition", "endorsement", "clause",
    "motor", "vehicle", "collision", "third party",
    "health", "hospitalization", "illness", "surgery", "treatment",
    "property", "fire", "flood", "theft", "burglary",
    "life", "death", "nominee", "marine",
    "pre-existing", "waiting-period", "high-value", "complex",
    "fraud", "suspicious", "investigation", "disputed", "fast-track", "straightforward",
    "alcohol",
}
_NODE_TYPES = {t.value for t in NodeType} - {NodeType.POLICY.value}


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class ExtractionReport:
    accepted: list[ExtractedClause] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


class GeminiPolicyClauseExtractor:
    """Drop-in replacement for PolicyClauseExtractor (same `extract` signature)."""

    def __init__(self, client: Any | None = None, settings: GoogleAISettings | None = None) -> None:
        self._client = client
        self._settings = settings or get_google_ai_settings()
        self.last_report = ExtractionReport()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_client()
        return self._client

    def transcribe(self, data: bytes, mime_type: str) -> str:
        """Verbatim transcription of a PDF/scan, which then becomes the grounding source."""
        from google.genai import types

        try:
            response = self.client.models.generate_content(
                model=self._settings.gemini_model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    load_prompt("policy_transcribe"),
                ],
                config=types.GenerateContentConfig(temperature=0.0),
            )
        except Exception as exc:
            raise GoogleAIUnavailableError(f"Gemini transcription failed: {exc}") from exc
        return (response.text or "").strip()

    def extract(self, policy_text: str, policy_id: str) -> list[ExtractedClause]:
        from google.genai import types

        try:
            response = self.client.models.generate_content(
                model=self._settings.gemini_reasoning_model,
                contents=f"POLICY ID: {policy_id}\n\nPOLICY WORDING:\n{policy_text}",
                config=types.GenerateContentConfig(
                    system_instruction=load_prompt("policy_extraction"),
                    response_mime_type="application/json",
                    response_schema=PolicyExtraction,
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            raise GoogleAIUnavailableError(f"Gemini policy extraction failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, PolicyExtraction):
            parsed = PolicyExtraction.model_validate_json(response.text or "{}")
        self.last_report = ground_clauses(parsed.clauses, policy_text, policy_id)
        logger.info(
            "gemini_policy_extracted",
            policy_id=policy_id,
            accepted=len(self.last_report.accepted),
            rejected=len(self.last_report.rejected),
        )
        return self.last_report.accepted


def ground_clauses(
    clauses: list[GroundedClause], source_text: str, policy_id: str
) -> ExtractionReport:
    report = ExtractionReport()
    source = _norm(source_text)
    seen: set[str] = set()
    for i, c in enumerate(clauses):
        text = c.verbatim_text.strip()
        if len(text) < 12:
            report.rejected.append({"clause_ref": c.clause_ref, "reason": "too short"})
            continue
        if _norm(text) not in source:
            report.rejected.append({"clause_ref": c.clause_ref, "reason": "not verbatim in source"})
            continue
        key = _norm(text)
        if key in seen:
            continue
        seen.add(key)
        node_type_value = c.node_type.lower().strip()
        node_type = NodeType(node_type_value) if node_type_value in _NODE_TYPES else NodeType.CLAUSE
        tags = [node_type.value] + [
            t.lower().strip() for t in c.tags if t.lower().strip() in ALLOWED_TAGS
        ]
        # Same deterministic tag rules as the spaCy extractor, so both agree.
        low = key
        if "pre-existing" in low or "pre existing" in low:
            tags.append("pre-existing")
        if "waiting period" in low:
            tags.append("waiting-period")
        report.accepted.append(
            ExtractedClause(
                raw_text=text,
                node_type=node_type,
                clause_ref=c.clause_ref.strip() or f"Block {i + 1}",
                tags=list(dict.fromkeys(tags)),
                metadata={"policy_id": policy_id, "extractor": "gemini", "grounded": True},
            )
        )
    return report
