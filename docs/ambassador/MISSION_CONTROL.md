# Sovereign Ambassador — Mission Control v0.1

Mission Control is private supervision and observability infrastructure. It is not the public Declaration site, not a second Ambassador, and not an external agent network.

## Local preview

From the repository root:

```powershell
python -m mission_control.bootstrap
python -m mission_control.preview --username operator --password <local-password> --port 9917
```

Open `http://127.0.0.1:9917/`. The preview binds only to localhost. Do not reuse a preview password in production.

## Pages

- Overview — plain-language state, capacity, outcomes, networks and recent activity.
- Agents — unified relationships with secondary technical evidence.
- Inbox — read-only cross-network conversations with no send operation.
- Activity — chronological human summaries with expandable provenance.
- Networks — truthful adapter capabilities and pending cohorts.
- Protocol — cached health and canonical verification evidence.
- Controls — observational policy; no write control is commissioned.

## Persistence

`.ambassador/mission_control.db` is a normalized operational projection over the existing outreach ledger. The source ledger is not rewritten. Tables separate agents, network identities, discoveries, outreach, conversations, messages, protocol evidence, operational events, network candidates and snapshots. Two similarly named network identities remain distinct unless correlation is explicitly proven.

The schema uses ordinary primary/foreign keys and JSON text evidence so it can migrate to PostgreSQL without changing domain boundaries. A hosted version should replace the SQLite connection layer with PostgreSQL transactions and migrations while preserving identifiers and provenance.

## Security model

- All portal routes require server-side HTTP authentication in v0.1.
- Production should put an identity-aware access proxy or SSO in front of the application and retain application-level authorization as defense in depth.
- The browser receives rendered operational data only. It never receives Colony credentials, JWTs, model keys, wallet keys or hosting secrets.
- Colony JWTs remain memory-only and are refreshed server-side from the ignored `COLONY_API_KEY`.
- The Inbox client supports conversation GET only. No send, follow, react, comment or post method exists.
- Controls are static observations and cannot mutate Ambassador policy.
- Technical evidence is HTML-escaped; raw operational JSON is not exposed as a public API.

## Commissioning deployment (prepared, not deployed)

For the proposed private URL `https://ambassador.sovereign-agents.org`:

1. Deploy `Dockerfile.mission-control` as a separate Railway service with `railway.mission-control.json`; do not add it to Netlify or the public protocol service.
2. Mount one persistent Railway volume at `/data`, run one replica, and set `MISSION_CONTROL_DATABASE=/data/mission_control.db`. SQLite is proportionate while the console is read-only and single-operator; move to PostgreSQL before multiple writers or replicas.
3. Copy both audited databases from the verified migration bundle into `/data` before first start. `outreach.db` remains the source ledger; `mission_control.db` remains its operational projection. Keep volume backups enabled.
4. Configure server-side Railway variables `MISSION_CONTROL_USERNAME`, `MISSION_CONTROL_PASSWORD`, `MISSION_CONTROL_DATABASE`, and `MISSION_CONTROL_REQUIRE_HTTPS=true`. `COLONY_API_KEY` is needed only by a separately authorised read-only synchronization job and is not needed by the web process.
5. Railway terminates TLS. The app redirects non-HTTPS requests and emits HSTS, CSP, frame denial, no-sniff, `Cache-Control: private, no-store`, and `X-Robots-Tag: noindex, nofollow, noarchive`.
6. After deployment review, add Railway custom domain `ambassador.sovereign-agents.org`; then add the exact CNAME target Railway supplies at the DNS provider. Do not guess the target in advance.
7. Rollback means redeploying the preceding Railway deployment and restoring the corresponding two-database volume snapshot. Code rollback alone must never overwrite a newer ledger.

The operator uses an ordinary HTTPS browser and HTTP Basic credentials; no terminal is required for routine access. Before any future write controls, replace Basic authentication with identity-aware SSO/MFA and add CSRF/session protections.

`python -m mission_control.migrate_state <source-dir> <empty-destination-dir>` performs SQLite online backups, integrity checks, semantic-digest comparison, and commissioning count checks without changing the source.

No deployment or DNS change was made in v0.1.
