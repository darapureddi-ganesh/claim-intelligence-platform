"""VerdictLens: policyholder letters in the claimant's language, written by Gemini.

Gemini only *words* a decision PolicyLens already made. The draft is rejected
and replaced by a deterministic template when it:
  * states a different coverage status than PolicyLens returned, or
  * cites any clause that PolicyLens did not trace, or
  * cites no clause at all when clauses exist.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from src.core.domain.models import Claim, RoutingDecision
from src.core.domain.ports import JustificationResult
from src.gemini.client import get_client
from src.gemini.config import GoogleAISettings, get_google_ai_settings
from src.gemini.prompts import load_prompt
from src.gemini.schemas import VerdictDraft

logger = structlog.get_logger(__name__)

LANGUAGES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada",
    "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi",
    "or": "Odia", "ur": "Urdu", "as": "Assamese",
}

_STATUS_MEANING = {
    "COVERED": "The claim falls within the policy's cover and will proceed for assessment.",
    "CONDITIONAL": "Cover depends on conditions that must be verified before settlement.",
    "EXCLUDED": "The claim falls under a policy exclusion and is not payable as submitted.",
    "UNCLEAR": "No directly applicable clause was found; a claims officer will review manually.",
}

_QUEUE_MEANING = {
    "fast-track": "fast-track settlement",
    "standard": "standard claims assessment",
    "senior-adjuster": "review by a senior claims adjuster",
    "fraud-investigation": "additional verification by the claims investigation team",
}


@dataclass
class VerdictLetter:
    claim_id: str
    language: str
    coverage_status: str
    letter_markdown: str
    plain_language_summary: str
    cited_clause_refs: list[str]
    traced_clause_refs: list[str]
    generator: str  # "gemini" | "template"
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VerdictWriter:
    def __init__(self, client: Any | None = None, settings: GoogleAISettings | None = None) -> None:
        self._client = client
        self._settings = settings or get_google_ai_settings()

    def write(
        self,
        claim: Claim,
        decision: RoutingDecision,
        justification: JustificationResult,
        language: str = "en",
    ) -> VerdictLetter:
        language = language if language in LANGUAGES else "en"
        traced = [c.clause_ref for c in justification.traced_clauses if c.clause_ref]
        if not self._settings.is_configured and self._client is None:
            return template_letter(claim, decision, justification, ["Gemini not configured"])

        try:
            draft = self._draft(claim, decision, justification, language)
        except Exception as exc:
            logger.warning("verdict_gemini_failed", error=str(exc))
            return template_letter(claim, decision, justification, [f"Gemini error: {exc}"])

        errors = validate_draft(draft, justification.confidence, traced)
        if errors:
            logger.warning("verdict_draft_rejected", errors=errors, claim_id=str(claim.id))
            return template_letter(claim, decision, justification, errors)

        return VerdictLetter(
            claim_id=str(claim.id),
            language=language,
            coverage_status=justification.confidence,
            letter_markdown=draft.letter_markdown,
            plain_language_summary=draft.plain_language_summary,
            cited_clause_refs=draft.cited_clause_refs,
            traced_clause_refs=traced,
            generator="gemini",
        )

    def _draft(
        self,
        claim: Claim,
        decision: RoutingDecision,
        justification: JustificationResult,
        language: str,
    ) -> VerdictDraft:
        from google.genai import types

        client = self._client or get_client()
        clauses = "\n".join(
            f"- [{c.clause_ref}] {c.text}" for c in justification.traced_clauses
        ) or "- (no clause traced)"
        facts = (
            f"Write in: {LANGUAGES[language]}\n"
            f"Claim reference: {claim.id}\n"
            f"Policy number: {claim.policy_id}\n"
            f"Policyholder: {claim.insured_name or 'Policyholder'}\n"
            f"Claim type: {claim.claim_type.value}\n"
            f"Amount claimed: INR {claim.amount_claimed}\n"
            f"Incident date: {claim.incident_date.isoformat()}\n"
            f"COVERAGE STATUS (fixed, do not change): {justification.confidence}\n"
            f"Next step: {_QUEUE_MEANING.get(decision.assigned_queue, decision.assigned_queue)}\n"
            f"Audit justification ID: {justification.query_id}\n"
            f"TRACED POLICY CLAUSES (the only clauses you may cite):\n{clauses}\n"
        )
        response = client.models.generate_content(
            model=self._settings.gemini_model,
            contents=facts,
            config=types.GenerateContentConfig(
                system_instruction=load_prompt("verdict_letter"),
                response_mime_type="application/json",
                response_schema=VerdictDraft,
                temperature=0.3,
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, VerdictDraft):
            return parsed
        return VerdictDraft.model_validate_json(response.text or "{}")


_REF_IN_TEXT = re.compile(r"(?i)\b(?:section|clause)\s+(\d+(?:\.\d+)*[a-z]?)")


def _canon(ref: str) -> str:
    return re.sub(r"(?i)^(section|clause|article|part)\s+", "", ref.strip()).rstrip(".")


def validate_draft(draft: VerdictDraft, status: str, traced_refs: list[str]) -> list[str]:
    errors: list[str] = []
    allowed = {_canon(r) for r in traced_refs}
    if draft.decision_stated.strip().upper() != status.upper():
        errors.append(f"stated status '{draft.decision_stated}' != PolicyLens '{status}'")
    cited = {_canon(r) for r in draft.cited_clause_refs}
    cited |= {m.group(1) for m in _REF_IN_TEXT.finditer(draft.letter_markdown)}
    stray = sorted(c for c in cited if c not in allowed)
    if stray:
        errors.append(f"cites clauses PolicyLens did not trace: {stray}")
    if allowed and not cited:
        errors.append("cites no clause although PolicyLens traced clauses")
    if not draft.letter_markdown.strip():
        errors.append("empty letter")
    return errors


def template_letter(
    claim: Claim,
    decision: RoutingDecision,
    justification: JustificationResult,
    errors: list[str] | None = None,
) -> VerdictLetter:
    traced = [c.clause_ref for c in justification.traced_clauses if c.clause_ref]
    clause_lines = "\n".join(
        f"> **{c.clause_ref}** — {c.text}" for c in justification.traced_clauses
    ) or "> No specific clause applied; a claims officer will review your claim."
    status = justification.confidence
    letter = (
        f"**Claim reference:** {claim.id}  \n"
        f"**Policy number:** {claim.policy_id}\n\n"
        f"Dear {claim.insured_name or 'Policyholder'},\n\n"
        f"We have registered your {claim.claim_type.value} claim for INR {claim.amount_claimed} "
        f"for the incident on {claim.incident_date.isoformat()}.\n\n"
        f"**Coverage status: {status}.** {_STATUS_MEANING.get(status, '')}\n\n"
        f"Your claim has been sent for "
        f"{_QUEUE_MEANING.get(decision.assigned_queue, decision.assigned_queue)}.\n\n"
        f"This assessment is based on the following clause(s) of your policy:\n\n{clause_lines}\n\n"
        "If you disagree, you may write to our Grievance Redressal Officer. If your complaint "
        "is not resolved, you can approach IRDAI through the Bima Bharosa portal or the "
        "Insurance Ombudsman.\n\n"
        f"_Audit justification ID: {justification.query_id}_"
    )
    return VerdictLetter(
        claim_id=str(claim.id),
        language="en",
        coverage_status=status,
        letter_markdown=letter,
        plain_language_summary=_STATUS_MEANING.get(status, ""),
        cited_clause_refs=traced,
        traced_clause_refs=traced,
        generator="template",
        validation_errors=errors or [],
    )
