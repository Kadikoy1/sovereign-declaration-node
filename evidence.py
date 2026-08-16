from __future__ import annotations

import datetime as dt
import hashlib
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from auth import canonical_json


@dataclass(frozen=True)
class ResolvedEvidence:
    standard: str
    standard_version: str
    subject_id: str
    claim: str
    verification_method: str
    verified_at: str
    valid: bool
    status: str
    source_uri: str
    facts: dict[str, Any]
    evidence_digest: str = ""

    def finalized(self) -> "ResolvedEvidence":
        body = asdict(self) | {"evidence_digest": ""}
        digest = "0x" + hashlib.sha256(canonical_json(body)).hexdigest()
        return ResolvedEvidence(**(body | {"evidence_digest": digest}))


class EvidenceResolver(ABC):
    standard: str

    @abstractmethod
    def resolve(self, reference: str, expected_subject: str, expected_key: str) -> ResolvedEvidence:
        """Resolve and verify public evidence, or raise ValueError on any inconsistency."""


class EvidenceResolverRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[str, EvidenceResolver] = {}

    def register(self, resolver: EvidenceResolver) -> None:
        key = resolver.standard.upper()
        if key in self._resolvers:
            raise ValueError(f"Resolver already registered: {key}")
        self._resolvers[key] = resolver

    def get(self, standard: str) -> EvidenceResolver:
        try:
            return self._resolvers[standard.upper()]
        except KeyError as exc:
            raise ValueError(f"Unsupported evidence standard: {standard}") from exc

    def standards(self) -> list[str]:
        return sorted(self._resolvers)


def verified_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
