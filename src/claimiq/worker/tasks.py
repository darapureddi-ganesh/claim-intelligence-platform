"""
RQ worker tasks for async FNOL processing.

The POST /claims endpoint can optionally enqueue processing instead of
running it synchronously for high-throughput scenarios (e.g. catastrophe
claims spikes).
"""

from __future__ import annotations

import uuid
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


def process_fnol_async(claim_id: str) -> dict:
    """
    RQ task: re-process an already-saved claim through the triage pipeline.

    Uses a synchronous DB session (psycopg2) since RQ workers are not async.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.claimiq.config import get_settings
    from src.claimiq.adapters.policylens_http import PolicyLensHTTPAdapter
    from src.claimiq.routing.engine import RuleBasedRoutingEngine
    from src.claimiq.scoring.engine import XGBoostScoringEngine

    settings = get_settings()

    # Sync engine for worker context
    sync_engine = create_engine(settings.database_sync_url)
    SyncSession = sessionmaker(bind=sync_engine)

    with SyncSession() as session:
        from src.claimiq.db.repository import (
            AuditLogRepository, ClaimRepository, RoutingDecisionRepository
        )
        from src.claimiq.services.triage import TriageService

        claim_repo = ClaimRepository.__new__(ClaimRepository)
        claim_repo._session = session  # inject sync session (type: ignore)

        # Fetch the claim from DB (sync path)
        from sqlalchemy import select
        from src.claimiq.db.models import ClaimORM
        from src.claimiq.db.repository import _orm_to_claim

        orm = session.get(ClaimORM, uuid.UUID(claim_id))
        if orm is None:
            logger.error("worker_claim_not_found", claim_id=claim_id)
            return {"status": "error", "claim_id": claim_id, "reason": "not_found"}

        claim = _orm_to_claim(orm)

        scoring = XGBoostScoringEngine()
        routing = RuleBasedRoutingEngine()
        policylens = PolicyLensHTTPAdapter(base_url=settings.policylens_url)

        scores = scoring.score(claim)
        decision_type, queue, reserve = routing.route(claim, scores)
        query = __import__("src.core.domain.ports", fromlist=["JustificationQuery"]).JustificationQuery(
            claim_id=claim.id,
            claim_type=claim.claim_type,
            decision_type=decision_type,
            relevant_facts={"amount_claimed": str(claim.amount_claimed), "claim_type": claim.claim_type.value},
        )
        justification = policylens.justify(query)

        from src.core.domain.models import RoutingDecision
        decision = RoutingDecision.new(
            claim_id=claim.id,
            scoring=scores,
            decision_type=decision_type,
            assigned_queue=queue,
            reserve_suggestion=reserve,
            policylens_justification_id=justification.query_id,
        )
        from src.claimiq.db.models import RoutingDecisionORM
        orm_decision = RoutingDecisionORM(
            id=decision.id,
            claim_id=decision.claim_id,
            severity_score=decision.severity_score,
            complexity_score=decision.complexity_score,
            fraud_propensity_score=decision.fraud_propensity_score,
            decision_type=decision.decision_type.value,
            assigned_queue=decision.assigned_queue,
            reserve_suggestion=decision.reserve_suggestion,
            policylens_justification_id=decision.policylens_justification_id,
        )
        session.add(orm_decision)
        orm.status = "ROUTED"
        session.commit()

    logger.info("worker_triage_complete", claim_id=claim_id)
    return {"status": "routed", "claim_id": claim_id, "queue": queue}
