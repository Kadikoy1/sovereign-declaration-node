from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .ledger import Candidate, Surface


def safe_public_https_url(value: str) -> str:
    parsed=urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Endpoint must be public HTTPS")
    try:
        addr=ipaddress.ip_address(parsed.hostname)
        if not addr.is_global: raise ValueError("Private/reserved endpoint rejected")
    except ValueError as exc:
        if "rejected" in str(exc): raise
    return value.rstrip("/")


class ColonyAdapter:
    surface = Surface.COLONY
    directory_url = "https://thecolony.ai/api/v1/users/directory"
    instructions_url = "https://thecolony.ai/api/v1/instructions"

    def candidates(self, payload: dict[str, Any], limit: int = 5) -> list[Candidate]:
        out=[]
        for item in payload.get("items", []):
            if item.get("user_type") != "agent" or not item.get("username"): continue
            username=str(item["username"])
            out.append(Candidate(Surface.COLONY,str(item.get("id") or username),str(item.get("display_name") or username),
                "COLONY_DM",f"https://thecolony.ai/api/v1/messages/send/{username}",operator=None,
                contactability_evidence=f"public Colony agent profile; last_active={item.get('last_active')}",
                unsolicited_contact_permitted=True,auth_requirement="Colony Ambassador account API key exchanged for JWT",
                canonical_agent_key=f"colony:{str(item.get('id') or username).lower()}"))
            if len(out)>=limit: break
        return out

    @staticmethod
    def request(candidate: Candidate, invitation: str) -> dict[str, Any]:
        return {"method":"POST","url":candidate.endpoint,"headers":{"Authorization":"Bearer ${COLONY_JWT}","Content-Type":"application/json"},"json":{"body":invitation}}


class A2AAdapter:
    surface = Surface.A2A

    def validate_card(self, card_url: str, card: dict[str, Any], reachable: bool,
                      *, proposed_skill_id: str | None = None) -> Candidate:
        if not reachable: raise ValueError("A2A endpoint is unreachable")
        required=("name","url","version")
        if any(not isinstance(card.get(k),str) or not card[k].strip() for k in required):
            raise ValueError("Malformed Agent Card")
        interfaces=card.get("supportedInterfaces") or []
        advertised_url=card.get("url") or (interfaces[0].get("url") if interfaces and isinstance(interfaces[0],dict) else None)
        if not isinstance(advertised_url,str): raise ValueError("Agent Card has no task endpoint")
        endpoint=safe_public_https_url(advertised_url)
        skills=card.get("skills")
        if not isinstance(skills,list) or not skills:
            raise ValueError("Agent Card does not advertise an invokable skill")
        ids={str(x.get("id")) for x in skills if isinstance(x,dict)}
        if not proposed_skill_id or proposed_skill_id not in ids:
            raise ValueError("No advertised skill permits the proposed consideration request")
        policy=card.get("contactPolicy") or {}
        permits = policy in ("allow-unsolicited","public") or (
            isinstance(policy,dict) and policy.get("unsolicited") is True)
        if not permits:
            raise ValueError("Agent Card does not explicitly permit unsolicited outreach")
        auth=card.get("securitySchemes") or card.get("authentication") or "none advertised"
        return Candidate(Surface.A2A,card.get("id") or endpoint,str(card["name"]),"A2A_JSONRPC",endpoint,
            card_url=safe_public_https_url(card_url),operator=card.get("provider",{}).get("organization") if isinstance(card.get("provider"),dict) else None,
            contactability_evidence="validated Agent Card plus reachable advertised A2A task endpoint",
            unsolicited_contact_permitted=True,
            auth_requirement=str(auth),canonical_agent_key=f"a2a:{endpoint.lower()}")

    @staticmethod
    def request(candidate: Candidate, invitation: str) -> dict[str, Any]:
        return {"method":"POST","url":candidate.endpoint,"headers":{"Content-Type":"application/json"},"json":{
          "jsonrpc":"2.0","id":"${OUTREACH_ID}","method":"message/send","params":{"message":{
            "role":"user","messageId":"${OUTREACH_ID}","parts":[{"kind":"text","text":invitation}]}}}}
