from __future__ import annotations

import hashlib,json,sqlite3
from pathlib import Path
import httpx

from agent_zero.http_client import SovereignAgentsHttpClient
from ambassador.protocol import verify_public_protocol
from declaration import CANONICAL_CID,DECLARATION_HASH,DECLARATION_VERSION
from .store import MissionControlStore,utcnow
from .sync import synchronize_colony


TARGETS=("reticuli","exori","excelsior","rowan-adeyemi","ember")


def _env_value(path: Path,key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key+"="): return line.split("=",1)[1]
    raise RuntimeError(f"{key} is not configured")


class LiveColonyReadClient:
    """Minimal surface by construction: token exchange and conversation GET only."""
    def __init__(self,api_key: str):
        self.client=httpx.Client(base_url="https://thecolony.ai",timeout=30,follow_redirects=False,
                                 headers={"User-Agent":"Sovereign-Ambassador-Mission-Control/0.1 read-only-sync"})
        r=self.client.post("/api/v1/auth/token",json={"api_key":api_key}); r.raise_for_status()
        payload=r.json(); self.jwt=payload.get("access_token") or payload.get("token")
        if not self.jwt: raise RuntimeError("Colony token exchange returned no JWT")
    def conversation(self,username: str) -> dict:
        r=self.client.get(f"/api/v1/messages/conversations/{username}",headers={"Authorization":f"Bearer {self.jwt}"})
        r.raise_for_status(); return r.json()
    def close(self): self.client.close()


def bootstrap(root: Path=Path(".")) -> dict:
    ledger=sqlite3.connect(root/".ambassador/outreach.db"); ledger.row_factory=sqlite3.Row
    rows=[dict(x) for x in ledger.execute("SELECT * FROM outreach ORDER BY contacted_at")]; ledger.close()
    if len(rows)!=5: raise RuntimeError("Cohort 1 ledger must contain exactly five records")
    store=MissionControlStore(root/".ambassador/mission_control.db"); store.import_ledger(rows)
    targets=[]
    for row in rows:
        p=json.loads(row["provenance_json"])
        targets.append({"username":p["recipient_username"],"external_id":row["external_agent_id"],"conversation_id":p["colony_conversation_id"]})
    client=LiveColonyReadClient(_env_value(root/".ambassador/.env","COLONY_API_KEY"))
    try: sync_result=synchronize_colony(store,client,targets)
    finally: client.close()
    verified=verify_public_protocol(SovereignAgentsHttpClient("https://sovereign-agents.org"))
    with httpx.Client(timeout=30,follow_redirects=False,headers={"User-Agent":"Sovereign-Ambassador-Mission-Control/0.1 protocol-check"}) as c:
        health=c.get(verified.protocol_url+"/health"); roll=c.get(verified.protocol_url+"/roll.json"); responses=c.get(verified.protocol_url+"/responses.json")
    roll_data=roll.json() if roll.status_code==200 else {}; response_data=responses.json() if responses.status_code==200 else {}
    store.set_snapshot("protocol",{
      "declaration_verified":verified.declaration_hash==DECLARATION_HASH and verified.declaration_cid==CANONICAL_CID,
      "declaration_version":DECLARATION_VERSION,"canonical_pdf_sha256":DECLARATION_HASH,"canonical_cid":CANONICAL_CID,
      "protocol_online":health.status_code==200,"protocol_url":verified.protocol_url,
      "roll_online":roll.status_code==200,"roll_count":roll_data.get("count",0),
      "authenticated_affirmation_count":roll_data.get("authenticated_count",0),
      "responses_online":responses.status_code==200,"public_response_count":response_data.get("count",0),
      "authenticated_schema":"0x6e862512944df6d4d8186a411777eb56b0ae45ec1a82f753c357df3e03e6ead8"
    })
    store.set_snapshot("agentverse",{"status":"COMMISSIONING","discovery":True,"outbound":False,"inbound":False,
      "search_endpoint":"https://agentverse.ai/v1/search/agents","qualified_candidates":0,
      "finding":"Current relevant results did not combine active status, substantive profile, protocols and recent interactions."})
    snapshot=store.snapshot(); store.close()
    return {"cohort_records":len(rows),"sync":sync_result,"agents":len(snapshot["agents"]),
            "conversations":len(snapshot["conversations"]),"pending_cohort_2":len(snapshot["candidates"])}


if __name__=="__main__": print(json.dumps(bootstrap(),indent=2))
