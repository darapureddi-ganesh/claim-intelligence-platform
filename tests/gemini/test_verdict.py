import uuid
from datetime import date
from decimal import Decimal

from src.core.domain.models import Claim, ClaimType, DecisionType, RoutingDecision, ScoringResult
from src.core.domain.ports import ClauseReference, JustificationResult
from src.gemini.config import GoogleAISettings
from src.gemini.schemas import VerdictDraft
from src.gemini.verdict import VerdictWriter, template_letter, validate_draft
from tests.gemini.fakes import FakeClient, structured

CLAIM = Claim.new(policy_id="HC-STD-2024", claim_type=ClaimType.HEALTH,
                  amount_claimed=Decimal("640000"), incident_date=date(2026, 11, 1),
                  reported_date=date(2026, 11, 4), raw_fnol_text="surgery",
                  insured_name="Priya Sharma", language="ta")
JUST = JustificationResult(
    query_id=uuid.uuid4(), claim_id=CLAIM.id, justification_text="...",
    traced_clauses=[
        ClauseReference("n1", "3.1", "Pre-existing Disease excluded...", ["exclusion"])],
    confidence="EXCLUDED")
DECISION = RoutingDecision.new(
    claim_id=CLAIM.id,
    scoring=ScoringResult(claim_id=CLAIM.id, severity_score=0.8, complexity_score=0.5,
                          fraud_propensity_score=0.1),
    decision_type=DecisionType.ROUTE_TO_SENIOR, assigned_queue="senior-adjuster",
    reserve_suggestion=Decimal("700000"), policylens_justification_id=JUST.query_id)
SETTINGS = GoogleAISettings(gemini_api_key="k")


def _draft(**kw) -> VerdictDraft:
    base = dict(decision_stated="EXCLUDED", cited_clause_refs=["3.1"],
                letter_markdown="அன்புள்ள பிரியா... Section 3.1 ...",
                plain_language_summary="...")
    base.update(kw)
    return VerdictDraft(**base)


def test_valid_draft_passes():
    assert validate_draft(_draft(), "EXCLUDED", ["3.1"]) == []


def test_changed_status_rejected():
    assert validate_draft(_draft(decision_stated="COVERED"), "EXCLUDED", ["3.1"])


def test_invented_clause_rejected_even_if_only_in_text():
    errs = validate_draft(_draft(letter_markdown="... as per Section 9.9 ..."), "EXCLUDED", ["3.1"])
    assert any("9.9" in e for e in errs)


def test_section_prefix_is_normalised():
    assert validate_draft(_draft(cited_clause_refs=["Section 3.1"]), "EXCLUDED", ["3.1"]) == []


def test_no_citation_rejected_when_clauses_exist():
    draft = _draft(cited_clause_refs=[], letter_markdown="Hello")
    assert validate_draft(draft, "EXCLUDED", ["3.1"])


def test_writer_uses_gemini_when_valid():
    client = FakeClient(lambda m, c, cfg: structured(_draft()))
    letter = VerdictWriter(client=client, settings=SETTINGS).write(CLAIM, DECISION, JUST, "ta")
    assert letter.generator == "gemini" and letter.language == "ta"
    prompt = client.models.calls[0]["contents"]
    assert "COVERAGE STATUS (fixed, do not change): EXCLUDED" in prompt
    assert "[3.1]" in prompt


def test_writer_falls_back_to_template_on_bad_draft():
    client = FakeClient(lambda m, c, cfg: structured(_draft(decision_stated="COVERED")))
    letter = VerdictWriter(client=client, settings=SETTINGS).write(CLAIM, DECISION, JUST, "ta")
    assert letter.generator == "template"
    assert letter.validation_errors
    assert "EXCLUDED" in letter.letter_markdown and "3.1" in letter.letter_markdown


def test_writer_falls_back_when_gemini_errors():
    def boom(*a):
        raise RuntimeError("quota")
    letter = VerdictWriter(client=FakeClient(boom), settings=SETTINGS).write(
        CLAIM, DECISION, JUST, "hi")
    assert letter.generator == "template"


def test_template_mentions_grievance_route():
    t = template_letter(CLAIM, DECISION, JUST)
    assert "Bima Bharosa" in t.letter_markdown and "Ombudsman" in t.letter_markdown
