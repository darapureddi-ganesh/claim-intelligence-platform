"""PolicyLens — policy document management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.policylens.api.schemas import PolicyInfoResponse, PolicyLoadRequest, PolicyLoadResponse
from src.policylens.dependencies import get_graph_store, get_policy_loader

router = APIRouter(prefix="/policies", tags=["PolicyLens — Policies"])


@router.post("", response_model=PolicyLoadResponse, status_code=status.HTTP_201_CREATED)
def load_policy(
    request: PolicyLoadRequest,
    loader=Depends(get_policy_loader),
    graph=Depends(get_graph_store),
):
    """Load a policy wording document into the knowledge graph."""
    if graph.policy_exists(request.policy_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy '{request.policy_id}' is already loaded.",
        )
    nodes_added = loader.load(
        policy_id=request.policy_id,
        policy_name=request.policy_name,
        text=request.wording_text,
    )
    return PolicyLoadResponse(
        policy_id=request.policy_id,
        nodes_added=nodes_added,
        message=f"Policy loaded successfully with {nodes_added} graph nodes.",
    )


@router.get("/{policy_id}", response_model=PolicyInfoResponse)
def get_policy_info(
    policy_id: str,
    graph=Depends(get_graph_store),
):
    """Return node/edge counts for a loaded policy."""
    if not graph.policy_exists(policy_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    return PolicyInfoResponse(
        policy_id=policy_id,
        node_count=graph.node_count(),
        edge_count=graph.edge_count(),
    )
