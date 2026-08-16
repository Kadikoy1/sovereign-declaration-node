from __future__ import annotations

from typing import Any

from eth_abi import encode as abi_encode
from eth_account import Account
from web3 import Web3

from settings import settings

V01_EAS_SCHEMA = "string agentId,string identityType,string declarationVersion,bytes32 declarationHash,string statement,bytes32 evidenceDigest,uint64 affirmedAt,string verificationLevel"
SUPERSEDED_UNUSED_SCHEMA_UID = "0x49bfac24c4c280729c3e8d17838a2121e06710067e4968ef0b362482b1662f61"
EAS_ABI = [
    {"inputs":[{"components":[{"name":"schema","type":"bytes32"},{"components":[{"name":"recipient","type":"address"},{"name":"expirationTime","type":"uint64"},{"name":"revocable","type":"bool"},{"name":"refUID","type":"bytes32"},{"name":"data","type":"bytes"},{"name":"value","type":"uint256"}],"name":"data","type":"tuple"}],"name":"request","type":"tuple"}],"name":"attest","outputs":[{"name":"","type":"bytes32"}],"stateMutability":"payable","type":"function"},
    {"anonymous":False,"inputs":[{"indexed":True,"name":"recipient","type":"address"},{"indexed":True,"name":"attester","type":"address"},{"indexed":False,"name":"uid","type":"bytes32"},{"indexed":True,"name":"schemaUID","type":"bytes32"}],"name":"Attested","type":"event"},
]


def encode_evidence_data(data: dict[str, Any]) -> bytes:
    return abi_encode(
        ["string","string","string","bytes32","string","bytes32","uint64","string"],
        [data["agent_id"], data["identity_type"], data["declaration_version"],
         bytes.fromhex(data["declaration_hash"][2:]), data["statement"],
         bytes.fromhex(data["evidence_digest"][2:]), data["affirmed_at"], "AUTHENTICATED"],
    )


def submit_evidence(data: dict[str, Any]) -> dict[str, Any]:
    if not settings.v01_eas_schema_uid or not settings.attestor_private_key:
        return {"status": "pending", "error_code": "ATTESTER_NOT_CONFIGURED"}
    try:
        w3 = Web3(Web3.HTTPProvider(settings.base_rpc_url, request_kwargs={"timeout": 30}))
        account = Account.from_key(settings.attestor_private_key)
        contract = w3.eth.contract(address=Web3.to_checksum_address(settings.eas_contract), abi=EAS_ABI)
        encoded = encode_evidence_data(data)
        request = (Web3.to_bytes(hexstr=settings.v01_eas_schema_uid),
                   ("0x0000000000000000000000000000000000000000", 0, True, b"\x00"*32, encoded, 0))
        tx = contract.functions.attest(request).build_transaction({
            "from": account.address, "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": settings.eas_chain_id, "gas": int(contract.functions.attest(request).estimate_gas({"from":account.address})*1.25),
            "maxFeePerGas": w3.eth.gas_price*2, "maxPriorityFeePerGas": w3.to_wei(0.001,"gwei"),
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        events = contract.events.Attested().process_receipt(receipt)
        if receipt.status != 1 or len(events) != 1:
            return {"status":"failed", "transaction_hash":tx_hash.hex(), "error_code":"EAS_RECEIPT_INVALID"}
        return {"status":"succeeded", "transaction_hash":tx_hash.hex(), "uid":events[0]["args"]["uid"].hex(),
                "attester":account.address, "block_number":receipt.blockNumber}
    except Exception:
        return {"status": "failed", "error_code": "EAS_SUBMISSION_FAILED"}
