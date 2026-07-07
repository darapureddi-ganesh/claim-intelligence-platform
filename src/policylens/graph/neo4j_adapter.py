"""
Neo4j graph store adapter — migration path stub.

Raises NotImplementedError on every method. Swap in for NetworkXGraphStore
when scaling to multi-tenant production. The interface is identical so the
reasoning engine requires zero changes.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.ports import IGraphStore


class Neo4jGraphStore(IGraphStore):
    """Production-scale graph store backed by Neo4j. Not implemented for pilot."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        raise NotImplementedError(
            "Neo4j adapter is not yet implemented. "
            "Use NetworkXGraphStore for the pilot deployment. "
            "See TRD Section 7 for migration guidance."
        )

    def add_policy(self, policy_id: str, metadata: dict[str, Any]) -> None:
        raise NotImplementedError

    def add_node(self, node_id: str, node_type: str, text: str, clause_ref: str, tags: list[str], **kwargs: Any) -> None:
        raise NotImplementedError

    def add_edge(self, from_id: str, to_id: str, relation: str) -> None:
        raise NotImplementedError

    def get_nodes_by_tags(self, tags: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def traverse(self, start_node_id: str, relation: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def policy_exists(self, policy_id: str) -> bool:
        raise NotImplementedError
