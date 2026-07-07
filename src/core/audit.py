"""Audit service — writes every triage action to the audit log. Framework-agnostic."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import structlog

from src.core.domain.models import AuditEntry

logger = structlog.get_logger(__name__)


class AuditService:
    """
    Writes AuditEntry records. The repository dependency is injected so this
    class stays framework-agnostic.
    """

    def __init__(self, repository: "AuditRepository") -> None:
        self._repo = repository

    def log(
        self,
        claim_id: UUID,
        action: str,
        actor: str,
        details: dict[str, Any] | None = None,
        source_clause_ref: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry.new(
            claim_id=claim_id,
            action=action,
            actor=actor,
            details=details or {},
            source_clause_ref=source_clause_ref,
        )
        self._repo.save(entry)
        logger.info(
            "audit_event",
            claim_id=str(claim_id),
            action=action,
            actor=actor,
            source_clause_ref=source_clause_ref,
        )
        return entry


class InMemoryAuditRepository:
    """In-memory implementation for tests and local dev without a DB."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def save(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    def get_by_claim(self, claim_id: UUID) -> list[AuditEntry]:
        return [e for e in self._entries if e.claim_id == claim_id]

    def all(self) -> list[AuditEntry]:
        return list(self._entries)


# Type stub for the real SQLAlchemy-backed repo (defined in claimiq.db)
class AuditRepository:
    def save(self, entry: AuditEntry) -> None: ...
