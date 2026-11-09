"""End-to-end through the Cloud Run FastAPI app with a fake Gemini client."""

import base64

import pytest
from fastapi.testclient import TestClient

from src.core.domain.models import Claim, ClaimType, DecisionType, ScoringResult
from src.gemini.config import GoogleAISettings
from src.gemini.intake import GeminiFNOLExtractor
from src.gemini.pii import GemmaPIIRedactor
from src.gemini.policy_extractor import GeminiPolicyClauseExtractor
from src.gemini.schemas import ExtractedFNOL, VerdictDraft
from src.gemini.verdict import VerdictWriter
from src.gemini.vision import DamageAnnotator
from src.platform.app import create_app
from src.platform.service import EvidenceAwareRoutingEngine, PlatformService
from src.platform.store import InMemoryStore
from tests.gemini.fakes import FakeClient, image, structured, text

S = GoogleAISettings(gemini_api_key="secret-key-should-never-leak")


class Script:
    """Routes fake Gemini calls by schema / model."""

    def __init__(self):
        self.extraction = ExtractedFNOL.model_validate({
            "policy_id": "HC-STD-2024", "insured_name": "Ravi Kumar", "claim_type": "motor",
            "amount_claimed_inr": 85000, "incident_date": "2026-11-08",
            "reported_date": "2026-11-09", "detected_language": "hi",
            "narrative_original": "रवि का फ़ोन 9876543210", "narrative_english": "Truck hit car",
            "alcohol_or_drugs_involved": {"value": False, "evidence": ""},
        })
        self.draft = None

    def __call__(self, model, contents, cfg):
        schema = getattr(cfg, "response_schema", None) if cfg else None
        if schema is ExtractedFNOL:
            return structured(self.extraction)
        if schema is VerdictDraft:
            return structured(self.draft)
        if model.startswith("gemma"):
            return text(contents.split("TEXT:\n", 1)[1].replace("Ravi", "[NAME]"))
        if "banana" in model:
            return image(b"PNGDATA", "rear bumper - severe")
        raise AssertionError(f"unexpected call {model}")


@pytest.fixture
def setup():
    script = Script()
    client = FakeClient(script)
    svc = PlatformService(
        store=InMemoryStore(),
        extractor=GeminiFNOLExtractor(client=client, settings=S),
        redactor=GemmaPIIRedactor(client=client, settings=S),
        policy_extractor=GeminiPolicyClauseExtractor(client=client, settings=S),
        verdict_writer=VerdictWriter(client=client, settings=S),
        annotator=DamageAnnotator(client=client, settings=S),
    )
    return TestClient(create_app(service=svc)), script


def test_multimodal_intake_files_and_justifies(setup):
    c, _ = setup
    r = c.post("/api/intake", data={"text": "accident"},
               files=[("files", ("car.jpg", b"\xff\xd8jpeg", "image/jpeg"))])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["submitted"] is True
    assert d["routing_decision"]["policylens_justification_id"] == d["justification"]["query_id"]
    assert d["justification"]["traced_clauses"]
    assert "9876543210" not in str(d["claim"])  # PII redacted before storage
    actions = [a["action"] for a in d["audit_trail"]]
    assert actions[:2] == ["FNOL_RECEIVED", "PII_REDACTED"]
    assert "DECISION_PERSISTED" in actions


def test_intake_without_policy_number_is_not_filed(setup):
    c, script = setup
    script.extraction.policy_id = ""
    d = c.post("/api/intake", data={"text": "my car broke"}).json()
    assert d["submitted"] is False
    assert "policy number" in d["missing"]
    assert c.get("/api/claims").json() == []


def test_evidenced_alcohol_fact_triggers_exclusion(setup):
    c, script = setup
    script.extraction.alcohol_or_drugs_involved.value = True
    script.extraction.alcohol_or_drugs_involved.evidence = "FIR: driver under influence"
    d = c.post("/api/intake", data={"text": "x"}).json()
    assert d["justification"]["confidence"] == "EXCLUDED"


def test_high_severity_flag_escalates_to_investigation(setup):
    c, script = setup
    script.extraction = ExtractedFNOL.model_validate({
        **script.extraction.model_dump(exclude={"consistency_flags"}),
        "consistency_flags": [{"flag": "damage_inconsistent", "severity": "high",
                               "evidence": "front damage only"}]})
    d = c.post("/api/intake", data={"text": "x"}).json()
    assert d["routing_decision"]["assigned_queue"] == "fraud-investigation"
    assert d["routing_decision"]["decision_type"] == "flag_for_investigation"


def test_verdict_endpoint_validates_and_stores(setup):
    c, script = setup
    claim = c.post("/api/intake", data={"text": "x"}).json()
    refs = [t["clause_ref"] for t in claim["justification"]["traced_clauses"]]
    script.draft = VerdictDraft(decision_stated=claim["justification"]["confidence"],
                                cited_clause_refs=refs[:1], letter_markdown="प्रिय रवि ...",
                                plain_language_summary="...")
    cid = claim["claim"]["id"]
    v = c.post(f"/api/claims/{cid}/verdict?language=hi").json()
    assert v["generator"] == "gemini"
    detail = c.get(f"/api/claims/{cid}").json()
    assert "verdict_hi" in detail["extras"]
    assert detail["audit_trail"][-1]["action"] == "VERDICT_GENERATED"


