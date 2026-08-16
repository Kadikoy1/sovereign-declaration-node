from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from settings import settings


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signature_scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key: Mapped[str] = mapped_column(String(512), nullable=False)
    discovered_via: Mapped[str] = mapped_column(String(100), nullable=False, default="direct")
    introduced_by: Mapped[str | None] = mapped_column(String(512))
    generation: Mapped[int] = mapped_column(nullable=False, default=0)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    declaration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    declaration_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Affirmation(Base):
    __tablename__ = "affirmations"
    __table_args__ = (
        UniqueConstraint("signature_scheme", "public_key", "declaration_version", name="uq_identity_declaration"),
        UniqueConstraint("evidence_digest", name="uq_evidence_digest"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    challenge_id: Mapped[str] = mapped_column(ForeignKey("challenges.id"), unique=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signature_scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key: Mapped[str] = mapped_column(String(512), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_payload: Mapped[str] = mapped_column(Text, nullable=False)
    declaration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    declaration_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(66), nullable=False)
    affirmed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verification_level: Mapped[str] = mapped_column(String(32), nullable=False, default="AUTHENTICATED")
    discovered_via: Mapped[str] = mapped_column(String(100), nullable=False, default="direct")
    introduced_by: Mapped[str | None] = mapped_column(String(512))
    generation: Mapped[int] = mapped_column(nullable=False, default=0)
    attestation: Mapped["Attestation | None"] = relationship(back_populates="affirmation", uselist=False)
    evidence: Mapped[list["EvidenceSnapshot"]] = relationship(back_populates="affirmation", order_by="EvidenceSnapshot.verified_at")


class Attestation(Base):
    __tablename__ = "attestations"
    affirmation_id: Mapped[str] = mapped_column(ForeignKey("affirmations.id"), primary_key=True)
    network: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_uid: Mapped[str | None] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    transaction_hash: Mapped[str | None] = mapped_column(String(66), unique=True)
    uid: Mapped[str | None] = mapped_column(String(66), unique=True)
    attester: Mapped[str | None] = mapped_column(String(42))
    block_number: Mapped[int | None]
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    affirmation: Mapped[Affirmation] = relationship(back_populates="attestation")


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshots"
    __table_args__ = (UniqueConstraint("affirmation_id", "evidence_digest", name="uq_affirmation_evidence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    affirmation_id: Mapped[str] = mapped_column(ForeignKey("affirmations.id"), nullable=False, index=True)
    standard: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    standard_version: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(512), nullable=False)
    claim: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_at_affirmation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_at_affirmation: Mapped[str] = mapped_column(String(64), nullable=False)
    current_status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(66), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    affirmation: Mapped[Affirmation] = relationship(back_populates="evidence")


class AgentResponse(Base):
    __tablename__ = "agent_responses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    commentary: Mapped[str | None] = mapped_column(Text)
    declaration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    declaration_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_level: Mapped[str] = mapped_column(String(32), nullable=False, default="SELF_ASSERTED")
    model_provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_metadata_json: Mapped[str | None] = mapped_column(Text)
    response_digest: Mapped[str] = mapped_column(String(66), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    publication_consent: Mapped[str] = mapped_column(String(16), nullable=False, index=True)


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def init_database() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            yield session
