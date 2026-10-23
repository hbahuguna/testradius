# ADR-001 — The cell is a container; the AUT is a separate workload

## Context
The cell must run the client's application to exercise it, but it must never run client code in its own namespace, and it must satisfy: read-only root filesystem, non-root user, `CAP_SYS_ADMIN` dropped, no privileged mode. Building an image inside the cell implies Docker-in-Docker or BuildKit, which normally requires privileged mode, a writable rootfs, and mount capabilities. Those requirements directly contradict the cell's hardening constraints. We also need reproducible builds tied to a commit SHA so coverage can be trusted (E4-S3).

## Decision
1. The cell is an ephemeral container/Job. It never executes client code.
2. The AUT is deployed as a **separate workload** (Deployment/Job + Service) in the same VPC, from a **pinned image digest**.
3. The build is a **separate build Job** (kaniko or rootless BuildKit) created by the cell through a tightly scoped ServiceAccount in the customer cluster. The cell orchestrates; it does not build.
4. Dev-only exception: `infra/compose` uses the host Docker socket for the builder (never for the cell). This is documented as non-production.
5. Optional customer mode: the customer's CI builds the image and passes the digest; the cell only deploys. This is the recommended mode for regulated clients.

## Consequences
- (+) Isolation is real: a compromised cell has no client code and no build privileges.
- (+) Digests make coverage→commit verification tractable.
- (+) The same model works for SaaS and BYOC.
- (−) More moving parts: build Job, registry auth, scoped RBAC, image pull latency.
- (−) Cold-start time increases (build + pull + readiness).
- (−) The cell needs cluster API permissions; those must be namespaced and audited.

## Alternatives considered
- **Docker-in-Docker in the cell** — rejected: privileged, `CAP_SYS_ADMIN`, writable rootfs, and it puts client code inside the cell's trust boundary.
- **Build in the control plane** — rejected: violates "no client code in the CP".
- **Prebuilt-only (no builder)** — viable for v1 and kept as a supported mode, but it pushes work onto every customer's CI and makes the demo dependent on external pipelines.

---
