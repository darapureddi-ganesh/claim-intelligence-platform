from src.gemini.config import GoogleAISettings
from src.gemini.pii import GemmaPIIRedactor, regex_redact
from tests.gemini.fakes import FakeClient, text

RAW = ("Ravi Kumar, Aadhaar 2345 6789 0123, PAN ABCDE1234F, phone +91 98765 43210, "
       "ravi@example.com, lives at 12 MG Road, Bengaluru. Admitted to Apollo.")


def test_regex_redacts_indian_identifiers():
    r = regex_redact(RAW)
    for leaked in ("2345 6789 0123", "ABCDE1234F", "98765 43210", "ravi@example.com"):
        assert leaked not in r.text
    assert r.counts == {"AADHAAR": 1, "PAN": 1, "EMAIL": 1, "PHONE": 1}
    assert "Apollo" in r.text


def test_gemma_adds_names_and_addresses():
    def gemma(model, contents, cfg):
        assert model.startswith("gemma")
        body = contents.split("TEXT:\n", 1)[1]
        return text(body.replace("Ravi Kumar", "[NAME]").replace("12 MG Road", "[ADDRESS]"))
    r = GemmaPIIRedactor(client=FakeClient(gemma),
                         settings=GoogleAISettings(gemini_api_key="k")).redact(RAW)
    assert r.engine == "regex+gemma"
    assert "Ravi Kumar" not in r.text and "12 MG Road" not in r.text
    assert r.counts["NAME"] == 1 and r.counts["ADDRESS"] == 1


def test_gemma_output_that_unredacts_is_rejected():
    r = GemmaPIIRedactor(client=FakeClient(lambda *a: text(RAW)),
                         settings=GoogleAISettings(gemini_api_key="k")).redact(RAW)
    assert r.engine == "regex"
    assert "ABCDE1234F" not in r.text


def test_gemma_chatty_output_is_rejected():
    chatty = "Sure! Here is the redacted text you asked for. " * 20
    r = GemmaPIIRedactor(client=FakeClient(lambda *a: text(chatty)),
                         settings=GoogleAISettings(gemini_api_key="k")).redact(RAW)
    assert r.engine == "regex"


def test_no_backend_means_regex_only():
    r = GemmaPIIRedactor(settings=GoogleAISettings(gemini_api_key="")).redact(RAW)
    assert r.engine == "regex"
