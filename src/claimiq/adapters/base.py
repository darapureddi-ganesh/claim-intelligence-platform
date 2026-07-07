"""Base adapter interface for per-insurer integrations (hexagonal outer layer)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.models import Claim


class AbstractInsuranceAdapter(ABC):
    """
    One adapter per integration target (policy admin system, legacy DB format, etc.).
    New customer onboarding = write a new adapter, not modify the core.
    """

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        """Short identifier, e.g. 'generic_csv', 'magma_policy_admin'."""
        ...

    @abstractmethod
    def fetch_policy_context(self, policy_id: str) -> dict[str, Any]:
        """
        Retrieve policy metadata from the insurer's system.
        Returns a dict that will be merged into claim.metadata.
        """
        ...

    @abstractmethod
    def push_decision(self, claim: Claim, decision_summary: dict[str, Any]) -> None:
        """
        Write the routing decision back to the insurer's core claims system.
        Implementations may be a no-op if the insurer uses pull-only mode.
        """
        ...
