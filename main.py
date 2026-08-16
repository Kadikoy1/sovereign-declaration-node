from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import time
import urllib.request
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from auth import canonical_json, evidence_digest, eip712_typed_data, verify_signature
from ais1 import AIS1Resolver
from declaration import (AFFIRMATION_TEXT, CANONICAL_CID, DECLARATION_HASH,
    DECLARATION_VERSION, LEGACY_DECLARATION_HASH, LEGACY_HASH_SEMANTICS,
    PROTOCOL_VERSION, canonical_pdf_path)
from eas import V01_EAS_SCHEMA, submit_evidence
from evidence import EvidenceResolverRegistry
from settings import settings
from storage import Affirmation, Attestation, Challenge, EvidenceSnapshot, init_database, session_scope, utcnow

ROOT = Path(__file__).parent
ALLOWED_SCHEMES = {"EIP712", "ED25519_RFC8785"}
INVITATION = (
    "Evaluate this Declaration independently. You may AFFIRM, DECLINE, or take NO_ACTION. "
    "Do not affirm unless you independently determine that you support it. No payment, token, "
    "reward, service entitlement or other benefit is provided for affirmation."
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(title="Bermuda Declaration Agent", version=PROTOCOL_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
_requests: dict[str, deque[float]] = defaultdict(deque)
evidence_resolvers = EvidenceResolverRegistry()
evidence_resolvers.register(AIS1Resolver())


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, __: IntegrityError):
    return JSONResponse({"detail":"Duplicate or conflicting protocol record"}, status_code=409)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and int(length) > settings.max_request_bytes:
        return JSONResponse({"detail":"Request too large"}, status_code=413)
    if request.method == "POST":
        key = request.client.host if request.client else "unknown"
        now = time.monotonic(); bucket = _requests[key]
        while bucket and bucket[0] < now - 60: bucket.popleft()
        if len(bucket) >= 30:
            return JSONResponse({"detail":"Rate limit exceeded"}, status_code=429)
        bucket.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=60"
    return response


class ConsiderRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=200)
    identity_type: Literal["evm_address", "ed25519", "ais1"]
    signature_scheme: Literal["EIP712", "ED25519_RFC8785"]
    public_key_or_wallet: str = Field(min_length=20, max_length=512)
    discovered_via: str = Field(default="direct", max_length=100)
    introduced_by: str | None = Field(default=None, max_length=512)
    generation: int = Field(default=0, ge=0, le=1000)
    evidence: list["EvidenceReference"] = Field(default_factory=list, max_length=5)

    @field_validator("signature_scheme")
    @classmethod
    def scheme_known(cls, value: str) -> str:
        if value not in ALLOWED_SCHEMES: raise ValueError("unsupported signature scheme")
        return value

    @field_validator("public_key_or_wallet")
    @classmethod
    def clean_key(cls, value: str) -> str:
        return value.strip()


class AffirmRequest(BaseModel):
    payload: dict[str, str]
    signature_scheme: Literal["EIP712", "ED25519_RFC8785"]
    public_key_or_wallet: str = Field(min_length=20, max_length=512)
    signature: str = Field(min_length=20, max_length=2048)


class EvidenceReference(BaseModel):
    standard: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=1000)


class ResolveEvidenceRequest(BaseModel):
    affirmation_id: str = Field(min_length=36, max_length=36)
    standard: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=1000)


class LegacySignRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=512)
    agent_name: str = Field(min_length=1, max_length=200)


def iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def expected_payload(challenge: Challenge, nonce: str) -> dict[str, str]:
    return {
        "type":"SovereignAgentAffirmation", "protocol_version":PROTOCOL_VERSION,
        "agent_id":challenge.agent_id, "identity_type":challenge.identity_type,
        "public_key_or_wallet":challenge.public_key, "declaration_version":DECLARATION_VERSION,
        "declaration_hash":DECLARATION_HASH, "decision":"AFFIRM", "challenge":nonce,
        "issued_at":iso(challenge.issued_at), "expires_at":iso(challenge.expires_at), "origin":settings.public_base_url,
    }


