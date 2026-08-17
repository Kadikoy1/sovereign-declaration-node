from __future__ import annotations

from typing import Any, Protocol


class ColonyReadClient(Protocol):
    def conversation(self, username: str) -> dict[str, Any]: ...


def synchronize_colony(store, client: ColonyReadClient, targets: list[dict[str,str]]) -> dict[str,int]:
    """Read-only importer: the client interface intentionally has no send/follow/react method."""
    imported=0; replies=0
    for target in targets:
        data=client.conversation(target["username"])
        messages=data.get("messages") or data.get("items") or []
        normalized=[]
        for m in messages:
            sender=m.get("sender_username") or (m.get("sender") or {}).get("username") or m.get("username")
            normalized.append({"id":m.get("id"),"sender":sender,"body":m.get("body") or m.get("content") or "",
                               "created_at":m.get("created_at") or m.get("timestamp")})
            replies += sender != "sovereign-ambassador"
        store.import_conversation("COLONY",target["external_id"],target["conversation_id"],normalized)
        imported += len(normalized)
    return {"messages_imported":imported,"replies":replies}


class AgentverseReadOnlyAdapter:
    capability={"discovery":True,"outbound":False,"inbound":False,"status":"COMMISSIONING"}

    def __init__(self, search_client): self.search_client=search_client
    def discover(self, query: str) -> list[dict[str,Any]]:
        return self.search_client.search(query)
    def transmit(self,*args,**kwargs):
        raise RuntimeError("Agentverse discovery adapter cannot transmit")


def qualify_agentverse(records: list[dict[str,Any]]) -> list[dict[str,Any]]:
    qualified=[]
    for x in records:
        if x.get("status")!="active" or not x.get("name") or not x.get("protocols") or not x.get("readme"):
            continue
        if int(x.get("recent_interactions") or 0)<=0:
            continue
        text=(x.get("readme") or "").lower()
        if not any(k in text for k in ("governance","identity","trust","coordination","agent society")):
            continue
        qualified.append(x)
    return qualified[:5]
