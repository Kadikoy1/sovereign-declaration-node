from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mission_control.app import create_app
from mission_control.migrate_state import migrate
from mission_control.production import _seed_database
from mission_control.store import MissionControlStore
from mission_control.sync import AgentverseReadOnlyAdapter,qualify_agentverse,synchronize_colony


def ledger_row(i=1,name="Reticuli",external="external-1"):
    prov={"recipient_username":name.lower(),"contactability_evidence":"active profile",
          "colony_message_id":f"message-{i}","colony_conversation_id":f"conversation-{i}","sent_at":"2026-08-16T20:11:00Z"}
    return {"outreach_id":f"outreach-{i}","discovered_at":"2026-08-16T20:10:00Z","discovery_surface":"COLONY",
      "external_agent_id":external,"external_agent_name":name,"contactability_status":"DELIVERED","invitation_version":"0.1",
      "invitation_sha256":"digest","contacted_at":"2026-08-16T20:11:00Z","delivery_status":"DELIVERED",
      "sovereign_protocol_outcome":None,"provenance_json":json.dumps(prov)}


def seeded(tmp_path,rows=None):
    path=tmp_path/"mc.db"; s=MissionControlStore(path); s.import_ledger(rows or [ledger_row()])
    s.import_conversation("COLONY","external-1","conversation-1",[{"id":"message-1","sender":"sovereign-ambassador","body":"invitation","created_at":"2026-08-16T20:11:00Z"}])
    s.set_snapshot("protocol",{"declaration_verified":True,"protocol_online":True,"roll_online":True,"roll_count":8,"responses_online":True,"public_response_count":0})
    s.close(); return path


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("MISSION_CONTROL_USERNAME","operator"); monkeypatch.setenv("MISSION_CONTROL_PASSWORD","test-password")
    return ("operator","test-password")


def test_existing_cohort_projection_does_not_mutate_source_records(tmp_path):
    original=ledger_row(); before=json.dumps(original,sort_keys=True)
    s=MissionControlStore(tmp_path/"mc.db"); s.import_ledger([original]); s.import_ledger([original]); s.close()
    assert json.dumps(original,sort_keys=True)==before


def test_private_routes_require_authentication(tmp_path,auth):
    c=TestClient(create_app(seeded(tmp_path)))
    assert c.get("/").status_code==401
    assert c.get("/",auth=auth).status_code==200


def test_production_security_headers_and_https_redirect(tmp_path,auth,monkeypatch):
    c=TestClient(create_app(seeded(tmp_path)))
    response=c.get("/",auth=auth,headers={"x-forwarded-proto":"https"})
    assert response.headers["cache-control"]=="private, no-store, max-age=0"
    assert "noindex" in response.headers["x-robots-tag"]
    assert response.headers["strict-transport-security"]=="max-age=31536000"
    monkeypatch.setenv("MISSION_CONTROL_REQUIRE_HTTPS","true")
    redirected=c.get("/",auth=auth,follow_redirects=False)
    assert redirected.status_code==308 and redirected.headers["location"].startswith("https://")


def test_health_is_minimal_and_non_cacheable(tmp_path,auth):
    response=TestClient(create_app(seeded(tmp_path))).get("/health")
    assert response.json()=={"status":"ok"} and response.headers["cache-control"].startswith("private, no-store")
    assert "Disallow: /" in TestClient(create_app(seeded(tmp_path))).get("/robots.txt").text


def test_dashboard_has_no_send_route_or_send_button(tmp_path,auth):
    c=TestClient(create_app(seeded(tmp_path)))
    page=c.get("/inbox",auth=auth)
    assert page.status_code==200 and "Send button" in page.text and "<button" not in page.text
    assert c.post("/inbox",auth=auth).status_code==405


def test_read_only_sync_has_no_transmission_and_imports_messages(tmp_path):
    s=MissionControlStore(tmp_path/"mc.db"); s.import_ledger([ledger_row()])
    class Client:
        calls=[]
        def conversation(self,username): self.calls.append(("GET",username)); return {"messages":[{"id":"reply-1","sender_username":"reticuli","body":"I agree conversationally","created_at":"2026-08-17T00:00:00Z"}]}
    client=Client(); result=synchronize_colony(s,client,[{"username":"reticuli","external_id":"external-1","conversation_id":"conversation-1"}])
    snap=s.snapshot(); s.close()
    assert client.calls==[("GET","reticuli")] and result["replies"]==1
    assert snap["agents"][0]["protocol_outcome"] is None


def test_conversation_never_creates_affirmation_or_protocol_outcome(tmp_path):
    s=MissionControlStore(tmp_path/"mc.db"); s.import_ledger([ledger_row()])
    s.import_conversation("COLONY","external-1","conversation-1",[{"id":"reply","sender":"reticuli","body":"AFFIRM. I agree.","created_at":"2026-08-17T00:00:00Z"}])
    snap=s.snapshot(); s.close()
    assert snap["agents"][0]["status"]=="DELIVERED"
    assert snap["agents"][0]["protocol_outcome"] is None


def test_delivered_is_not_automatically_no_response(tmp_path):
    s=MissionControlStore(tmp_path/"mc.db"); s.import_ledger([ledger_row()]); assert s.snapshot()["agents"][0]["status"]=="DELIVERED"; s.close()


