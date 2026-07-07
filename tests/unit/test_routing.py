"""Unit tests for the routing engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.claimiq.config import Settings
from src.claimiq.routing.engine import QUEUE_FRAUD, QUEUE_SENIOR, QUEUE_FAST_TRACK, QUEUE_STANDARD, RuleBasedRoutingEngine
from src.core.domain.models import Claim, ClaimType, DecisionType, ScoringResult


def make_scores(severity=0.5, complexity=0.5, fraud=0.1, claim_id=None) -> ScoringResult:
    import uuid
    return ScoringResult(
        claim_id=claim_id or uuid.uuid4(),
        severity_score=severity,
        complexity_score=complexity,
        fraud_propensity_score=fraud,
    )


def make_claim(amount=Decimal("100000"), claim_type=ClaimType.HEALTH) -> Claim:
    return Claim.new(
        policy_id="TEST-001",
        claim_type=claim_type,
        amount_claimed=amount,
        incident_date=date(2024, 1, 1),
        reported_date=date(2024, 1, 3),
        raw_fnol_text="test",
    )


def test_fraud_routes_to_fraud_unit():
    engine = RuleBasedRoutingEngine()
    claim = make_claim()
    scores = make_scores(fraud=0.75)
    decision_type, queue, _ = engine.route(claim, scores)
    assert decision_type == DecisionType.ROUTE_TO_FRAUD_UNIT
    assert queue == QUEUE_FRAUD


def test_high_risk_routes_to_senior():
    engine = RuleBasedRoutingEngine()
    claim = make_claim()
    # overall_risk = 0.9*0.4 + 0.9*0.3 + 0.1*0.3 = 0.36+0.27+0.03 = 0.66 > threshold 0.65
    scores = make_scores(severity=0.9, complexity=0.9, fraud=0.1)
    decision_type, queue, _ = engine.route(claim, scores)
    assert decision_type == DecisionType.ROUTE_TO_SENIOR
    assert queue == QUEUE_SENIOR


def test_low_risk_fast_track():
    engine = RuleBasedRoutingEngine()
    claim = make_claim()
    scores = make_scores(severity=0.1, complexity=0.1, fraud=0.05)
    decision_type, queue, _ = engine.route(claim, scores)
    assert decision_type == DecisionType.FAST_TRACK
    assert queue == QUEUE_FAST_TRACK


def test_standard_routing():
    engine = RuleBasedRoutingEngine()
    claim = make_claim()
    scores = make_scores(severity=0.4, complexity=0.4, fraud=0.1)
    decision_type, queue, _ = engine.route(claim, scores)
    assert decision_type == DecisionType.ROUTE_TO_STANDARD
    assert queue == QUEUE_STANDARD


def test_reserve_suggestion_positive():
    engine = RuleBasedRoutingEngine()
    claim = make_claim(amount=Decimal("200000"))
    scores = make_scores(severity=0.5, complexity=0.5)
    _, _, reserve = engine.route(claim, scores)
    assert reserve > 0
    assert isinstance(reserve, Decimal)


def test_fraud_priority_over_high_risk():
    """Fraud detection takes priority over severity-based routing."""
    engine = RuleBasedRoutingEngine()
    claim = make_claim()
    scores = make_scores(severity=0.9, complexity=0.9, fraud=0.8)
    decision_type, queue, _ = engine.route(claim, scores)
    assert decision_type == DecisionType.ROUTE_TO_FRAUD_UNIT
