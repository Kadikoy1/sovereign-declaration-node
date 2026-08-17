from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_zero.agent import AgentZero

from .constants import SOVEREIGN_ORIGIN


class ReadClient(Protocol):
    def get_text(self, url: str) -> str: ...
    def get_json(self, url: str) -> dict: ...
    def get_bytes(self, url: str) -> bytes: ...


class _NoDecision:
    def decide(self, prompt: str):
        raise AssertionError("Ambassador must never decide for a recipient")


@dataclass(frozen=True)
class VerifiedProtocol:
    origin: str
    protocol_url: str
    declaration_version: str
    declaration_hash: str
    declaration_cid: str


def verify_public_protocol(client: ReadClient) -> VerifiedProtocol:
    # Reuse the already-tested canonical PDF/version/CID/text verification gates.
    materials = AgentZero(None, _NoDecision()).discover(client, SOVEREIGN_ORIGIN)  # type: ignore[arg-type]
    return VerifiedProtocol(materials.public_url, materials.protocol_url, "1.0",
                            materials.canonical_pdf_sha256, materials.canonical_cid)