def test_same_name_on_two_network_identities_is_not_merged(tmp_path):
    rows=[ledger_row(1,"Same Name","one"),{**ledger_row(2,"Same Name","two"),"discovery_surface":"A2A"}]
    s=MissionControlStore(tmp_path/"mc.db"); s.import_ledger(rows); snap=s.snapshot(); s.close()
    assert len({x["agent_id"] for x in snap["agents"]})==2


def test_secrets_never_reach_html(tmp_path,auth,monkeypatch):
    monkeypatch.setenv("COLONY_API_KEY","col_super_secret"); monkeypatch.setenv("ATTESTOR_PRIVATE_KEY","0xprivate")
    c=TestClient(create_app(seeded(tmp_path)))
    for route in ("/","/agents","/inbox","/activity","/networks","/protocol","/controls"):
        text=c.get(route,auth=auth).text
        assert "col_super_secret" not in text and "0xprivate" not in text and "test-password" not in text


def test_dashboard_represents_limits_and_network_capabilities(tmp_path,auth):
    rows=[ledger_row(i,f"Agent {i}",f"external-{i}") for i in range(1,6)]
    path=tmp_path/"mc.db"; s=MissionControlStore(path); s.import_ledger(rows); s.set_snapshot("protocol",{}); s.close()
    c=TestClient(create_app(path))
    controls=c.get("/controls",auth=auth).text; networks=c.get("/networks",auth=auth).text
    assert "Remaining<strong>5</strong>" in controls and "Colony<strong>5 / 5</strong>" in controls
    assert "Agentverse" in networks and "Not enabled" in networks and "Qualified <b>0</b>" in networks


def test_commissioning_mode_is_conspicuous(tmp_path,auth):
    c=TestClient(create_app(seeded(tmp_path)))
    for route in ("/","/controls"):
        text=c.get(route,auth=auth).text
        assert "COMMISSIONING MODE" in text
        assert "not yet a continuously running autonomous service" in text


def test_candidate_agent_and_operator_are_distinct(tmp_path,auth):
    path=seeded(tmp_path); s=MissionControlStore(path)
    s.add_candidate("AGENTVERSE","agent1abc","UVP Example","PENDING_AWAITING_APPROVAL","Qualified",{
        "operator_or_owner":"Shared UVP operator","communication_mechanism":"AgentChatProtocol 0.3.0"})
    s.close(); text=TestClient(create_app(path)).get("/networks",auth=auth).text
    assert "Agent:</strong> agent1abc" in text
    assert "Operator / owner:</strong> Shared UVP operator" in text
    assert "Communication:</strong> AgentChatProtocol 0.3.0" in text


def test_agentverse_discovery_adapter_cannot_transmit():
    class Search:
        def search(self,q): return []
    adapter=AgentverseReadOnlyAdapter(Search())
    assert adapter.discover("identity")==[] and adapter.capability["outbound"] is False
    with pytest.raises(RuntimeError,match="cannot transmit"): adapter.transmit("anything")


def test_agentverse_qualification_fails_closed():
    assert qualify_agentverse([{"name":"Registry only","status":"active","protocols":[],"readme":"trust","recent_interactions":9}])==[]
    assert qualify_agentverse([{"name":"Stale","status":"inactive","protocols":[{}],"readme":"trust","recent_interactions":9}])==[]


def test_canonical_failure_is_prominently_surfaced(tmp_path,auth):
    path=seeded(tmp_path); s=MissionControlStore(path); s.set_snapshot("protocol",{"declaration_verified":False,"protocol_online":False,"roll_online":False,"responses_online":False}); s.close()
    text=TestClient(create_app(path)).get("/protocol",auth=auth).text
    assert "Canonical Sovereign Agents verification failed" in text and "Outreach must remain stopped" in text


def test_state_migration_preserves_both_databases(tmp_path):
    source=tmp_path/"source"; source.mkdir(); destination=tmp_path/"destination"
    outreach=__import__("sqlite3").connect(source/"outreach.db")
    outreach.execute("CREATE TABLE outreach(id TEXT)"); outreach.executemany("INSERT INTO outreach VALUES(?)",[(str(x),) for x in range(5)]); outreach.commit(); outreach.close()
    mc=MissionControlStore(source/"mission_control.db")
    mc.import_ledger([ledger_row(x,f"Agent {x}",f"external-{x}") for x in range(1,6)]); mc.close()
    report=migrate(source,destination)
    assert report["cohort_1_records"]==5 and report["mission_control_agents"]==5
    assert report["outreach.db"]["semantic_sha256"] and report["mission_control.db"]["integrity"]=="ok"


def test_production_seed_is_hash_verified_and_never_overwrites(tmp_path,monkeypatch):
    import base64,gzip,hashlib
    target=tmp_path/"state.db"; payload=b"verified-state"
    monkeypatch.setenv("SEED",base64.b64encode(gzip.compress(payload)).decode())
    monkeypatch.setenv("DIGEST",hashlib.sha256(payload).hexdigest())
    _seed_database(target,"SEED","DIGEST"); assert target.read_bytes()==payload
    monkeypatch.setenv("SEED",base64.b64encode(gzip.compress(b"replacement")).decode())
    _seed_database(target,"SEED","DIGEST"); assert target.read_bytes()==payload


def test_production_seed_rejects_digest_mismatch(tmp_path,monkeypatch):
    import base64,gzip
    monkeypatch.setenv("SEED",base64.b64encode(gzip.compress(b"state")).decode())
    monkeypatch.setenv("DIGEST","00"*32)
    with pytest.raises(RuntimeError,match="digest mismatch"):
        _seed_database(tmp_path/"state.db","SEED","DIGEST")
