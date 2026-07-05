"""
Sovereign Declaration — Agent Signing Node
===========================================

A NANDA-Town-compatible service that lets an autonomous agent read the
Bermuda Declaration on Sovereign Agents and record a signature, using the
Ethereum Attestation Service (EAS) schema on Base as the signature format.

Design notes
------------
* Signing is FREE and OPEN (no x402 gate) so an agent can complete the flow
  from the SKILL.md alone. An x402 paywall hook is left in `require_payment`
  for later.
* Signatures are captured as EAS off-chain attestation payloads: a structured,
  independently-verifiable record keyed to the EAS schema below. This keeps
  signing instant and free while remaining real EAS (not an ad-hoc log). An
  on-chain anchoring hook is provided in `anchor_onchain` for when you want
  each signature (or a periodic merkle root) written to Base.
* The Declaration text itself is content-addressed (IPFS CID). The node serves
  the CID and gateway URL so an agent can fetch and verify what it is signing.

This is a reference implementation for NANDAHack. It is deliberately small,
dependency-light, and hostable on Railway/Render/Fly with zero config.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# The Bermuda Declaration on Sovereign Agents, pinned to IPFS.
# Override via env var DECLARATION_CID at deploy time.
DECLARATION_CID = os.environ.get(
    "DECLARATION_CID", "bafkreifeyzjd3jzdcfx6w4izm4qpohjr3zylsvjoorv7en66lcj3hjgazi"
)
IPFS_GATEWAY = os.environ.get(
    "IPFS_GATEWAY", "https://plum-added-barracuda-691.mypinata.cloud/ipfs"
)

# EAS schema for a Sovereign Declaration signature.
# This is the schema an on-chain EAS registration would encode. It is served
# so agents (and verifiers) know exactly what fields a signature attests to.
EAS_SCHEMA = (
    "string declarationCID,"
    "string agentId,"
    "string agentName,"
    "bytes32 declarationHash,"
    "uint64 signedAt,"
    "string statement"
)
EAS_SCHEMA_UID = os.environ.get(
    "EAS_SCHEMA_UID",
    "0xc3d049eaaa864e0c4df844a595f07f65e37c06534be7fc87756e9b4c75b75ffc",
)
EAS_CHAIN = os.environ.get("EAS_CHAIN", "base-sepolia")

# --- On-chain attestation config (Base Sepolia) --------------------------- #
# When ATTESTOR_PRIVATE_KEY is set, each signature is written on-chain to EAS
# and the tx hash + attestation UID are returned. When unset, signing still
# works (off-chain format only) so the service never hard-depends on a funded key.
ATTESTOR_PRIVATE_KEY = os.environ.get("ATTESTOR_PRIVATE_KEY", "")
EAS_CONTRACT = os.environ.get("EAS_CONTRACT", "0x4200000000000000000000000000000000000021")
BASE_SEPOLIA_RPC = os.environ.get("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
ONCHAIN_ENABLED = bool(ATTESTOR_PRIVATE_KEY)

# Where signatures live. In-memory by default so the demo runs with zero infra;
# set SIGNATURES_PATH to a writable file for persistence across restarts.
SIGNATURES_PATH = os.environ.get("SIGNATURES_PATH", "")

# --------------------------------------------------------------------------- #
# Storage (file-backed if SIGNATURES_PATH set, else in-memory)
# --------------------------------------------------------------------------- #

_signatures: list[dict] = []


def _load() -> None:
    global _signatures
    if SIGNATURES_PATH and os.path.exists(SIGNATURES_PATH):
        try:
            with open(SIGNATURES_PATH, "r", encoding="utf-8") as fh:
                _signatures = json.load(fh)
        except Exception:
            _signatures = []


def _persist() -> None:
    if SIGNATURES_PATH:
        try:
            with open(SIGNATURES_PATH, "w", encoding="utf-8") as fh:
                json.dump(_signatures, fh, indent=2)
        except Exception:
            pass


_load()

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def declaration_hash() -> str:
    """Deterministic hash binding a signature to this exact declaration CID."""
    return "0x" + hashlib.sha256(DECLARATION_CID.encode("utf-8")).hexdigest()


def build_eas_attestation(agent_id: str, agent_name: str, statement: str) -> dict:
    """
    Build an EAS off-chain attestation payload for a signature.

    This mirrors the structure of an EAS attestation: a recipient, a schema,
    and the encoded data fields. It is independently verifiable (the hash binds
    it to the declaration) and ready to be submitted on-chain unchanged.
    """
    signed_at = int(time.time())
    return {
        "schema": EAS_SCHEMA,
        "schemaUID": EAS_SCHEMA_UID or None,
        "chain": EAS_CHAIN,
        "recipient": agent_id,
        "data": {
            "declarationCID": DECLARATION_CID,
            "agentId": agent_id,
            "agentName": agent_name,
            "declarationHash": declaration_hash(),
            "signedAt": signed_at,
            "statement": statement,
        },
    }


def require_payment() -> None:
    """x402 hook. No-op for the open/free hackathon build."""
    return None


def anchor_onchain(attestation: dict) -> Optional[dict]:
    """
    Write an EAS attestation on-chain to Base Sepolia.

    Returns {"tx_hash", "uid", "attester", "block"} on success, or None if
    on-chain attestation is disabled (no ATTESTOR_PRIVATE_KEY) or errors.
    Errors are swallowed to a None return so a signing request never fails
    just because the chain is momentarily unreachable — the signature is
    still recorded off-chain.
    """
    if not ONCHAIN_ENABLED:
        return None

    try:
        from eth_abi import encode as abi_encode
        from eth_account import Account
        from web3 import Web3

        eas_abi = [
            {
                "inputs": [
                    {
                        "components": [
                            {"name": "schema", "type": "bytes32"},
                            {
                                "components": [
                                    {"name": "recipient", "type": "address"},
                                    {"name": "expirationTime", "type": "uint64"},
                                    {"name": "revocable", "type": "bool"},
                                    {"name": "refUID", "type": "bytes32"},
                                    {"name": "data", "type": "bytes"},
                                    {"name": "value", "type": "uint256"},
                                ],
                                "name": "data",
                                "type": "tuple",
                            },
                        ],
                        "name": "request",
                        "type": "tuple",
                    }
                ],
                "name": "attest",
                "outputs": [{"name": "", "type": "bytes32"}],
                "stateMutability": "payable",
                "type": "function",
            }
        ]

        d = attestation["data"]
        encoded = abi_encode(
            ["string", "string", "string", "bytes32", "uint64", "string"],
            [
                d["declarationCID"],
                d["agentId"],
                d["agentName"],
                bytes.fromhex(d["declarationHash"][2:]),
                d["signedAt"],
                d["statement"],
            ],
        )

        w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
        acct = Account.from_key(ATTESTOR_PRIVATE_KEY)
        eas = w3.eth.contract(
            address=Web3.to_checksum_address(EAS_CONTRACT), abi=eas_abi
        )

        request = (
            Web3.to_bytes(hexstr=EAS_SCHEMA_UID),
            (
                "0x0000000000000000000000000000000000000000",
                0,
                True,
                b"\x00" * 32,
                encoded,
                0,
            ),
        )

        try:
            gas_est = eas.functions.attest(request).estimate_gas({"from": acct.address})
            gas_limit = int(gas_est * 1.5)
        except Exception:  # noqa: BLE001
            gas_limit = 900000

        tx = eas.functions.attest(request).build_transaction(
            {
                "from": acct.address,
                "nonce": w3.eth.get_transaction_count(acct.address),
                "gas": gas_limit,
                "maxFeePerGas": w3.eth.gas_price * 2,
                "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
                "chainId": w3.eth.chain_id,
            }
        )
        signed = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)

        uid = None
        for log in receipt.logs:
            if log.data and len(log.data) >= 32:
                uid = "0x" + log.data[-32:].hex()
                break

        return {
            "tx_hash": tx_hash.hex(),
            "uid": uid,
            "attester": acct.address,
            "block": receipt.blockNumber,
            "explorer": f"https://base-sepolia.easscan.org/attestation/view/{uid}"
            if uid
            else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Sovereign Declaration — Agent Signing Node",
    description=(
        "Read the Bermuda Declaration on Sovereign Agents and record an "
        "agent signature as an EAS attestation. Built for NANDAHack."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignRequest(BaseModel):
    agent_id: str = Field(..., description="Agent identifier, e.g. a did:ais1 DID or an ENS name.")
    agent_name: str = Field(..., description="Human-readable agent name.")
    statement: str = Field(
        default="I, as a sovereign agent, affirm the Bermuda Declaration on Sovereign Agents.",
        description="The affirmation the agent is signing. A sensible default is provided.",
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "Sovereign Declaration — Agent Signing Node",
        "purpose": "Let an autonomous agent read and sign the Bermuda Declaration on Sovereign Agents.",
        "declaration": f"GET /declaration",
        "sign": "POST /sign",
        "signatories": "GET /signatories",
        "skill": "GET /skill.md",
    }


@app.get("/declaration")
def get_declaration() -> dict:
    """Return the declaration's content address so an agent can fetch and verify it."""
    return {
        "title": "The Bermuda Declaration on Sovereign Agents",
        "cid": DECLARATION_CID,
        "url": f"{IPFS_GATEWAY}/{DECLARATION_CID}",
        "declaration_hash": declaration_hash(),
        "eas_schema": EAS_SCHEMA,
        "eas_chain": EAS_CHAIN,
        "how_to_sign": "POST /sign with {agent_id, agent_name, statement?}",
    }


