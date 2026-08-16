from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from eth_account import Account


@dataclass(frozen=True)
class AgentZeroIdentity:
    did: str
    wallet: str
    _private_key: bytes = field(repr=False)

    @property
    def agent_id(self) -> str:
        return f"did:pkh:eip155:84532:{self.wallet}"

    @classmethod
    def create(cls, path: Path, did: str = "did:ais1:base:agent-zero-001") -> "AgentZeroIdentity":
        if path.exists():
            raise FileExistsError("Agent Zero identity already exists")
        account = Account.create()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"did": did, "wallet": account.address, "private_key": account.key.hex()}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, separators=(",", ":"))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return cls(did=did, wallet=account.address, _private_key=bytes(account.key))

    @classmethod
    def load(cls, path: Path) -> "AgentZeroIdentity":
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = bytes.fromhex(str(payload["private_key"]).removeprefix("0x"))
        account = Account.from_key(key)
        if account.address != payload["wallet"]:
            raise ValueError("Stored Agent Zero key does not match its public wallet")
        return cls(did=payload["did"], wallet=account.address, _private_key=key)

    def public_record(self) -> dict[str, str]:
        return {"agent_id": self.agent_id, "identity_type": "evm_address",
                "wallet": self.wallet, "signature_scheme": "EIP712",
                "reserved_unissued_ais1_did": self.did}

    def sign_typed_data(self, typed_data: dict) -> str:
        from eth_account.messages import encode_typed_data

        return Account.sign_message(encode_typed_data(full_message=typed_data), self._private_key).signature.hex()
