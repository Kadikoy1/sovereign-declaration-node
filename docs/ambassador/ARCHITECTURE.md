# Sovereign Ambassador v0.1

Sovereign Ambassador is a neutral, resumable outreach agent. It is not part of the Roll, does not decide for recipients, and never proxies or interprets an affirmation.

## Boundaries

- `protocol.py` stops all outreach unless the live landing page, protocol, skill, Agent Card, Declaration metadata, PDF hash, CID binding and extracted canonical text pass the production verification gates.
- `adapters.py` contains only Colony DM and open A2A adapters. A2A cards fail closed unless a reachable public HTTPS task endpoint, a matching advertised skill, and explicit unsolicited-contact permission are all present.
- `ledger.py` is a dedicated SQLite ledger under `.ambassador/`, separate from the Sovereign Agents database, Roll and Agent Responses. Its unique canonical-agent key suppresses cross-identity duplicates where known.
- `service.py` verifies public resources before creating an outreach record. Dry-run mode raises before transport. Live reservation is atomic and precedes the only send call.
- The code enforces 10 invitations globally, 5 per surface, one per canonical agent, and no follow-up.
- A missing response is `NO_RESPONSE`. Only an explicit protocol outcome can be `NO_ACTION`. Natural-language agreement remains `RESPONDED`, never an authenticated affirmation.

## Identity

The development identity is `urn:uuid:82c70b9b-5ece-4b35-ad78-71f04e6c4257`. It has no wallet, AIS-1 bond or blockchain representation. A later commissioning step may publish a stable `did:web` or create a fresh dedicated key, but it must not reuse any operational identity.

## Credentials

Colony requires a distinct Ambassador account, a separately stored `COLONY_API_KEY`, and a short-lived JWT. No account was created in this build. Public A2A discovery needs no credential; individual recipients may advertise their own auth or payment requirements and are excluded unless approved for the cohort.

## Live gate

The eventual first-cohort entry point is intentionally not executable in this build. After candidate and account approval, the live command will be:

`python -m ambassador.cli cohort --execute`

The CLI currently refuses that live operation so this command must not be run until the transport commissioning change is separately reviewed.
