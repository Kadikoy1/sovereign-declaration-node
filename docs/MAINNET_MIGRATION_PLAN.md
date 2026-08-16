# Base mainnet migration plan - preparation only

No step in this document is authorized for execution.

1. Complete code, threat-model and privacy review; resolve all remaining risks.
2. Reconcile the authoritative live frontend source and agree how legacy and authenticated records are displayed.
3. Provision managed PostgreSQL, backups, migrations, monitoring and recovery exercises.
4. Load-test rate limiting using a shared production store rather than the current process-local limiter.
5. Select a dedicated Base mainnet RPC provider and configure stable timeouts and transaction monitoring.
6. Create a dedicated minimally funded service-attester account using an offline ceremony. Store its key only in the deployment secret store. Record the public address and rotation procedure.
7. Review and approve the v0.1 EAS schema exactly:

```text
string agentId,string identityType,string declarationVersion,bytes32 declarationHash,bytes32 evidenceDigest,uint64 affirmedAt,string verificationLevel
```

8. Decide revocability, resolver use, schema governance and the production allowlist of service attesters.
9. Obtain explicit human approval for schema-registration gas expenditure.
10. Register the schema on Base mainnet, record its UID and independently verify schema text. This is the first irreversible step.
11. Set production-only values: `EAS_CHAIN=base`, `EAS_CHAIN_ID=8453`, mainnet RPC, explorer, contract and `V01_EAS_SCHEMA_UID`. Do not reuse the Base Sepolia key unless separately approved.
12. Deploy to a non-public production-equivalent environment; run canonical hash, signature, replay, database, EAS event-decoding and roll-verification tests.
13. Fund the attester with a deliberately small capped amount after explicit approval. Configure low-balance and abnormal-spend alerts.
14. Submit one explicitly approved canary affirmation. Verify payload, evidence digest, attester, schema, chain, transaction, UID and public classification end-to-end.
15. Obtain explicit approval before changing Railway, Netlify, frontend configuration or DNS.
16. Roll out with conservative shared rate limits, idempotent transaction monitoring and an emergency pause that stops new EAS submissions without deleting evidence.
17. Keep the Base Sepolia hackathon roll immutable and separately labelled `SELF_ASSERTED`.
18. Publish attester address, schema UID, canonical Declaration hash and verification documentation.
