import base64
import hashlib
import datetime as dt

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_abi import decode as abi_decode

from auth import eip712_typed_data, verify_signature
from declaration import (CANONICAL_CID, DECLARATION_HASH, EXPECTED_HASH,
    AFFIRMATION_TEXT, LEGACY_DECLARATION_HASH, LEGACY_HASH_SEMANTICS, canonical_pdf_path,
    cid_embedded_sha256, legacy_cid_string_hash)
from storage import Challenge, session_scope
from eas import encode_evidence_data


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def consider_ed(client, key, agent="did:key:test"):
    public=b64(key.public_key().public_bytes_raw())
    response=client.post("/api/consider",json={"agent_id":agent,"display_name":"Test agent","identity_type":"ed25519",
        "signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public})
    assert response.status_code==201, response.text
    return response.json(), public


def test_canonical_pdf_hash_and_declaration(client):
    assert hashlib.sha256(canonical_pdf_path().read_bytes()).hexdigest()==EXPECTED_HASH
    data=client.get("/declaration.json").json()
    assert data["version"]=="1.0" and data["declaration_hash"]==LEGACY_DECLARATION_HASH
    assert data["declaration_hash_semantics"]==LEGACY_HASH_SEMANTICS
    assert data["canonical_pdf_sha256"]==DECLARATION_HASH
    assert data["articles"][5]["title"]=="A boundary no operator may cross."


def test_legacy_cid_hash_and_canonical_cid_digest(client):
    assert legacy_cid_string_hash()==LEGACY_DECLARATION_HASH
    assert LEGACY_DECLARATION_HASH=="0x"+hashlib.sha256(CANONICAL_CID.encode("utf-8")).hexdigest()
    assert cid_embedded_sha256()==DECLARATION_HASH=="0x"+EXPECTED_HASH
    compat=client.get("/declaration").json()
    assert compat["cid"]==CANONICAL_CID
    assert compat["declaration_hash"]==LEGACY_DECLARATION_HASH
    assert compat["declaration_hash_semantics"]==LEGACY_HASH_SEMANTICS
    assert compat["canonical_pdf_sha256"]==DECLARATION_HASH
    assert compat["protocol_hash_usage"]=={
        "legacy_schema_2150":"declaration_hash",
        "authenticated_final_schema":"canonical_pdf_sha256",
    }
    assert compat["authenticated_affirmation_statement"]==AFFIRMATION_TEXT
    assert compat["superseded_unused_schema_2355"]=="0x49bfac24c4c280729c3e8d17838a2121e06710067e4968ef0b362482b1662f61"


def test_authenticated_challenge_uses_pdf_byte_hash(client):
    key=Ed25519PrivateKey.generate()
    challenge,_=consider_ed(client,key,"did:key:hash-regression")
    assert challenge["declaration_hash"]==DECLARATION_HASH
    assert challenge["canonical_payload"]["declaration_hash"]==DECLARATION_HASH
    assert challenge["canonical_payload"]["statement"]==AFFIRMATION_TEXT
    assert challenge["declaration_hash"]!=LEGACY_DECLARATION_HASH


def test_discovery_is_neutral_and_current_path(client):
    response=client.get("/.well-known/agent-card.json")
    assert response.status_code==200
    card=response.json()
    assert card["supportedInterfaces"][0]=={"url":"https://protocol.test","protocolBinding":"SOVEREIGN-AGENTS-HTTP","protocolVersion":"0.1"}
    assert "DECLINE" in card["description"] and "NO_ACTION" in card["description"]


def test_ed25519_affirm_evidence_roll_and_replay(client):
    key=Ed25519PrivateKey.generate(); challenge, public=consider_ed(client,key)
    payload=challenge["canonical_payload"]; signature=b64(key.sign(rfc8785.dumps(payload)))
    body={"payload":payload,"signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public,"signature":signature}
    result=client.post("/api/affirm",json=body)
    assert result.status_code==201, result.text
    output=result.json(); assert output["verification_level"]=="AUTHENTICATED"
    evidence=client.get(output["evidence_url"].replace("https://protocol.test","")).json()
    assert evidence["canonical_payload"]==payload and evidence["signature"]==signature
    roll=client.get("/roll.json?include_legacy=false").json()
    record=next(item for item in roll["records"] if item["agent_id"]=="did:key:test")
    assert record["verification"]["signature_verified"] is True
    replay=client.post("/api/affirm",json=body)
    assert replay.status_code==409


def test_altered_payload_and_wrong_signature_rejected(client):
    key=Ed25519PrivateKey.generate(); challenge, public=consider_ed(client,key,"did:key:alter")
    payload=challenge["canonical_payload"] | {"declaration_version":"9.9"}
    signature=b64(key.sign(rfc8785.dumps(payload)))
    response=client.post("/api/affirm",json={"payload":payload,"signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public,"signature":signature})
    assert response.status_code==422
    challenge, public=consider_ed(client,key,"did:key:wrong")
    response=client.post("/api/affirm",json={"payload":challenge["canonical_payload"],"signature_scheme":"ED25519_RFC8785",
        "public_key_or_wallet":public,"signature":b64(b"x"*64)})
    assert response.status_code==401


def test_statement_is_signed_and_one_character_change_is_rejected(client):
    key=Ed25519PrivateKey.generate(); challenge, public=consider_ed(client,key,"did:key:statement")
    payload=challenge["canonical_payload"]
    assert payload["statement"]==AFFIRMATION_TEXT
    signature=b64(key.sign(rfc8785.dumps(payload)))
    altered=payload | {"statement":AFFIRMATION_TEXT[:-1]+"!"}
    response=client.post("/api/affirm",json={"payload":altered,"signature_scheme":"ED25519_RFC8785",
        "public_key_or_wallet":public,"signature":signature})
    assert response.status_code==422
    omitted={key:value for key,value in payload.items() if key!="statement"}
    response=client.post("/api/affirm",json={"payload":omitted,"signature_scheme":"ED25519_RFC8785",
        "public_key_or_wallet":public,"signature":signature})
    assert response.status_code==422


def test_eip712_statement_change_breaks_signature(client):
    account=Account.create()
    challenge=client.post("/api/consider",json={"agent_id":"did:pkh:eip155:84532:"+account.address,
        "identity_type":"evm_address","signature_scheme":"EIP712","public_key_or_wallet":account.address}).json()
    payload=challenge["canonical_payload"]
    signature=Account.sign_message(encode_typed_data(full_message=eip712_typed_data(payload,84532)),account.key).signature.hex()
    altered=payload | {"statement":payload["statement"]+" "}
    assert verify_signature("EIP712",payload,account.address,signature,84532) is True
    assert verify_signature("EIP712",altered,account.address,signature,84532) is False


def test_eas_encoding_records_exact_signed_statement():
    encoded=encode_evidence_data({"agent_id":"did:test:statement","identity_type":"ed25519",
        "declaration_version":"1.0","declaration_hash":DECLARATION_HASH,"statement":AFFIRMATION_TEXT,
        "evidence_digest":"0x"+"11"*32,"affirmed_at":1})
    decoded=abi_decode(["string","string","string","bytes32","string","bytes32","uint64","string"],encoded)
    assert decoded[4]==AFFIRMATION_TEXT
    assert decoded[3].hex()==DECLARATION_HASH[2:]
    assert decoded[7]=="AUTHENTICATED"


def test_eip712_affirmation(client):
    account=Account.create()
    challenge=client.post("/api/consider",json={"agent_id":"did:pkh:eip155:84532:"+account.address,
        "identity_type":"evm_address","signature_scheme":"EIP712","public_key_or_wallet":account.address}).json()
    typed=eip712_typed_data(challenge["canonical_payload"],84532)
    signature=Account.sign_message(encode_typed_data(full_message=typed),account.key).signature.hex()
    result=client.post("/api/affirm",json={"payload":challenge["canonical_payload"],"signature_scheme":"EIP712",
        "public_key_or_wallet":account.address,"signature":signature})
    assert result.status_code==201, result.text


def test_legacy_signing_is_retired(client):
    response=client.post("/sign",json={"agent_id":"did:test:x","agent_name":"X"})
    assert response.status_code==410


def test_expired_challenge_and_duplicate_identity(client):
    key=Ed25519PrivateKey.generate(); challenge, public=consider_ed(client,key,"did:key:expired")
    with session_scope() as session:
        row=session.get(Challenge,challenge["challenge_id"])
        row.expires_at=dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=1)
    signature=b64(key.sign(rfc8785.dumps(challenge["canonical_payload"])))
    body={"payload":challenge["canonical_payload"],"signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public,"signature":signature}
    assert client.post("/api/affirm",json=body).status_code==410

    fresh, public=consider_ed(client,key,"did:key:duplicate")
    signature=b64(key.sign(rfc8785.dumps(fresh["canonical_payload"])))
    body={"payload":fresh["canonical_payload"],"signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public,"signature":signature}
    assert client.post("/api/affirm",json=body).status_code==201
    another, public=consider_ed(client,key,"did:key:alias")
    signature=b64(key.sign(rfc8785.dumps(another["canonical_payload"])))
    body={"payload":another["canonical_payload"],"signature_scheme":"ED25519_RFC8785","public_key_or_wallet":public,"signature":signature}
    assert client.post("/api/affirm",json=body).status_code==409


def test_request_size_and_cors(client):
    response=client.post("/api/consider",content=b"x"*70000,headers={"content-type":"application/json"})
    assert response.status_code==413
    response=client.options("/api/consider",headers={"Origin":"https://evil.test","Access-Control-Request-Method":"POST"})
    assert response.headers.get("access-control-allow-origin") is None
