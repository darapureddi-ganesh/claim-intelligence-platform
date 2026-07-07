"""Port interfaces — the hexagonal boundary. Core domain depends only on these abstractions."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.domain.models import Claim, ClaimType, DecisionType, FNOLData, RoutingDecision, ScoringResult


# ---------------------------------------------------------------------------
# PolicyLens port (consumed by ClaimIQ + VerdictLens)
# ---------------------------------------------------------------------------

@dataclass
class JustificationQuery:
    claim_id: UUID
    claim_type: ClaimType
    decision_type: DecisionType
    relevant_facts: dict[str, Any]
    query_id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class ClauseReference:
    node_id: str
    clause_ref: str
    text: str
    tags: list[str] = field(default_factory=list)


@dataclass
class JustificationResult:
    query_id: UUID
    claim_id: UUID
    justification_text: str
    traced_clauses: list[ClauseReference]
    confidence: str  # "COVERED" | "EXCLUDED" | "CONDITIONAL" | "UNCLEAR"
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_deterministic(self) -> bool:
        """True when every clause is traceable to a graph node (no LLM generation)."""
        return bool(self.traced_clauses)


class IPolicyLensPort(ABC):
    @abstractmethod
    def justify(self, query: JustificationQuery) -> JustificationResult: ...


# ---------------------------------------------------------------------------
# Scoring port
# ---------------------------------------------------------------------------

class IScoringEngine(ABC):
    @abstractmethod
    def score(self, claim: Claim) -> ScoringResult: ...


# ---------------------------------------------------------------------------
# Routing port
# ---------------------------------------------------------------------------

class IRoutingEngine(ABC):
    @abstractmethod
    def route(self, claim: Claim, scores: ScoringResult) -> tuple[DecisionType, str, Any]: ...
    # returns: (decision_type, assigned_queue_name, reserve_suggestion)


# ---------------------------------------------------------------------------
# Document parsing port
# ---------------------------------------------------------------------------

class IDocumentParser(ABC):
    @abstractmethod
    def parse(self, raw: bytes | str, mime_type: str) -> FNOLData: ...


# ---------------------------------------------------------------------------
# Graph store port (PolicyLens internal)
# ---------------------------------------------------------------------------

class IGraphStore(ABC):
    @abstractmethod
    def add_policy(self, policy_id: str, metadata: dict[str, Any]) -> None: ...

    @abstractmethod
    def add_node(self, node_id: str, node_type: str, text: str, clause_ref: str, tags: list[str]) -> None: ...

    @abstractmethod
    def add_edge(self, from_id: str, to_id: str, relation: str) -> None: ...

    @abstractmethod
    def get_nodes_by_tags(self, tags: list[str]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_node(self, node_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def traverse(self, start_node_id: str, relation: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def policy_exists(self, policy_id: str) -> bool: ...
