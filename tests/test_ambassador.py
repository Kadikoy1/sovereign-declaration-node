from __future__ import annotations

import hashlib

import pytest

import ambassador.service as service_module
from ambassador.adapters import A2AAdapter
from ambassador.constants import INVITATION_BYTES, INVITATION_SHA256, INVITATION_VERSION
from ambassador.ledger import Candidate, OutreachLedger, OutreachStatus, Surface
from ambassador.protocol import VerifiedProtocol
from ambassador.service import SovereignAmbassador


VERIFIED = VerifiedProtocol("https://sovereign-agents.org", "https://protocol.test", "1.0", "0x"+"ab"*32, "bafk-test")


def candidate(surface: Surface, number: int, *, contactable: bool = True) -> Candidate:
    if surface is Surface.COLONY:
        return Candidate(surface,f"colony-{number}",f"Colony {number}","COLONY_DM",
                         f"https://thecolony.ai/api/v1/messages/send/agent-{number}",
                         unsolicited_contact_permitted=contactable,canonical_agent_key=f"colony:{number}")
    return Candidate(surface,f"a2a-{number}",f"A2A {number}","A2A_JSONRPC",
                     f"https://agent-{number}.example/a2a",card_url=f"https://agent-{number}.example/.well-known/agent-card.json",
                     unsolicited_contact_permitted=contactable,canonical_agent_key=f"a2a:{number}")


@pytest.fixture
def verified(monkeypatch):
    monkeypatch.setattr(service_module,"verify_public_protocol",lambda client: VERIFIED)


def test_invitation_is_frozen_utf8_and_digest_matches():
    INVITATION_BYTES.decode("utf-8")
    assert hashlib.sha256(INVITATION_BYTES).hexdigest() == INVITATION_SHA256
    assert INVITATION_VERSION == "0.1"
    assert b"No outcome is preferred" in INVITATION_BYTES


def test_global_ten_invitation_ceiling(tmp_path):
    ledger=OutreachLedger(tmp_path/"ledger.db")
    ids=[]
    for surface in (Surface.COLONY,Surface.A2A):
        for i in range(5): ids.append(ledger.discover(candidate(surface,i)))
    for oid in ids: ledger.reserve_invitation(oid,INVITATION_VERSION,INVITATION_SHA256)
    extra=ledger.discover(Candidate(Surface.A2A,"extra","Extra","A2A_JSONRPC","https://extra.example/a2a",
                                    unsolicited_contact_permitted=True,canonical_agent_key="extra"))
    with pytest.raises(RuntimeError,match="global invitation ceiling"):
        ledger.reserve_invitation(extra,INVITATION_VERSION,INVITATION_SHA256)


@pytest.mark.parametrize("surface",list(Surface))
def test_five_per_surface_ceiling(surface,tmp_path):
    ledger=OutreachLedger(tmp_path/f"{surface}.db")
    for i in range(5):
        oid=ledger.discover(candidate(surface,i)); ledger.reserve_invitation(oid,"0.1","digest")
    oid=ledger.discover(candidate(surface,99))
    with pytest.raises(RuntimeError,match="invitation ceiling"):
        ledger.reserve_invitation(oid,"0.1","digest")


def test_duplicate_suppression_and_restart_never_resends(tmp_path):
    path=tmp_path/"resume.db"; ledger=OutreachLedger(path); c=candidate(Surface.COLONY,1)
    first=ledger.discover(c); second=ledger.discover(c)
    assert first == second and len(ledger.rows()) == 1
    ledger.reserve_invitation(first,"0.1","digest")
    resumed=OutreachLedger(path); assert resumed.discover(c) == first
    with pytest.raises(ValueError,match="already invited"):
        resumed.reserve_invitation(first,"0.1","digest")


