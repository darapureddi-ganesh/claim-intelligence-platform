"""ClaimIQ — FNOL intake and claim query endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.claimiq.api.schemas import (
    AuditEntryResponse,
    ClaimDetailResponse,
    ClaimResponse,
    FNOLSubmissionRequest,
    RoutingDecisionResponse,
)
from src.claimiq.db.repository import AuditLogRepository, ClaimRepository, RoutingDecisionRepository
from src.claimiq.db.session import get_session
from src.claimiq.dependencies import get_triage_service
from src.claimiq.services.triage import JustificationRequiredError, TriageService
from src.core.domain.models import Claim, ClaimStatus, ClaimType

router = APIRouter(prefix="/claims", tags=["ClaimIQ — Claims"])


@router.post("", response_model=ClaimDetailResponse, status_code=status.HTTP_201_CREATED)
async def submit_claim(
    request: FNOLSubmissionRequest,
    session: AsyncSession = Depends(get_session),
    triage: TriageService = Depends(get_triage_service),
):
    """
    Submit a new FNOL claim. Synchronously scores, routes, and obtains
    PolicyLens justification before returning.
    """
    claim = Claim.new(
        policy_id=request.policy_id,
        claim_type=ClaimType(request.claim_type),
        amount_claimed=request.amount_claimed,
        incident_date=request.incident_date,
        reported_date=request.reported_date,
        raw_fnol_text=request.narrative,
        insured_name=request.insured_name,
        language=request.language,
        metadata=request.metadata,
    )

    claim_repo = ClaimRepository(session)
    await claim_repo.save(claim)

    try:
        decision = await triage.process(claim)
    except JustificationRequiredError as exc:
        await claim_repo.update_status(claim.id, ClaimStatus.ERROR)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PolicyLens justification unavailable — claim saved but not routed: {exc}",
        ) from exc

    audit_repo = AuditLogRepository(session)
    audit_entries = await audit_repo.get_by_claim_id(claim.id)

    return ClaimDetailResponse(
        claim=_to_claim_response(claim, ClaimStatus.ROUTED),
        routing_decision=RoutingDecisionResponse(
            id=decision.id,
            claim_id=decision.claim_id,
            severity_score=decision.severity_score,
            complexity_score=decision.complexity_score,
            fraud_propensity_score=decision.fraud_propensity_score,
            decision_type=decision.decision_type.value,
            assigned_queue=decision.assigned_queue,
            reserve_suggestion=decision.reserve_suggestion,
            policylens_justification_id=decision.policylens_justification_id,
        ),
        audit_trail=[
            AuditEntryResponse(
                id=e.id,
                claim_id=e.claim_id,
                timestamp=e.timestamp,
                action=e.action,
                actor=e.actor,
                details=e.details,
                source_clause_ref=e.source_clause_ref,
            )
            for e in audit_entries
        ],
    )


@router.get("/{claim_id}", response_model=ClaimDetailResponse)
async def get_claim(
    claim_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Retrieve a claim with its routing decision and full audit trail."""
    claim_repo = ClaimRepository(session)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    decision_repo = RoutingDecisionRepository(session)
    decision = await decision_repo.get_by_claim_id(claim_id)

    audit_repo = AuditLogRepository(session)
    audit_entries = await audit_repo.get_by_claim_id(claim_id)

    return ClaimDetailResponse(
        claim=_to_claim_response(claim, claim.status),
        routing_decision=(
            RoutingDecisionResponse(
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
            if decision
            else None
        ),
        audit_trail=[
            AuditEntryResponse(
                id=e.id,
                claim_id=e.claim_id,
                timestamp=e.timestamp,
                action=e.action,
                actor=e.actor,
                details=e.details,
                source_clause_ref=e.source_clause_ref,
            )
            for e in audit_entries
        ],
    )


def _to_claim_response(claim: Claim, status: ClaimStatus) -> ClaimResponse:
    return ClaimResponse(
        id=claim.id,
        policy_id=claim.policy_id,
        insured_name=claim.insured_name,
        claim_type=claim.claim_type.value,
        amount_claimed=claim.amount_claimed,
        incident_date=claim.incident_date,
        reported_date=claim.reported_date,
        status=status.value,
    )
