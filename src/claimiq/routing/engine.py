"""
Routing engine — assigns a claim to an adjuster queue and suggests a reserve.

Rules are deterministic and threshold-based. Thresholds are configurable
via Settings so they can be tuned per-insurer without code changes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from src.claimiq.config import Settings, get_settings
from src.core.domain.models import Claim, DecisionType, ScoringResult
from src.core.domain.ports import IRoutingEngine

logger = structlog.get_logger(__name__)

# Queue names — these must match rows in the queues table
QUEUE_STANDARD = "standard"
QUEUE_SENIOR = "senior-adjuster"
QUEUE_FRAUD = "fraud-investigation"
QUEUE_FAST_TRACK = "fast-track"


class RuleBasedRoutingEngine(IRoutingEngine):
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()

    def route(
        self, claim: Claim, scores: ScoringResult
    ) -> tuple[DecisionType, str, Decimal]:
        """
        Returns (decision_type, queue_name, reserve_suggestion).

        Priority order:
        1. Fraud signal → fraud unit (always, regardless of amount)
        2. High overall risk → senior adjuster
        3. Low risk → fast-track
        4. Default → standard queue
        """
        overall = scores.overall_risk

        if scores.fraud_propensity_score >= self._s.fraud_unit_threshold:
            decision = DecisionType.ROUTE_TO_FRAUD_UNIT
            queue = QUEUE_FRAUD
        elif overall >= self._s.senior_adjuster_threshold:
            decision = DecisionType.ROUTE_TO_SENIOR
            queue = QUEUE_SENIOR
        elif overall <= self._s.fast_track_threshold:
            decision = DecisionType.FAST_TRACK
            queue = QUEUE_FAST_TRACK
        else:
            decision = DecisionType.ROUTE_TO_STANDARD
            queue = QUEUE_STANDARD

        reserve = self._calculate_reserve(claim.amount_claimed, scores)

        logger.info(
            "claim_routed",
            claim_id=str(claim.id),
            decision=decision.value,
            queue=queue,
            reserve=str(reserve),
            overall_risk=round(overall, 4),
        )
        return decision, queue, reserve

    def _calculate_reserve(self, amount_claimed: Decimal, scores: ScoringResult) -> Decimal:
        overall = scores.overall_risk
        if overall >= self._s.senior_adjuster_threshold:
            multiplier = Decimal(str(self._s.reserve_multiplier_high))
        elif overall <= self._s.fast_track_threshold:
            multiplier = Decimal(str(self._s.reserve_multiplier_low))
        else:
            multiplier = Decimal(str(self._s.reserve_multiplier_medium))
        # Round to nearest 100 INR
        raw = amount_claimed * multiplier
        return (raw / 100).quantize(Decimal("1")) * 100
