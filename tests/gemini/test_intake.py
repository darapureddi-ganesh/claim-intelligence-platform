from datetime import date
from decimal import Decimal

import pytest

from src.core.domain.models import ClaimType
from src.gemini.config import GoogleAISettings
from src.gemini.intake import Attachment, GeminiFNOLExtractor, to_fnol_data
from src.gemini.schemas import ConsistencyFlag, EvidencedBool, ExtractedFNOL
from tests.gemini.fakes import FakeClient, structured

SETTINGS = GoogleAISettings(gemini_api_key="test")


def _x(**kw) -> ExtractedFNOL:
    base = dict(policy_id="HC-STD-2024", insured_name="Ravi Kumar", claim_type="motor",
                amount_claimed_inr=85000, incident_date="2026-11-08",
                reported_date="2026-11-09", detected_language="hi",
                narrative_original="कार को ट्रक ने टक्कर मारी",
                narrative_english="A truck hit the car")
    base.update(kw)
    return ExtractedFNOL.model_validate(base)


def test_to_fnol_maps_core_fields():
    f = to_fnol_data(_x())
    assert f.policy_id == "HC-STD-2024"
    assert f.claim_type == ClaimType.MOTOR
    assert f.amount_claimed == Decimal("85000.0")
    assert f.incident_date == date(2026, 11, 8)
    assert f.detected_language == "hi"
    assert f.raw_text == "A truck hit the car"


def test_waiting_period_is_computed_by_code_not_model():
    f = to_fnol_data(_x(policy_start_date="2026-10-20"))
    assert f.metadata["within_waiting_period"] is True
    f = to_fnol_data(_x(policy_start_date="2025-01-01"))
    assert f.metadata["within_waiting_period"] is False


def test_bad_policy_start_date_does_not_trigger_waiting_period():
    f = to_fnol_data(_x(policy_start_date="sometime last year"))
    assert "within_waiting_period" not in f.metadata


def test_unevidenced_exclusion_facts_are_dropped():
    f = to_fnol_data(_x(pre_existing_condition=EvidencedBool(value=True, evidence="")))
    assert "pre_existing_condition" not in f.metadata
    f = to_fnol_data(_x(pre_existing_condition=EvidencedBool(
        value=True, evidence="diabetic for 6 years")))
    assert f.metadata["pre_existing_condition"] is True
    assert f.metadata["pre_existing_evidence"] == "diabetic for 6 years"


def test_reported_before_incident_is_clamped():
    f = to_fnol_data(_x(incident_date="2026-11-08", reported_date="2026-11-01"))
    assert f.reported_date == f.incident_date


def test_missing_policy_becomes_unknown():
    assert to_fnol_data(_x(policy_id="  ")).policy_id == "UNKNOWN"


def test_extractor_sends_attachments_and_schema():
    x = _x(consistency_flags=[ConsistencyFlag(flag="date_mismatch", severity="high",
                                              evidence="bill dated before accident")])
    client = FakeClient(lambda m, c, cfg: structured(x))
    out = GeminiFNOLExtractor(client=client, settings=SETTINGS).extract(
        text="accident", attachments=[Attachment(b"\x89PNG", "image/png", "car.png")])
    assert out.consistency_flags[0].flag == "date_mismatch"
    call = client.models.calls[0]
    assert call["model"] == SETTINGS.gemini_model
    assert call["config"].response_schema is ExtractedFNOL
    parts = call["contents"][0].parts
    assert any(getattr(p, "inline_data", None) for p in parts)


def test_extractor_rejects_unsupported_and_empty():
    ex = GeminiFNOLExtractor(client=FakeClient(lambda *a: None), settings=SETTINGS)
    with pytest.raises(ValueError):
        ex.extract(attachments=[Attachment(b"x", "application/zip", "a.zip")])
    with pytest.raises(ValueError):
        ex.extract(text="   ")
