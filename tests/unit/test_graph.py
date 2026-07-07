"""Unit tests for the NetworkX graph store."""

from __future__ import annotations

import pytest

from src.policylens.graph.models import NodeType
from src.policylens.graph.store import NetworkXGraphStore


@pytest.fixture
def graph() -> NetworkXGraphStore:
    return NetworkXGraphStore(persist_path=None)


def test_add_and_retrieve_policy(graph):
    graph.add_policy("HC-001", {"name": "Test Health Policy"})
    assert graph.policy_exists("HC-001")
    node = graph.get_node("pol:HC-001")
    assert node is not None
    assert node["node_type"] == NodeType.POLICY.value


def test_add_clause_node(graph):
    graph.add_policy("HC-001", {"name": "Test"})
    graph.add_node(
        node_id="pol:HC-001:clause:1",
        node_type=NodeType.CLAUSE.value,
        text="Coverage for hospitalization",
        clause_ref="Section 2.1",
        tags=["health", "coverage"],
        policy_id="HC-001",
    )
    node = graph.get_node("pol:HC-001:clause:1")
    assert node["text"] == "Coverage for hospitalization"
    assert "health" in node["tags"]


def test_add_edge_and_traverse(graph):
    graph.add_policy("HC-001", {"name": "Test"})
    graph.add_node("pol:HC-001:clause:1", NodeType.CLAUSE.value, "Clause 1", "1", ["health"], "HC-001")
    graph.add_node("pol:HC-001:clause:2", NodeType.EXCLUSION.value, "Exclusion", "2", ["health"], "HC-001")
    graph.add_edge("pol:HC-001", "pol:HC-001:clause:1", "contains")
    graph.add_edge("pol:HC-001", "pol:HC-001:clause:2", "excludes")

    reachable = graph.traverse("pol:HC-001")
    ids = [n["id"] for n in reachable]
    assert "pol:HC-001:clause:1" in ids
    assert "pol:HC-001:clause:2" in ids


def test_get_nodes_by_tags(graph):
    graph.add_policy("HC-001", {"name": "Test"})
    graph.add_node("pol:HC-001:clause:1", NodeType.COVERAGE.value, "Health coverage", "2.1", ["health", "hospitalization"], "HC-001")
    graph.add_node("pol:HC-001:clause:2", NodeType.EXCLUSION.value, "Motor exclusion", "8.1", ["motor"], "HC-001")

    results = graph.get_nodes_by_tags(["health"])
    ids = [n["id"] for n in results]
    assert "pol:HC-001:clause:1" in ids
    assert "pol:HC-001:clause:2" not in ids


def test_exclusion_nodes_query(graph):
    graph.add_policy("HC-001", {"name": "Test"})
    graph.add_node("pol:HC-001:excl:1", NodeType.EXCLUSION.value, "Pre-existing excluded", "3.1", ["pre-existing"], "HC-001")
    graph.add_node("pol:HC-001:cov:1", NodeType.COVERAGE.value, "Hospitalization covered", "2.1", ["health"], "HC-001")

    exclusions = graph.get_exclusion_nodes("HC-001")
    assert len(exclusions) == 1
    assert exclusions[0]["id"] == "pol:HC-001:excl:1"


def test_node_count(graph):
    assert graph.node_count() == 0
    graph.add_policy("HC-001", {"name": "Test"})
    assert graph.node_count() == 1
    graph.add_node("pol:HC-001:clause:1", NodeType.CLAUSE.value, "text", "ref", [], "HC-001")
    assert graph.node_count() == 2


def test_policy_not_exists(graph):
    assert not graph.policy_exists("NONEXISTENT-999")
