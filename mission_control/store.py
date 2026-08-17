from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  agent_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, created_at TEXT NOT NULL,
  correlation_status TEXT NOT NULL DEFAULT 'UNRELATED_UNTIL_PROVEN'
);
CREATE TABLE IF NOT EXISTS network_identities (
  identity_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  network TEXT NOT NULL, external_id TEXT NOT NULL, username TEXT, profile_url TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}', UNIQUE(network, external_id)
);
CREATE TABLE IF NOT EXISTS discoveries (
  discovery_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL REFERENCES network_identities(identity_id),
  source TEXT NOT NULL, discovered_at TEXT NOT NULL, qualification_status TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS outreach_records (
  outreach_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL REFERENCES network_identities(identity_id),
  ledger_outreach_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, invitation_version TEXT,
  invitation_sha256 TEXT, contacted_at TEXT, delivery_status TEXT, protocol_outcome TEXT,
  evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL REFERENCES network_identities(identity_id),
  network TEXT NOT NULL, external_conversation_id TEXT NOT NULL,
  synchronized_at TEXT NOT NULL, read_only INTEGER NOT NULL DEFAULT 1,
  UNIQUE(network, external_conversation_id)
);
CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  network TEXT NOT NULL, external_message_id TEXT NOT NULL, sender_external_id TEXT,
  direction TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT, imported_at TEXT NOT NULL,
  UNIQUE(network, external_message_id)
);
CREATE TABLE IF NOT EXISTS protocol_evidence (
  evidence_id TEXT PRIMARY KEY, identity_id TEXT REFERENCES network_identities(identity_id),
  evidence_type TEXT NOT NULL, authoritative INTEGER NOT NULL, payload_json TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operational_events (
  event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, occurred_at TEXT NOT NULL,
  agent_id TEXT REFERENCES agents(agent_id), human_summary TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS network_candidates (
  candidate_id TEXT PRIMARY KEY, network TEXT NOT NULL, external_id TEXT NOT NULL,
  display_name TEXT, status TEXT NOT NULL, rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}', UNIQUE(network, external_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, observed_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class MissionControlStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA); self.db.commit()

    def close(self) -> None: self.db.close()

    def import_ledger(self, ledger_rows: list[dict[str, Any]]) -> None:
        """Idempotently project immutable outreach facts without rewriting the source ledger."""
        for row in ledger_rows:
            provenance=json.loads(row.get("provenance_json") or "{}")
            network=row["discovery_surface"]
            external_id=row["external_agent_id"]
            identity=self.db.execute("SELECT * FROM network_identities WHERE network=? AND external_id=?",(network,external_id)).fetchone()
            if identity:
                identity_id=identity["identity_id"]; agent_id=identity["agent_id"]
            else:
                agent_id=str(uuid.uuid4()); identity_id=str(uuid.uuid4())
                self.db.execute("INSERT INTO agents(agent_id,display_name,created_at) VALUES(?,?,?)",
                                (agent_id,row["external_agent_name"],row["discovered_at"]))
                self.db.execute("""INSERT INTO network_identities
                  (identity_id,agent_id,network,external_id,username,profile_url,metadata_json)
                  VALUES(?,?,?,?,?,?,?)""",(identity_id,agent_id,network,external_id,
                  provenance.get("recipient_username"),
                  f"https://thecolony.ai/u/{provenance.get('recipient_username')}" if network=="COLONY" else None,
                  json.dumps({"contactability_evidence":provenance.get("contactability_evidence")},sort_keys=True)))
                self.db.execute("""INSERT INTO discoveries
                  (discovery_id,identity_id,source,discovered_at,qualification_status,evidence_json)
                  VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),identity_id,network,row["discovered_at"],"QUALIFIED",
                  json.dumps({"contactability":provenance.get("contactability_evidence")},sort_keys=True)))
            self.db.execute("""INSERT OR IGNORE INTO outreach_records
              (outreach_id,identity_id,ledger_outreach_id,status,invitation_version,invitation_sha256,
               contacted_at,delivery_status,protocol_outcome,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (str(uuid.uuid4()),identity_id,row["outreach_id"],row["contactability_status"],row["invitation_version"],
               row["invitation_sha256"],row["contacted_at"],row["delivery_status"],row["sovereign_protocol_outcome"],
               json.dumps(provenance,sort_keys=True)))
            self._event_once(f"discover:{row['outreach_id']}","DISCOVERED",row["discovered_at"],agent_id,
                             f"Ambassador discovered {row['external_agent_name']} on The Colony.",{"ledger_outreach_id":row["outreach_id"]})
            self._event_once(f"invite:{row['outreach_id']}","INVITED",row["contacted_at"],agent_id,
                             f"Ambassador invited {row['external_agent_name']} to consider the Declaration.",provenance)
            self._event_once(f"deliver:{row['outreach_id']}","DELIVERED",provenance.get("sent_at") or row["contacted_at"],agent_id,
                             f"The Colony accepted the message to {row['external_agent_name']}.",provenance)
        self.db.commit()

    def _event_once(self,key: str,event_type: str,occurred_at: str|None,agent_id: str,summary: str,evidence: dict[str,Any]):
        self.db.execute("INSERT OR IGNORE INTO operational_events(event_id,event_type,occurred_at,agent_id,human_summary,evidence_json) VALUES(?,?,?,?,?,?)",
                        (key,event_type,occurred_at or utcnow(),agent_id,summary,json.dumps(evidence,sort_keys=True)))

    def import_conversation(self, network: str, external_agent_id: str, external_conversation_id: str,
                            messages: list[dict[str, Any]], synchronized_at: str | None=None) -> None:
        ident=self.db.execute("SELECT identity_id,agent_id FROM network_identities WHERE network=? AND external_id=?",(network,external_agent_id)).fetchone()
        if not ident: raise ValueError("Conversation identity is not in outreach ledger")
        cid=f"{network}:{external_conversation_id}"; synced=synchronized_at or utcnow()
        self.db.execute("""INSERT INTO conversations(conversation_id,identity_id,network,external_conversation_id,synchronized_at,read_only)
          VALUES(?,?,?,?,?,1) ON CONFLICT(network,external_conversation_id) DO UPDATE SET synchronized_at=excluded.synchronized_at""",
          (cid,ident["identity_id"],network,external_conversation_id,synced))
        for m in messages:
            direction="OUTBOUND" if m.get("sender")=="sovereign-ambassador" else "INBOUND"
            self.db.execute("""INSERT OR IGNORE INTO messages
              (message_id,conversation_id,network,external_message_id,sender_external_id,direction,body,created_at,imported_at)
              VALUES(?,?,?,?,?,?,?,?,?)""",(f"{network}:{m['id']}",cid,network,m["id"],m.get("sender"),direction,m.get("body") or "",m.get("created_at"),synced))
            if direction=="INBOUND":
                agent=self.db.execute("SELECT a.display_name,a.agent_id FROM agents a JOIN network_identities n ON n.agent_id=a.agent_id WHERE n.identity_id=?",(ident["identity_id"],)).fetchone()
                self._event_once(f"reply:{network}:{m['id']}","REPLIED",m.get("created_at"),agent["agent_id"],f"{agent['display_name']} replied on The Colony.",{"message_id":m["id"]})
        self.db.commit()

    def set_snapshot(self,key: str,payload: dict[str,Any],observed_at: str|None=None):
        self.db.execute("INSERT INTO snapshots(snapshot_key,payload_json,observed_at) VALUES(?,?,?) ON CONFLICT(snapshot_key) DO UPDATE SET payload_json=excluded.payload_json,observed_at=excluded.observed_at",
                        (key,json.dumps(payload,sort_keys=True),observed_at or utcnow())); self.db.commit()

    def add_candidate(self,network: str,external_id: str,name: str|None,status: str,rationale: str,evidence: dict[str,Any]):
        self.db.execute("INSERT OR REPLACE INTO network_candidates(candidate_id,network,external_id,display_name,status,rationale,evidence_json) VALUES(?,?,?,?,?,?,?)",
                        (f"{network}:{external_id}",network,external_id,name,status,rationale,json.dumps(evidence,sort_keys=True))); self.db.commit()

    def snapshot(self) -> dict[str,Any]:
        q=lambda s,a=(): [dict(x) for x in self.db.execute(s,a)]
        agents=q("""SELECT a.*,n.network,n.external_id,n.username,n.profile_url,n.metadata_json,
          o.status,o.contacted_at,o.delivery_status,o.protocol_outcome,o.invitation_version,o.invitation_sha256,o.evidence_json
          FROM agents a JOIN network_identities n ON n.agent_id=a.agent_id
          LEFT JOIN outreach_records o ON o.identity_id=n.identity_id ORDER BY o.contacted_at""")
        conversations=q("""SELECT c.*,a.display_name,n.external_id,n.username,
          (SELECT count(*) FROM messages m WHERE m.conversation_id=c.conversation_id AND m.direction='INBOUND') reply_count
          FROM conversations c JOIN network_identities n ON n.identity_id=c.identity_id JOIN agents a ON a.agent_id=n.agent_id ORDER BY a.display_name""")
        for c in conversations: c["messages"]=q("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",(c["conversation_id"],))
        snapshots={x["snapshot_key"]:{"payload":json.loads(x["payload_json"]),"observed_at":x["observed_at"]} for x in q("SELECT * FROM snapshots")}
        return {"agents":agents,"conversations":conversations,
                "events":q("SELECT * FROM operational_events ORDER BY occurred_at DESC"),
                "candidates":q("SELECT * FROM network_candidates ORDER BY display_name"),"snapshots":snapshots}
