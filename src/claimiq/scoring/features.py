"""Feature engineering for claim scoring models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np

from src.core.domain.models import Claim, ClaimType

_CLAIM_TYPE_INDEX = {t.value: i for i, t in enumerate(ClaimType)}
_AMOUNT_BRACKETS = [0, 25_000, 100_000, 500_000, 1_000_000, 5_000_000, float("inf")]


def extract_features(claim: Claim) -> np.ndarray:
    """Return a 1D numpy feature vector for scoring."""
    amount = float(claim.amount_claimed)
    incident_age_days = (claim.reported_date - claim.incident_date).days

    features = [
        _claim_type_to_int(claim.claim_type),
        _amount_bucket(amount),
        min(amount / 100_000, 50.0),      # raw amount scaled
        max(0, min(incident_age_days, 365)),  # days between incident and report (capped)
        int(incident_age_days > 30),       # late-reporting flag
        int(incident_age_days > 90),       # very-late-reporting flag
        int(claim.language != "en"),       # non-English document flag
        _policy_age_flag(claim.metadata),
        _weekend_incident_flag(claim.incident_date),
        _high_value_flag(amount),
    ]
    return np.array(features, dtype=float)


def feature_names() -> list[str]:
    return [
        "claim_type_int",
        "amount_bucket",
        "amount_scaled",
        "incident_age_days",
        "late_report_flag",
        "very_late_report_flag",
        "non_english_flag",
        "policy_age_flag",
        "weekend_incident_flag",
        "high_value_flag",
    ]


def _claim_type_to_int(ct: ClaimType) -> int:
    return _CLAIM_TYPE_INDEX.get(ct.value, len(_CLAIM_TYPE_INDEX))


def _amount_bucket(amount: float) -> int:
    for i, threshold in enumerate(_AMOUNT_BRACKETS[1:], start=1):
        if amount <= threshold:
            return i - 1
    return len(_AMOUNT_BRACKETS) - 2


def _policy_age_flag(metadata: dict[str, Any]) -> int:
    policy_start = metadata.get("policy_start_date")
    if policy_start and isinstance(policy_start, str):
        try:
            from datetime import datetime
            start = datetime.fromisoformat(policy_start).date()
            return int((date.today() - start).days < 90)
        except ValueError:
            pass
    return 0


def _weekend_incident_flag(incident_date: date) -> int:
    return int(incident_date.weekday() >= 5)


def _high_value_flag(amount: float) -> int:
    return int(amount >= 500_000)
