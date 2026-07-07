"""Integration tests for the PolicyLens REST API."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.policylens.dependencies import get_graph_store, get_policy_loader, get_reasoning_engine
from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from src.policylens.nlp.extractor import PolicyClauseExtractor
from src.policylens.reasoning.engine import RuleBasedReasoningEngine
from src.policylens.main import create_app


def make_test_app() -> tuple:
    """Create a fresh app + in-memory graph for each test (no disk persistence)."""
    graph = NetworkXGraphStore(persist_path=None)
    app = create_app()
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_policy_loader] = lambda: PolicyLoader(graph=graph, extractor=PolicyClauseExtractor())
    app.dependency_overrides[get_reasoning_engine] = lambda: RuleBasedReasoningEngine(graph=graph)
    return app, graph


@pytest.fixture
def client_and_graph():
    app, graph = make_test_app()
    return TestClient(app), graph


@pytest.fixture
def client(client_and_graph):
    return client_and_graph[0]


@pytest.fixture
def loaded_policy(client_and_graph) -> str:
    c, _ = client_and_graph
    with open("tests/fixtures/sample_policy.txt") as f:
        text = f.read()
    response = c.post("/policies", json={
        "policy_id": "HC-TEST-001",
        "policy_name": "Test Health Policy",
        "wording_text": text,
    })
    assert response.status_code == 201
    return "HC-TEST-001"


@pytest.fixture
def loaded_client(client_and_graph, loaded_policy):
    """Client whose graph already has the sample policy loaded."""
    return client_and_graph[0]


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "policylens"


def test_load_policy(client):
    with open("tests/fixtures/sample_policy.txt") as f:
        text = f.read()
    response = client.post("/policies", json={
        "policy_id": "HC-TEST-002",
        "policy_name": "Test Policy",
        "wording_text": text,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["policy_id"] == "HC-TEST-002"
    assert data["nodes_added"] > 0


def test_duplicate_policy_returns_409(client):
    with open("tests/fixtures/sample_policy.txt") as f:
        text = f.read()
    payload = {"policy_id": "HC-DUP-001", "policy_name": "Dup", "wording_text": text}
    client.post("/policies", json=payload)
    response = client.post("/policies", json=payload)
    assert response.status_code == 409


def test_get_policy_info(loaded_client, loaded_policy):
    response = loaded_client.get(f"/policies/{loaded_policy}")
    assert response.status_code == 200
    data = response.json()
    assert data["node_count"] > 0


def test_get_nonexistent_policy_returns_404(client):
    response = client.get("/policies/NONEXISTENT-999")
    assert response.status_code == 404


def test_query_justification(loaded_client, loaded_policy):
    response = loaded_client.post("/query", json={
        "claim_id": str(uuid.uuid4()),
        "claim_type": "health",
        "decision_type": "route_to_standard",
        "relevant_facts": {"amount_claimed": "100000", "claim_type": "health"},
    })
    assert response.status_code == 200
    data = response.json()
    assert data["justification_text"]
    assert data["confidence"] in ("COVERED", "EXCLUDED", "CONDITIONAL", "UNCLEAR")
    assert "query_id" in data
    assert "traced_clauses" in data


def test_query_pre_existing_excluded(loaded_client, loaded_policy):
    response = loaded_client.post("/query", json={
        "claim_id": str(uuid.uuid4()),
        "claim_type": "health",
        "decision_type": "route_to_standard",
        "relevant_facts": {
            "amount_claimed": "100000",
            "claim_type": "health",
            "pre_existing_condition": True,
        },
    })
    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == "EXCLUDED"


def test_query_high_value_senior_routing(loaded_client, loaded_policy):
    response = loaded_client.post("/query", json={
        "claim_id": str(uuid.uuid4()),
        "claim_type": "health",
        "decision_type": "route_to_senior",
        "relevant_facts": {
            "amount_claimed": "800000",
            "claim_type": "health",
            "severity_score": 0.8,
            "pre_existing_condition": False,
            "within_waiting_period": False,
        },
    })
    assert response.status_code == 200