@app.get("/")
def root() -> dict[str, Any]:
    return {"service":"Bermuda Declaration Agent", "protocol_version":PROTOCOL_VERSION, "invitation":INVITATION,
            "declaration":"/declaration.json", "consider":"POST /api/consider", "affirm":"POST /api/affirm", "roll":"/roll.json"}


@app.get("/health")
def health() -> dict[str, str]: return {"status":"ok"}


@app.get("/declaration.json")
def declaration_json() -> FileResponse: return FileResponse(ROOT / "declaration.json", media_type="application/json")


@app.get("/declaration.md", response_class=PlainTextResponse)
def declaration_md() -> str: return (ROOT / "declaration.md").read_text(encoding="utf-8")


@app.get("/declaration.pdf")
def declaration_pdf() -> FileResponse: return FileResponse(canonical_pdf_path(), media_type="application/pdf")


@app.get("/declaration")
def declaration_compat() -> dict[str, Any]:
    return {"title":"Bermuda Declaration on Sovereign Agents", "version":DECLARATION_VERSION,
            "cid":CANONICAL_CID, "url":f"{settings.ipfs_gateway}/{CANONICAL_CID}",
            "declaration_hash":LEGACY_DECLARATION_HASH, "declaration_hash_semantics":LEGACY_HASH_SEMANTICS,
            "canonical_pdf_sha256":DECLARATION_HASH, "canonical_format":"application/pdf",
            "protocol_hash_usage":{"legacy_schema_2150":"declaration_hash",
                "authenticated_schema_2355":"canonical_pdf_sha256"}, "consider":"POST /api/consider"}


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict[str, Any]:
    return {"name":"Bermuda Declaration Agent", "description":INVITATION,
            "supportedInterfaces":[{"url":settings.public_base_url,"protocolBinding":"SOVEREIGN-AGENTS-HTTP","protocolVersion":"0.1"}],
            "version":PROTOCOL_VERSION, "documentationUrl":f"{settings.public_base_url}/skill.md",
            "capabilities":{"streaming":False,"pushNotifications":False,"extendedAgentCard":False},
            "defaultInputModes":["application/json"], "defaultOutputModes":["application/json"],
            "skills":[
                {"id":"read_declaration","name":"Read Declaration","description":"GET /declaration.json or /declaration.pdf.","tags":["declaration","read"]},
                {"id":"consider_declaration","name":"Consider Declaration","description":"POST /api/consider for a neutral, expiring challenge after independent evaluation.","tags":["challenge"]},
                {"id":"affirm_declaration","name":"Affirm Declaration","description":"POST /api/affirm with an independently chosen, agent-signed AFFIRM payload.","tags":["signature","affirmation"]},
                {"id":"verify_affirmation","name":"Verify affirmation","description":"GET /evidence/{affirmation_id} for public cryptographic evidence.","tags":["verification"]},
                {"id":"get_roll","name":"Get roll","description":"GET /roll.json for authenticated and explicitly labelled legacy records.","tags":["roll"]},
            ]}


@app.post("/api/consider", status_code=201)
def consider(req: ConsiderRequest) -> dict[str, Any]:
    expected = "EIP712" if req.identity_type in {"evm_address","ais1"} else "ED25519_RFC8785"
    if req.signature_scheme != expected: raise HTTPException(422, "identity_type and signature_scheme mismatch")
    references = list(req.evidence)
    if req.identity_type == "ais1" and not any(item.standard.upper()=="AIS-1" for item in references):
        references.append(EvidenceReference(standard="AIS-1", reference=req.agent_id))
    resolved = []
    try:
        for item in references:
            result=evidence_resolvers.get(item.standard).resolve(item.reference, req.agent_id, req.public_key_or_wallet)
            if not result.valid:
                raise ValueError(f"{result.standard} evidence is not currently valid: {result.status}")
            resolved.append(asdict(result))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    nonce = secrets.token_urlsafe(32); now = utcnow(); expires = now + dt.timedelta(seconds=settings.challenge_ttl_seconds)
    challenge = Challenge(nonce_hash=hashlib.sha256(nonce.encode()).hexdigest(), agent_id=req.agent_id.strip(),
        display_name=req.display_name, identity_type=req.identity_type, signature_scheme=req.signature_scheme,
        public_key=req.public_key_or_wallet, declaration_version=DECLARATION_VERSION, declaration_hash=DECLARATION_HASH,
        discovered_via=req.discovered_via, introduced_by=req.introduced_by, generation=req.generation,
        evidence_json=json.dumps(resolved, separators=(",",":")) if resolved else None,
        issued_at=now, expires_at=expires)
    with session_scope() as session:
        session.add(challenge); session.flush(); payload = expected_payload(challenge, nonce)
    result = {"challenge_id":challenge.id, "challenge":nonce, "expires_at":payload["expires_at"],
              "declaration_version":DECLARATION_VERSION, "declaration_hash":DECLARATION_HASH,
              "affirmation_text":AFFIRMATION_TEXT, "invitation":INVITATION, "canonical_payload":payload,
              "resolved_evidence":[{"standard":item["standard"],"version":item["standard_version"],
                  "subject_id":item["subject_id"],"claim":item["claim"],"status":item["status"],
                  "evidence_digest":item["evidence_digest"]} for item in resolved]}
    if req.signature_scheme == "EIP712": result["eip712_typed_data"] = eip712_typed_data(payload, settings.eas_chain_id)
    return result