def test_silence_is_no_response_never_no_action(tmp_path):
    ledger=OutreachLedger(tmp_path/"x.db"); oid=ledger.discover(candidate(Surface.COLONY,1))
    ledger.record_remote(oid,response=None,explicit_outcome=None)
    row=ledger.rows()[0]
    assert row["contactability_status"] == OutreachStatus.NO_RESPONSE
    assert row["sovereign_protocol_outcome"] is None


@pytest.mark.parametrize("outcome",["DECLINE","NO_ACTION"])
def test_decline_and_no_action_are_retained(outcome,tmp_path):
    ledger=OutreachLedger(tmp_path/f"{outcome}.db"); oid=ledger.discover(candidate(Surface.A2A,1))
    ledger.record_remote(oid,response=outcome,explicit_outcome=outcome)
    row=ledger.rows()[0]
    assert row["contactability_status"] == outcome and row["affirmation_uid"] is None


def test_natural_language_agreement_is_not_authenticated_affirmation(tmp_path):
    ledger=OutreachLedger(tmp_path/"x.db"); oid=ledger.discover(candidate(Surface.A2A,1))
    ledger.record_remote(oid,response="Sounds good, I agree",explicit_outcome=None)
    row=ledger.rows()[0]
    assert row["contactability_status"] == OutreachStatus.RESPONDED
    assert row["sovereign_protocol_outcome"] is None and row["affirmation_uid"] is None


@pytest.mark.parametrize("card,reachable",[
    ({"name":"Broken","url":"http://localhost:9","version":"1","skills":[{"id":"x"}]},True),
    ({"name":"No skills","url":"https://agent.example/a2a","version":"1"},True),
    ({"name":"Offline","url":"https://agent.example/a2a","version":"1","skills":[{"id":"x"}]},False),
])
def test_malformed_untrusted_or_unreachable_agent_cards_fail_closed(card,reachable):
    with pytest.raises(ValueError): A2AAdapter().validate_card("https://agent.example/.well-known/agent-card.json",card,reachable)


def test_uncontactable_candidate_is_not_prepared(tmp_path,verified):
    ambassador=SovereignAmbassador(OutreachLedger(tmp_path/"x.db"),object())
    with pytest.raises(ValueError,match="not contactable"):
        ambassador.prepare(candidate(Surface.COLONY,1,contactable=False))


def test_protocol_failure_stops_before_outreach_record(tmp_path,monkeypatch):
    ledger=OutreachLedger(tmp_path/"x.db")
    monkeypatch.setattr(service_module,"verify_public_protocol",lambda client: (_ for _ in ()).throw(ValueError("canonical mismatch")))
    with pytest.raises(ValueError,match="canonical mismatch"):
        SovereignAmbassador(ledger,object()).prepare(candidate(Surface.COLONY,1))
    assert ledger.rows() == []


def test_dry_run_can_generate_but_cannot_transmit(tmp_path,verified):
    class Transport:
        called=False
        def send(self,request): self.called=True; return {}
    transport=Transport(); ambassador=SovereignAmbassador(OutreachLedger(tmp_path/"x.db"),object(),dry_run=True,transport=transport)
    prepared=ambassador.prepare(candidate(Surface.A2A,1))
    assert prepared.request["method"] == "POST" and "No outcome is preferred" in str(prepared.request)
    with pytest.raises(RuntimeError,match="cannot transmit"): ambassador.invite(prepared)
    assert not transport.called and ambassador.ledger.contacted_count() == 0


def test_exactly_one_invitation_and_no_follow_up(tmp_path,verified):
    class Transport:
        calls=0
        def send(self,request): self.calls += 1; return {"accepted":True}
    t=Transport(); ambassador=SovereignAmbassador(OutreachLedger(tmp_path/"x.db"),object(),dry_run=False,transport=t)
    prepared=ambassador.prepare(candidate(Surface.COLONY,1)); ambassador.invite(prepared)
    with pytest.raises(ValueError,match="already invited"): ambassador.invite(prepared)
    assert t.calls == 1
