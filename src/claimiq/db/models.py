"""SQLAlchemy ORM models for ClaimIQ."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class QueueORM(Base):
    __tablename__ = "queues"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    skill_requirements = Column(JSON, nullable=False, default=list)
    geography = Column(String(100), nullable=True)
    max_workload = Column(Float, nullable=False, default=50.0)

    adjusters = relationship("AdjusterORM", back_populates="queue")


class AdjusterORM(Base):
    __tablename__ = "adjusters"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    queue_id = Column(PGUUID(as_uuid=True), ForeignKey("queues.id"), nullable=True)
    skills = Column(JSON, nullable=False, default=list)
    geography = Column(String(100), nullable=True)
    current_workload = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, nullable=False, default=True)

    queue = relationship("QueueORM", back_populates="adjusters")


class ClaimORM(Base):
    __tablename__ = "claims"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(String(100), nullable=False, index=True)
    insured_name = Column(String(200), nullable=False, default="")
    claim_type = Column(String(50), nullable=False)
    amount_claimed = Column(Numeric(15, 2), nullable=False)
    incident_date = Column(DateTime(timezone=False), nullable=False)
    reported_date = Column(DateTime(timezone=False), nullable=False)
    raw_fnol_json = Column(JSON, nullable=False, default=dict)
    language = Column(String(10), nullable=False, default="en")
    status = Column(String(30), nullable=False, default="RECEIVED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    routing_decision = relationship("RoutingDecisionORM", back_populates="claim", uselist=False)
    audit_entries = relationship("AuditLogORM", back_populates="claim", order_by="AuditLogORM.timestamp")


class RoutingDecisionORM(Base):
    __tablename__ = "routing_decisions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(PGUUID(as_uuid=True), ForeignKey("claims.id"), nullable=False, unique=True, index=True)
    severity_score = Column(Float, nullable=False)
    complexity_score = Column(Float, nullable=False)
    fraud_propensity_score = Column(Float, nullable=False, name="fraud_score")
    decision_type = Column(String(50), nullable=False)
    assigned_queue = Column(String(100), nullable=False)
    reserve_suggestion = Column(Numeric(15, 2), nullable=False)
    # Non-nullable at DB level — enforced here and in TriageService
    policylens_justification_id = Column(PGUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("ClaimORM", back_populates="routing_decision")


class AuditLogORM(Base):
    __tablename__ = "audit_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(PGUUID(as_uuid=True), ForeignKey("claims.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    action = Column(String(50), nullable=False)
    actor = Column(String(100), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    source_clause_ref = Column(Text, nullable=True)

    claim = relationship("ClaimORM", back_populates="audit_entries")