def test_nano_banana_annotation_keeps_original_hash(setup):
    c, _ = setup
    cid = c.post("/api/intake", data={"text": "x"}).json()["claim"]["id"]
    a = c.post("/api/vision/annotate", data={"claim_id": cid},
               files={"file": ("car.jpg", b"original-bytes", "image/jpeg")}).json()
    assert a["annotated_image"] == "data:image/png;base64," + base64.b64encode(b"PNGDATA").decode()
    import hashlib
    assert a["original_sha256"] == hashlib.sha256(b"original-bytes").hexdigest()


def test_structured_api_and_listing(setup):
    c, _ = setup
    r = c.post("/api/claims", json={
        "policy_id": "HC-STD-2024", "insured_name": "Priya", "claim_type": "health",
        "amount_claimed": 250000, "incident_date": "2026-11-01", "reported_date": "2026-11-02"})
    assert r.status_code == 201
    rows = c.get("/api/claims").json()
    assert rows[0]["queue"] in {"standard", "senior-adjuster", "fast-track", "fraud-investigation"}


def test_config_never_exposes_key(setup):
    c, _ = setup
    assert "secret-key" not in c.get("/api/config").text


def test_policy_upload_with_gemini_grounding(setup):
    c, script = setup
    from src.gemini.schemas import GroundedClause, PolicyExtraction
    wording = "1.1 Flood damage to the insured vehicle is covered under this section."
    original = script.__call__

    def with_policy(model, contents, cfg):
        if getattr(cfg, "response_schema", None) is PolicyExtraction:
            return structured(PolicyExtraction(clauses=[
                GroundedClause(clause_ref="1.1", node_type="coverage",
                               verbatim_text="Flood damage to the insured vehicle is covered "
                                             "under this section.", tags=["motor", "flood"]),
                GroundedClause(clause_ref="1.2", node_type="exclusion",
                               verbatim_text="Invented exclusion that is not in the wording.",
                               tags=["motor"]),
            ]))
        return original(model, contents, cfg)

    c.app.state.service.policy_extractor._client = FakeClient(with_policy)
    r = c.post("/api/policies", json={"policy_id": "MOTOR-1", "policy_name": "Motor",
                                      "wording_text": wording, "extractor": "gemini"})
    assert r.status_code == 201, r.text
    assert r.json()["nodes_added"] == 1
    assert r.json()["rejected_clauses"][0]["clause_ref"] == "1.2"
    clauses = c.get("/api/policies/MOTOR-1/clauses").json()
    assert [x["clause_ref"] for x in clauses] == ["1.1"]


def test_unconfigured_google_ai_returns_503():
    svc = PlatformService(store=InMemoryStore(),
                          extractor=GeminiFNOLExtractor(settings=GoogleAISettings()))
    c = TestClient(create_app(service=svc))
    import src.gemini.client as gc
    gc.get_client.cache_clear()
    r = c.post("/api/intake", data={"text": "x"})
    assert r.status_code == 503


def _scores(fraud=0.0):
    import uuid
    return ScoringResult(claim_id=uuid.uuid4(), severity_score=0.1, complexity_score=0.1,
                         fraud_propensity_score=fraud)


class _Fixed:
    def __init__(self, d, q):
        self.d, self.q = d, q

    def route(self, claim, scores):
        from decimal import Decimal
        return self.d, self.q, Decimal("100")


def _claim(flags):
    from datetime import date
    from decimal import Decimal
    return Claim.new(policy_id="P", claim_type=ClaimType.MOTOR, amount_claimed=Decimal("1000"),
                     incident_date=date(2026, 1, 1), reported_date=date(2026, 1, 2),
                     raw_fnol_text="", metadata={"ai_consistency_flags": flags})


def test_medium_flag_blocks_fast_track_only():
    r = EvidenceAwareRoutingEngine(_Fixed(DecisionType.FAST_TRACK, "fast-track"))
    assert r.route(_claim([{"severity": "medium"}]), _scores())[1] == "standard"
    assert r.route(_claim([{"severity": "low"}]), _scores())[1] == "fast-track"
    r2 = EvidenceAwareRoutingEngine(_Fixed(DecisionType.ROUTE_TO_SENIOR, "senior-adjuster"))
    assert r2.route(_claim([{"severity": "medium"}]), _scores())[1] == "senior-adjuster"


def test_spoken_policy_number_matching(setup):
    c, _ = setup
    svc = c.app.state.service
    assert svc.match_policy("hc std 2024") == "HC-STD-2024"
    assert svc.match_policy("HC-STD-2025") is None
    assert svc.match_policy("") is None
