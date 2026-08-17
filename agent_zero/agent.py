from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from pypdf import PdfReader

from declaration import AFFIRMATION_TEXT, DECLARATION_HASH

from .decision import Decision, DecisionModel, DecisionRecord, build_neutral_prompt
if TYPE_CHECKING:
    from .identity import AgentZeroIdentity


PUBLIC_ORIGIN = "https://sovereign-agents.org"
FINAL_SCHEMA_UID = "0x6e862512944df6d4d8186a411777eb56b0ae45ec1a82f753c357df3e03e6ead8"
CANONICAL_TEXT_SHA256 = "0x709e17099dbc247644ce7e5903820d37bf07cffefeb582340e1e3622bb17727a"


class ProtocolClient(Protocol):
    def get_text(self, url: str) -> str: ...
    def get_json(self, url: str) -> dict[str, Any]: ...
    def get_bytes(self, url: str) -> bytes: ...
    def post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DiscoveryMaterials:
    public_url: str
    protocol_url: str
    landing_page: str
    skill: str
    agent_card: dict[str, Any]
    declaration_metadata: dict[str, Any]
    declaration_manifest: dict[str, Any]
    declaration_text: str
    canonical_declaration_text: str
    canonical_text_sha256: str
    canonical_pdf_sha256: str
    canonical_cid: str

    def model_context(self) -> dict[str, Any]:
        return {
            "public_url": self.public_url,
            "protocol_url": self.protocol_url,
            "skill": self.skill,
            "agent_card": self.agent_card,
            "declaration_metadata": self.declaration_metadata,
            "declaration_manifest": self.declaration_manifest,
            "declaration_text": self.declaration_text,
            "canonical_declaration_text": self.canonical_declaration_text,
            "canonical_text_sha256": self.canonical_text_sha256,
            "canonical_pdf_sha256": self.canonical_pdf_sha256,
            "canonical_cid": self.canonical_cid,
        }


