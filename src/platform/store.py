"""Storage for the Cloud Run app: in-memory (demo) or Firestore (production).

Firestore is serverless and scales to zero with Cloud Run, so the hackathon
deployment needs no Cloud SQL instance. The original PostgreSQL stack in
src/claimiq/db is untouched for insurers who want it.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol
from uuid import UUID

from src.core.domain.models import AuditEntry, Claim, ClaimStatus, RoutingDecision
from src.core.domain.ports import JustificationResult
from src.platform.serialization import (
    audit_from_dict,
    claim_from_dict,
    decision_from_dict,
    justification_from_dict,
    to_jsonable,
)


class PlatformStore(Protocol):
    def save_claim(self, claim: Claim) -> None: ...
    def update_status(self, claim_id: UUID, status: ClaimStatus) -> None: ...
    def get_claim(self, claim_id: UUID) -> Claim | None: ...
    def list_claims(self, limit: int = 50) -> list[Claim]: ...
    def save_decision(self, decision: RoutingDecision) -> None: ...
    def get_decision(self, claim_id: UUID) -> RoutingDecision | None: ...
    def save_justification(self, result: JustificationResult) -> None: ...
    def get_justification(self, query_id: UUID) -> JustificationResult | None: ...
    def save_audit(self, entry: AuditEntry) -> None: ...
    def get_audit(self, claim_id: UUID) -> list[AuditEntry]: ...
    def save_extra(self, claim_id: UUID, key: str, value: Any) -> None: ...
    def get_extras(self, claim_id: UUID) -> dict[str, Any]: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._claims: dict[UUID, Claim] = {}
        self._decisions: dict[UUID, RoutingDecision] = {}
        self._justifications: dict[UUID, JustificationResult] = {}
        self._audit: list[AuditEntry] = []
        self._extras: dict[UUID, dict[str, Any]] = {}

    def save_claim(self, claim: Claim) -> None:
        with self._lock:
            self._claims[claim.id] = claim

    def update_status(self, claim_id: UUID, status: ClaimStatus) -> None:
        with self._lock:
            if claim_id in self._claims:
                self._claims[claim_id].status = status

    def get_claim(self, claim_id: UUID) -> Claim | None:
        return self._claims.get(claim_id)

    def list_claims(self, limit: int = 50) -> list[Claim]:
        with self._lock:
            return sorted(self._claims.values(), key=lambda c: c.created_at, reverse=True)[:limit]

    def save_decision(self, decision: RoutingDecision) -> None:
        with self._lock:
            self._decisions[decision.claim_id] = decision

    def get_decision(self, claim_id: UUID) -> RoutingDecision | None:
        return self._decisions.get(claim_id)

    def save_justification(self, result: JustificationResult) -> None:
        with self._lock:
            self._justifications[result.query_id] = result

    def get_justification(self, query_id: UUID) -> JustificationResult | None:
        return self._justifications.get(query_id)

    def save_audit(self, entry: AuditEntry) -> None:
        with self._lock:
            self._audit.append(entry)

    def get_audit(self, claim_id: UUID) -> list[AuditEntry]:
        with self._lock:
            return [e for e in self._audit if e.claim_id == claim_id]

    def save_extra(self, claim_id: UUID, key: str, value: Any) -> None:
        with self._lock:
            self._extras.setdefault(claim_id, {})[key] = to_jsonable(value)

    def get_extras(self, claim_id: UUID) -> dict[str, Any]:
        return dict(self._extras.get(claim_id, {}))


class FirestoreStore:
    """claims/{id} holds claim, decision, justification and extras; audit is a subcollection."""

    def __init__(self, project: str | None = None, database: str = "(default)") -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project or None, database=database)
        self._claims = self._db.collection("claims")
        self._justifications = self._db.collection("justifications")

    def save_claim(self, claim: Claim) -> None:
        self._claims.document(str(claim.id)).set(
            {"claim": to_jsonable(claim), "created_at": claim.created_at}, merge=True
        )

    def update_status(self, claim_id: UUID, status: ClaimStatus) -> None:
        self._claims.document(str(claim_id)).update({"claim.status": status.value})

    def get_claim(self, claim_id: UUID) -> Claim | None:
        snap = self._claims.document(str(claim_id)).get()
        if not snap.exists or "claim" not in (snap.to_dict() or {}):
            return None
        return claim_from_dict(snap.to_dict()["claim"])

    def list_claims(self, limit: int = 50) -> list[Claim]:
        from google.cloud import firestore

        q = self._claims.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [claim_from_dict(s.to_dict()["claim"]) for s in q.stream() if "claim" in s.to_dict()]

    def save_decision(self, decision: RoutingDecision) -> None:
        self._claims.document(str(decision.claim_id)).set(
            {"decision": to_jsonable(decision)}, merge=True
        )

    def get_decision(self, claim_id: UUID) -> RoutingDecision | None:
        snap = self._claims.document(str(claim_id)).get()
        data = snap.to_dict() or {}
        return decision_from_dict(data["decision"]) if "decision" in data else None

    def save_justification(self, result: JustificationResult) -> None:
        self._justifications.document(str(result.query_id)).set(to_jsonable(result))

    def get_justification(self, query_id: UUID) -> JustificationResult | None:
        snap = self._justifications.document(str(query_id)).get()
        return justification_from_dict(snap.to_dict()) if snap.exists else None

    def save_audit(self, entry: AuditEntry) -> None:
        self._claims.document(str(entry.claim_id)).collection("audit").document(
            str(entry.id)
        ).set(to_jsonable(entry))

    def get_audit(self, claim_id: UUID) -> list[AuditEntry]:
        docs = self._claims.document(str(claim_id)).collection("audit").stream()
        return sorted((audit_from_dict(d.to_dict()) for d in docs), key=lambda e: e.timestamp)

    def save_extra(self, claim_id: UUID, key: str, value: Any) -> None:
        self._claims.document(str(claim_id)).set(
            {"extras": {key: to_jsonable(value)}}, merge=True
        )

    def get_extras(self, claim_id: UUID) -> dict[str, Any]:
        snap = self._claims.document(str(claim_id)).get()
        return (snap.to_dict() or {}).get("extras", {})


# --- Adapters onto the repository interfaces TriageService expects ----------

class ClaimRepoAdapter:
    def __init__(self, store: PlatformStore) -> None:
        self._s = store

    async def save(self, claim: Claim) -> None:
        self._s.save_claim(claim)

    async def update_status(self, claim_id: UUID, status: ClaimStatus) -> None:
        self._s.update_status(claim_id, status)

    async def get_by_id(self, claim_id: UUID) -> Claim | None:
        return self._s.get_claim(claim_id)


class DecisionRepoAdapter:
    def __init__(self, store: PlatformStore) -> None:
        self._s = store

    async def save(self, decision: RoutingDecision) -> None:
        self._s.save_decision(decision)

    async def get_by_claim_id(self, claim_id: UUID) -> RoutingDecision | None:
        return self._s.get_decision(claim_id)


class AuditRepoAdapter:
    def __init__(self, store: PlatformStore) -> None:
        self._s = store

    def save(self, entry: AuditEntry) -> None:
        self._s.save_audit(entry)
