import main
from evidence import EvidenceResolver, ResolvedEvidence, verified_now


class FakeAIS1Resolver(EvidenceResolver):
    standard="AIS-1"
    def resolve(self,reference,expected_subject,expected_key):
        if reference != "did:ais1:base:test-agent": raise ValueError("not found")
        return ResolvedEvidence(standard="AIS-1",standard_version="0.2",subject_id=reference,
            claim="IDENTIFIED_AGENT",verification_method="TEST_DID_AND_BOND",verified_at=verified_now(),
            valid=True,status="ACTIVE",source_uri="https://ais-1.org/resolve/test-agent.json",
            facts={"authorized_key":expected_key,"bond_id":"ais1:base:99999","tier":1}).finalized()


def test_ais1_evidence_bound_at_affirmation(client):
    original=main.evidence_resolvers._resolvers["AIS-1"]
    main.evidence_resolvers._resolvers["AIS-1"]=FakeAIS1Resolver()
    try:
        # AIS-1 currently binds an EVM authentication key; use the existing EIP-712 helper path.
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        from auth import eip712_typed_data
        account=Account.create()
        challenge=client.post("/api/consider",json={"agent_id":"did:ais1:base:test-agent","identity_type":"ais1",
            "signature_scheme":"EIP712","public_key_or_wallet":account.address}).json()
        signature=Account.sign_message(encode_typed_data(full_message=eip712_typed_data(challenge["canonical_payload"],84532)),account.key).signature.hex()
        result=client.post("/api/affirm",json={"payload":challenge["canonical_payload"],"signature_scheme":"EIP712",
            "public_key_or_wallet":account.address,"signature":signature})
        assert result.status_code==201,result.text
        record=client.get("/roll.json?include_legacy=false").json()["records"][0]
        assert record["verification"]["level"]=="IDENTIFIED_AGENT"
        assert record["standards_evidence"][0]["valid_at_affirmation"] is True
    finally:
        main.evidence_resolvers._resolvers["AIS-1"]=original


def test_later_evidence_attachment_is_historical_not_rewritten(client):
    original=main.evidence_resolvers._resolvers["AIS-1"]
    main.evidence_resolvers._resolvers["AIS-1"]=FakeAIS1Resolver()
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        from auth import eip712_typed_data
        account=Account.create()
        challenge=client.post("/api/consider",json={"agent_id":"did:pkh:eip155:8453:"+account.address,"identity_type":"evm_address",
            "signature_scheme":"EIP712","public_key_or_wallet":account.address}).json()
        signature=Account.sign_message(encode_typed_data(full_message=eip712_typed_data(challenge["canonical_payload"],84532)),account.key).signature.hex()
        affirmed=client.post("/api/affirm",json={"payload":challenge["canonical_payload"],"signature_scheme":"EIP712",
            "public_key_or_wallet":account.address,"signature":signature}).json()
        attached=client.post("/api/evidence/resolve",json={"affirmation_id":affirmed["affirmation_id"],"standard":"AIS-1",
            "reference":"did:ais1:base:test-agent"})
        assert attached.status_code==201,attached.text
        evidence=client.get(affirmed["evidence_url"].replace("https://protocol.test","")).json()["standards_evidence"][-1]
        assert evidence["claim"]=="IDENTIFIED_AGENT"
        # The later identity is current evidence, not retroactive evidence at the affirmation time.
        roll=client.get("/roll.json?include_legacy=false").json()["records"]
        record=next(item for item in roll if item["agent_id"].startswith("did:pkh:eip155:8453:"))
        assert record["standards_evidence"][-1]["valid_at_affirmation"] is False
        assert record["standards_evidence"][-1]["status_at_affirmation"]=="NOT_VERIFIED_AT_AFFIRMATION"
    finally:
        main.evidence_resolvers._resolvers["AIS-1"]=original
