"""
TriageService — orchestrates the full FNOL-to-decision pipeline.

Non-negotiable invariants enforced here:
1. Every routing decision MUST have a PolicyLens justification_id before it is persisted.
2. Every step is logged to the audit trail with claim_id + timestamp.
3. If PolicyLens is unavailable, the decision is NOT persisted (fail-safe).
"""

from __future__ import annotations

import structlog

from src.claimiq.db.repository import AuditLogRepository, ClaimRepository, RoutingDecisionRepository
from src.core.audit import AuditService
from src.core.domain.models import Claim, ClaimStatus, RoutingDecision
from src.core.domain.ports import (
    IPolicyLensPort,
    IRoutingEngine,
    IScoringEngine,
    JustificationQuery,
)

logger = structlog.get_logger(__name__)


class JustificationRequiredError(RuntimeError):
    """Raised when PolicyLens justification cannot be obtained. Decision is not persisted."""


class TriageService:
    def __init__(
        self,
        scoring_engine: IScoringEngine,
        routing_engine: IRoutingEngine,
        policylens: IPolicyLensPort,
        claim_repo: ClaimRepository,
        decision_repo: RoutingDecisionRepository,
        audit_repo: AuditLogRepository,
    ) -> None:
        self._scoring = scoring_engine
        self._routing = routing_engine
        self._policylens = policylens
        self._claim_repo = claim_repo
        self._decision_repo = decision_repo
        self._audit = AuditService(audit_repo)

    async def process(self, claim: Claim) -> RoutingDecision:
        """
        Full triage pipeline:
        1. Score the claim
        2. Determine routing + reserve suggestion
        3. Request PolicyLens justification (REQUIRED)
        4. Persist decision + audit trail
        """
        # Step 1 — Scoring
        scores = self._scoring.score(claim)
        self._audit.log(
            claim_id=claim.id,
            action="SCORED",
            actor="claimiq.scoring",
            details={
                "severity": scores.severity_score,
                "complexity": scores.complexity_score,
                "fraud": scores.fraud_propensity_score,
                "model_version": scores.model_version,
            },
        )

        # Step 2 — Routing
        decision_type, queue, reserve = self._routing.route(claim, scores)
        self._audit.log(
            claim_id=claim.id,
            action="ROUTING_DETERMINED",
            actor="claimiq.routing",
            details={"decision_type": decision_type.value, "queue": queue, "reserve": str(reserve)},
        )

        # Step 3 — PolicyLens justification (NON-NEGOTIABLE)
        query = JustificationQuery(
            claim_id=claim.id,
            claim_type=claim.claim_type,
            decision_type=decision_type,
            relevant_facts={
                "claim_type": claim.claim_type.value,
                "amount_claimed": str(claim.amount_claimed),
                "severity_score": scores.severity_score,
                "complexity_score": scores.complexity_score,
                "fraud_propensity_score": scores.fraud_propensity_score,
                "incident_age_days": (claim.reported_date - claim.incident_date).days,
                **claim.metadata,
            },
        )
        try:
            justification = self._policylens.justify(query)
        except Exception as exc:
            self._audit.log(
                claim_id=claim.id,
                action="POLICYLENS_FAILED",
                actor="claimiq.triage",
                details={"error": str(exc)},
            )
            raise JustificationRequiredError(
                f"PolicyLens justification failed for claim {claim.id}: {exc}"
            ) from exc

        self._audit.log(
            claim_id=claim.id,
            action="POLICYLENS_QUERIED",
            actor="claimiq.triage",
            details={
                "justification_id": str(justification.query_id),
                "confidence": justification.confidence,
                "clauses": len(justification.traced_clauses),
            },
            source_clause_ref=", ".join(c.clause_ref for c in justification.traced_clauses),
        )

        # Step 4 — Build and persist decision
        routing_decision = RoutingDecision.new(
            claim_id=claim.id,
            scoring=scores,
            decision_type=decision_type,
            assigned_queue=queue,
            reserve_suggestion=reserve,
            policylens_justification_id=justification.query_id,
        )
        await self._decision_repo.save(routing_decision)
        await self._claim_repo.update_status(claim.id, ClaimStatus.ROUTED)

        self._audit.log(
            claim_id=claim.id,
            action="DECISION_PERSISTED",
            actor="claimiq.triage",
            details={"decision_id": str(routing_decision.id), "queue": queue},
        )

        logger.info(
            "triage_complete",
            claim_id=str(claim.id),
            decision_type=decision_type.value,
            queue=queue,
            justification_id=str(justification.query_id),
        )
        return routing_decision
