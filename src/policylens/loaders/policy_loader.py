"""Loads a policy wording document into the knowledge graph."""

from __future__ import annotations

import structlog

from src.core.domain.ports import IGraphStore
from src.policylens.graph.models import EdgeRelation, NodeType
from src.policylens.nlp.extractor import PolicyClauseExtractor

logger = structlog.get_logger(__name__)


class PolicyLoader:
    def __init__(self, graph: IGraphStore, extractor: PolicyClauseExtractor | None = None) -> None:
        self._graph = graph
        self._extractor = extractor or PolicyClauseExtractor()

    def load(self, policy_id: str, policy_name: str, text: str) -> int:
        """
        Parse policy text, extract clauses, and populate the graph.
        Returns the number of nodes added.
        """
        if self._graph.policy_exists(policy_id):
            logger.warning("policy_already_loaded", policy_id=policy_id)
            return 0

        self._graph.add_policy(policy_id, {"name": policy_name, "source": "text"})
        policy_node_id = f"pol:{policy_id}"

        clauses = self._extractor.extract(text, policy_id)
        added = 0

        for i, clause in enumerate(clauses):
            node_id = f"pol:{policy_id}:{clause.node_type.value}:{i}"
            self._graph.add_node(
                node_id=node_id,
                node_type=clause.node_type.value,
                text=clause.raw_text,
                clause_ref=clause.clause_ref,
                tags=clause.tags,
                policy_id=policy_id,
                metadata=clause.metadata,
            )
            # Connect to policy root
            relation = EdgeRelation.CONTAINS.value
            if clause.node_type == NodeType.EXCLUSION:
                relation = EdgeRelation.EXCLUDES.value
            elif clause.node_type == NodeType.ENDORSEMENT:
                relation = EdgeRelation.MODIFIES.value
            elif clause.node_type == NodeType.CONDITION:
                relation = EdgeRelation.REQUIRES.value
            self._graph.add_edge(policy_node_id, node_id, relation)
            added += 1

        logger.info("policy_loaded", policy_id=policy_id, nodes_added=added)
        return added
