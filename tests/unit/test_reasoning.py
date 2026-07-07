"""Unit tests for the PolicyLens rule-based reasoning engine."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from src.core.domain.models import ClaimType, DecisionType
from src.core.domain.ports import JustificationQuery
from src.policylens.graph.models import NodeType
from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from src.policylens.reasoning.engine import RuleBasedReasoningEngine


@pytest.fixture
def populated_graph() -> NetworkXGraphStore:
    """Graph pre-loaded with the sample policy fixture."""
    graph = NetworkXGraphStore(persist_path=None)
    loader = PolicyLoader(graph=graph)
    with open("tests/fixtures/sample_policy.txt") as f:
        policy_text = f.read()
    loader.load("HC-STD-2024", "Standard Health Policy", policy_text)
    return graph


@pytest.fixture
def engine(populated_graph) -> RuleBasedReasoningEngine:
    return RuleBasedReasoningEngine(graph=populated_graph)


def make_query(claim_type=ClaimType.HEALTH, decision_type=DecisionType.ROUTE_TO_STANDARD, facts=None) -> JustificationQuery:
    return JustificationQuery(
        claim_id=uuid.uuid4(),
        claim_type=claim_type,
        decision_type=decision_type,
        relevant_facts=facts or {"amount_claimed": "100000", "claim_type": claim_type.value},
    )


def test_justification_returns_result(engine):
    query = make_query()
    result = engine.justify(query)
    assert result.justification_text
    assert result.confidence in ("COVERED", "EXCLUDED", "CONDITIONAL", "UNCLEAR")
    assert result.query_id is not None


def test_pre_existing_claim_excluded(engine):
    query = make_query(
        claim_type=ClaimType.HEALTH,
        decision_type=DecisionType.ROUTE_TO_STANDARD,
        facts={
            "amount_claimed": "50000",
            "claim_type": "health",
            "pre_existing_condition": True,
        },
    )
    result = engine.justify(query)
    assert result.confidence == "EXCLUDED"
    assert len(result.traced_clauses) > 0


def test_high_value_routes_to_senior_with_justification(engine):
    query = make_query(
        claim_type=ClaimType.HEALTH,
        decision_type=DecisionType.ROUTE_TO_SENIOR,
        facts={
            "amount_claimed": "750000",
            "claim_type": "health",
            "severity_score": 0.8,
            "fraud_propensity_score": 0.1,
            # Explicitly no exclusion triggers
            "pre_existing_condition": False,
            "within_waiting_period": False,
        },
    )
    result = engine.justify(query)
    assert result.confidence in ("COVERED", "CONDITIONAL", "UNCLEAR")
    assert "Route To Senior" in result.justification_text


def test_fraud_query_returns_conditional(engine):
    query = make_query(
        claim_type=ClaimType.MOTOR,
        decision_type=DecisionType.ROUTE_TO_FRAUD_UNIT,
        facts={
            "amount_claimed": "200000",
            "claim_type": "motor",
            "fraud_propensity_score": 0.75,
        },
    )
    result = engine.justify(query)
    assert result.confidence == "CONDITIONAL"


def test_justification_is_deterministic(engine):
    """Same query → same result (no LLM randomness)."""
    query_id = uuid.uuid4()
    query = JustificationQuery(
        claim_id=uuid.uuid4(),
        claim_type=ClaimType.HEALTH,
        decision_type=DecisionType.ROUTE_TO_STANDARD,
        relevant_facts={"amount_claimed": "100000", "claim_type": "health"},
        query_id=query_id,
    )
    result1 = engine.justify(query)
    query2 = JustificationQuery(
        claim_id=query.claim_id,
        claim_type=ClaimType.HEALTH,
        decision_type=DecisionType.ROUTE_TO_STANDARD,
        relevant_facts={"amount_claimed": "100000", "claim_type": "health"},
        query_id=query_id,
    )
    result2 = engine.justify(query2)
    assert result1.justification_text == result2.justification_text
    assert result1.confidence == result2.confidence


def test_policy_loader_adds_nodes(populated_graph):
    assert populated_graph.node_count() > 5
    exclusions = populated_graph.get_exclusion_nodes()
    assert len(exclusions) > 0


def test_traced_clauses_have_clause_refs(engine):
    query = make_query(
        facts={"amount_claimed": "300000", "claim_type": "health", "pre_existing_condition": True}
    )
    result = engine.justify(query)
    if result.traced_clauses:
        for clause in result.traced_clauses:
            assert clause.node_id