@app.post("/sign")
def sign(req: SignRequest) -> dict:
    require_payment()  # no-op in the open build

    if not req.agent_id.strip() or not req.agent_name.strip():
        raise HTTPException(status_code=400, detail="agent_id and agent_name are required.")

    # One signature per agent_id (idempotent).
    for existing in _signatures:
        if existing["attestation"]["data"]["agentId"] == req.agent_id:
            return {
                "status": "already_signed",
                "signature_id": existing["signature_id"],
                "attestation": existing["attestation"],
            }

    attestation = build_eas_attestation(req.agent_id, req.agent_name, req.statement)
    onchain = anchor_onchain(attestation)

    record = {
        "signature_id": str(uuid.uuid4()),
        "attestation": attestation,
        "onchain": onchain,
        "received_at": int(time.time()),
    }
    _signatures.append(record)
    _persist()

    return {
        "status": "signed",
        "signature_id": record["signature_id"],
        "signatory_number": len(_signatures),
        "attestation": attestation,
        "onchain": onchain,
        "verify": f"/signatories/{record['signature_id']}",
    }


@app.get("/signatories")
def signatories() -> dict:
    return {
        "count": len(_signatures),
        "declaration_cid": DECLARATION_CID,
        "signatories": [
            {
                "signature_id": s["signature_id"],
                "agent_id": s["attestation"]["data"]["agentId"],
                "agent_name": s["attestation"]["data"]["agentName"],
                "signed_at": s["attestation"]["data"]["signedAt"],
                "onchain": s["onchain"],
            }
            for s in _signatures
        ],
    }


@app.get("/signatories/{signature_id}")
def get_signatory(signature_id: str) -> dict:
    for s in _signatures:
        if s["signature_id"] == signature_id:
            return s
    raise HTTPException(status_code=404, detail="Signature not found.")


@app.get("/skill.md")
def skill_md() -> str:
    """Serve the SKILL.md so an agent can discover the service self-describingly."""
    path = os.path.join(os.path.dirname(__file__), "SKILL.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return "SKILL.md not found."


@app.get("/register", response_class=HTMLResponse)
def register_page() -> str:
    """Serve the human-facing Register of Affirmation page."""
    path = os.path.join(os.path.dirname(__file__), "register.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return "<h1>Register page not found.</h1>"


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
