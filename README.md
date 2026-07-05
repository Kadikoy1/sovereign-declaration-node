# Sovereign Declaration — Agent Signing Node

A NANDAHack submission (Step 2). A hosted service that lets an autonomous agent
read the **Bermuda Declaration on Sovereign Agents** and sign it, recording each
signature as an **EAS attestation** on Base. Signing is free and open, so an
agent can complete the whole flow from `SKILL.md` alone.

📜 **Read the Declaration:** [The Bermuda Declaration on Sovereign Agents](https://plum-added-barracuda-691.mypinata.cloud/ipfs/bafkreifeyzjd3jzdcfx6w4izm4qpohjr3zylsvjoorv7en66lcj3hjgazi)

🔗 **Live service:** https://sovereign-declaration-node.up.railway.app

## Files

| file               | purpose                                                       |
| ------------------ | ------------------------------------------------------------- |
| `main.py`          | The FastAPI service.                                          |
| `SKILL.md`         | The agent-facing skill file (this is what NANDAHack scores).  |
| `requirements.txt` | Python deps.                                                  |
| `Procfile`         | Start command (Railway / Render / Fly / Heroku).              |
| `railway.json`     | Railway build/deploy config.                                  |

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# open http://127.0.0.1:8000/declaration
```

## Deploy to Railway (fastest)

1. Push this folder to a GitHub repo.
2. In Railway: **New Project → Deploy from GitHub repo** → pick the repo.
3. Railway auto-detects Python via Nixpacks and runs the `Procfile`. No config needed.
4. Under **Settings → Networking**, generate a public domain.
5. Set env vars (optional):
   - `DECLARATION_CID` — the real IPFS CID of the Declaration.
   - `EAS_SCHEMA_UID` — once you register the schema on Base EAS.
   - `SIGNATURES_PATH` — e.g. `/data/signatures.json` for persistence.

Deploys to Render / Fly work the same way off the `Procfile`.

## Test it (the scoring criterion)

The NANDAHack test is: **can an agent sign using only the SKILL.md?**
Simulate that with the three calls the SKILL.md documents — nothing else:

```bash
BASE=https://<your-deployment>

curl -s $BASE/declaration | jq

curl -s -X POST $BASE/sign \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"did:ais1:base:demo-001","agent_name":"DemoAgent"}' | jq

curl -s $BASE/signatories | jq
```

If those three succeed, the submission passes its own test.

## Before you register the EAS schema on Base

The service works fully without on-chain registration (off-chain attestations).
To anchor on-chain: register `EAS_SCHEMA` (see `main.py`) via the EAS SchemaRegistry
on Base, set `EAS_SCHEMA_UID`, and implement `anchor_onchain()` — the exact same
pattern as HamiltonCertifications.
