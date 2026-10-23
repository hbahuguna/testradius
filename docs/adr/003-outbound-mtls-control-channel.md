# ADR-003 — mTLS + run-scoped tokens, with the cell initiating the connection

## Context
The brief states the CP talks to cells "only via their internal API over mTLS". Read literally, that requires inbound reachability from the CP into the cell. In BYOC the cell runs in the customer's VPC; customers will not expose public ingress or a NAT pinhole to a vendor, and requiring it would fail most security reviews. The CP must also never hold the client's LLM/repo credentials, and every endpoint must be authorized by a short-lived run-scoped token.

## Decision
1. **Connectivity:** the cell **initiates** an outbound mTLS connection to the CP and maintains a multiplexed control channel (dispatch, cancellation, evidence URL re-mint, policy reload). The CP never dials into the customer VPC. Direct CP→cell mTLS remains allowed only for SaaS or explicitly peered deployments.
2. **Transport identity:** certificates issued by an internal CA, bound to the cell deployment id, TTL ≤ 24 h, rotated with overlap; revocation checked at handshake.
3. **Authorization:** the CP issues a **run-scoped JWT** (`aud=cell_id`, `sub=run_id`, `scope=run`, `exp` ≤ 2× the run timeout, `jti` single-use for mutating calls). The cell verifies locally — no callback to the CP per request — and binds the token to the mTLS identity.
4. **Resilience:** the cell buffers events during a CP outage (bounded, with explicit loss markers) and flushes on reconnect. Dispatch is idempotent by run id.

## Consequences
- (+) Works through NAT and corporate firewalls; nothing inbound is exposed.
- (+) Revocation and attribution are per-deployment and per-run.
- (−) The CP must own channel lifecycle: reconnect, backpressure, ordering, at-most-once dispatch.
- (−) "CP talks to the cell API" becomes "CP talks over the channel" — an explicit deviation from the literal brief.
- (−) Live SSE in the UI is relayed through the CP, adding a hop.

## Alternatives considered
- **Inbound mTLS only** — rejected for BYOC (security review failure); kept for SaaS.
- **WireGuard/Tailscale overlay** — rejected: extra operational burden on customers, conflicts with minimum-footprint BYOC.
- **Queue-only (SQS/NATS) dispatch + polling** — simpler and viable; loses low-latency bidirectional calls (cancel, URL re-mint). Kept as the fallback if Q1 is declined; costs ~2 days in S5 and degrades the live demo.

---

## Sprint 2 implementation note
The cell verifies HS256 JWTs locally with the standard library (no crypto wheel); claims are
`iss`/`aud`/`sub`/`scope`/`exp`/`jti`, and tokens are bound to one run id. The `jti` single-use
replay cache for mutating calls lands with the CP control channel in Sprint 5; until then the
cell's create endpoint is local-dev only and the cancel/policy endpoints are loopback/demo.
