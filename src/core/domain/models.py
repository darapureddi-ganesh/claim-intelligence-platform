"""Core domain models — pure Python, no framework dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    SCORED = "SCORED"
    ROUTED = "ROUTED"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class ClaimType(str, Enum):
    MOTOR = "motor"
    HEALTH = "health"
    PROPERTY = "property"
    LIFE = "life"
    MARINE = "marine"
    OTHER = "other"


class DecisionType(str, Enum):
    ROUTE_TO_STANDARD = "route_to_standard"
    ROUTE_TO_SENIOR = "route_to_senior"
    ROUTE_TO_FRAUD_UNIT = "route_to_fraud_unit"
    FLAG_FOR_INVESTIGATION = "flag_for_investigation"
    FAST_TRACK = "fast_track"


@dataclass
class Claim:
    id: UUID
    policy_id: str
    claim_type: ClaimType
    amount_claimed: Decimal
    incident_date: date
    reported_date: date
    raw_fnol_text: str
    insured_name: str = ""
    language: str = "en"
    status: ClaimStatus = ClaimStatus.RECEIVED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def new(
        cls,
        policy_id: str,
        claim_type: ClaimType,
        amount_claimed: Decimal,
        incident_date: date,
        reported_date: date,
        raw_fnol_text: str,
        insured_name: str = "",
        language: str = "en",
        metadata: dict[str, Any] | None = None,
    ) -> "Claim":
        return cls(
            id=uuid.uuid4(),
            policy_id=policy_id,
            claim_type=claim_type,
            amount_claimed=amount_claimed,
            incident_date=incident_date,
            reported_date=reported_date,
            raw_fnol_text=raw_fnol_text,
            insured_name=insured_name,
            language=language,
            metadata=metadata or {},
        )


@dataclass
class ScoringResult:
    claim_id: UUID
    severity_score: float       # 0.0–1.0: how severe is the potential loss
    complexity_score: float     # 0.0–1.0: how complex is the claim to adjudicate
    fraud_propensity_score: float  # 0.0–1.0: fraud risk signal
    features_used: dict[str, Any] = field(default_factory=dict)
    model_version: str = "v0.1.0"

    @property
    def overall_risk(self) -> float:
        return (self.severity_score * 0.4 + self.complexity_score * 0.3 + self.fraud_propensity_score * 0.3)


@dataclass
class RoutingDecision:
    id: UUID
    claim_id: UUID
    severity_score: float
    complexity_score: float
    fraud_propensity_score: float
    decision_type: DecisionType
    assigned_queue: str
    reserve_suggestion: Decimal
    # Non-nullable: every decision must be justified — enforced at service layer
    policylens_justification_id: UUID
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def new(
        cls,
        claim_id: UUID,
        scoring: ScoringResult,
        decision_type: DecisionType,
        assigned_queue: str,
        reserve_suggestion: Decimal,
        policylens_justification_id: UUID,
    ) -> "RoutingDecision":
        return cls(
            id=uuid.uuid4(),
            claim_id=claim_id,
            severity_score=scoring.severity_score,
            complexity_score=scoring.complexity_score,
            fraud_propensity_score=scoring.fraud_propensity_score,
            decision_type=decision_type,
            assigned_queue=assigned_queue,
            reserve_suggestion=reserve_suggestion,
            policylens_justification_id=policylens_justification_id,
        )


@dataclass
class AuditEntry:
    id: UUID
    claim_id: UUID
    timestamp: datetime
    action: str
    actor: str
    details: dict[str, Any] = field(default_factory=dict)
    source_clause_ref: str | None = None

    @classmethod
    def new(
        cls,
        claim_id: UUID,
        action: str,
        actor: str,
        details: dict[str, Any] | None = None,
        source_clause_ref: str | None = None,
    ) -> "AuditEntry":
        return cls(
            id=uuid.uuid4(),
            claim_id=claim_id,
            timestamp=datetime.utcnow(),
            action=action,
            actor=actor,
            details=details or {},
            source_clause_ref=source_clause_ref,
        )


@dataclass
class FNOLData:
    """Normalised output from document/text parsing."""
    policy_id: str
    claim_type: ClaimType
    amount_claimed: Decimal
    incident_date: date
    reported_date: date
    insured_name: str
    raw_text: str
    detected_language: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)
