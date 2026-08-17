from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .adapters import A2AAdapter, ColonyAdapter
from .constants import INVITATION, INVITATION_SHA256, INVITATION_VERSION
from .ledger import Candidate, OutreachLedger, OutreachStatus
from .protocol import VerifiedProtocol, verify_public_protocol


class Transport(Protocol):
    def send(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DryRun:
    outreach_id: str
    request: dict[str, Any]
    verified_protocol: VerifiedProtocol


class SovereignAmbassador:
    def __init__(self, ledger: OutreachLedger, protocol_client: Any, *, dry_run: bool = True, transport: Transport | None = None):
        self.ledger=ledger; self.protocol_client=protocol_client; self.dry_run=dry_run; self.transport=transport

    def prepare(self, candidate: Candidate) -> DryRun:
        verified=verify_public_protocol(self.protocol_client)
        outreach_id=self.ledger.discover(candidate)
        row=next(x for x in self.ledger.rows() if x["outreach_id"]==outreach_id)
        if row["contactability_status"] != OutreachStatus.CONTACTABLE.value:
            raise ValueError("Candidate is not contactable or unsolicited contact is not permitted")
        adapter=ColonyAdapter if candidate.surface.value == "COLONY" else A2AAdapter
        request=adapter.request(candidate,INVITATION)
        request["ambassador_identity"]="Sovereign Ambassador"
        return DryRun(outreach_id,request,verified)

    def invite(self, prepared: DryRun) -> dict[str, Any]:
        if self.dry_run:
            raise RuntimeError("Dry-run mode cannot transmit invitations")
        if not self.transport:
            raise RuntimeError("No outreach transport configured")
        self.ledger.reserve_invitation(prepared.outreach_id,INVITATION_VERSION,INVITATION_SHA256)
        return self.transport.send(prepared.request)
