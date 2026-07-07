"""Normalizes raw FNOL field values into the domain model."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.core.domain.models import ClaimType

_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%Y%m%d"]

_CLAIM_TYPE_ALIASES: dict[str, ClaimType] = {
    "motor": ClaimType.MOTOR, "vehicle": ClaimType.MOTOR, "car": ClaimType.MOTOR,
    "auto": ClaimType.MOTOR, "bike": ClaimType.MOTOR, "two-wheeler": ClaimType.MOTOR,
    "health": ClaimType.HEALTH, "medical": ClaimType.HEALTH, "hospitalization": ClaimType.HEALTH,
    "hospitalisation": ClaimType.HEALTH, "illness": ClaimType.HEALTH,
    "property": ClaimType.PROPERTY, "fire": ClaimType.PROPERTY, "home": ClaimType.PROPERTY,
    "building": ClaimType.PROPERTY, "flood": ClaimType.PROPERTY,
    "life": ClaimType.LIFE, "death": ClaimType.LIFE, "term": ClaimType.LIFE,
    "marine": ClaimType.MARINE, "cargo": ClaimType.MARINE,
}


def normalize_claim_type(raw: str) -> ClaimType:
    lower = raw.lower().strip()
    for alias, ct in _CLAIM_TYPE_ALIASES.items():
        if alias in lower:
            return ct
    try:
        return ClaimType(lower)
    except ValueError:
        return ClaimType.OTHER


def normalize_amount(raw: Any) -> Decimal:
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip()
    # Remove currency symbols and commas
    text = re.sub(r"[₹\$,\s]", "", text)
    text = re.sub(r"(?i)inr|rs\.?", "", text).strip()
    # Handle "lakh" / "crore" suffixes
    m = re.match(r"([\d.]+)\s*(?i)(lakh|lac)", text)
    if m:
        return Decimal(m.group(1)) * Decimal("100000")
    m = re.match(r"([\d.]+)\s*(?i)crore", text)
    if m:
        return Decimal(m.group(1)) * Decimal("10000000")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def normalize_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return date.today()


def detect_language(text: str) -> str:
    """Naive language detection: Hindi unicode range → 'hi', else 'en'."""
    hindi_chars = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    if hindi_chars / max(len(text), 1) > 0.1:
        return "hi"
    return "en"
