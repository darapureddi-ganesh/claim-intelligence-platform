"""Initial schema: claims, routing_decisions, audit_log, adjusters, queues.

Revision ID: 001
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("skill_requirements", JSON, nullable=False, server_default="[]"),
        sa.Column("geography", sa.String(100), nullable=True),
        sa.Column("max_workload", sa.Float, nullable=False, server_default="50"),
    )

    op.create_table(
        "adjusters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id"), nullable=True),
        sa.Column("skills", JSON, nullable=False, server_default="[]"),
        sa.Column("geography", sa.String(100), nullable=True),
        sa.Column("current_workload", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_id", sa.String(100), nullable=False),
        sa.Column("insured_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("claim_type", sa.String(50), nullable=False),
        sa.Column("amount_claimed", sa.Numeric(15, 2), nullable=False),
        sa.Column("incident_date", sa.DateTime(timezone=False), nullable=False),
        sa.Column("reported_date", sa.DateTime(timezone=False), nullable=False),
        sa.Column("raw_fnol_json", JSON, nullable=False, server_default="{}"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("status", sa.String(30), nullable=False, server_default="RECEIVED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_claims_policy_id", "claims", ["policy_id"])
    op.create_index("ix_claims_status", "claims", ["status"])

    op.create_table(
        "routing_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=False, unique=True),
        sa.Column("severity_score", sa.Float, nullable=False),
        sa.Column("complexity_score", sa.Float, nullable=False),
        sa.Column("fraud_score", sa.Float, nullable=False),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column("assigned_queue", sa.String(100), nullable=False),
        sa.Column("reserve_suggestion", sa.Numeric(15, 2), nullable=False),
        # DB-level enforcement of the non-negotiable: no routing decision without justification
        sa.Column("policylens_justification_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_routing_decisions_claim_id", "routing_decisions", ["claim_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("details", JSON, nullable=False, server_default="{}"),
        sa.Column("source_clause_ref", sa.Text, nullable=True),
    )
    op.create_index("ix_audit_log_claim_id", "audit_log", ["claim_id"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("routing_decisions")
    op.drop_table("claims")
    op.drop_table("adjusters")
    op.drop_table("queues")
