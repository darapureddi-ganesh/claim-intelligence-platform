"""PolicyLens knowledge graph node and edge types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    POLICY = "policy"
    SECTION = "section"
    CLAUSE = "clause"
    ENDORSEMENT = "endorsement"
    EXCLUSION = "exclusion"
    COVERAGE = "coverage"
    CONDITION = "condition"


class EdgeRelation(str, Enum):
    CONTAINS = "contains"
    MODIFIES = "modifies"
    EXCLUDES = "excludes"
    REQUIRES = "requires"
    SUPERSEDES = "supersedes"


@dataclass
class PolicyNode:
    id: str              # e.g. "pol:HC001:sec:2:clause:4a"
    node_type: NodeType
    text: str            # verbatim source policy wording
    clause_ref: str      # human-readable ref, e.g. "Section 2.4(a)"
    policy_id: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type.value,
            "text": self.text,
            "clause_ref": self.clause_ref,
            "policy_id": self.policy_id,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyNode":
        return cls(
            id=data["id"],
            node_type=NodeType(data["node_type"]),
            text=data["text"],
            clause_ref=data["clause_ref"],
            policy_id=data["policy_id"],
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PolicyEdge:
    from_id: str
    to_id: str
    relation: EdgeRelation
    metadata: dict[str, Any] = field(default_factory=dict)
