import pytest

import ais1
from ais1 import AIS1Resolver

DID="did:ais1:base:payagent-001"
KEY="0x6B921244b7239Ac9B961c06794Ec5eA3B61e87Bd"
CONTRACT="0x52d0E17b80d19470E0d97Ea6b62bf35d867FDcb3"
SPONSOR="did:ais1:sponsor:kadikoy-bm-202302362"

REGISTRY={"ais1_registry_version":"0.2","last_updated":"2026-04-04","bonds":[{
    "bond_id":"ais1:base:00001","bond_number":1,"contract_version":"v0.1","contract_address":CONTRACT,
    "agent_did":DID,"agent_class":"ala","parent_did":"","sponsor_did":SPONSOR,"tier":1,
    "status":"active","issued_at":"2026-04-02","jurisdiction":"BM","network":"base-mainnet",
    "txn_hash":"0x"+"1"*64,"did_document_url":"https://ais-1.org/resolve/payagent-001.json"}]}
DOCUMENT={"id":DID,"verificationMethod":[{"id":DID+"#primary","blockchainAccountId":"eip155:8453:"+KEY}],
    "authentication":[DID+"#primary"],"ais1":{"spec_version":"0.2","bond_id":"ais1:base:00001"}}


class Call:
    def __init__(self,value): self.value=value
    def call(self): return self.value


class Functions:
    def getBondByAgentDid(self,did): return Call(1)
    def verifyBond(self,bond_id): return Call((True,1,SPONSOR,1))


class Eth:
    def contract(self,**kwargs): return type("Contract",(),{"functions":Functions()})()


class FakeWeb3:
    HTTPProvider=staticmethod(lambda *args,**kwargs: object())
    def __init__(self,provider): self.eth=Eth()
    @staticmethod
    def is_address(value): return isinstance(value,str) and value.startswith("0x") and len(value)==42
    @staticmethod
    def to_checksum_address(value): return value


def sources(url):
    return REGISTRY if url.endswith("registry.json") else DOCUMENT


def test_ais1_resolver_verifies_did_key_registry_and_chain(monkeypatch):
    monkeypatch.setattr(ais1,"_trusted_json",sources)
    monkeypatch.setattr(ais1,"Web3",FakeWeb3)
    result=AIS1Resolver().resolve(DID,DID,KEY)
    assert result.valid and result.claim=="IDENTIFIED_AGENT"
    assert result.facts["bond_number"]==1 and result.facts["tier_name"]=="VERIFIED"
    assert result.facts["aml_label"]=="CLEARED" and result.evidence_digest.startswith("0x")


def test_ais1_resolver_rejects_key_and_registry_mismatch(monkeypatch):
    monkeypatch.setattr(ais1,"_trusted_json",sources)
    monkeypatch.setattr(ais1,"Web3",FakeWeb3)
    with pytest.raises(ValueError,match="not authorized"):
        AIS1Resolver().resolve(DID,DID,"0x"+"2"*40)
    bad={**REGISTRY,"bonds":[{**REGISTRY["bonds"][0],"network":"other"}]}
    monkeypatch.setattr(ais1,"_trusted_json",lambda url: bad if url.endswith("registry.json") else DOCUMENT)
    with pytest.raises(ValueError,match="not on Base"):
        AIS1Resolver().resolve(DID,DID,KEY)


def test_ais1_resolver_preserves_verified_revocation_status(monkeypatch):
    class RevokedFunctions(Functions):
        def verifyBond(self,bond_id): return Call((False,1,SPONSOR,1))
    class RevokedEth(Eth):
        def contract(self,**kwargs): return type("Contract",(),{"functions":RevokedFunctions()})()
    class RevokedWeb3(FakeWeb3):
        def __init__(self,provider): self.eth=RevokedEth()
    revoked={**REGISTRY,"bonds":[{**REGISTRY["bonds"][0],"status":"revoked"}]}
    monkeypatch.setattr(ais1,"_trusted_json",lambda url: revoked if url.endswith("registry.json") else DOCUMENT)
    monkeypatch.setattr(ais1,"Web3",RevokedWeb3)
    result=AIS1Resolver().resolve(DID,DID,KEY)
    assert result.valid is False and result.status=="REVOKED"
