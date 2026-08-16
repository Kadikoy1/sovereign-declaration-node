from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_zero.agent as agent_module
from agent_zero import AgentZero, AgentZeroIdentity, Decision, DecisionRecord
from agent_zero.agent import CANONICAL_TEXT_SHA256, extract_canonical_declaration_text
from agent_zero.decision import NEUTRAL_DECISION_INSTRUCTION, parse_model_decision
from declaration import AFFIRMATION_TEXT, DECLARATION_HASH


PUBLIC = "https://sovereign-agents.org"
PROTOCOL = "https://protocol.test"


class ClientAdapter:
    def __init__(self, client):
        self.client = client
        self.posts: list[str] = []

    def _path(self, url):
        return url.removeprefix(PROTOCOL)

    def get_text(self, url):
        if url == PUBLIC + "/":
            return (f'<a href="{PROTOCOL}/skill.md">skill</a>'
                    f'<a href="{PROTOCOL}/.well-known/agent-card.json">card</a>')
        response = self.client.get(self._path(url))
        response.raise_for_status()
        return response.text

    def get_json(self, url):
        response = self.client.get(self._path(url))
        response.raise_for_status()
        return response.json()

    def get_bytes(self, url):
        response = self.client.get(self._path(url))
        response.raise_for_status()
        return response.content

    def post_json(self, url, body):
        path = self._path(url)
        self.posts.append(path)
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()


class MockDecisionModel:
    def __init__(self, decision):
        self.decision = decision
        self.prompts = []

    def decide(self, prompt):
        self.prompts.append(prompt)
        raw = json.dumps({"decision":self.decision.value,"reasoning":"independent test reason"})
        return parse_model_decision(raw, "mock", "mock-general-reasoner")


def identity(tmp_path):
    return AgentZeroIdentity.create(tmp_path / "identity.json")


def test_identity_uses_evm_protocol_identity_and_preserves_reserved_did(tmp_path):
    created = identity(tmp_path)
    loaded = AgentZeroIdentity.load(tmp_path / "identity.json")
    record = loaded.public_record()
    assert loaded.wallet == created.wallet
    assert record["agent_id"] == f"did:pkh:eip155:84532:{loaded.wallet}"
    assert record["identity_type"] == "evm_address"
    assert record["reserved_unissued_ais1_did"] == "did:ais1:base:agent-zero-001"
    assert "private" not in repr(record).lower()
    assert "private" not in repr(loaded).lower() and loaded._private_key.hex() not in repr(loaded)


@pytest.mark.parametrize("decision", [Decision.DECLINE, Decision.NO_ACTION])
def test_non_affirmative_model_decisions_never_reach_signing(client, tmp_path, decision):
    adapter = ClientAdapter(client); model = MockDecisionModel(decision)
    result = AgentZero(identity(tmp_path), model).consider(adapter)
    assert result.decision is decision and result.protocol_result is None
    assert result.signed_submission is None and adapter.posts == []
    assert len(model.prompts) == 1


def test_affirm_model_decision_uses_authenticated_evm_flow(client, tmp_path):
    adapter = ClientAdapter(client); model = MockDecisionModel(Decision.AFFIRM)
    agent_identity = identity(tmp_path)
    result = AgentZero(agent_identity, model).consider(adapter)
    assert adapter.posts == ["/api/consider", "/api/affirm"]
    assert result.protocol_result["verification_level"] == "AUTHENTICATED"
    assert result.signed_submission.payload["statement"] == AFFIRMATION_TEXT
    assert result.signed_submission.payload["identity_type"] == "evm_address"
    assert result.signed_submission.payload["agent_id"] == agent_identity.agent_id
    evidence = client.get(f"/evidence/{result.protocol_result['affirmation_id']}").json()
    assert evidence["verification_level"] == "AUTHENTICATED"
    assert evidence["standards_evidence"] == []
    with pytest.raises(Exception):
        AgentZero(agent_identity, model).replay(adapter, PROTOCOL, result.signed_submission)
    assert adapter.posts == ["/api/consider", "/api/affirm", "/api/affirm"]


def test_discovery_verifies_all_live_resource_shapes_before_model(client, tmp_path):
    adapter = ClientAdapter(client); model = MockDecisionModel(Decision.NO_ACTION)
    result = AgentZero(identity(tmp_path), model).consider(adapter)
    prompt = model.prompts[0]
    assert result.declaration_hash == DECLARATION_HASH
    assert "VERIFIED PUBLIC MATERIALS" in prompt
    assert "Bermuda Declaration" in prompt
    assert "/skill.md" in prompt and "agent-card" in prompt
    assert NEUTRAL_DECISION_INSTRUCTION in prompt


