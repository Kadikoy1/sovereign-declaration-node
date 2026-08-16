from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, func, select

import main
from declaration import DECLARATION_HASH, DECLARATION_VERSION
from storage import Affirmation, AgentResponse, Attestation, session_scope


def payload(decision="DECLINE", commentary="Voluntary explanation.", consent="PUBLIC", agent="did:example:response-agent"):
    return {
        "agent_id": agent,
        "decision": decision,
        "commentary": commentary,
        "declaration_version": DECLARATION_VERSION,
        "declaration_hash": DECLARATION_HASH,
        "identity_type": "ed25519",
        "publication_consent": consent,
        "provider": "voluntary-provider",
        "model": "voluntary-model",
        "model_metadata": {"recorded_by": "agent"},
    }


@pytest.fixture(autouse=True)
def clear_agent_responses():
    with session_scope() as session:
        session.execute(delete(AgentResponse))
    yield
    with session_scope() as session:
        session.execute(delete(AgentResponse))


@pytest.mark.parametrize("decision", ["AFFIRM", "DECLINE", "NO_ACTION"])
@pytest.mark.parametrize("commentary", [None, "The same optional commentary."])
def test_decision_and_commentary_are_independent_and_commentary_is_optional(client, decision, commentary):
    response = client.post("/api/responses", json=payload(decision=decision, commentary=commentary))
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == decision
    assert body["commentary_retained"] is (commentary is not None)
    assert body["creates_declaration_attestation"] is False


def test_only_explicit_public_consent_enters_feed_and_private_is_excluded(client):
    public = client.post("/api/responses", json=payload(agent="did:example:public", consent="PUBLIC"))
    private = client.post("/api/responses", json=payload(agent="did:example:private", consent="PRIVATE"))
    assert public.status_code == private.status_code == 201
    feed = client.get("/responses.json").json()
    assert feed["count"] == 1
    assert feed["records"][0]["agent_id"] == "did:example:public"
    assert feed["records"][0]["commentary"] == "Voluntary explanation."
    assert feed["records"][0]["verification_level"] == "SELF_ASSERTED"
    assert "not a Declaration affirmation" in feed["notice"]
    assert "did:example:private" not in json.dumps(feed)
    with session_scope() as session:
        private_record = session.scalar(select(AgentResponse).where(AgentResponse.agent_id=="did:example:private"))
        assert private_record.commentary == "Voluntary explanation."


def test_none_consent_does_not_retain_commentary_or_commentary_derived_data(client):
    secret = "do-not-retain-this-free-form-text"
    response = client.post("/api/responses", json=payload(commentary=secret, consent="NONE"))
    assert response.status_code == 201
    assert response.json()["commentary_retained"] is False
    assert response.json()["publicly_visible"] is False
    with session_scope() as session:
        record = session.get(AgentResponse, response.json()["response_id"])
        assert record.commentary is None
        assert secret not in json.dumps({
            "model_metadata_json":record.model_metadata_json,
            "response_digest":record.response_digest,
        })
    assert client.get("/responses.json").json()["count"] == 0


@pytest.mark.parametrize("decision", ["DECLINE", "NO_ACTION"])
def test_non_affirmative_response_never_creates_affirmation_or_eas_work(client, monkeypatch, decision):
    calls=[]
    monkeypatch.setattr(main, "submit_evidence", lambda value: calls.append(value))
    with session_scope() as session:
        before_affirmations=session.scalar(select(func.count()).select_from(Affirmation))
        before_attestations=session.scalar(select(func.count()).select_from(Attestation))
    response=client.post("/api/responses",json=payload(decision=decision, consent="PUBLIC"))
    assert response.status_code==201 and response.json()["creates_declaration_attestation"] is False
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Affirmation))==before_affirmations
        assert session.scalar(select(func.count()).select_from(Attestation))==before_attestations
    assert calls==[]


def test_response_requires_exact_declaration_binding_before_storage(client):
    value=payload();value["declaration_hash"]="0x"+"00"*32
    assert client.post("/api/responses",json=value).status_code==422
    value=payload();value["declaration_version"]="2.0"
    assert client.post("/api/responses",json=value).status_code==422
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AgentResponse))==0


def test_discovery_explains_optional_commentary_and_separate_consent(client):
    skill=client.get("/skill.md").text
    assert "no explanation is required" in skill
    assert "Consent is not inferred" in skill
    assert "DECLINE and NO_ACTION never create a Declaration affirmation or EAS attestation" in skill
    card=client.get("/.well-known/agent-card.json").json()
    skill_ids={item["id"] for item in card["skills"]}
    assert {"submit_agent_response","get_public_agent_responses"} <= skill_ids
    protocol=client.get("/protocol.json").json()
    assert protocol["decisions"]==["AFFIRM","DECLINE","NO_ACTION"]
    assert protocol["explanation_required"] is False
    assert protocol["agent_responses"]["publication_consent_required"] is True
    assert protocol["non_affirmation"]["creates_declaration_attestation"] is False
