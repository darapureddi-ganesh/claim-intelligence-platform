"""FastAPI dependency injection for ClaimIQ."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.claimiq.adapters.policylens_http import PolicyLensHTTPAdapter
from src.claimiq.config import get_settings
from src.claimiq.db.repository import AuditLogRepository, ClaimRepository, RoutingDecisionRepository
from src.claimiq.db.session import get_session
from src.claimiq.routing.engine import RuleBasedRoutingEngine
from src.claimiq.scoring.engine import XGBoostScoringEngine
from src.claimiq.services.triage import TriageService


@lru_cache(maxsize=1)
def _get_scoring_engine() -> XGBoostScoringEngine:
    return XGBoostScoringEngine()


@lru_cache(maxsize=1)
def _get_routing_engine() -> RuleBasedRoutingEngine:
    return RuleBasedRoutingEngine()


def _get_policylens_adapter() -> PolicyLensHTTPAdapter:
    settings = get_settings()
    return PolicyLensHTTPAdapter(base_url=settings.policylens_url)


async def get_triage_service(
    session: AsyncSession = Depends(get_session),
) -> TriageService:
    return TriageService(
        scoring_engine=_get_scoring_engine(),
        routing_engine=_get_routing_engine(),
        policylens=_get_policylens_adapter(),
        claim_repo=ClaimRepository(session),
        decision_repo=RoutingDecisionRepository(session),
        audit_repo=AuditLogRepository(session),
    )
