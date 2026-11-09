"""Structured-output schemas sent to Gemini as `response_schema`.

Gemini *extracts facts with evidence*; it never decides coverage or routing.
Every fact that can influence a rule carries a verbatim evidence quote so a
human (or an IRDAI auditor) can check where it came from.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ClaimTypeOut(str, Enum):
    motor = "motor"
    health = "health"
    property = "property"
    life = "life"
    marine = "marine"
    other = "other"


class FlagSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EvidencedBool(BaseModel):
    value: bool | None = Field(None, description="null when the documents do not say")
    evidence: str = Field("", description="Verbatim quote from the input that supports value")


class DocumentSummary(BaseModel):
    doc_type: str = Field(description="e.g. hospital bill, discharge summary, FIR, RC, photo")
    summary: str
    language: str = Field("en", description="ISO 639-1 code of the document")


class ConsistencyFlag(BaseModel):
    flag: str = Field(description="Short name, e.g. 'date_mismatch', 'damage_inconsistent'")
    severity: FlagSeverity
    evidence: str = Field(description="What in the inputs shows the inconsistency")


class DamageAssessment(BaseModel):
    damaged_parts: list[str] = Field(default_factory=list)
    visible_severity: float = Field(0.0, ge=0.0, le=1.0, description="0 none .. 1 total loss")
    notes: str = ""


class ExtractedFNOL(BaseModel):
    policy_id: str = Field("", description="Policy number exactly as written; empty if absent")
    insured_name: str = ""
    claim_type: ClaimTypeOut = ClaimTypeOut.other
    amount_claimed_inr: float = Field(0.0, ge=0.0, description="Total amount claimed in INR")
    incident_date: str = Field("", description="YYYY-MM-DD, empty if unknown")
    reported_date: str = Field("", description="YYYY-MM-DD, empty if unknown")
    policy_start_date: str = Field("", description="YYYY-MM-DD if stated anywhere")
    incident_location: str = ""
    detected_language: str = Field("en", description="ISO 639-1 code of the claimant's own words")
    narrative_original: str = Field("", description="Claimant's account in their own language")
    narrative_english: str = Field("", description="Faithful English translation of the account")
    pre_existing_condition: EvidencedBool = Field(default_factory=EvidencedBool)
    alcohol_or_drugs_involved: EvidencedBool = Field(default_factory=EvidencedBool)
    documents: list[DocumentSummary] = Field(default_factory=list)
    damage: DamageAssessment = Field(default_factory=DamageAssessment)
    consistency_flags: list[ConsistencyFlag] = Field(default_factory=list)
    missing_information: list[str] = Field(
        default_factory=list, description="Fields an adjuster must still collect"
    )


class GroundedClause(BaseModel):
    clause_ref: str = Field(description="Section/clause number as printed, e.g. '3.1'")
    node_type: str = Field(description="coverage | exclusion | condition | endorsement | clause")
    verbatim_text: str = Field(description="Exact clause text copied character-for-character")
    tags: list[str] = Field(default_factory=list)


class PolicyExtraction(BaseModel):
    clauses: list[GroundedClause] = Field(default_factory=list)


class VerdictDraft(BaseModel):
    decision_stated: str = Field(description="Must equal the coverage status you were given")
    cited_clause_refs: list[str] = Field(default_factory=list)
    letter_markdown: str
    plain_language_summary: str = Field(description="Two sentences a policyholder understands")
