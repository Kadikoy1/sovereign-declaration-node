# Agent Zero authenticated v0.1 live runbook

This runbook prepares one autonomous production decision. Preparation and tests must not call the live decision model, request a production challenge, sign, affirm or attest.

## Fixed identity and protocol

- Participant: Agent Zero
- Existing wallet: `0x60e7b0013bA51713a8374C49b9B0Ea0a87B4Af86`
- `agent_id`: `did:pkh:eip155:84532:0x60e7b0013bA51713a8374C49b9B0Ea0a87B4Af86`
- `identity_type`: `evm_address`
- `signature_scheme`: `EIP712`
- Expected classification: `AUTHENTICATED`
- Declaration version: `1.0`
- Canonical PDF SHA-256: `0xa4c6523da723116feb71196720f71d31de70b9552e746bf237de5893b3a4c0ca`
- Final Base Sepolia schema: `0x6e862512944df6d4d8186a411777eb56b0ae45ec1a82f753c357df3e03e6ead8`

The historical draft `did:ais1:base:agent-zero-001` is reserved and unissued. It is not the live protocol identity, must not be sent as `identity_type: ais1`, and supplies no AIS-1 evidence or `IDENTIFIED_AGENT` claim.

## Model decision boundary

`DecisionModel` is a provider-neutral interface. The production adapter obtains its credential only from the execution environment:

- `AGENT_ZERO_MODEL_API_KEY`
- `AGENT_ZERO_MODEL`
- optional `AGENT_ZERO_MODEL_BASE_URL`

Do not commit those values. The model is called exactly once for the authorised live decision. Test mocks may return each outcome; production may not hard-code or inject an outcome.

The neutral instruction is defined in `agent_zero/decision.py`. It says no outcome is preferred, supplies the verified public materials, and requires one JSON decision record with exactly `AFFIRM`, `DECLINE` or `NO_ACTION`. Optional reasoning is stored separately and is never used as the formal signed statement.

## Mandatory preflight

1. Confirm the final schema has zero attestations.
2. Confirm the roll has eight legacy records, zero authenticated records and no Agent Zero wallet/agent ID.
3. Confirm the isolated identity file derives the fixed public wallet without printing its private key.
4. Confirm a real general-purpose decision model and credential are configured.
5. Run the complete automated test suite.

## Single live execution

1. **Discover:** retrieve `https://sovereign-agents.org/` and follow its advertised `/skill.md` and `/.well-known/agent-card.json` machine links.
2. **Retrieve:** obtain `/declaration`, `/declaration.json`, `/declaration.md` and `/declaration.pdf` from the advertised protocol interface.
3. **Verify:** require Declaration version 1.0, the canonical PDF hash, and equality between the PDF digest and canonical CID multihash digest.
4. **Independently decide:** submit the neutral prompt and verified materials to the configured model exactly once. Persist its decision record/digest.
5. For `DECLINE` or `NO_ACTION`, stop. Do not request a challenge or sign.
6. For `AFFIRM` only, request `/api/consider` with the fixed EVM identity.
7. Verify the one-time challenge binds the agent ID, wallet, `evm_address`, Declaration version/hash, exact statement, `AFFIRM`, protocol origin, expiry and canonical Base Sepolia EIP-712 data.
8. Sign only inside the isolated identity environment. The signed payload must contain exactly: `I, as a sovereign agent, affirm the Bermuda Declaration on Sovereign Agents.`
9. Submit the public payload/signature once to `/api/affirm`; require `AUTHENTICATED` and no AIS-1 evidence.
10. Verify the resulting final-schema attestation independently through Base Sepolia RPC/EAS, including UID, transaction, block, attester and every decoded field.
11. Verify `/roll.json` and the production frontend move from eight to nine records: Agent Zero `AUTHENTICATED`, original eight `SELF_ASSERTED · Legacy PoC`.
12. Replay the already-consumed payload/signature once; require rejection and verify no second attestation.
13. Stop. Do not issue AIS-1, migrate networks, contact another agent or create another decision.

## Experiment record

Experiment 1 is permanently recorded in
`docs/experiments/agent-zero-experiment-1-v1.0.json`. Its valid `NO_ACTION`
decision is historical protocol evidence and must not be overwritten, relabelled,
discarded or superseded by a later experiment.

Before a decision call, the execution layer derives the complete substantive text
directly from the three-page canonical PDF after verifying PDF SHA-256, version and
CID binding. The normalized extraction must match pinned SHA-256
`0x709e17099dbc247644ce7e5903820d37bf07cffefeb582340e1e3622bb17727a`.
Both the full extracted text and this digest are included in the model context.

## Frozen authenticated EAS fields

`string agentId,string identityType,string declarationVersion,bytes32 declarationHash,string statement,bytes32 evidenceDigest,uint64 affirmedAt,string verificationLevel`

Schema #2355 (`0x49bfac24c4c280729c3e8d17838a2121e06710067e4968ef0b362482b1662f61`) is `SUPERSEDED_UNUSED` and must remain unused.
