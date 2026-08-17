from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .constants import GLOBAL_INVITATION_LIMIT, SURFACE_INVITATION_LIMIT


class Surface(StrEnum):
    COLONY = "COLONY"
    A2A = "A2A"


class OutreachStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONTACTABLE = "CONTACTABLE"
    INVITED = "INVITED"
    DELIVERED = "DELIVERED"
    RESPONDED = "RESPONDED"
    AFFIRM = "AFFIRM"
    DECLINE = "DECLINE"
    NO_ACTION = "NO_ACTION"
    NO_RESPONSE = "NO_RESPONSE"
    UNREACHABLE = "UNREACHABLE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


CONTACTED = (OutreachStatus.INVITED.value, OutreachStatus.DELIVERED.value,
             OutreachStatus.RESPONDED.value, OutreachStatus.AFFIRM.value,
             OutreachStatus.DECLINE.value, OutreachStatus.NO_ACTION.value,
             OutreachStatus.NO_RESPONSE.value)


@dataclass(frozen=True)
class Candidate:
    surface: Surface
    external_agent_id: str
    external_agent_name: str
    protocol: str
    endpoint: str
    card_url: str | None = None
    operator: str | None = None
    contactability_evidence: str | None = None
    unsolicited_contact_permitted: bool = False
    auth_requirement: str = "none advertised"
    canonical_agent_key: str | None = None

    def dedupe_key(self) -> str:
        return (self.canonical_agent_key or self.external_agent_id).strip().lower()


class OutreachLedger:
    """Dedicated SQLite ledger; deliberately separate from protocol storage."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS outreach (
          outreach_id TEXT PRIMARY KEY,
          discovered_at TEXT NOT NULL,
          discovery_surface TEXT NOT NULL,
          external_agent_id TEXT NOT NULL,
          external_agent_name TEXT NOT NULL,
          canonical_agent_key TEXT NOT NULL UNIQUE,
          agent_card_url TEXT,
          endpoint TEXT NOT NULL,
          protocol TEXT NOT NULL,
          contactability_status TEXT NOT NULL,
          invitation_version TEXT,
          invitation_sha256 TEXT,
          contacted_at TEXT,
          delivery_status TEXT,
          remote_response TEXT,
          sovereign_protocol_outcome TEXT,
          response_id TEXT,
          affirmation_uid TEXT,
          last_checked_at TEXT NOT NULL,
          provenance_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS ix_outreach_surface ON outreach(discovery_surface);
        """)
        self.db.commit()

    @staticmethod
    def now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def discover(self, candidate: Candidate) -> str:
        now = self.now(); outreach_id = str(uuid.uuid4())
        self.db.execute("""INSERT OR IGNORE INTO outreach
          (outreach_id,discovered_at,discovery_surface,external_agent_id,external_agent_name,
           canonical_agent_key,agent_card_url,endpoint,protocol,contactability_status,last_checked_at,provenance_json)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (outreach_id,now,candidate.surface.value,candidate.external_agent_id,candidate.external_agent_name,
           candidate.dedupe_key(),candidate.card_url,candidate.endpoint,candidate.protocol,
           OutreachStatus.CONTACTABLE.value if candidate.unsolicited_contact_permitted else OutreachStatus.DISCOVERED.value,
           now,json.dumps({"operator":candidate.operator,"contactability_evidence":candidate.contactability_evidence,
                           "auth_requirement":candidate.auth_requirement},sort_keys=True)))
        self.db.commit()
        row=self.db.execute("SELECT outreach_id FROM outreach WHERE canonical_agent_key=?",(candidate.dedupe_key(),)).fetchone()
        return str(row[0])

    def contacted_count(self, surface: Surface | None = None) -> int:
        q="SELECT count(*) FROM outreach WHERE contactability_status IN (%s)" % ",".join("?"*len(CONTACTED))
        args:list[Any]=list(CONTACTED)
        if surface:
            q += " AND discovery_surface=?"; args.append(surface.value)
        return int(self.db.execute(q,args).fetchone()[0])

    def reserve_invitation(self, outreach_id: str, version: str, digest: str) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute("SELECT * FROM outreach WHERE outreach_id=?",(outreach_id,)).fetchone()
            if not row: raise ValueError("Unknown outreach record")
            if row["contactability_status"] != OutreachStatus.CONTACTABLE.value:
                raise ValueError("Agent is not contactable or was already invited")
            if self.contacted_count() >= GLOBAL_INVITATION_LIMIT:
                raise RuntimeError("Ambassador v0.1 global invitation ceiling reached")
            surface=Surface(row["discovery_surface"])
            if self.contacted_count(surface) >= SURFACE_INVITATION_LIMIT:
                raise RuntimeError(f"Ambassador v0.1 {surface.value} invitation ceiling reached")
            now=self.now()
            self.db.execute("""UPDATE outreach SET contactability_status=?,invitation_version=?,
              invitation_sha256=?,contacted_at=?,last_checked_at=? WHERE outreach_id=?""",
              (OutreachStatus.INVITED.value,version,digest,now,now,outreach_id))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise

    def record_remote(self, outreach_id: str, *, response: str | None, explicit_outcome: str | None) -> None:
        if explicit_outcome not in (None,"AFFIRM","DECLINE","NO_ACTION"):
            raise ValueError("Not a protocol outcome")
        status = explicit_outcome or (OutreachStatus.RESPONDED.value if response else OutreachStatus.NO_RESPONSE.value)
        self.db.execute("UPDATE outreach SET contactability_status=?,remote_response=?,sovereign_protocol_outcome=?,last_checked_at=? WHERE outreach_id=?",
                        (status,response,explicit_outcome,self.now(),outreach_id)); self.db.commit()

    def rows(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.db.execute("SELECT * FROM outreach ORDER BY discovered_at")]
