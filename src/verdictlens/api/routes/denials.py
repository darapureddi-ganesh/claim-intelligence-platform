"""
VerdictLens — denial explanation & compliance documentation (Phase 2).

Reuses the PolicyLens graph (no new infrastructure) to generate structured
denial letters and IRDAI-compliant reasoning documents.

STATUS: Phase 2 stub. Returns 501 until Phase 2 build begins.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/denials", tags=["VerdictLens — Denial Explanations"])


@router.post("/{claim_id}/explain")
def explain_denial(claim_id: UUID) -> dict:
    """
    Generate a denial explanation document for a claim.
    Reuses PolicyLens graph — no new reasoning infrastructure required.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "VerdictLens (Phase 2) is not yet implemented. "
            "PolicyLens graph is already populated — Phase 2 adds document formatting only."
        ),
    )
