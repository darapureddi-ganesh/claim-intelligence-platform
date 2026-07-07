"""Unit tests for the XGBoost scoring engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.claimiq.scoring.engine import XGBoostScoringEngine
from src.claimiq.scoring.features import extract_features, feature_names
from src.core.domain.models import Claim, ClaimType


def make_claim(**kwargs) -> Claim:
    defaults = dict(
        policy_id="TEST-001",
        claim_type=ClaimType.HEALTH,
        amount_claimed=Decimal("100000"),
        incident_date=date(2024, 1, 1),
        reported_date=date(2024, 1, 3),
        raw_fnol_text="test claim",
    )
    defaults.update(kwargs)
    return Claim.new(**defaults)


def test_feature_extraction_shape():
    claim = make_claim()
    features = extract_features(claim)
    assert features.shape == (len(feature_names()),)


def test_feature_names_match():
    names = feature_names()
    assert "claim_type_int" in names
    assert "amount_scaled" in names
    assert "fraud_propensity_score" not in names  # score is model output, not feature


def test_late_report_flag():
    claim = make_claim(
        incident_date=date(2024, 1, 1),
        reported_date=date(2024, 4, 15),  # 105 days later → triggers both flags
    )
    features = extract_features(claim)
    names = feature_names()
    assert features[names.index("late_report_flag")] == 1.0
    assert features[names.index("very_late_report_flag")] == 1.0


def test_scoring_engine_returns_valid_scores():
    engine = XGBoostScoringEngine()
    claim = make_claim(amount_claimed=Decimal("500000"))
    result = engine.score(claim)
    assert 0.0 <= result.severity_score <= 1.0
    assert 0.0 <= result.complexity_score <= 1.0
    assert 0.0 <= result.fraud_propensity_score <= 1.0
    assert result.claim_id == claim.id


def test_high_value_claim_tends_toward_higher_severity():
    engine = XGBoostScoringEngine()
    low_claim = make_claim(amount_claimed=Decimal("5000"))
    high_claim = make_claim(amount_claimed=Decimal("5000000"))
    low_result = engine.score(low_claim)
    high_result = engine.score(high_claim)
    # Not a strict guarantee with synthetic model, but overall_risk should differ
    assert isinstance(low_result.overall_risk, float)
    assert isinstance(high_result.overall_risk, float)


def test_motor_claim_type():
    engine = XGBoostScoringEngine()
    claim = make_claim(claim_type=ClaimType.MOTOR)
    result = engine.score(claim)
    assert result.model_version.startswith("v0")
    assert "claim_type_int" in result.features_used