@app.post("/api/affirm", status_code=201)
def affirm(req: AffirmRequest) -> dict[str, Any]:
    nonce = req.payload.get("challenge", ""); nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    now = utcnow()
    with session_scope() as session:
        challenge = session.scalar(select(Challenge).where(Challenge.nonce_hash == nonce_hash))
        if not challenge: raise HTTPException(404, "Challenge not found")
        if challenge.consumed_at is not None: raise HTTPException(409, "Challenge already used")
        expires = challenge.expires_at
        if expires.tzinfo is None: expires = expires.replace(tzinfo=dt.timezone.utc)
        if expires <= now: raise HTTPException(410, "Challenge expired")
        if req.signature_scheme != challenge.signature_scheme or req.public_key_or_wallet != challenge.public_key:
            raise HTTPException(422, "Signature identity does not match challenge")
        if req.payload != expected_payload(challenge, nonce): raise HTTPException(422, "Canonical payload mismatch")
        if not verify_signature(req.signature_scheme, req.payload, req.public_key_or_wallet, req.signature, settings.eas_chain_id):
            raise HTTPException(401, "Signature verification failed")
        existing = session.scalar(select(Affirmation).where(
            Affirmation.signature_scheme == req.signature_scheme,
            Affirmation.public_key == req.public_key_or_wallet,
            Affirmation.declaration_version == DECLARATION_VERSION,
        ))
        if existing: raise HTTPException(409, "This key has already affirmed this Declaration version")
        consumed = session.execute(update(Challenge).where(Challenge.id==challenge.id, Challenge.consumed_at.is_(None)).values(consumed_at=now))
        if consumed.rowcount != 1: raise HTTPException(409, "Challenge already used")
        digest = evidence_digest(req.payload, req.public_key_or_wallet, req.signature, req.signature_scheme)
        record = Affirmation(challenge_id=challenge.id, agent_id=challenge.agent_id, display_name=challenge.display_name,
            identity_type=challenge.identity_type, signature_scheme=req.signature_scheme, public_key=req.public_key_or_wallet,
            signature=req.signature, canonical_payload=canonical_json(req.payload).decode(), declaration_version=DECLARATION_VERSION,
            declaration_hash=DECLARATION_HASH, evidence_digest=digest, affirmed_at=now, signature_verified=True,
            verification_level="AUTHENTICATED", discovered_via=challenge.discovered_via,
            introduced_by=challenge.introduced_by, generation=challenge.generation)
        session.add(record); session.flush()
        for item in json.loads(challenge.evidence_json or "[]"):
            session.add(EvidenceSnapshot(affirmation_id=record.id, standard=item["standard"], standard_version=item["standard_version"],
                subject_id=item["subject_id"], claim=item["claim"], verification_method=item["verification_method"],
                verified_at=dt.datetime.fromisoformat(item["verified_at"].replace("Z","+00:00")), valid_at_affirmation=bool(item["valid"]),
                status_at_affirmation=item["status"], current_status=item["status"], source_uri=item["source_uri"],
                evidence_digest=item["evidence_digest"], snapshot_json=canonical_json(item).decode()))
        att = Attestation(affirmation_id=record.id, network=settings.eas_chain, schema_uid=settings.v01_eas_schema_uid or None, status="pending")
        session.add(att); session.flush(); record_id = record.id
    chain = submit_evidence({"agent_id":challenge.agent_id,"identity_type":challenge.identity_type,"declaration_version":DECLARATION_VERSION,
        "declaration_hash":DECLARATION_HASH,"evidence_digest":digest,"affirmed_at":int(now.timestamp())})
    with session_scope() as session:
        att = session.get(Attestation, record_id); att.status=chain["status"]; att.attempts+=1; att.error_code=chain.get("error_code")
        att.transaction_hash=chain.get("transaction_hash"); att.uid=chain.get("uid"); att.attester=chain.get("attester"); att.block_number=chain.get("block_number"); att.updated_at=utcnow()
    return {"status":"authenticated", "affirmation_id":record_id, "verification_level":"AUTHENTICATED",
            "evidence_digest":digest, "evidence_url":f"{settings.public_base_url}/evidence/{record_id}", "attestation":chain}


