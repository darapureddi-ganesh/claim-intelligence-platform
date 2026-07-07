"""
FNOL document parser.

Phase 1 (English pilot): handles structured JSON payloads and plain text.
Phase 1d: multilingual OCR layer slots in here by providing a new IDocumentParser
adapter — the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from src.claimiq.intake.normalizer import detect_language, normalize_amount, normalize_claim_type, normalize_date
from src.core.domain.models import ClaimType, FNOLData
from src.core.domain.ports import IDocumentParser


class EnglishTextFNOLParser(IDocumentParser):
    """
    Parses structured JSON or plain-text FNOL submissions.
    Normalises amounts, dates, and claim types into the domain FNOLData model.
    """

    def parse(self, raw: bytes | str, mime_type: str = "application/json") -> FNOLData:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        if mime_type == "application/json" or raw.strip().startswith("{"):
            return self._parse_json(raw)
        return self._parse_plain_text(raw)

    def _parse_json(self, text: str) -> FNOLData:
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON FNOL payload: {exc}") from exc

        policy_id = str(data.get("policy_id") or data.get("policyId") or "UNKNOWN")
        insured_name = str(data.get("insured_name") or data.get("insuredName") or "")
        raw_ct = data.get("claim_type") or data.get("claimType") or "other"
        claim_type = normalize_claim_type(str(raw_ct))
        amount = normalize_amount(data.get("amount_claimed") or data.get("amount") or 0)
        incident_date = normalize_date(data.get("incident_date") or data.get("incidentDate") or date.today())
        reported_date = normalize_date(data.get("reported_date") or data.get("reportedDate") or date.today())
        narrative = str(data.get("narrative") or data.get("description") or "")
        language = data.get("language") or detect_language(narrative) or "en"

        # Pass through any extra fields as metadata
        known_keys = {"policy_id", "policyId", "insured_name", "insuredName", "claim_type",
                      "claimType", "amount_claimed", "amount", "incident_date", "incidentDate",
                      "reported_date", "reportedDate", "narrative", "description", "language"}
        metadata = {k: v for k, v in data.items() if k not in known_keys}

        return FNOLData(
            policy_id=policy_id,
            claim_type=claim_type,
            amount_claimed=amount,
            incident_date=incident_date,
            reported_date=reported_date,
            insured_name=insured_name,
            raw_text=text,
            detected_language=language,
            metadata=metadata,
        )

    def _parse_plain_text(self, text: str) -> FNOLData:
        """Best-effort extraction from unstructured plain text (English)."""
        import re

        policy_m = re.search(r"policy\s*(?:no\.?|id|number)[:\s]+([A-Z0-9\-]+)", text, re.IGNORECASE)
        amount_m = re.search(r"(?:claim|amount)[:\s]+([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
        claim_type_m = re.search(
            r"(motor|vehicle|health|medical|property|fire|life|marine)", text, re.IGNORECASE
        )

        return FNOLData(
            policy_id=policy_m.group(1) if policy_m else "UNKNOWN",
            claim_type=normalize_claim_type(claim_type_m.group(1) if claim_type_m else "other"),
            amount_claimed=normalize_amount(amount_m.group(1) if amount_m else "0"),
            incident_date=date.today(),
            reported_date=date.today(),
            insured_name="",
            raw_text=text,
            detected_language=detect_language(text),
        )
