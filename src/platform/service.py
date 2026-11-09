"""PlatformService — the end-to-end flow behind the Cloud Run app.

    Gemini reads  →  Gemma redacts  →  ML scores + rules route  →
    PolicyLens graph justifies (zero LLM)  →  Gemini explains, citation-checked

The existing TriageService (and its "no justification, no decision" invariant)
is reused unchanged; this layer only wires Google AI around it.
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.claimiq.routing.engine import QUEUE_FRAUD, QUEUE_STANDARD, RuleBasedRoutingEngine
from src.claimiq.scoring.engine import XGBoostScoringEngine
from src.claimiq.services.triage import TriageService
from src.core.audit import AuditService
from src.core.domain.models import (
    Claim,
    DecisionType,
    FNOLData,
    ScoringResult,
)
from src.core.domain.ports import (
    IPolicyLensPort,
    IRoutingEngine,
    JustificationQuery,
    JustificationResult,
)
from src.gemini.intake import Attachment, GeminiFNOLExtractor, to_fnol_data
from src.gemini.pii import GemmaPIIRedactor
from src.gemini.policy_extractor import GeminiPolicyClauseExtractor
from src.gemini.verdict import VerdictWriter
from src.gemini.vision import DamageAnnotator
from src.platform.serialization import to_jsonable
from src.platform.store import (
    AuditRepoAdapter,
    ClaimRepoAdapter,
    DecisionRepoAdapter,
    PlatformStore,
)
from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from src.policylens.nlp.extractor import PolicyClauseExtractor
from src.policylens.reasoning.engine import RuleBasedReasoningEngine

logger = structlog.get_logger(__name__)


class ClaimNotFoundError(KeyError):
    pass


class RecordingPolicyLens(IPolicyLensPort):
    """In-process PolicyLens that also stores each justification for VerdictLens."""

    def __init__(self, engine: RuleBasedReasoningEngine, store: PlatformStore) -> None:
        self._engine = engine
        self._store = store

    def justify(self, query: JustificationQuery) -> JustificationResult:
        result = self._engine.justify(query)
        self._store.save_justification(result)
        return result


class EvidenceAwareRoutingEngine(IRoutingEngine):
    """Deterministic escalation on Gemini's evidence flags. The model never routes.

    * any HIGH-severity consistency flag  → flag for investigation (fraud queue)
    * any MEDIUM flag on a fast-track     → standard queue (a human looks first)
    """

    def __init__(self, inner: IRoutingEngine) -> None:
        self._inner = inner

    def route(self, claim: Claim, scores: ScoringResult) -> tuple[DecisionType, str, Decimal]:
        decision, queue, reserve = self._inner.route(claim, scores)
        flags = claim.metadata.get("ai_consistency_flags") or []
        severities = {str(f.get("severity", "")).lower() for f in flags if isinstance(f, dict)}
        if "high" in severities and decision != DecisionType.ROUTE_TO_FRAUD_UNIT:
            return DecisionType.FLAG_FOR_INVESTIGATION, QUEUE_FRAUD, reserve
        if "medium" in severities and decision == DecisionType.FAST_TRACK:
            return DecisionType.ROUTE_TO_STANDARD, QUEUE_STANDARD, reserve
        return decision, queue, reserve


class PlatformService:
    def __init__(
        self,
        store: PlatformStore,
        graph: NetworkXGraphStore | None = None,
        extractor: GeminiFNOLExtractor | None = None,
        redactor: GemmaPIIRedactor | None = None,
        policy_extractor: GeminiPolicyClauseExtractor | None = None,
        verdict_writer: VerdictWriter | None = None,
        annotator: DamageAnnotator | None = None,
    ) -> None:
        self.store = store
        self.graph = graph or NetworkXGraphStore(persist_path=None)
        self.extractor = extractor or GeminiFNOLExtractor()
        self.redactor = redactor or GemmaPIIRedactor()
        self.policy_extractor = policy_extractor or GeminiPolicyClauseExtractor()
        self.verdict_writer = verdict_writer or VerdictWriter()
        self.annotator = annotator or DamageAnnotator()
        self._scoring = XGBoostScoringEngine()
        self._routing = EvidenceAwareRoutingEngine(RuleBasedRoutingEngine())
        self._reasoning = RuleBasedReasoningEngine(self.graph)
        self._audit = AuditService(AuditRepoAdapter(store))
        self.policies: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ policies
    def load_policy(
        self,
        policy_id: str,
        policy_name: str,
        text: str = "",
        document: Attachment | None = None,
        use_gemini: bool = True,
    ) -> dict[str, Any]:
        if self.graph.policy_exists(policy_id):
            raise ValueError(f"Policy '{policy_id}' is already loaded.")
        if document is not None:
            text = self.policy_extractor.transcribe(document.data, document.mime_type)
        if not text.strip():
            raise ValueError("Policy wording is empty.")

        extractor_name = "rules"
        rejected: list[dict[str, str]] = []
        if use_gemini:
            loader = PolicyLoader(graph=self.graph, extractor=self.policy_extractor)
            extractor_name = "gemini"
        else:
            loader = PolicyLoader(graph=self.graph, extractor=PolicyClauseExtractor())
        nodes = loader.load(policy_id, policy_name, text)
        if use_gemini:
            rejected = self.policy_extractor.last_report.rejected
        info = {
            "policy_id": policy_id,
            "policy_name": policy_name,
            "nodes_added": nodes,
            "extractor": extractor_name,
            "rejected_clauses": rejected,
        }
        self.policies[policy_id] = info
        return info

    def match_policy(self, spoken: str) -> str | None:
        """Match a spoken/typed policy number on letters and digits only."""
        key = re.sub(r"[^A-Z0-9]", "", spoken.upper())
        if not key:
            return None
        for pid in self.policies:
            if re.sub(r"[^A-Z0-9]", "", pid.upper()) == key:
                return pid
        return None

    def policy_clauses(self, policy_id: str) -> list[dict[str, Any]]:
        return [
            {k: n.get(k) for k in ("id", "node_type", "clause_ref", "text", "tags")}
            for n in self.graph.get_all_nodes()
            if n.get("policy_id") == policy_id and n.get("node_type") != "policy"
        ]

    # ------------------------------------------------------------------ intake
    def extract(self, text: str, attachments: list[Attachment]) -> dict[str, Any]:
        extraction = self.extractor.extract(text=text, attachments=attachments)
        fnol = to_fnol_data(extraction)
        missing = list(extraction.missing_information)
        if fnol.policy_id == "UNKNOWN":
            missing.append("policy number")
        if fnol.amount_claimed <= 0:
            missing.append("amount claimed")
        return {
            "extraction": extraction.model_dump(mode="json"),
            "fnol": to_jsonable(fnol),
            "ready_to_submit": fnol.policy_id != "UNKNOWN" and fnol.amount_claimed > 0,
            "missing": sorted(set(missing)),
            "_fnol_obj": fnol,
        }

    async def intake_and_triage(self, text: str, attachments: list[Attachment]) -> dict[str, Any]:
        result = self.extract(text, attachments)
        fnol: FNOLData = result.pop("_fnol_obj")
        if not result["ready_to_submit"]:
            return {**result, "submitted": False}
        detail = await self.submit(fnol, channel="gemini-multimodal")
        return {**result, "submitted": True, **detail}

    async def submit(self, fnol: FNOLData, channel: str = "api") -> dict[str, Any]:
        redaction = self.redactor.redact(fnol.raw_text)
        redacted_counts = dict(redaction.counts)
        engines = {redaction.engine}
        metadata = dict(fnol.metadata)
        if metadata.get("narrative_original"):
            original = self.redactor.redact(str(metadata["narrative_original"]))
            metadata["narrative_original"] = original.text
            engines.add(original.engine)
            for k, v in original.counts.items():
                redacted_counts[k] = redacted_counts.get(k, 0) + v
        metadata["intake_channel"] = metadata.get("intake_channel", channel)

        claim = Claim.new(
            policy_id=fnol.policy_id,
            claim_type=fnol.claim_type,
            amount_claimed=fnol.amount_claimed,
            incident_date=fnol.incident_date,
            reported_date=fnol.reported_date,
            raw_fnol_text=redaction.text,
            insured_name=fnol.insured_name,
            language=fnol.detected_language,
            metadata=metadata,
        )
        self.store.save_claim(claim)
        self._audit.log(claim.id, "FNOL_RECEIVED", f"intake.{channel}",
                        details={"language": claim.language})
        if redacted_counts:
            engine = "regex+gemma" if "regex+gemma" in engines else "regex"
            self._audit.log(claim.id, "PII_REDACTED", f"privacy.{engine}",
                            details={"counts": redacted_counts})
        flags = metadata.get("ai_consistency_flags") or []
        if flags:
            self._audit.log(claim.id, "AI_EVIDENCE_FLAGS", "gemini.intake",
                            details={"flags": flags})

        triage = TriageService(
            scoring_engine=self._scoring,
            routing_engine=self._routing,
            policylens=RecordingPolicyLens(self._reasoning, self.store),
            claim_repo=ClaimRepoAdapter(self.store),
            decision_repo=DecisionRepoAdapter(self.store),
            audit_repo=AuditRepoAdapter(self.store),
        )
        await triage.process(claim)
        return self.claim_detail(claim.id)

    # ------------------------------------------------------------------ read
    def claim_detail(self, claim_id: UUID) -> dict[str, Any]:
        claim = self.store.get_claim(claim_id)
        if claim is None:
            raise ClaimNotFoundError(str(claim_id))
        decision = self.store.get_decision(claim_id)
        justification = (
            self.store.get_justification(decision.policylens_justification_id)
            if decision else None
        )
        return {
            "claim": to_jsonable(claim),
            "routing_decision": to_jsonable(decision) if decision else None,
            "justification": to_jsonable(justification) if justification else None,
            "audit_trail": to_jsonable(self.store.get_audit(claim_id)),
            "extras": self.store.get_extras(claim_id),
        }

    def list_claims(self, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for c in self.store.list_claims(limit):
            d = self.store.get_decision(c.id)
            out.append({
                "id": str(c.id), "policy_id": c.policy_id, "insured_name": c.insured_name,
                "claim_type": c.claim_type.value, "amount_claimed": str(c.amount_claimed),
                "language": c.language, "status": c.status.value,
                "queue": d.assigned_queue if d else None,
                "channel": c.metadata.get("intake_channel"),
                "created_at": c.created_at.isoformat(),
            })
        return out

    # ------------------------------------------------------------------ verdict
    def verdict(self, claim_id: UUID, language: str = "en") -> dict[str, Any]:
        claim = self.store.get_claim(claim_id)
        decision = self.store.get_decision(claim_id) if claim else None
        if claim is None or decision is None:
            raise ClaimNotFoundError(str(claim_id))
        justification = self.store.get_justification(decision.policylens_justification_id)
        if justification is None:
            raise ClaimNotFoundError(f"justification for {claim_id}")
        letter = self.verdict_writer.write(claim, decision, justification, language)
        self.store.save_extra(claim_id, f"verdict_{letter.language}", letter.to_dict())
        self._audit.log(
            claim_id, "VERDICT_GENERATED", f"verdictlens.{letter.generator}",
            details={"language": letter.language, "validation_errors": letter.validation_errors},
            source_clause_ref=", ".join(letter.cited_clause_refs) or None,
        )
        return letter.to_dict()

    # ------------------------------------------------------------------ vision
    def annotate(self, data: bytes, mime_type: str, claim_id: UUID | None = None) -> dict[str, Any]:
        claim_type = "motor"
        if claim_id:
            claim = self.store.get_claim(claim_id)
            if claim is None:
                raise ClaimNotFoundError(str(claim_id))
            claim_type = claim.claim_type.value
        result = self.annotator.annotate(data, mime_type, claim_type).to_dict()
        if claim_id:
            self.store.save_extra(claim_id, f"annotation_{result['original_sha256'][:12]}",
                                  {k: v for k, v in result.items() if k != "annotated_image"})
            self._audit.log(claim_id, "PHOTO_ANNOTATED", "nano-banana",
                            details={"original_sha256": result["original_sha256"]})
        return result

    # ------------------------------------------------------------------ voice
    async def submit_from_voice(self, args: dict[str, Any]) -> dict[str, Any]:
        """Called by the Gemini Live `submit_fnol` tool."""
        from src.gemini.schemas import ExtractedFNOL

        x = ExtractedFNOL.model_validate({
            "policy_id": args.get("policy_id", ""),
            "insured_name": args.get("insured_name", ""),
            "claim_type": args.get("claim_type", "other"),
            "amount_claimed_inr": float(args.get("amount_claimed_inr") or 0),
            "incident_date": args.get("incident_date", ""),
            "reported_date": args.get("reported_date", ""),
            "incident_location": args.get("incident_location", ""),
            "detected_language": args.get("language", "en"),
            "narrative_original": args.get("narrative_original", ""),
            "narrative_english": args.get("narrative_english", ""),
        })
        fnol = to_fnol_data(x)
        fnol = replace(fnol, metadata={**fnol.metadata, "intake_channel": "gemini-live-voice"})
        if fnol.policy_id == "UNKNOWN" or fnol.amount_claimed <= 0:
            return {"ok": False, "error": "policy number and amount are required"}
        detail = await self.submit(fnol, channel="gemini-live-voice")
        d, j = detail["routing_decision"], detail["justification"]
        return {
            "ok": True,
            "claim_id": detail["claim"]["id"],
            "assigned_queue": d["assigned_queue"],
            "coverage_status": j["confidence"] if j else "UNCLEAR",
            "clauses": [c["clause_ref"] for c in (j or {}).get("traced_clauses", [])][:4],
        }