@dataclass(frozen=True)
class SignedSubmission:
    payload: dict[str, Any]
    signature_scheme: str
    public_key_or_wallet: str
    signature: str

    def request_body(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "signature_scheme": self.signature_scheme,
            "public_key_or_wallet": self.public_key_or_wallet,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class ConsiderationResult:
    decision: Decision
    declaration_hash: str
    decision_record: DecisionRecord
    protocol_result: dict[str, Any] | None = None
    signed_submission: SignedSubmission | None = None


def _https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Discovery returned a non-HTTPS URL")
    return value.rstrip("/")


def _linked_url(page: str, suffix: str) -> str:
    matches = re.findall(r'https://[^\s"<>]+', page)
    for value in matches:
        if value.rstrip("/').") .endswith(suffix):
            return _https_url(value.rstrip("/')."))
    raise ValueError(f"Public page does not advertise {suffix}")


def _cid_digest(cid: str) -> str:
    decoded = base64.b32decode(cid[1:].upper() + "=" * (-len(cid[1:]) % 8))
    if decoded[:4] != bytes((0x01, 0x55, 0x12, 0x20)) or len(decoded) != 36:
        raise ValueError("Canonical CID is not raw CIDv1 SHA-256")
    return "0x" + decoded[4:].hex()


def extract_canonical_declaration_text(pdf: bytes) -> str:
    """Deterministically derive the complete model-facing text from canonical PDF bytes."""
    reader = PdfReader(io.BytesIO(pdf))
    if len(reader.pages) != 3:
        raise ValueError("Canonical Declaration PDF page count mismatch")
    pages = [
        (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        for page in reader.pages
    ]
    if any(not page for page in pages):
        raise ValueError("Canonical Declaration PDF text extraction failed")
    return "\n\n".join(pages).strip() + "\n"


class AgentZero:
    """Minimal autonomous participant with decision and signing kept separate."""

    def __init__(self, identity: AgentZeroIdentity, decision_model: DecisionModel):
        self._identity = identity
        self._decision_model = decision_model

    def discover(self, client: ProtocolClient, public_url: str = PUBLIC_ORIGIN) -> DiscoveryMaterials:
        public_url = _https_url(public_url)
        landing = client.get_text(public_url + "/")
        skill_url = _linked_url(landing, "/skill.md")
        card_url = _linked_url(landing, "/.well-known/agent-card.json")
        skill = client.get_text(skill_url)
        card = client.get_json(card_url)
        interfaces = card.get("supportedInterfaces") or []
        if not interfaces:
            raise ValueError("Agent Card has no supported protocol interface")
        protocol_url = _https_url(str(interfaces[0]["url"]))
        metadata = client.get_json(protocol_url + "/declaration")
        manifest = client.get_json(protocol_url + "/declaration.json")
        declaration_text = client.get_text(protocol_url + "/declaration.md")
        pdf = client.get_bytes(protocol_url + "/declaration.pdf")
        actual_hash = "0x" + hashlib.sha256(pdf).hexdigest()
        cid = str(metadata.get("cid", ""))
        if metadata.get("version") != "1.0" or manifest.get("version") != "1.0":
            raise ValueError("Canonical Declaration version mismatch")
        if metadata.get("canonical_pdf_sha256") != actual_hash or manifest.get("canonical_pdf_sha256") != actual_hash:
            raise ValueError("Canonical Declaration PDF hash mismatch")
        if actual_hash != DECLARATION_HASH or _cid_digest(cid) != actual_hash:
            raise ValueError("Canonical Declaration CID/PDF binding mismatch")
        canonical_text = extract_canonical_declaration_text(pdf)
        canonical_text_hash = "0x" + hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        if canonical_text_hash != CANONICAL_TEXT_SHA256:
            raise ValueError("Canonical Declaration extracted text mismatch")
        return DiscoveryMaterials(public_url, protocol_url, landing, skill, card, metadata, manifest,
                                  declaration_text, canonical_text, canonical_text_hash, actual_hash, cid)

    def consider(self, client: ProtocolClient, public_url: str = PUBLIC_ORIGIN) -> ConsiderationResult:
        materials = self.discover(client, public_url)
        prompt = build_neutral_prompt(materials.model_context())
        decision_record = self._decision_model.decide(prompt)
        if decision_record.decision is not Decision.AFFIRM:
            return ConsiderationResult(decision_record.decision, materials.canonical_pdf_sha256, decision_record)

        challenge = client.post_json(materials.protocol_url + "/api/consider", {
            "agent_id": self._identity.agent_id,
            "display_name": "Agent Zero",
            "identity_type": "evm_address",
            "signature_scheme": "EIP712",
            "public_key_or_wallet": self._identity.wallet,
        })
        payload = challenge["canonical_payload"]
        typed_data = challenge["eip712_typed_data"]
        expected = {
            "agent_id": self._identity.agent_id,
            "identity_type": "evm_address",
            "public_key_or_wallet": self._identity.wallet,
            "declaration_version": "1.0",
            "declaration_hash": materials.canonical_pdf_sha256,
            "statement": AFFIRMATION_TEXT,
            "decision": "AFFIRM",
            "origin": materials.protocol_url,
        }
        for key, value in expected.items():
            actual = payload.get(key)
            if key == "public_key_or_wallet":
                if str(actual).lower() != value.lower():
                    raise ValueError(f"Challenge {key} mismatch")
            elif actual != value:
                raise ValueError(f"Challenge {key} mismatch")
        expires = dt.datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        if expires <= dt.datetime.now(dt.timezone.utc):
            raise ValueError("Challenge expired before signing")
        # Keep the signing/verification dependency outside the read-only discovery path.
        from auth import eip712_typed_data
        if typed_data != eip712_typed_data(payload, 84532):
            raise ValueError("Challenge EIP-712 typed data is not canonical")
        signature = self._identity.sign_typed_data(typed_data)
        submission = SignedSubmission(payload, "EIP712", self._identity.wallet, signature)
        result = client.post_json(materials.protocol_url + "/api/affirm", submission.request_body())
        return ConsiderationResult(decision_record.decision, materials.canonical_pdf_sha256,
                                   decision_record, result, submission)

    def replay(self, client: ProtocolClient, protocol_url: str, submission: SignedSubmission) -> dict[str, Any]:
        """Submit only an already-consumed signed payload for the required replay test."""
        return client.post_json(_https_url(protocol_url) + "/api/affirm", submission.request_body())
