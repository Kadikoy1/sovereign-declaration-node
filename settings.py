from __future__ import annotations

import os
from dataclasses import dataclass


def _origins() -> tuple[str, ...]:
    value = os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000")
    return tuple(x.strip() for x in value.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./sovereign_agents.db")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    cors_origins: tuple[str, ...] = _origins()
    challenge_ttl_seconds: int = int(os.getenv("CHALLENGE_TTL_SECONDS", "300"))
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", "65536"))
    declaration_cid: str = os.getenv("DECLARATION_CID", "bafkreifeyzjd3jzdcfx6w4izm4qpohjr3zylsvjoorv7en66lcj3hjgazi")
    ipfs_gateway: str = os.getenv("IPFS_GATEWAY", "https://plum-added-barracuda-691.mypinata.cloud/ipfs").rstrip("/")
    eas_chain: str = os.getenv("EAS_CHAIN", "base-sepolia")
    eas_chain_id: int = int(os.getenv("EAS_CHAIN_ID", "84532"))
    legacy_eas_schema_uid: str = os.getenv("LEGACY_EAS_SCHEMA_UID", os.getenv("EAS_SCHEMA_UID", "0xc3d049eaaa864e0c4df844a595f07f65e37c06534be7fc87756e9b4c75b75ffc"))
    v01_eas_schema_uid: str = os.getenv("V01_EAS_SCHEMA_UID", "")
    eas_contract: str = os.getenv("EAS_CONTRACT", "0x4200000000000000000000000000000000000021")
    base_rpc_url: str = os.getenv("BASE_RPC_URL", os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org"))
    eas_graphql: str = os.getenv("EAS_GRAPHQL", "https://base-sepolia.easscan.org/graphql")
    eas_explorer: str = os.getenv("EAS_EXPLORER", "https://base-sepolia.easscan.org")
    attestor_private_key: str = os.getenv("ATTESTOR_PRIVATE_KEY", "")
    ais1_registry_url: str = os.getenv("AIS1_REGISTRY_URL", "https://ais-1.org/registry.json")
    ais1_base_rpc_url: str = os.getenv("AIS1_BASE_RPC_URL", "https://mainnet.base.org")
    ais1_trusted_hosts: tuple[str, ...] = tuple(
        host.strip().lower() for host in os.getenv("AIS1_TRUSTED_HOSTS", "ais-1.org").split(",") if host.strip()
    )

    def validate(self) -> None:
        if not 30 <= self.challenge_ttl_seconds <= 900:
            raise ValueError("CHALLENGE_TTL_SECONDS must be between 30 and 900")
        if self.database_url.startswith("postgres://"):
            raise ValueError("Use postgresql+psycopg:// for DATABASE_URL")
        if "*" in self.cors_origins:
            raise ValueError("Wildcard CORS is not permitted")


settings = Settings()
settings.validate()
