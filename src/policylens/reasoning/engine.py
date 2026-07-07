"""
Rule-based reasoning engine for PolicyLens.

IMPORTANT: Zero LLM. Every justification traces back to specific graph nodes
(source policy text). This is the IRDAI audit-defensibility requirement.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.domain.models import ClaimType, DecisionType
from src.core.domain.ports import (
    ClauseReference,
    IGraphStore,
    JustificationQuery,
    JustificationResult,
)
from src.policylens.graph.models import NodeType

logger = structlog.get_logger(__name__)

# Routing thresholds that trigger senior adjuster routing
_SENIOR_ROUTE_AMOUNT_THRESHOLD = Decimal("500000")  # INR 5 lakh
_FRAUD_SCORE_THRESHOLD = 0.6

# Claim-type → relevant graph tags
_CLAIM_TYPE_TAGS: dict[ClaimType, list[str]] = {
    ClaimType.MOTOR: ["motor", "vehicle", "collision", "third party"],
    ClaimType.HEALTH: ["health", "hospitalization", "illness", "surgery", "treatment"],
    ClaimType.PROPERTY: ["property", "fire", "flood", "theft", "burglary"],
    ClaimType.LIFE: ["life", "death", "nominee"],
    ClaimType.MARINE: ["marine"],
    ClaimType.OTHER: [],
}

# Decision-type → what we are looking for in the graph
_DECISION_TAGS: dict[DecisionType, list[str]] = {
    DecisionType.ROUTE_TO_SENIOR: ["high-value", "complex"],
    DecisionType.ROUTE_TO_FRAUD_UNIT: ["fraud", "suspicious"],
    DecisionType.FLAG_FOR_INVESTIGATION: ["investigation", "disputed"],
    DecisionType.FAST_TRACK: ["fast-track", "straightforward"],
    DecisionType.ROUTE_TO_STANDARD: [],
}


class RuleBasedReasoningEngine:
    """
    Traverses the policy knowledge graph to justify a routing/reserve decision.

    Algorithm:
    1. Collect claim-type tags + decision-type tags
    2. Search for matching coverage/condition nodes in the graph
    3. Check exclusion nodes — any match → confidence = EXCLUDED
    4. Check condition nodes — relevant conditions → confidence = CONDITIONAL
    5. Build justification from traced clause texts (never LLM-generated)
    """

    def __init__(self, graph: IGraphStore) -> None:
        self._graph = graph

    def justify(self, query: JustificationQuery) -> JustificationResult:
        facts = query.relevant_facts
        claim_tags = _CLAIM_TYPE_TAGS.get(query.claim_type, [])
        decision_tags = _DECISION_TAGS.get(query.decision_type, [])
        search_tags = list(set(claim_tags + decision_tags))

        # Step 1: find relevant nodes by tag overlap
        candidate_nodes = self._graph.get_nodes_by_tags(search_tags) if search_tags else []

        # Step 2: check exclusions
        exclusion_nodes = [
            n for n in candidate_nodes
            if n.get("node_type") == NodeType.EXCLUSION.value
        ]
        exclusion_matches = self._apply_exclusion_rules(exclusion_nodes, facts)

        # Step 3: check coverage/condition nodes
        coverage_nodes = [
            n for n in candidate_nodes
            if n.get("node_type") in (NodeType.COVERAGE.value, NodeType.CONDITION.value)
        ]

        # Step 4: determine confidence
        confidence = self._determine_confidence(
            query=query,
            facts=facts,
            exclusion_matches=exclusion_matches,
            coverage_nodes=coverage_nodes,
        )

        # Step 5: build traced clause list from all matched nodes
        all_traced = exclusion_matches + coverage_nodes
        # Add generic structural support when no specific tags hit
        if not all_traced:
            all_traced = self._fallback_clause_lookup(query.claim_type)

        traced_clauses = [
            ClauseReference(
                node_id=n["id"],
                clause_ref=n.get("clause_ref", ""),
                text=n.get("text", ""),
                tags=n.get("tags", []),
            )
            for n in all_traced
        ]

        justification_text = self._build_justification_text(
            query=query,
            confidence=confidence,
            traced_clauses=traced_clauses,
            facts=facts,
        )

        result = JustificationResult(
            query_id=query.query_id,
            claim_id=query.claim_id,
            justification_text=justification_text,
            traced_clauses=traced_clauses,
            confidence=confidence,
            timestamp=datetime.utcnow(),
        )

        logger.info(
            "justification_produced",
            claim_id=str(query.claim_id),
            decision_type=query.decision_type.value,
            confidence=confidence,
            clauses_traced=len(traced_clauses),
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_exclusion_rules(
        self,
        exclusion_nodes: list[dict[str, Any]],
        facts: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return exclusion nodes whose tags match the claim facts."""
        matches = []
        claim_type = facts.get("claim_type", "")
        for node in exclusion_nodes:
            node_tags = node.get("tags", [])
            # Pre-existing condition exclusion
            if "pre-existing" in node_tags and facts.get("pre_existing_condition"):
                matches.append(node)
            # Waiting period exclusion
            elif "waiting-period" in node_tags and facts.get("within_waiting_period"):
                matches.append(node)
        return matches

    def _determine_confidence(
        self,
        query: JustificationQuery,
        facts: dict[str, Any],
        exclusion_matches: list[dict[str, Any]],
        coverage_nodes: list[dict[str, Any]],
    ) -> str:
        if exclusion_matches:
            return "EXCLUDED"
        amount = Decimal(str(facts.get("amount_claimed", "0")))
        fraud_score = float(facts.get("fraud_propensity_score", 0.0))
        if query.decision_type == DecisionType.ROUTE_TO_FRAUD_UNIT or fraud_score >= _FRAUD_SCORE_THRESHOLD:
            return "CONDITIONAL"
        if query.decision_type == DecisionType.ROUTE_TO_SENIOR and amount >= _SENIOR_ROUTE_AMOUNT_THRESHOLD:
            return "COVERED"
        if coverage_nodes:
            return "COVERED"
        return "UNCLEAR"

    def _fallback_clause_lookup(self, claim_type: ClaimType) -> list[dict[str, Any]]:
        """Return top-level policy nodes when no tag-specific match is found."""
        tags = _CLAIM_TYPE_TAGS.get(claim_type, [])
        if not tags:
            return []
        return self._graph.get_nodes_by_tags(tags)[:3]

    def _build_justification_text(
        self,
        query: JustificationQuery,
        confidence: str,
        traced_clauses: list[ClauseReference],
        facts: dict[str, Any],
    ) -> str:
        decision_label = query.decision_type.value.replace("_", " ").title()
        refs = ", ".join(c.clause_ref for c in traced_clauses if c.clause_ref) or "policy wording"
        amount = facts.get("amount_claimed", "N/A")

        if confidence == "EXCLUDED":
            return (
                f"Decision [{decision_label}] — claim is NOT covered under this policy. "
                f"Applicable exclusion clause(s): {refs}. "
                f"Claimed amount: INR {amount}."
            )
        if confidence == "CONDITIONAL":
            return (
                f"Decision [{decision_label}] — claim coverage is conditional. "
                f"Relevant clause(s): {refs}. "
                f"Conditions must be verified before settlement. "
                f"Claimed amount: INR {amount}."
            )
        if confidence == "COVERED":
            return (
                f"Decision [{decision_label}] — claim is covered under this policy. "
                f"Supporting clause(s): {refs}. "
                f"Claimed amount: INR {amount}."
            )
        return (
            f"Decision [{decision_label}] — coverage status is unclear. "
            f"No directly applicable clause found for claim type '{query.claim_type.value}'. "
            f"Manual review required. Claimed amount: INR {amount}."
        )
