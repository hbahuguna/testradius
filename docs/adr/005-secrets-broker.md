# ADR-005 — Secrets broker: portable interface, Vault default, cloud-native supported

## Context
The cell needs an LLM key, a repo token, DB credentials, and evidence-bucket credentials at runtime. The CP must never hold them. BYOC deployments are in customer clouds with different secret managers; SaaS runs on AWS. Secrets must never be baked into images or written to disk, and every fetch must be auditable.

## Decision
1. A `SecretProvider` interface in the cell: `get(ref, ttl)`, with `VaultProvider` (KV v2 + K8s auth), `AwsSecretsManagerProvider` (IRSA), and `FakeProvider` for tests.
2. **Vault is the default** and the reference implementation, because it works across clouds and gives dynamic, TTL-bound credentials and audit devices.
3. AWS Secrets Manager is a first-class adapter for customers who mandate cloud-native.
4. The CP stores only **secret references** (Vault path / ARN) in policy; values are fetched by the cell at run time, held in memory, cleared at teardown, and never logged, written to the workspace, or uploaded as evidence.
5. Secret fetches are audit events (`ref`, `ttl`, `outcome`) — never the value.

## Consequences
- (+) No static secrets in images or config; revocation and TTL are real.
- (+) One interface, two backends; BYOC customers keep their own vault.
- (−) The broker becomes a run dependency; unavailability fails fast (`SecretUnavailable`).
- (−) Vault is operational overhead for small BYOC customers; the AWS adapter mitigates.
- (−) Dynamic DB creds require per-stack provisioning; v1 supports static-with-TTL fallback and documents it.

## Alternatives considered
- Cloud-native only (Secrets Manager) — simpler on AWS, poor multi-cloud parity, and forces AWS on BYOC.
- Sealed secrets / SOPS in-cluster — rejected: static, weak rotation, no per-run scope.
- CP-held keys — rejected outright by the architecture.

---
