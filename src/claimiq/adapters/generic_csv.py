"""
Generic CSV adapter — reads legacy flat-file/CSV exports from insurer systems.

This is the demo adapter for onboarding a new insurer whose only integration
capability is a CSV export from their legacy policy admin system.
"""

from __future__ import annotations

import csv
import io
import structlog
from typing import Any

from src.claimiq.adapters.base import AbstractInsuranceAdapter
from src.core.domain.models import Claim

logger = structlog.get_logger(__name__)


class GenericCSVAdapter(AbstractInsuranceAdapter):
    """
    Reads a CSV with at minimum the columns:
    policy_id, insured_name, sum_insured, policy_start_date, claim_type
    """

    def __init__(self, csv_content: str | None = None) -> None:
        self._policies: dict[str, dict[str, Any]] = {}
        if csv_content:
            self._load_csv(csv_content)

    @property
    def adapter_id(self) -> str:
        return "generic_csv"

    def load_from_string(self, csv_content: str) -> int:
        return self._load_csv(csv_content)

    def fetch_policy_context(self, policy_id: str) -> dict[str, Any]:
        ctx = self._policies.get(policy_id, {})
        if not ctx:
            logger.warning("policy_not_found_in_csv_adapter", policy_id=policy_id)
        return ctx

    def push_decision(self, claim: Claim, decision_summary: dict[str, Any]) -> None:
        # CSV adapters are read-only by definition — push is a no-op
        logger.info(
            "csv_adapter_push_noop",
            claim_id=str(claim.id),
            decision_type=decision_summary.get("decision_type"),
        )

    def _load_csv(self, content: str) -> int:
        reader = csv.DictReader(io.StringIO(content))
        loaded = 0
        for row in reader:
            pid = row.get("policy_id", "").strip()
            if pid:
                self._policies[pid] = {k.strip(): v.strip() for k, v in row.items()}
                loaded += 1
        logger.info("csv_adapter_loaded", policies=loaded)
        return loaded
