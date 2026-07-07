"""FastAPI dependency injection for PolicyLens."""

from __future__ import annotations

import os
from functools import lru_cache

from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from src.policylens.nlp.extractor import PolicyClauseExtractor
from src.policylens.reasoning.engine import RuleBasedReasoningEngine

_GRAPH_PERSIST_PATH = os.getenv("POLICYLENS_GRAPH_PATH", "policylens_graph.json")


@lru_cache(maxsize=1)
def _get_shared_graph() -> NetworkXGraphStore:
    """Singleton graph store shared across all requests (in-process for pilot)."""
    return NetworkXGraphStore(persist_path=_GRAPH_PERSIST_PATH)


def get_graph_store() -> NetworkXGraphStore:
    return _get_shared_graph()


def get_policy_loader() -> PolicyLoader:
    return PolicyLoader(graph=_get_shared_graph(), extractor=PolicyClauseExtractor())


def get_reasoning_engine() -> RuleBasedReasoningEngine:
    return RuleBasedReasoningEngine(graph=_get_shared_graph())
