"""
HTTP adapter for calling the PolicyLens service.

Implements IPolicyLensPort so TriageService never directly depends on
PolicyLens internals — only the port interface.
"""

from __future__ import annotations

import httpx
import structlog

from src.core.domain.ports import (
    ClauseReference,
    IPolicyLensPort,
    JustificationQuery,
    JustificationResult,
)

logger = structlog.get_logger(__name__)


class PolicyLensHTTPAdapter(IPolicyLensPort):
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def justify(self, query: JustificationQuery) -> JustificationResult:
        payload = {
            "claim_id": str(query.claim_id),
            "claim_type": query.claim_type.value,
            "decision_type": query.decision_type.value,
            "relevant_facts": query.relevant_facts,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self._base_url}/query", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"PolicyLens HTTP call failed: {exc}") from exc

        data = response.json()
        from datetime import datetime
        from uuid import UUID

        return JustificationResult(
            query_id=UUID(data["query_id"]),
            claim_id=UUID(data["claim_id"]),
            justification_text=data["justification_text"],
            traced_clauses=[
                ClauseReference(
                    node_id=c["node_id"],
                    clause_ref=c["clause_ref"],
                    text=c["text"],
                    tags=c.get("tags", []),
                )
                for c in data.get("traced_clauses", [])
            ],
            confidence=data["confidence"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
