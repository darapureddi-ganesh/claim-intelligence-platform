"""ClaimIQ API schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FNOLSubmissionRequest(BaseModel):
    policy_id: str
    insured_name: str = ""
    claim_type: str
    amount_claimed: Decimal = Field(gt=0)
    incident_date: date
    reported_date: date
    narrative: str = ""
    language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimResponse(BaseModel):
    id: UUID
    policy_id: str
    insured_name: str
    claim_type: str
    amount_claimed: Decimal
    incident_date: date
    reported_date: date
    status: str
    created_at: datetime | None = None


class RoutingDecisionResponse(BaseModel):
    id: UUID
    claim_id: UUID
    severity_score: float
    complexity_score: float
    fraud_propensity_score: float
    decision_type: str
    assigned_queue: str
    reserve_suggestion: Decimal
    policylens_justification_id: UUID
    created_at: datetime | None = None


class AuditEntryResponse(BaseModel):
    id: UUID
    claim_id: UUID
    timestamp: datetime
    action: str
    actor: str
    details: dict[str, Any]
    source_clause_ref: str | None


class ClaimDetailResponse(BaseModel):
    claim: ClaimResponse
    routing_decision: RoutingDecisionResponse | None = None
    audit_trail: list[AuditEntryResponse] = Field(default_factory=list)


class AsyncSubmissionResponse(BaseModel):
    claim_id: UUID
    status: str
    message: str
