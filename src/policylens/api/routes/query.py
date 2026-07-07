"""PolicyLens — justification query endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.core.domain.models import ClaimType, DecisionType
from src.core.domain.ports import JustificationQuery
from src.policylens.api.schemas import ClauseReferenceResponse, JustificationQueryRequest, JustificationResponse
from src.policylens.dependencies import get_reasoning_engine

router = APIRouter(prefix="/query", tags=["PolicyLens — Query"])


@router.post("", response_model=JustificationResponse)
def justify_decision(
    request: JustificationQueryRequest,
    engine=Depends(get_reasoning_engine),
):
    """
    Justify a routing/reserve decision by tracing back to policy clauses.
    Returns deterministic, graph-traced justification — no LLM generation.
    """
    query = JustificationQuery(
        claim_id=request.claim_id,
        claim_type=ClaimType(request.claim_type),
        decision_type=DecisionType(request.decision_type),
        relevant_facts=request.relevant_facts,
    )
    result = engine.justify(query)
    return JustificationResponse(
        query_id=result.query_id,
        claim_id=result.claim_id,
        justification_text=result.justification_text,
        traced_clauses=[
            ClauseReferenceResponse(
                node_id=c.node_id,
                clause_ref=c.clause_ref,
                text=c.text,
                tags=c.tags,
            )
            for c in result.traced_clauses
        ],
        confidence=result.confidence,
        timestamp=result.timestamp,
    )
