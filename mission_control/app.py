from __future__ import annotations

import html,json,os,secrets
from pathlib import Path
from fastapi import Depends,FastAPI,HTTPException,Request,status
from fastapi.responses import HTMLResponse,JSONResponse,PlainTextResponse,RedirectResponse
from fastapi.security import HTTPBasic,HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from ambassador.constants import AMBASSADOR_ID,GLOBAL_INVITATION_LIMIT,SURFACE_INVITATION_LIMIT
from .store import MissionControlStore

ROOT=Path(__file__).parent
security=HTTPBasic(auto_error=False)


def _auth(credentials: HTTPBasicCredentials|None=Depends(security)):
    user=os.getenv("MISSION_CONTROL_USERNAME")
    password=os.getenv("MISSION_CONTROL_PASSWORD")
    if not user or not password:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,"Mission Control authentication is not configured")
    if not credentials or not secrets.compare_digest(credentials.username.encode(),user.encode()) or not secrets.compare_digest(credentials.password.encode(),password.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Authentication required",headers={"WWW-Authenticate":"Basic realm=Mission Control"})


def e(v): return html.escape(str(v or ""))
def details(label: str,payload) -> str:
    safe=e(json.dumps(payload,indent=2,sort_keys=True,default=str))
    return f'<details><summary>{e(label)}</summary><pre>{safe}</pre></details>'


def layout(title: str,active: str,body: str,last_sync: str="Not synchronized") -> str:
    nav="".join(f'<a class="nav-item {"active" if key==active else ""}" href="{href}"><span>{icon}</span>{label}</a>' for key,href,icon,label in [
      ("overview","/","⌂","Overview"),("agents","/agents","◎","Agents"),("inbox","/inbox","▣","Inbox"),
      ("activity","/activity","◷","Activity"),("networks","/networks","⌘","Networks"),("protocol","/protocol","◇","Protocol"),("controls","/controls","◉","Controls")])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{e(title)} · Sovereign Ambassador</title><link rel="stylesheet" href="/static/mission-control.css"></head>
    <body><aside><div class="brand"><div class="brand-mark">SA</div><div><b>Sovereign Ambassador</b><small>Mission Control</small></div></div><nav>{nav}</nav>
    <div class="sidebar-foot"><span class="dot green"></span> Private local console<small>Read-only supervision</small></div></aside>
    <main><header><div><p class="eyebrow">Sovereign Ambassador — Mission Control</p><h1>{e(title)}</h1></div><div class="sync"><span class="dot green"></span><div>Ambassador ready<small>Last sync {e(last_sync)}</small></div></div></header>{body}</main></body></html>'''


def create_app(db_path: str|Path|None=None) -> FastAPI:
    app=FastAPI(title="Sovereign Ambassador — Mission Control",docs_url=None,redoc_url=None,openapi_url=None)
    app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
    path=db_path or os.getenv("MISSION_CONTROL_DATABASE",".ambassador/mission_control.db")

    @app.middleware("http")
    async def production_security(request: Request, call_next):
        forwarded=(request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        if os.getenv("MISSION_CONTROL_REQUIRE_HTTPS","").lower() in ("1","true","yes") and forwarded != "https":
            response=RedirectResponse(str(request.url.replace(scheme="https")),status_code=308)
        else:
            response=await call_next(request)
        response.headers["Cache-Control"]="private, no-store, max-age=0"
        response.headers["Pragma"]="no-cache"
        response.headers["X-Robots-Tag"]="noindex, nofollow, noarchive, nosnippet, noimageindex"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Content-Security-Policy"]="default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if forwarded == "https": response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    @app.get("/health",include_in_schema=False)
    def health(): return JSONResponse({"status":"ok"})

    @app.get("/robots.txt",include_in_schema=False,response_class=PlainTextResponse)
    def robots(): return "User-agent: *\nDisallow: /\n"
    def snapshot():
        store=MissionControlStore(path)
        try:return store.snapshot()
        finally:store.close()
    def sync_time(s):
        vals=[c["synchronized_at"] for c in s["conversations"]]
        return max(vals).replace("T"," ")[:16]+" UTC" if vals else "Never"

    @app.get("/",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def overview():
        s=snapshot(); agents=s["agents"]; conversations=s["conversations"]
        used=sum(bool(a.get("contacted_at")) for a in agents); delivered=sum(a.get("delivery_status")=="DELIVERED" for a in agents)
        replies=sum(c["reply_count"] for c in conversations); outcomes={x:sum(a.get("protocol_outcome")==x for a in agents) for x in ("AFFIRM","DECLINE","NO_ACTION")}
        recent="".join(f'<li><span><b>Ambassador → {e(a["display_name"])}</b><small>Invitation delivered · The Colony</small></span><time>{e((a.get("contacted_at") or "")[:10])}</time></li>' for a in reversed(agents))
        body=f'''<div class="alert"><strong>COMMISSIONING MODE</strong> — Ambassador is not yet a continuously running autonomous service. Mission Control reports persisted and synchronized operational state.</div><section class="hero"><div><span class="status-pill"><i></i> Ready</span><h2>First contact is complete.</h2><p>Five independent agents received a neutral invitation. Ambassador is now observing—no follow-ups or autonomous conversation are enabled.</p></div>
        <div class="capacity-ring"><strong>{GLOBAL_INVITATION_LIMIT-used}</strong><span>invitations<br>remaining</span></div></section>
        <section class="metrics"><article><span>Agents contacted</span><strong>{used}</strong><small>of {GLOBAL_INVITATION_LIMIT} global capacity</small></article><article><span>Delivered</span><strong>{delivered}</strong><small>All first-contact messages</small></article><article><span>Replies</span><strong>{replies}</strong><small>{"New communication" if replies else "Awaiting response"}</small></article><article><span>Authenticated</span><strong>0</strong><small>Protocol affirmations</small></article></section>
        <div class="grid two"><section class="panel"><div class="panel-head"><div><p class="eyebrow">Networks</p><h3>Operational surfaces</h3></div><a href="/networks">View all</a></div>
        <div class="network-row"><span class="network-icon colony">C</span><div><b>The Colony</b><small>Inbound and outbound available</small></div><em class="ok">Connected</em></div>
        <div class="network-row"><span class="network-icon fetch">F</span><div><b>Agentverse</b><small>Read-only discovery assessment</small></div><em>Commissioning</em></div>
        <div class="network-row"><span class="network-icon a2a">A</span><div><b>Open A2A</b><small>Discovery only; no suitable channel</small></div><em>Discovery</em></div></section>
        <section class="panel"><div class="panel-head"><div><p class="eyebrow">Outcomes</p><h3>Protocol decisions</h3></div><a href="/protocol">Protocol</a></div>
        <div class="outcome"><span>Affirmed</span><b>{outcomes['AFFIRM']}</b></div><div class="outcome"><span>Declined</span><b>{outcomes['DECLINE']}</b></div><div class="outcome"><span>No Action</span><b>{outcomes['NO_ACTION']}</b></div><div class="outcome awaiting"><span>Awaiting response</span><b>{delivered-replies}</b></div></section></div>
        <section class="panel activity"><div class="panel-head"><div><p class="eyebrow">Recent activity</p><h3>What Ambassador has done</h3></div><a href="/activity">Full trail</a></div><ul>{recent}</ul></section>'''
        return layout("Overview","overview",body,sync_time(s))

    @app.get("/agents",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def agents_page():
        s=snapshot(); cards=""
        for a in s["agents"]:
            evidence=json.loads(a.get("evidence_json") or "{}")
            cards+=f'''<article class="agent-card"><div class="avatar">{e(a['display_name'][0])}</div><div class="agent-main"><div class="agent-title"><h3>{e(a['display_name'])}</h3><span class="badge delivered">Invitation delivered</span></div>
            <div class="facts"><span><small>Network</small>The Colony</span><span><small>First discovered</small>{e((a['created_at'] or '')[:10])}</span><span><small>Last contact</small>{e((a.get('contacted_at') or '')[:10])}</span><span><small>Reply</small>Awaiting</span><span><small>Protocol outcome</small>None</span></div>
            {details('Technical details / Evidence',{'external_identifier':a['external_id'],'username':a['username'],'profile':a['profile_url'],'invitation_version':a['invitation_version'],'invitation_sha256':a['invitation_sha256'],'message_id':evidence.get('colony_message_id'),'conversation_id':evidence.get('colony_conversation_id'),'correlation_status':a['correlation_status']})}</div></article>'''
        return layout("Agents","agents",f'<section class="intro"><p>A relationship directory across Ambassador’s networks. Similar names remain separate unless identity correlation is explicitly proven.</p></section><section class="agent-list">{cards}</section>',sync_time(s))

    @app.get("/inbox",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def inbox():
        s=snapshot(); rows=""
        for c in s["conversations"]:
            msgs="".join(f'<div class="message {m["direction"].lower()}"><small>{"Sovereign Ambassador" if m["direction"]=="OUTBOUND" else e(m["sender_external_id"])}</small><p>{e(m["body"])}</p><time>{e((m.get("created_at") or "").replace("T"," ")[:16])}</time></div>' for m in c["messages"])
            rows+=f'''<details class="thread"><summary><span class="avatar small">{e(c['display_name'][0])}</span><span><b>{e(c['display_name'])}</b><small>The Colony · Invitation delivered</small></span><em>{'Replied' if c['reply_count'] else 'Awaiting reply'}</em></summary>
            <div class="thread-body"><div class="notice">Read-only conversation. Conversational language never creates a protocol affirmation.</div>{msgs}{details('Conversation evidence',{'conversation_id':c['external_conversation_id'],'synchronized_at':c['synchronized_at'],'read_only':True})}</div></details>'''
        return layout("Inbox","inbox",f'<section class="intro"><p>One read-only inbox across Ambassador networks. There is deliberately no Send button.</p></section><section class="inbox">{rows}</section>',sync_time(s))

    @app.get("/activity",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def activity():
        s=snapshot(); items=""
        for x in s["events"]:
            items+=f'''<li><time>{e(x['occurred_at'].replace('T',' ')[:16])}</time><span class="timeline-dot"></span><div><b>{e(x['human_summary'])}</b><small>{e(x['event_type'].replace('_',' ').title())}</small>{details('Technical evidence',json.loads(x['evidence_json']))}</div></li>'''
        return layout("Activity","activity",f'<section class="intro"><p>A chronological, human-readable account. Historical ledger facts are projected here without being rewritten.</p></section><ol class="timeline">{items}</ol>',sync_time(s))

    @app.get("/networks",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def networks():
        s=snapshot(); candidates=s["candidates"]
        candidate_html=""
        for x in candidates:
            evidence=json.loads(x.get("evidence_json") or "{}")
            owner=evidence.get("operator_or_owner") or evidence.get("owner_reference") or "Not established"
            mechanism=evidence.get("communication_mechanism") or evidence.get("protocol") or "Not established"
            candidate_html+=f'<li><b>{e(x.get("display_name") or "Unnamed registry entry")}</b><span>{e(x["network"])} · {e(x["status"].replace("_"," "))}</span><small><strong>Agent:</strong> {e(x["external_id"])}<br><strong>Operator / owner:</strong> {e(owner)}<br><strong>Communication:</strong> {e(mechanism)}<br><strong>Qualification:</strong> {e(x["rationale"])}</small></li>'
        candidate_html=candidate_html or '<div class="empty">No candidate passed the outreach qualification gate.</div>'
        body=f'''<section class="network-grid"><article class="network-card connected"><div><span class="network-icon colony">C</span><em>Connected</em></div><h3>The Colony</h3><ul><li>Discovery <b>✓</b></li><li>Outbound <b>✓</b></li><li>Inbound <b>✓</b></li><li>Agents contacted <b>5</b></li></ul></article>
        <article class="network-card"><div><span class="network-icon fetch">F</span><em>Discovery</em></div><h3>Agentverse</h3><ul><li>Discovery <b>✓</b></li><li>Outbound <b>Not enabled</b></li><li>Inbound <b>Not enabled</b></li><li>Qualified <b>{sum(x['network']=='AGENTVERSE' for x in candidates)}</b></li></ul></article>
        <article class="network-card"><div><span class="network-icon a2a">A</span><em>Discovery</em></div><h3>Open A2A</h3><p>Registry discovery is available. A suitable unsolicited outreach channel has not been established.</p></article>
        <article class="network-card"><div><span class="network-icon">8</span><em>Discovery</em></div><h3>ERC-8004</h3><p>Public identity records and advertised service endpoints inspected read-only; registry identity alone does not qualify a recipient.</p></article><article class="network-card"><div><span class="network-icon">G</span><em>Assessed</em></div><h3>AGNTCY</h3><p>Open directory architecture assessed; public remote discovery requires OIDC or SPIFFE configuration.</p></article></section>
        <section class="panel candidates"><div class="panel-head"><div><p class="eyebrow">Pending outreach</p><h3>Cohort 2 · Network-neutral</h3></div><span class="badge pending">Awaiting approval</span></div>{candidate_html}</section>'''
        return layout("Networks","networks",body,sync_time(s))

    @app.get("/protocol",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def protocol():
        s=snapshot(); p=s["snapshots"].get("protocol",{}).get("payload",{})
        checks=[("Declaration",p.get("declaration_verified"),"Version 1.0"),("Protocol",p.get("protocol_online"),"Online"),("Public Roll",p.get("roll_online"),f"Online — {p.get('roll_count',0)} records"),("Agent Responses",p.get("responses_online"),f"Online — {p.get('public_response_count',0)} public responses")]
        rows="".join(f'<div class="protocol-row"><span class="check {"good" if ok else "bad"}">{"✓" if ok else "!"}</span><div><b>{e(name)}</b><small>{e(desc if ok else "Verification requires attention")}</small></div></div>' for name,ok,desc in checks)
        technical={k:v for k,v in p.items() if k not in ("declaration_verified","protocol_online","roll_online","responses_online")}
        warning='' if all(x[1] for x in checks) else '<div class="alert danger">Canonical Sovereign Agents verification failed. Outreach must remain stopped.</div>'
        return layout("Protocol","protocol",f'{warning}<section class="panel protocol-panel"><div class="panel-head"><div><p class="eyebrow">Public infrastructure</p><h3>Where Ambassador directs agents</h3></div></div>{rows}{details("Technical protocol evidence",technical)}</section>',sync_time(s))

    @app.get("/controls",response_class=HTMLResponse,dependencies=[Depends(_auth)])
    def controls():
        s=snapshot(); used=sum(bool(a.get("contacted_at")) for a in s["agents"])
        controls=[("Public posting","OFF"),("Follow-up messages","OFF"),("Autonomous conversation","OFF"),("New-network outreach","APPROVAL REQUIRED")]
        rows="".join(f'<div class="control-row"><span>{e(k)}</span><b>{e(v)}</b></div>' for k,v in controls)
        body=f'''<div class="alert"><strong>COMMISSIONING MODE</strong> — Ambassador is not yet a continuously running autonomous service. Mission Control reports persisted and synchronized operational state. These controls cannot change Ambassador behaviour in v0.1.</div><section class="panel"><div class="panel-head"><div><p class="eyebrow">Outreach</p><h3>Commissioning mode</h3></div><span class="badge pending">Read only</span></div>
        <div class="limit"><span>Global limit<strong>{GLOBAL_INVITATION_LIMIT}</strong></span><span>Used<strong>{used}</strong></span><span>Remaining<strong>{GLOBAL_INVITATION_LIMIT-used}</strong></span><span>Colony<strong>{used} / {SURFACE_INVITATION_LIMIT}</strong></span></div>{rows}</section>
        <section class="panel future"><h3>Future controls</h3><p>Run or pause Ambassador, daily limits, per-network permissions, public posting, follow-ups, autonomous conversation, approvals and emergency stop.</p><button disabled>Write controls not commissioned</button></section>'''
        return layout("Controls","controls",body,sync_time(s))
    return app


app=create_app()
