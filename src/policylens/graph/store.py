"""NetworkX-backed policy knowledge graph store.

Pilot implementation. Conforms to IGraphStore so it can be swapped for
Neo4jGraphStore at scale without changing the reasoning engine.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import networkx as nx

from src.core.domain.ports import IGraphStore
from src.policylens.graph.models import EdgeRelation, NodeType, PolicyEdge, PolicyNode


class NetworkXGraphStore(IGraphStore):
    """
    Thread-safe in-process graph store backed by NetworkX DiGraph.
    Persists to a JSON file when a path is provided.
    """

    def __init__(self, persist_path: str | None = None) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if persist_path:
            self._load_from_disk()

    # ------------------------------------------------------------------
    # IGraphStore implementation
    # ------------------------------------------------------------------

    def add_policy(self, policy_id: str, metadata: dict[str, Any]) -> None:
        with self._lock:
            node = PolicyNode(
                id=f"pol:{policy_id}",
                node_type=NodeType.POLICY,
                text=metadata.get("name", policy_id),
                clause_ref="",
                policy_id=policy_id,
                metadata=metadata,
            )
            self._add_node(node)

    def add_node(
        self,
        node_id: str,
        node_type: str,
        text: str,
        clause_ref: str,
        tags: list[str],
        policy_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            node = PolicyNode(
                id=node_id,
                node_type=NodeType(node_type),
                text=text,
                clause_ref=clause_ref,
                policy_id=policy_id,
                tags=tags,
                metadata=metadata or {},
            )
            self._add_node(node)

    def add_edge(self, from_id: str, to_id: str, relation: str) -> None:
        with self._lock:
            self._graph.add_edge(from_id, to_id, relation=relation)
            self._persist()

    def get_nodes_by_tags(self, tags: list[str]) -> list[dict[str, Any]]:
        with self._lock:
            tag_set = set(tags)
            results = []
            for node_id, data in self._graph.nodes(data=True):
                node_tags = set(data.get("tags", []))
                if tag_set & node_tags:
                    results.append({"id": node_id, **data})
            return results

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._graph.has_node(node_id):
                data = dict(self._graph.nodes[node_id])
                data["id"] = node_id
                return data
            return None

    def traverse(self, start_node_id: str, relation: str | None = None) -> list[dict[str, Any]]:
        """Return all nodes reachable from start_node_id, optionally filtered by edge relation."""
        with self._lock:
            if not self._graph.has_node(start_node_id):
                return []
            visited = []
            for node_id in nx.descendants(self._graph, start_node_id):
                if relation is not None:
                    # Check if any path edge has the matching relation
                    edges_to_node = self._graph.in_edges(node_id, data=True)
                    if not any(d.get("relation") == relation for _, _, d in edges_to_node):
                        continue
                data = dict(self._graph.nodes[node_id])
                data["id"] = node_id
                visited.append(data)
            return visited

    def policy_exists(self, policy_id: str) -> bool:
        with self._lock:
            return self._graph.has_node(f"pol:{policy_id}")

    # ------------------------------------------------------------------
    # Extra query helpers
    # ------------------------------------------------------------------

    def get_all_nodes(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"id": n, **d} for n, d in self._graph.nodes(data=True)]

    def get_exclusion_nodes(self, policy_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for node_id, data in self._graph.nodes(data=True):
                if data.get("node_type") == NodeType.EXCLUSION.value:
                    if policy_id is None or data.get("policy_id") == policy_id:
                        results.append({"id": node_id, **data})
            return results

    def get_coverage_nodes(self, policy_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for node_id, data in self._graph.nodes(data=True):
                if data.get("node_type") == NodeType.COVERAGE.value:
                    if policy_id is None or data.get("policy_id") == policy_id:
                        results.append({"id": node_id, **data})
            return results

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _add_node(self, node: PolicyNode) -> None:
        self._graph.add_node(
            node.id,
            node_type=node.node_type.value,
            text=node.text,
            clause_ref=node.clause_ref,
            policy_id=node.policy_id,
            tags=node.tags,
            metadata=node.metadata,
        )
        self._persist()

    def _persist(self) -> None:
        if not self._persist_path:
            return
        data = nx.node_link_data(self._graph)
        with open(self._persist_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_from_disk(self) -> None:
        import os
        if not os.path.exists(self._persist_path):
            return
        with open(self._persist_path) as f:
            data = json.load(f)
        self._graph = nx.node_link_graph(data)
