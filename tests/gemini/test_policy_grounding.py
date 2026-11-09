from src.gemini.config import GoogleAISettings
from src.gemini.policy_extractor import GeminiPolicyClauseExtractor, ground_clauses
from src.gemini.schemas import GroundedClause, PolicyExtraction
from src.policylens.graph.store import NetworkXGraphStore
from src.policylens.loaders.policy_loader import PolicyLoader
from tests.gemini.fakes import FakeClient, structured

WORDING = open("data/sample_policy.txt").read()

GOOD = GroundedClause(
    clause_ref="3.1", node_type="exclusion",
    verbatim_text="This policy does not cover any Pre-existing Disease for the first 48 months "
                  "of continuous coverage.",
    tags=["health", "made-up-tag"])
PARAPHRASED = GroundedClause(
    clause_ref="3.3", node_type="exclusion",
    verbatim_text="Self-harm and suicide attempts are never covered.", tags=["health"])
ALCOHOL = GroundedClause(
    clause_ref="8.1", node_type="exclusion",
    verbatim_text="Damage due to driving under influence of alcohol or drugs is excluded.",
    tags=["motor", "alcohol"])


def test_verbatim_clause_accepted_paraphrase_rejected():
    report = ground_clauses([GOOD, PARAPHRASED], WORDING, "HC")
    assert [c.clause_ref for c in report.accepted] == ["3.1"]
    assert report.rejected == [{"clause_ref": "3.3", "reason": "not verbatim in source"}]


def test_tags_are_restricted_and_rule_tags_added():
    c = ground_clauses([GOOD], WORDING, "HC").accepted[0]
    assert "made-up-tag" not in c.tags
    assert {"exclusion", "health", "pre-existing"} <= set(c.tags)
    assert c.metadata["grounded"] is True


def test_whitespace_and_case_differences_still_ground():
    messy = GOOD.model_copy(update={"verbatim_text": "  this POLICY does not cover any\n"
                                    "Pre-existing   Disease for the first 48 months of "
                                    "continuous coverage. "})
    assert len(ground_clauses([messy], WORDING, "HC").accepted) == 1


def test_gemini_extractor_plugs_into_existing_policy_loader():
    client = FakeClient(lambda m, c, cfg: structured(
        PolicyExtraction(clauses=[GOOD, PARAPHRASED, ALCOHOL])))
    ex = GeminiPolicyClauseExtractor(client=client, settings=GoogleAISettings(gemini_api_key="k"))
    graph = NetworkXGraphStore(persist_path=None)
    added = PolicyLoader(graph=graph, extractor=ex).load("HC-G", "Gemini test", WORDING)
    assert added == 2
    assert len(ex.last_report.rejected) == 1
    texts = [n["text"] for n in graph.get_nodes_by_tags(["alcohol"])]
    assert any("alcohol" in t for t in texts)