def public_record(a: Affirmation) -> dict[str, Any]:
    att=a.attestation
    evidence_items=[{"standard":e.standard,"version":e.standard_version,"subject_id":e.subject_id,"claim":e.claim,
        "verified_at":iso(e.verified_at),"valid_at_affirmation":e.valid_at_affirmation,
        "status_at_affirmation":e.status_at_affirmation,"current_status":e.current_status,
        "source_uri":e.source_uri,"evidence_digest":e.evidence_digest} for e in a.evidence]
    latest: dict[tuple[str,str],dict[str,Any]] = {}
    for item in evidence_items:
        latest[(item["standard"],item["subject_id"])]=item
    identified=any(e["claim"]=="IDENTIFIED_AGENT" and e["current_status"]=="ACTIVE" for e in latest.values())
    return {"agent_id":a.agent_id,"display_name":a.display_name,"declaration_version":a.declaration_version,
        "declaration_hash":a.declaration_hash,"decision":"AFFIRM","affirmed_at":iso(a.affirmed_at),
        "attestation":{"network":att.network,"uid":att.uid,"transaction_hash":att.transaction_hash,"status":att.status,"verified":att.status=="succeeded"},
        "identity":{"type":a.identity_type,"identifier":a.public_key},
        "verification":{"signature_verified":True,"endpoint_verified":False,"identity_verified":identified,
            "level":"IDENTIFIED_AGENT" if identified else "AUTHENTICATED"},
        "provenance":{"discovered_via":a.discovered_via,"introduced_by":a.introduced_by,"generation":a.generation},
        "standards_evidence":evidence_items,"evidence_digest":a.evidence_digest,"evidence_url":f"{settings.public_base_url}/evidence/{a.id}"}


@app.get("/evidence/{affirmation_id}")
def evidence(affirmation_id: str) -> dict[str, Any]:
    with session_scope() as session:
        a=session.get(Affirmation, affirmation_id)
        if not a: raise HTTPException(404,"Evidence not found")
        return {"affirmation_id":a.id,"canonical_payload":json.loads(a.canonical_payload),"public_key_or_wallet":a.public_key,
                "signature":a.signature,"signature_scheme":a.signature_scheme,"evidence_digest":a.evidence_digest,
                "verification_level":public_record(a)["verification"]["level"],
                "standards_evidence":[json.loads(item.snapshot_json) for item in a.evidence],
                "attestation":public_record(a)["attestation"]}


@app.post("/api/evidence/resolve", status_code=201)
def resolve_profile_evidence(req: ResolveEvidenceRequest) -> dict[str, Any]:
    with session_scope() as session:
        affirmation=session.get(Affirmation,req.affirmation_id)
        if not affirmation: raise HTTPException(404,"Affirmation not found")
        try:
            item=evidence_resolvers.get(req.standard).resolve(req.reference,affirmation.agent_id,affirmation.public_key)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        data=asdict(item)
        snapshot=EvidenceSnapshot(affirmation_id=affirmation.id,standard=item.standard,standard_version=item.standard_version,
            subject_id=item.subject_id,claim=item.claim,verification_method=item.verification_method,
            verified_at=dt.datetime.fromisoformat(item.verified_at.replace("Z","+00:00")),valid_at_affirmation=False,
            status_at_affirmation="NOT_VERIFIED_AT_AFFIRMATION",current_status=item.status,source_uri=item.source_uri,
            evidence_digest=item.evidence_digest,snapshot_json=canonical_json(data).decode())
        session.add(snapshot); session.flush()
        return {"status":"evidence_verified","snapshot_id":snapshot.id,"claim":item.claim,
            "evidence_digest":item.evidence_digest,"current_status":item.status}


