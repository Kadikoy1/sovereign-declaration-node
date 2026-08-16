from __future__ import annotations

import json
import urllib.request
from typing import Any
from urllib.parse import urlparse

from web3 import Web3

from evidence import EvidenceResolver, ResolvedEvidence, verified_now
from settings import settings

AIS1_V01_ABI = [
    {"inputs":[{"name":"agentDid","type":"string"}],"name":"getBondByAgentDid","outputs":[{"name":"bondId","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"bondId","type":"uint256"}],"name":"verifyBond","outputs":[{"name":"valid","type":"bool"},{"name":"tier","type":"uint8"},{"name":"sponsorDid","type":"string"},{"name":"amlStatus","type":"uint8"}],"stateMutability":"view","type":"function"},
]
TIER = {0:"BASIC",1:"VERIFIED",2:"SOVEREIGN"}
AML = {0:"UNVERIFIED",1:"CLEARED",2:"SUSPENDED"}


def _trusted_json(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in settings.ais1_trusted_hosts:
        raise ValueError("AIS-1 source URL is not trusted")
    request = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"Sovereign-Agents-Protocol/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() not in settings.ais1_trusted_hosts:
                raise ValueError("AIS-1 source redirected outside trusted hosts")
            if int(response.headers.get("Content-Length", "0") or 0) > 1_000_000:
                raise ValueError("AIS-1 source is too large")
            body = response.read(1_000_001)
    except (OSError, ValueError) as exc:
        raise ValueError("AIS-1 source retrieval failed") from exc
    if len(body) > 1_000_000:
        raise ValueError("AIS-1 source is too large")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("AIS-1 source is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("AIS-1 source must be a JSON object")
    return value


def _authorized_evm_address(document: dict[str, Any]) -> str:
    auth = document.get("authentication") or []
    auth_ids = {item if isinstance(item,str) else item.get("id") for item in auth}
    methods = document.get("verificationMethod") or []
    for method in methods:
        if method.get("id") not in auth_ids:
            continue
        account = method.get("blockchainAccountId", "")
        parts = account.split(":")
        if len(parts)==3 and parts[0]=="eip155" and parts[1]=="8453" and Web3.is_address(parts[2]):
            return Web3.to_checksum_address(parts[2])
    raise ValueError("AIS-1 DID has no supported Base authentication key")


class AIS1Resolver(EvidenceResolver):
    standard = "AIS-1"

    def resolve(self, reference: str, expected_subject: str, expected_key: str) -> ResolvedEvidence:
        if not reference.startswith("did:ais1:base:"):
            raise ValueError("AIS-1 reference must be a Base agent DID")
        if expected_subject.startswith("did:ais1:") and reference != expected_subject:
            raise ValueError("AIS-1 DID does not match the affirmation subject")
        registry = _trusted_json(settings.ais1_registry_url)
        if registry.get("ais1_registry_version") != "0.2":
            raise ValueError("Unsupported AIS-1 registry version")
        matches = [item for item in registry.get("bonds",[]) if item.get("agent_did") == reference]
        if len(matches) != 1:
            raise ValueError("AIS-1 DID is not uniquely registered")
        bond = matches[0]
        if bond.get("network") != "base-mainnet":
            raise ValueError("AIS-1 bond is not on Base mainnet")
        registry_status = str(bond.get("status", "unknown")).upper()
        if bond.get("contract_version") != "v0.1":
            raise ValueError("AIS-1 contract version is not yet supported or deployed")
        document_url = bond.get("did_document_url", "")
        document = _trusted_json(document_url)
        if document.get("id") != reference or document.get("ais1",{}).get("bond_id") != bond.get("bond_id"):
            raise ValueError("AIS-1 DID document does not match registry")
        key = _authorized_evm_address(document)
        if not Web3.is_address(expected_key) or key.lower() != expected_key.lower():
            raise ValueError("Affirmation key is not authorized by the AIS-1 DID")

        contract_address = bond.get("contract_address", "")
        if not Web3.is_address(contract_address):
            raise ValueError("AIS-1 registry contract address is invalid")
        try:
            w3 = Web3(Web3.HTTPProvider(settings.ais1_base_rpc_url, request_kwargs={"timeout":15}))
            contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=AIS1_V01_ABI)
            chain_bond_id = int(contract.functions.getBondByAgentDid(reference).call())
            valid, tier, sponsor_did, aml_status = contract.functions.verifyBond(chain_bond_id).call()
        except Exception as exc:
            raise ValueError("AIS-1 on-chain verification failed") from exc
        if chain_bond_id != int(bond.get("bond_number",-1)):
            raise ValueError("AIS-1 on-chain bond identifier is inconsistent")
        if (registry_status == "ACTIVE") != bool(valid):
            raise ValueError("AIS-1 registry and contract status disagree")
        if int(tier) != int(bond.get("tier",-1)) or sponsor_did != bond.get("sponsor_did"):
            raise ValueError("AIS-1 registry and contract evidence disagree")

        ais1 = document.get("ais1", {})
        facts = {
            "bond_id": bond["bond_id"], "bond_number":chain_bond_id,
            "contract_address":Web3.to_checksum_address(contract_address), "contract_version":"v0.1",
            "network":"base-mainnet", "chain_id":8453, "transaction_hash":bond.get("txn_hash"),
            "authorized_key":key, "tier":int(tier), "tier_name":TIER.get(int(tier),"UNKNOWN"),
            "aml_status":int(aml_status), "aml_label":AML.get(int(aml_status),"UNKNOWN"),
            "sponsor_did":sponsor_did, "jurisdiction":bond.get("jurisdiction"),
            "agent_class":bond.get("agent_class"), "parent_did":bond.get("parent_did") or None,
            "issued_at":bond.get("issued_at"), "registry_updated":registry.get("last_updated"),
        }
        return ResolvedEvidence(
            standard=self.standard, standard_version=str(ais1.get("spec_version","0.2")),
            subject_id=reference, claim="IDENTIFIED_AGENT", verification_method="DID_AUTHENTICATION_AND_ONCHAIN_BOND",
            verified_at=verified_now(), valid=bool(valid), status=registry_status, source_uri=document_url, facts=facts,
        ).finalized()