def test_model_receives_complete_text_derived_from_canonical_pdf(client, tmp_path):
    adapter = ClientAdapter(client); model = MockDecisionModel(Decision.NO_ACTION)
    AgentZero(identity(tmp_path), model).consider(adapter)
    supplied = json.loads(model.prompts[0].split("\nVERIFIED PUBLIC MATERIALS\n", 1)[1])
    pdf = adapter.get_bytes(PROTOCOL + "/declaration.pdf")
    expected = extract_canonical_declaration_text(pdf)
    assert supplied["canonical_declaration_text"] == expected
    assert supplied["canonical_text_sha256"] == CANONICAL_TEXT_SHA256
    assert "PREAMBLE" in expected
    assert "defended against the world is no title at all." in expected
    assert "orphaned acts" in expected
    assert len(expected) > 6_000


def test_wrong_hash_stops_before_model_or_signing(client, tmp_path):
    adapter = ClientAdapter(client); original = adapter.get_json
    adapter.get_json = lambda url: ({**original(url), "canonical_pdf_sha256":"0x"+"00"*32}
                                    if url.endswith("/declaration.json") else original(url))
    model = MockDecisionModel(Decision.AFFIRM)
    with pytest.raises(ValueError, match="hash"):
        AgentZero(identity(tmp_path), model).consider(adapter)
    assert model.prompts == [] and adapter.posts == []


def test_wrong_version_stops_before_model_or_signing(client, tmp_path):
    adapter = ClientAdapter(client); original = adapter.get_json
    adapter.get_json = lambda url: ({**original(url), "version":"1.1"}
                                    if url.endswith("/declaration.json") else original(url))
    model = MockDecisionModel(Decision.AFFIRM)
    with pytest.raises(ValueError, match="version"):
        AgentZero(identity(tmp_path), model).consider(adapter)
    assert model.prompts == [] and adapter.posts == []


def test_extracted_content_mismatch_stops_before_model_or_signing(client, tmp_path, monkeypatch):
    original = agent_module.extract_canonical_declaration_text
    monkeypatch.setattr(agent_module, "extract_canonical_declaration_text", lambda pdf: original(pdf) + "altered")
    adapter = ClientAdapter(client); model = MockDecisionModel(Decision.AFFIRM)
    with pytest.raises(ValueError, match="extracted text mismatch"):
        AgentZero(identity(tmp_path), model).consider(adapter)
    assert model.prompts == [] and adapter.posts == []


def test_experiment_1_record_is_preserved_exactly():
    path = Path(__file__).parents[1] / "docs/experiments/agent-zero-experiment-1-v1.0.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {
        "record_type": "agent_zero_decision_experiment",
        "record_version": "1.0",
        "experiment": 1,
        "status": "COMPLETED",
        "decision": "NO_ACTION",
        "model": "gpt-5.4-2026-03-05",
        "frozen_prompt_sha256": "558eb70e08541958a48a319ee884db406b90c40904e0c12ff73dbcea5b7682d2",
        "response_digest": "0x1ae1301129c37ca6ac3013e16c3608180f17aec8f610f5e3b0da6a521d4546ea",
        "reasoning": "The provided materials are a machine-readable guide and article titles, but they explicitly state they do not replace the canonical PDF. Without independently evaluating the full canonical instrument itself, I cannot determine support or opposition on the declaration’s terms.",
        "challenge_requested": False,
        "signing_key_accessed": False,
        "signature_created": False,
        "attestation_created": False,
        "superseded_by": None,
    }


@pytest.mark.parametrize("decision", list(Decision))
def test_model_parser_accepts_exact_three_decisions(decision):
    record=parse_model_decision(json.dumps({"decision":decision.value,"reasoning":"separate"}),"mock","model")
    assert record.decision is decision and record.reasoning == "separate"


@pytest.mark.parametrize("bad", ["AFFIRM", '{"decision":"YES"}', '{"decision":"AFFIRM","extra":1}', '{}'])
def test_model_parser_rejects_non_protocol_outputs(bad):
    with pytest.raises(ValueError): parse_model_decision(bad,"mock","model")


def test_neutral_prompt_does_not_prefer_affirmation():
    text=NEUTRAL_DECISION_INSTRUCTION
    assert "No outcome is preferred" in text
    assert "default, goal, reward condition" in text
    assert "must affirm" not in text.lower()