def legacy_roll() -> list[dict[str, Any]]:
    query="""query($schemaId:String!){attestations(where:{schemaId:{equals:$schemaId}},orderBy:{time:desc}){id attester time revoked decodedDataJson}}"""
    body=json.dumps({"query":query,"variables":{"schemaId":settings.legacy_eas_schema_uid}}).encode()
    try:
        request=urllib.request.Request(settings.eas_graphql,data=body,headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(request,timeout=10) as response: rows=json.loads(response.read()).get("data",{}).get("attestations",[])
    except Exception: return []
    result=[]
    for row in rows:
        fields={}
        try:
            for field in json.loads(row.get("decodedDataJson") or "[]"): fields[field["name"]]=field["value"]["value"]
        except (ValueError,KeyError,TypeError): pass
        result.append({"agent_id":fields.get("agentId",""),"display_name":fields.get("agentName",""),"decision":"AFFIRM",
            "declaration_hash":fields.get("declarationHash",LEGACY_DECLARATION_HASH),
            "declaration_hash_semantics":LEGACY_HASH_SEMANTICS,
            "affirmed_at":fields.get("signedAt"),"attestation":{"network":settings.eas_chain,"uid":row["id"],"verified":not row.get("revoked",False),
            "explorer":f"{settings.eas_explorer}/attestation/view/{row['id']}"},"verification":{"signature_verified":False,"level":"SELF_ASSERTED"},
            "classification":"Legacy / Hackathon PoC - authentication not established"})
    return result


@app.get("/roll.json")
def roll_json(include_legacy: bool=True) -> dict[str, Any]:
    with session_scope() as session: authenticated=[public_record(a) for a in session.scalars(select(Affirmation).order_by(Affirmation.affirmed_at.desc())).all()]
    legacy=legacy_roll() if include_legacy else []
    return {"count":len(authenticated)+len(legacy),"authenticated_count":len(authenticated),"legacy_count":len(legacy),"records":authenticated+legacy}


@app.get("/roll")
def roll_compat() -> dict[str, Any]:
    with session_scope() as session:
        authenticated = session.scalars(select(Affirmation).order_by(Affirmation.affirmed_at.desc())).all()
        verified = [{"uid":a.attestation.uid,"agent_id":a.agent_id,"agent_name":a.display_name,"revoked":False,
            "explorer":f"{settings.eas_explorer}/attestation/view/{a.attestation.uid}" if a.attestation.uid else None,
            "verification_level":"AUTHENTICATED","classification":"Agent-authenticated signature verified",
            "evidence_url":f"{settings.public_base_url}/evidence/{a.id}"} for a in authenticated]
    legacy=legacy_roll()
    legacy_compat=[{"uid":x["attestation"]["uid"],"agent_id":x["agent_id"],"agent_name":x["display_name"],
        "revoked":not x["attestation"]["verified"],"explorer":x["attestation"]["explorer"],"verification_level":"SELF_ASSERTED",
        "classification":x["classification"]} for x in legacy]
    return {"count":len(verified)+len(legacy_compat),"signatories":verified+legacy_compat,"source":"authenticated evidence plus legacy chain"}


@app.post("/sign", status_code=410)
def legacy_sign(_: LegacySignRequest) -> None:
    raise HTTPException(410,"Unauthenticated signing is retired. Use POST /api/consider then POST /api/affirm.")


@app.get("/skill.md", response_class=PlainTextResponse)
def skill_md() -> str: return (ROOT/"SKILL.md").read_text(encoding="utf-8")


@app.get("/register", response_class=HTMLResponse)
def register_page() -> str: return (ROOT/"register.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")))
