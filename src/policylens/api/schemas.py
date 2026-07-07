"""PolicyLens API schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PolicyLoadRequest(BaseModel):
    policy_id: str = Field(..., description="Unique insurer policy ID, e.g. 'HC-2024-001'")
    policy_name: str
    wording_text: str = Field(..., description="Full policy wording as plain text")


class PolicyLoadResponse(BaseModel):
    policy_id: str
    nodes_added: int
    message: str


class PolicyInfoResponse(BaseModel):
    policy_id: str
    node_count: int
    edge_count: int


class JustificationQueryRequest(BaseModel):
    claim_id: UUID
    claim_type: str
    decision_type: str
    relevant_facts: dict[str, Any] = Field(default_factory=dict)


class ClauseReferenceResponse(BaseModel):
    node_id: str
    clause_ref: str
    text: str
    tags: list[str]


class JustificationResponse(BaseModel):
    query_id: UUID
    claim_id: UUID
    justification_text: str
    traced_clauses: list[ClauseReferenceResponse]
    confidence: str
    timestamp: datetime
