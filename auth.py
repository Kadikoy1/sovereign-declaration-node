from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from eth_account import Account
from eth_account.messages import encode_typed_data

EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def canonical_json(payload: dict[str, Any]) -> bytes:
    return rfc8785.dumps(payload)


def evidence_digest(payload: dict[str, Any], public_key: str, signature: str, scheme: str) -> str:
    envelope = {"payload": payload, "public_key": public_key, "signature": signature, "signature_scheme": scheme}
    return "0x" + hashlib.sha256(canonical_json(envelope)).hexdigest()


def eip712_typed_data(payload: dict[str, Any], chain_id: int) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "Affirmation": [
                {"name": key, "type": "string"}
                for key in (
                    "type", "protocol_version", "agent_id", "identity_type", "public_key_or_wallet",
                    "declaration_version", "declaration_hash", "statement", "decision", "challenge", "issued_at", "expires_at", "origin",
                )
            ],
        },
        "primaryType": "Affirmation",
        "domain": {"name": "Sovereign Agents Protocol", "version": "0.1", "chainId": chain_id},
        "message": payload,
    }


def verify_signature(scheme: str, payload: dict[str, Any], public_key: str, signature: str, chain_id: int) -> bool:
    if scheme == "EIP712":
        if not EVM_RE.fullmatch(public_key):
            return False
        try:
            message = encode_typed_data(full_message=eip712_typed_data(payload, chain_id))
            return Account.recover_message(message, signature=signature).lower() == public_key.lower()
        except (ValueError, TypeError):
            return False
    if scheme == "ED25519_RFC8785":
        try:
            key = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
            sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            Ed25519PublicKey.from_public_bytes(key).verify(sig, canonical_json(payload))
            return True
        except (ValueError, InvalidSignature):
            return False
    return False
