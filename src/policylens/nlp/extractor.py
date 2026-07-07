"""
spaCy-based clause extractor.

Extracts coverage clauses, conditions, exclusions, and endorsements from raw
policy wording text. Produces structured PolicyNode candidates for graph loading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import spacy
from spacy.language import Language

from src.policylens.graph.models import NodeType


_SECTION_PATTERN = re.compile(r"(?:section|clause|article|part)\s+[\d.]+[a-z]?", re.IGNORECASE)
_EXCLUSION_KEYWORDS = {"not covered", "excluded", "exclusion", "does not cover", "shall not apply", "not payable"}
_COVERAGE_KEYWORDS = {"covered", "payable", "shall be paid", "benefit", "entitle", "eligible"}
_CONDITION_KEYWORDS = {"provided that", "subject to", "on condition", "unless", "if and only if"}
_ENDORSEMENT_KEYWORDS = {"endorsement", "rider", "addendum", "amendment"}

# Claim-type tags inferred from keywords in the clause text
_CLAIM_TYPE_TAG_MAP = {
    "motor": {"vehicle", "accident", "car", "bike", "motor", "third party", "collision"},
    "health": {"hospitalisation", "hospitalization", "illness", "surgery", "medical", "treatment", "doctor", "icu", "discharge"},
    "property": {"property", "building", "fire", "flood", "damage", "burglary", "theft"},
    "life": {"death", "demise", "nominee", "life assured", "survival"},
}


@dataclass
class ExtractedClause:
    raw_text: str
    node_type: NodeType
    clause_ref: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PolicyClauseExtractor:
    def __init__(self, model: str = "en_core_web_sm") -> None:
        try:
            self._nlp: Language = spacy.load(model)
        except OSError:
            # Minimal fallback for environments without the model downloaded
            self._nlp = spacy.blank("en")

    def extract(self, policy_text: str, policy_id: str) -> list[ExtractedClause]:
        """Split policy text into clause blocks and classify each one."""
        blocks = self._split_into_blocks(policy_text)
        clauses: list[ExtractedClause] = []
        for i, block in enumerate(blocks):
            if not block.strip():
                continue
            clause_ref = self._detect_clause_ref(block) or f"Block {i + 1}"
            node_type = self._classify_block(block)
            tags = self._infer_tags(block, node_type)
            clauses.append(
                ExtractedClause(
                    raw_text=block.strip(),
                    node_type=node_type,
                    clause_ref=clause_ref,
                    tags=tags,
                    metadata={"policy_id": policy_id, "block_index": i},
                )
            )
        return clauses

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _split_into_blocks(self, text: str) -> list[str]:
        """Split on numbered headings or double newlines."""
        # Split on patterns like "1.", "1.1", "Section 2", "Clause 3.4"
        parts = re.split(r"\n(?=\d+[\.\)]\s|\b(?:Section|Clause|Article|Part)\s+\d)", text, flags=re.IGNORECASE)
        if len(parts) <= 1:
            # Fallback: split on double newlines
            parts = text.split("\n\n")
        return parts

    def _detect_clause_ref(self, text: str) -> str | None:
        m = _SECTION_PATTERN.search(text)
        if m:
            return m.group(0).strip()
        # Also match leading number patterns: "1.2 Definitions"
        m2 = re.match(r"^(\d+(?:\.\d+)*[a-z]?)\s", text.strip())
        if m2:
            return m2.group(1)
        return None

    def _classify_block(self, text: str) -> NodeType:
        lower = text.lower()
        if any(kw in lower for kw in _EXCLUSION_KEYWORDS):
            return NodeType.EXCLUSION
        if any(kw in lower for kw in _ENDORSEMENT_KEYWORDS):
            return NodeType.ENDORSEMENT
        if any(kw in lower for kw in _CONDITION_KEYWORDS):
            return NodeType.CONDITION
        if any(kw in lower for kw in _COVERAGE_KEYWORDS):
            return NodeType.COVERAGE
        # Default to generic clause
        return NodeType.CLAUSE

    def _infer_tags(self, text: str, node_type: NodeType) -> list[str]:
        lower = text.lower()
        tags = [node_type.value]
        for claim_type, keywords in _CLAIM_TYPE_TAG_MAP.items():
            if any(kw in lower for kw in keywords):
                tags.append(claim_type)

        # Waiting period
        if re.search(r"waiting period|wait\s+\d+\s+day", lower):
            tags.append("waiting-period")
        # Pre-existing
        if "pre-existing" in lower or "pre existing" in lower:
            tags.append("pre-existing")
        # High-value
        if re.search(r"(?:rs\.?|inr|₹)\s*[\d,]+\s*(?:lakh|crore|million)", lower):
            tags.append("high-value")

        return list(dict.fromkeys(tags))  # deduplicate while preserving order
