"""Dataclass <-> JSON-safe dict conversion for the storage backends."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from src.core.domain.models import (
    AuditEntry,
    Claim,
    ClaimStatus,
    ClaimType,
    DecisionType,
    RoutingDecision,
)
from src.core.domain.ports import ClauseReference, JustificationResult


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (UUID, Decimal)):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def claim_from_dict(d: dict[str, Any]) -> Claim:
    return Claim(
        id=UUID(d["id"]),
        policy_id=d["policy_id"],
        claim_type=ClaimType(d["claim_type"]),
        amount_claimed=Decimal(d["amount_claimed"]),
        incident_date=date.fromisoformat(d["incident_date"]),
        reported_date=date.fromisoformat(d["reported_date"]),
        raw_fnol_text=d.get("raw_fnol_text", ""),
        insured_name=d.get("insured_name", ""),
        language=d.get("language", "en"),
        status=ClaimStatus(d.get("status", "RECEIVED")),
        metadata=d.get("metadata", {}),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


def decision_from_dict(d: dict[str, Any]) -> RoutingDecision:
    return RoutingDecision(
        id=UUID(d["id"]),
        claim_id=UUID(d["claim_id"]),
        severity_score=float(d["severity_score"]),
        complexity_score=float(d["complexity_score"]),
        fraud_propensity_score=float(d["fraud_propensity_score"]),
        decision_type=DecisionType(d["decision_type"]),
        assigned_queue=d["assigned_queue"],
        reserve_suggestion=Decimal(d["reserve_suggestion"]),
        policylens_justification_id=UUID(d["policylens_justification_id"]),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


def justification_from_dict(d: dict[str, Any]) -> JustificationResult:
    return JustificationResult(
        query_id=UUID(d["query_id"]),
        claim_id=UUID(d["claim_id"]),
        justification_text=d["justification_text"],
        traced_clauses=[ClauseReference(**c) for c in d.get("traced_clauses", [])],
        confidence=d["confidence"],
        timestamp=datetime.fromisoformat(d["timestamp"]),
    )


def audit_from_dict(d: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        id=UUID(d["id"]),
        claim_id=UUID(d["claim_id"]),
        timestamp=datetime.fromisoformat(d["timestamp"]),
        action=d["action"],
        actor=d["actor"],
        details=d.get("details", {}),
        source_clause_ref=d.get("source_clause_ref"),
    )
