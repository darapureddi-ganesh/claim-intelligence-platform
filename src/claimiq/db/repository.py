"""SQLAlchemy-backed repositories for ClaimIQ domain objects."""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.claimiq.db.models import AuditLogORM, ClaimORM, RoutingDecisionORM
from src.core.domain.models import AuditEntry, Claim, ClaimStatus, ClaimType, DecisionType, RoutingDecision


class ClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, claim: Claim) -> None:
        orm = ClaimORM(
            id=claim.id,
            policy_id=claim.policy_id,
            insured_name=claim.insured_name,
            claim_type=claim.claim_type.value,
            amount_claimed=claim.amount_claimed,
            incident_date=claim.incident_date,
            reported_date=claim.reported_date,
            raw_fnol_json={"text": claim.raw_fnol_text, **claim.metadata},
            language=claim.language,
            status=claim.status.value,
        )
        self._session.add(orm)
        await self._session.flush()

    async def update_status(self, claim_id: UUID, status: ClaimStatus) -> None:
        result = await self._session.get(ClaimORM, claim_id)
        if result:
            result.status = status.value

    async def get_by_id(self, claim_id: UUID) -> Claim | None:
        stmt = (
            select(ClaimORM)
            .options(selectinload(ClaimORM.routing_decision), selectinload(ClaimORM.audit_entries))
            .where(ClaimORM.id == claim_id)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _orm_to_claim(orm)


class RoutingDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, decision: RoutingDecision) -> None:
        orm = RoutingDecisionORM(
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
        self._session.add(orm)
        await self._session.flush()

    async def get_by_claim_id(self, claim_id: UUID) -> RoutingDecision | None:
        stmt = select(RoutingDecisionORM).where(RoutingDecisionORM.claim_id == claim_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _decision_orm_to_domain(orm)


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def save(self, entry: AuditEntry) -> None:
        orm = AuditLogORM(
            id=entry.id,
            claim_id=entry.claim_id,
            timestamp=entry.timestamp,
            action=entry.action,
            actor=entry.actor,
            details=entry.details,
            source_clause_ref=entry.source_clause_ref,
        )
        self._session.add(orm)

    async def get_by_claim_id(self, claim_id: UUID) -> list[AuditEntry]:
        stmt = select(AuditLogORM).where(AuditLogORM.claim_id == claim_id).order_by(AuditLogORM.timestamp)
        result = await self._session.execute(stmt)
        return [_audit_orm_to_domain(row) for row in result.scalars()]


# ------------------------------------------------------------------
# ORM → domain model converters
# ------------------------------------------------------------------

def _orm_to_claim(orm: ClaimORM) -> Claim:
    return Claim(
        id=orm.id,
        policy_id=orm.policy_id,
        insured_name=orm.insured_name or "",
        claim_type=ClaimType(orm.claim_type),
        amount_claimed=Decimal(str(orm.amount_claimed)),
        incident_date=orm.incident_date.date() if hasattr(orm.incident_date, "date") else orm.incident_date,
        reported_date=orm.reported_date.date() if hasattr(orm.reported_date, "date") else orm.reported_date,
        raw_fnol_text=orm.raw_fnol_json.get("text", "") if isinstance(orm.raw_fnol_json, dict) else "",
        language=orm.language,
        status=ClaimStatus(orm.status),
        metadata={k: v for k, v in (orm.raw_fnol_json or {}).items() if k != "text"},
    )


def _decision_orm_to_domain(orm: RoutingDecisionORM) -> RoutingDecision:
    return RoutingDecision(
        id=orm.id,
        claim_id=orm.claim_id,
        severity_score=orm.severity_score,
        complexity_score=orm.complexity_score,
        fraud_propensity_score=orm.fraud_propensity_score,
        decision_type=DecisionType(orm.decision_type),
        assigned_queue=orm.assigned_queue,
        reserve_suggestion=Decimal(str(orm.reserve_suggestion)),
        policylens_justification_id=orm.policylens_justification_id,
    )


def _audit_orm_to_domain(orm: AuditLogORM) -> AuditEntry:
    return AuditEntry(
        id=orm.id,
        claim_id=orm.claim_id,
        timestamp=orm.timestamp,
        action=orm.action,
        actor=orm.actor,
        details=orm.details or {},
        source_clause_ref=orm.source_clause_ref,
    )
