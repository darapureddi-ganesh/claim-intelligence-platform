"""
End-to-end triage flow test: FNOL in → routing decision with PolicyLens justification out.

Tests the core Phase 1c integration without a real database — uses in-memory
repositories and a direct PolicyLens engine (not HTTP).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.claimiq.routing.engine import RuleBasedRoutingEngine
from src.claimiq.scoring.engine import XGBoostScoringEngine
from src.claimiq.services.triage import JustificationRequiredError, TriageService
from src.core.audit import AuditService, InMemoryAuditRepository
from src.core.domain.models import Claim, ClaimType, RoutingDecision
from src.core.domain.ports import (
    ClauseReference,
    IPolicyLensPort,
    JustificationQuery,
    JustificationResult,
)
from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from src.policylens.reasoning.engine import RuleBasedReasoningEngine


# ---------------------------------------------------------------------------
# In-memory repositories for tests
# ---------------------------------------------------------------------------

class InMemoryClaimRepository:
    def __init__(self): self._claims = {}
    async def save(self, claim): self._claims[claim.id] = claim
    async def update_status(self, claim_id, status):
        if claim_id in self._claims:
            self._claims[claim_id].status = status
    async def get_by_id(self, claim_id): return self._claims.get(claim_id)


class InMemoryDecisionRepository:
    def __init__(self): self._decisions = {}
    async def save(self, decision): self._decisions[decision.claim_id] = decision
    async def get_by_claim_id(self, claim_id): return self._decisions.get(claim_id)


# ---------------------------------------------------------------------------
# PolicyLens in-process adapter (bypasses HTTP for unit-speed integration test)
# ---------------------------------------------------------------------------

class DirectPolicyLensAdapter(IPolicyLensPort):
    """Wraps the reasoning engine directly — no HTTP for test speed."""
    def __init__(self, engine: RuleBasedReasoningEngine):
        self._engine = engine

    def justify(self, query: JustificationQuery) -> JustificationResult:
        return self._engine.justify(query)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def policy_graph() -> NetworkXGraphStore:
    graph = NetworkXGraphStore(persist_path=None)
    loader = PolicyLoader(graph=graph)
    with open("tests/fixtures/sample_policy.txt") as f:
        text = f.read()
    loader.load("HC-STD-2024", "Standard Health Policy", text)
    return graph


@pytest.fixture
def triage_service(policy_graph) -> TriageService:
    audit_repo = InMemoryAuditRepository()
    return TriageService(
        scoring_engine=XGBoostScoringEngine(),
        routing_engine=RuleBasedRoutingEngine(),
        policylens=DirectPolicyLensAdapter(RuleBasedReasoningEngine(policy_graph)),
        claim_repo=InMemoryClaimRepository(),
        decision_repo=InMemoryDecisionRepository(),
        audit_repo=audit_repo,
    )


def make_claim(**kwargs) -> Claim:
    defaults = dict(
        policy_id="HC-STD-2024",
        claim_type=ClaimType.HEALTH,
        amount_claimed=Decimal("150000"),
        incident_date=date(2024, 3, 1),
        reported_date=date(2024, 3, 3),
        raw_fnol_text="Hospitalization claim for surgery.",
    )
    defaults.update(kwargs)
    return Claim.new(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_triage_produces_decision_with_justification(triage_service):
    claim = make_claim()
    decision = await triage_service.process(claim)

    assert isinstance(decision, RoutingDecision)
    assert decision.claim_id == claim.id
    # Non-negotiable: justification must be present
    assert decision.policylens_justification_id is not None
    assert decision.severity_score >= 0.0
    assert decision.reserve_suggestion > 0


@pytest.mark.asyncio
async def test_triage_aborts_when_policylens_unavailable():
    """If PolicyLens fails, the decision must NOT be persisted."""
    class BrokenPolicyLens(IPolicyLensPort):
        def justify(self, query): raise RuntimeError("PolicyLens unreachable")

    claim_repo = InMemoryClaimRepository()
    decision_repo = InMemoryDecisionRepository()

    service = TriageService(
        scoring_engine=XGBoostScoringEngine(),
        routing_engine=RuleBasedRoutingEngine(),
        policylens=BrokenPolicyLens(),
        claim_repo=claim_repo,
        decision_repo=decision_repo,
        audit_repo=InMemoryAuditRepository(),
    )
    claim = make_claim()
    with pytest.raises(JustificationRequiredError):
        await service.process(claim)

    # Decision must not be in the repository
    saved = await decision_repo.get_by_claim_id(claim.id)
    assert saved is None


@pytest.mark.asyncio
async def test_high_value_claim_routes_to_senior(triage_service):
    claim = make_claim(amount_claimed=Decimal("2000000"))
    decision = await triage_service.process(claim)
    # High-value or fraud-flagged — either is valid depending on synthetic model scores
    assert decision.assigned_queue in ("senior-adjuster", "fraud-investigation")


@pytest.mark.asyncio
async def test_small_claim_routes_to_fast_track_or_standard(triage_service):
    claim = make_claim(amount_claimed=Decimal("8000"))
    decision = await triage_service.process(claim)
    assert decision.assigned_queue in ("fast-track", "standard")


@pytest.mark.asyncio
async def test_audit_trail_contains_policylens_entry(triage_service, policy_graph):
    audit_repo = InMemoryAuditRepository()
    service = TriageService(
        scoring_engine=XGBoostScoringEngine(),
        routing_engine=RuleBasedRoutingEngine(),
        policylens=DirectPolicyLensAdapter(RuleBasedReasoningEngine(policy_graph)),
        claim_repo=InMemoryClaimRepository(),
        decision_repo=InMemoryDecisionRepository(),
        audit_repo=audit_repo,
    )
    claim = make_claim()
    await service.process(claim)

    actions = [e.action for e in audit_repo.all()]
    assert "SCORED" in actions
    assert "ROUTING_DETERMINED" in actions
    assert "POLICYLENS_QUERIED" in actions
    assert "DECISION_PERSISTED" in actions


@pytest.mark.asyncio
async def test_reserve_suggestion_is_positive(triage_service):
    claim = make_claim(amount_claimed=Decimal("300000"))
    decision = await triage_service.process(claim)
    assert decision.reserve_suggestion > Decimal("0")
