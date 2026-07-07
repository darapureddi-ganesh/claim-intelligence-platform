"""Seed the PolicyLens graph with the sample IRDAI-style health policy."""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POLICYLENS_URL = os.getenv("POLICYLENS_URL", "http://localhost:8001")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


def seed():
    policy_path = os.path.join(FIXTURES_DIR, "sample_policy.txt")
    with open(policy_path) as f:
        policy_text = f.read()

    payload = {
        "policy_id": "HC-STD-2024",
        "policy_name": "Standard Health Insurance Policy 2024",
        "wording_text": policy_text,
    }

    try:
        response = httpx.post(f"{POLICYLENS_URL}/policies", json=payload, timeout=30)
        if response.status_code == 409:
            print("Policy HC-STD-2024 already loaded.")
        elif response.status_code == 201:
            data = response.json()
            print(f"Policy loaded: {data['nodes_added']} nodes added.")
        else:
            print(f"Unexpected response {response.status_code}: {response.text}")
    except httpx.ConnectError:
        print(f"Could not connect to PolicyLens at {POLICYLENS_URL}. Is it running?")
        print("To seed locally, import PolicyLoader directly:")
        print("  from src.policylens.loaders.policy_loader import PolicyLoader")
        print("  from src.policylens.graph.store import NetworkXGraphStore")
        sys.exit(1)


if __name__ == "__main__":
    seed()
