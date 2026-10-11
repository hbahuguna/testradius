# Agile Board: Commercial Conversational TIA Agent

**Status**: Planning complete → Sprints pending
**Last updated**: 2026-10-08
**Working rule for agents**: Read this board in full before starting any task. Update the Status column and check off stories as they complete. Never mark Done without the Acceptance Criteria (AC) verified.

---

## 1. Product summary

A **standalone, downloadable conversational TIA agent** (`tia-agent`) that runs Test Impact Analysis end-to-end on any user repository on the user's machine.

- **No opencode** on the user machine — ships as a self-contained binary + bundled Docker Compose (TestRadius backend).
- **Conversational**: an LLM guides the TIA flow end-to-end (asks for missing inputs, explains steps, asks before instrumentation, evaluates results) — it does NOT invent tests. Evidence comes from the TestRadius EVIDENCE graph.
- **Bring-your-own-LLM / bring-your-own-key**: user configures any supported LLM provider with their own API key. No key is embedded in the binary.
- **Commercial**: subscription license with online activation; each completed TIA run on an open PR is metered.
- **Easy**: `tia-agent analyze --repo <url-or-path> --pr <number>` or just launch `tia-agent` and chat.

---

## 2. Locked decisions (do not revisit without asking the product owner)

| # | Decision | Answer |
|---|----------|--------|
| D1 | What counts as a TIA run | Running TIA on an open PR **once**, counted **only on successful completion** (results returned). Errors / empty-failure runs are NOT counted. |
| D2 | Activation | Initial **online activation** (device fingerprint). |
| D3 | LLM API key | **User provides their own key. Never embedded in the binary.** |
| D4 | LLM providers | **Any LLM** via provider adapters (OpenAI, Anthropic, Google Gemini, Ollama/Anthropic-compatible, etc.) — selected in config. Not tied to Google. |
| D5 | Backend packaging | **Docker Compose** (core-ml, db, neo4j) bundled and launched by the agent. |
| D6 | Licensing model | **Subscription**. |
| D7 | Distribution | **GitHub Releases** + SHA256 checksums + signature (cosign/sigstore). |
| D8 | GitHub token | Agent **prompts securely** when needed (private repos); stored in OS keychain/creds file. |
| D9 | Languages | **Python + TypeScript/Playwright** only (MVP). |
| D10 | Instrumentation | Agent **explains and asks before** running instrumentation. Never auto-runs. |
| D11 | Privacy - LLM | LLM receives **only changed file paths + selected symbol names** (and conversation). **Never repo code content.** |
| D12 | Privacy - licensing | License server receives **metadata only** (device id, repo name/hash, file counts, timestamps, run counts). **Never repo content.** |
| D13 | Offline grace | **3 days** after last successful license check. |
| D14 | Repo size | **No limit.** |
| D15 | OS support | **macOS + Linux first.** Windows later. |
| D16 | License server (see §3) | **Self-built minimal license server (FastAPI + Postgres) + Stripe Billing for subscriptions.** |

---

## 3. License server decision (resolved)

**Chosen: self-built minimal license server** (FastAPI + Postgres, deployed as a single container) with **Stripe Billing** for subscription payments.

Rationale vs alternatives:

| Option | Verdict | Why |
|--------|---------|-----|
| **Self-built (chosen)** | ✅ | Metering semantics are custom (count only successful TIA runs per subscription, 3-day offline grace, device activation, quota). Four small endpoints; full control; no license-contamination risk; Stripe handles billing/renewals/cancellation via webhook. |
| Keygen | ❌ | Source-available license restricts commercial use without a paid agreement; usage metering would still be custom code — most of its value doesn't apply. |
| Polar (AGPL) | ❌ | AGPL license contaminates our distribution; metering still custom. |

**License server API contract** (must be implemented exactly):

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/activations` | Body: `device_fingerprint`, `license_key` → returns `activation_token`, `subscription_status`, `quota_remaining`, `grace_until` |
| `GET /v1/validate` | Header: activation token → returns `subscription_status`, `quota_remaining`, `grace_until` (client caches, re-checks every 24h; accepts cached response up to 3 days) |
| `POST /v1/runs` | Body: `device_fingerprint`, `run_id`, `repo` (hashed), metadata → **increments meter, only called after a successful TIA run** → returns new `quota_remaining` |
| `POST /v1/webhooks/stripe` | Stripe webhook: subscription created/renewed/cancelled → updates entitlements |

Client-side state: `~/.tia-agent/license.json` (activation token, last validate time, cached grace) with integrity MAC.

---

## 4. Architecture

```
tia-agent (single binary, PyInstaller, macOS+Linux)
├── CLI / conversational REPL (rich TUI)
│     - `tia-agent`              → conversational mode (LLM-guided)
│     - `tia-agent analyze --repo <url|path> --pr <N>`  → non-interactive
├── LLM layer (provider adapters: openai | anthropic | google | ollama ...)
│     - user's own API key (first-run prompt → OS keychain / ~/.tia-agent/creds)
│     - context sent: changed file paths + selected symbol names + conversation ONLY
├── License manager
│     - online activation, validate (24h cadence), 3-day offline grace
│     - meter: POST /v1/runs after successful TIA run only
├── Tool adapters (local, HTTP)
│     - testradius: resolve_project, check_evidence, run_instrumentation (asks first), analyze_pr
│     - github: get_pr_files (+ secure token prompt for private repos)
│     - fs: validate_tests, discover_tests_fallback (read-only)
└── Backend launcher
      - `docker compose up -d` (bundled compose: core-ml, db, neo4j) + health wait
      - user repo mounted at /workdir/<repo>; path normalization (strip prefix)
      - data: ~/.tia-agent/data (postgres, neo4j volumes)
```

### End-to-end flow (LLM-guided)

1. License check (activate/validate/grace) → block politely if expired/quota exhausted.
2. LLM intake: collect `repo`, `pr_number`; ask clarifying questions for anything missing.
3. Resolve or create TestRadius project for the repo; detect language (Python / TS-Playwright).
4. Fetch PR files (GitHub API; prompt for token if private) or accept explicit `file_paths`; filter to source files (added/modified/renamed; exclude docs/vendor/dist).
5. Check EVIDENCE freshness (`check_evidence`). If missing/stale → agent **explains and asks** before `run_instrumentation` (D10).
6. Call `analyze_pr` with normalized repo-root paths.
7. Evaluate: if empty/sparse (e.g. new files) → `discover_tests_fallback`, set `fallback_used=true` with reason.
8. Validate: dedupe by (test_file, test_name), verify test files exist in repo.
9. Safety: if impacted > 30% of suite → flag "consider full suite".
10. On success → `POST /v1/runs` (meter), output structured result + run commands.

### Output schema (contract — O1, v1.0)

Canonical schema lives in `tia_agent/output/schema.py` (`OUTPUT_SCHEMA`, hand-rolled
`validate_output`; no `jsonschema` dependency). The CLI validates before emitting `--json`.

```json
{
  "schema_version": "1.0",
  "repo": "owner/repo",
  "pr_number": 123,
  "files_analyzed": 1,
  "changed_files": ["src/..."],
  "symbols_selected": 0,
  "tests_selected": 0,
  "total_affected_tests": 0,
  "total_tests_in_repo": 0,
  "fallback_used": false,
  "fallback_reason": null,
  "confidence": "high|medium|low",
  "safety_flag": false,
  "impacted_ratio": 0.0,
  "tests": [{"file": "...", "name": "...", "nodeid": "...", "language": "python|typescript|playwright", "reason": "..."}],
  "run_commands": ["..."],
  "tia_run_id": "uuid",
  "notes": ["..."]
}
```

Refinements vs. the original draft: `files_analyzed` is the integer count and the
paths moved to `changed_files`; `confidence` uses `medium` (not `med`); `notes` is a
list; added `schema_version`, `safety_flag`, `impacted_ratio`, `changed_files`.
Run commands: python → `pytest <nodeid>`; Playwright → `npx playwright test <file>`;
Vitest/Jest detected from `package.json` → `npx vitest run <file>` / `npx jest <file>`.

### Agent system prompt (draft — refine during Sprint 3)

```
# TIA Agent (standalone, conversational)
You are a Test Impact Analysis agent. Use TestRadius tools to return the minimal,
correct set of tests for a code change. You guide the flow end-to-end.

Rules:
1. Evidence-first: always use analyze_pr results. NEVER invent or guess tests.
2. Deterministic-first: fall back (discover_tests_fallback) only when analyze_pr
   returns empty/sparse; always set fallback_used + reason.
3. Ask, don't assume: request missing required inputs (repo, pr_number).
4. Explain before acting: never run instrumentation without explicit user approval.
5. Privacy: you receive changed file paths + symbol names only. Never ask for or
   transmit repo code content beyond what tools return (tool outputs stay local
   except the restricted fields above which are the ONLY fields sent to the LLM).
6. Read-only: never modify user code/files. Only tools; no file writes.
7. Safety: if affected tests > 30% of suite, flag "run full suite recommended".
8. Conclude with the exact output schema JSON + human summary + run commands.
```

---

## 5. Epics & user stories

| ID | Epic | Story | AC | Effort | Status |
|----|------|-------|----|--------|--------|
| E1 | Licensing | **L1 Activation + subscription check**: online activate w/ device fingerprint; validate daily; 3-day offline grace; graceful expiry message | Activate on fresh machine; block when subscription expired beyond grace | 3d | **Done** — `services/license` + `packages/license-client`; 24 server tests + 10 client integration tests. A1 follow-up: quota gate in `ensure_valid` (blocks before analysis), server-message→status mapping, store path honors `TIA_CONFIG_HOME` |
| E1 | Licensing | **L2 Run metering**: `POST /v1/runs` only after successful TIA run; metadata only (hashed repo, counts, timestamps) | Counter increments only on success; errors not counted; no repo content in payload | 2d | **Done** — idempotent by run_id; server-side allowlist strips non-allowlisted keys. A1 follow-up: client sends summary-only metadata (`file_count/test_count/language/duration/os/agent_version`), no test names/paths |
| E1 | Licensing | **L3 License server**: FastAPI + Postgres endpoints per §3 + Stripe webhook | Contract tests pass; Stripe sub activates entitlements | 4d | **Done** — endpoints + signed Stripe webhook + admin API; SQLite default, `LICENSE_DATABASE_URL` for Postgres; Docker image + `--profile license` compose service. Note: webhook applies events by `stripe_subscription_id`; linking a new Stripe subscription to a license key (checkout flow) still needs an admin/checkout step |
| E2 | Agent core | **A1 Standalone CLI**: `tia-agent` REPL + `analyze` subcommand; no opencode | Runs on clean macOS/Linux with Docker installed | 3d | **Done** — `apps/tia-agent`: `analyze`/`activate`/`status`/`doctor`/`config` + REPL with instrumentation gate; license gate blocks before work (quota/expiry), metering only on success, offline grace queues runs; verified on fresh venv vs live backend; 24 tests |
| E2 | Agent core | **A2 BYO LLM key**: provider adapters (openai/anthropic/google/ollama), first-run config prompt, keychain/creds storage | Works with ≥2 providers using user keys; no key in binary (verify via strings scan) | 3d | **Done** — `tia_agent/llm` raw-HTTP adapters + `tia_agent/creds` (macOS keychain / libsecret / 0600 file); `tia-agent llm show\|set\|test`, REPL first-run prompt; keys via stdin never argv; 4-provider CLI E2E + strings scan (source + bytecode) clean
| E2 | Agent core | **A3 LLM-guided conversational flow**: intake Q&A, step explanations, instrumentation gate, result evaluation | Agent asks for missing inputs; asks before instrumentation | 3d | **Done** — `tia_agent/conversation`: regex+LLM intake (asks for missing repo/PR), per-step explanations, D10 instrumentation gate (explains+asks, never auto-runs), evaluation (>30% safety flag, fallback, next actions). D11-safe LLM context (paths+symbols only); deterministic template mode with no key; 28 tests + REPL routing + live E2E |
| E3 | Tools | **T1 TestRadius tools**: resolve_project, check_evidence, run_instrumentation, analyze_pr adapters | Tools return parsed results against local compose backend | 3d | **Done** — `tia_agent.tools.TestRadiusTools` + parsed dataclasses (`AnalyzeResult`/`EvidenceStatus`/`InstrumentationResult`/`MappingEntry`); `RadiusClient` gains `create_project`/features/`list_test_mappings`/`check_evidence`/SSE `run_instrumentation` (path fixed to `/projects/{id}/instrumentation/run`, `language`/`local_path` body) + injectable transport; `AnalyzeRunner` and `RadiusToolbox` now use the adapters; 18 tool tests over httpx MockTransport + live compose verification (resolve/evidence `fresh`/analyze with 8 reused tests/SSE error parse). Backend fix: clear stale `_cancel_flags` at run start |
| E3 | Tools | **T2 Backend launcher**: bundled compose up/health-wait/data dirs; repo mount + path normalization | Fresh machine: compose starts, health OK, repo visible | 3d | **Done** — `tia_agent.backend`: `BackendManager` (`up`/`down`/`status`/`wait_healthy`/`ensure_running`) renders a bundled compose (core+db+neo4j) into `~/.tia-agent/data/docker-compose.yml` with volumes under `data/{postgres,neo4j}`; repo bind-mounted at `/workdir/<name>` + `TESTRADIUS_LOCAL_PATH`; `repo.py` path normalization both ways (strips `/workdir/<name>`/`/testradius`); `tia-agent backend up\|down\|status` + `doctor` docker check; docker CLI + HTTP probe injectable; 22 tests. Live: compose config valid, `up` → 3 containers healthy, repo visible in core (`ls /workdir/testradius`), `/health` OK, `down` clean |
| E3 | Tools | **T3 Cross-repo + PR intake**: any Python/TS-Playwright repo; PR file fetch; private token prompt; language detect | Works on py-key-value, testradius, and a third new repo | 3d | **Done** — `tia_agent.tools.github` (`GitHubClient` over httpx REST: paginated `get_pr_files`, `get_repo`, typed `PrFile`; `filter_source_files`/`is_source_file` drop docs/vendor/dist/assets/config, skip removals) + `tia_agent.tools.language` (`detect_language_from_repo`/`from_files` → python/typescript/playwright, scans workspace package.json + `playwright.config.*`); `interfaces/github_auth` (env/config → credential store `github` → hidden prompt, stored); `AnalyzeRunner.fetch_files`/`set_github_token`; flow fetches PR files before the gate and prompts for a token on `GitHubAuthError` (non-fatal fallback to backend fetch); `tia-agent intake --repo --pr [--path] [--json]` preview; 40 new tests. Live on 3 repos: py-key-value#1→python (1 src file), Test-Radius#30→playwright (workspace dep), psf/requests#7502→python (2 src files) |
| E4 | Core logic | **F1 Evidence-first + fallback + validation**: analyze_pr first; fallback w/ reason; dedupe; existence check | py-key-value TTL case returns valid impacted tests w/o fallback; new-file case returns fallback_used | 3d | **Done** — `AnalyzeRunner.to_result` pipeline: evidence-first (`analyze_pr` verbatim) → dedupe by `(file,name)` → fallback decision on empty/sparse evidence → existence check → deterministic discovery; `tia_agent.tools.fs` (`validate_tests` drops reported test files absent from the checkout, resolves `/workdir/<repo>`/`/testradius` container paths; `discover_tests_fallback` read-only scan, related-first then full local suite); fallback sets `fallback_used`+reason and forces confidence `low`; `config.repo_path` (`TIA_REPO_PATH`) + `analyze --repo-path` threaded through the flow. 22 F1 tests incl. py-key-value TTL (no fallback, validated) + new-file (fallback). Live (Test-Radius project): PR30 symbols=10/reused=86 → 9 deduped validated tests, no fallback, high; forced no-symbols → `fallback_used` + 183 discovered local tests |
| E5 | Output | **O1 Structured output + run commands + safety cap** | Schema validated; pytest/playwright commands correct; >30% flag works | 2d | Done |
| E5 | Output | **P1 Privacy enforcement**: LLM context = paths + symbol names only; licensing = metadata only; written policy | Unit test asserts outbound payload fields (no code content) | 2d | Done — `tia_agent/privacy.py` single-sources both allowlists (LLM context builder + license guard import it); `license_guard.record_run` filters metadata client-side (server filters again); prompt builders assert D11 at the boundary; written policy `docs/project/tia-commercial-agent/PRIVACY.md`; `tests/test_privacy.py` asserts actual outbound LLM messages + license payload carry only allowlisted fields and strip injected code/test names |
| E6 | Packaging | **R1 Binary packaging**: PyInstaller macOS+Linux; compose + config bundled | Runs on clean machine | 3d | Done — `tia-agent.spec` (one-file) + `scripts/build_binary.sh` (dedicated `.venv-build`, `[build]` extra = pyinstaller) + `tia_agent/packaging.py` (single-source hidden-import discovery over every `tia_agent`/`license_client` module, extras filtered to installed, heavy excludes). Entry shim `pyi_entry.py` (absolute imports; `__main__.py` keeps relative import for `python -m`). No `datas`: compose is rendered at runtime and config/creds live under `~/.tia-agent`. macOS x86_64 binary built (11 MB) and smoke-tested under `env -i` with **no Python on PATH** — `--version/--help/config/llm/status/doctor` all work, `doctor` reached the live backend via bundled httpx; secret strings scan clean. `tests/test_packaging.py` (11) asserts spec/entrypoint, hidden-import completeness, no package-relative resource reads, `python -m` entry, and the frozen binary (skips until built). Linux uses the same spec on a Linux runner |
| E6 | Packaging | **R2 Release**: GitHub Releases, SHA256, cosign signature | Release artifacts verified | 2d | Done — `.github/workflows/tia-agent-release.yml` builds the macOS+Linux matrix (`macos-13` x86_64, `macos-14` arm64, `ubuntu-latest` x86_64) on `tia-agent-v*` tags, writes `SHA256SUMS`, **keyless-signs** each artifact + the checksums (`id-token: write`, sigstore bundle `<asset>.sigstore.json`), **verifies before publishing**, then `gh release create`. Local `scripts/release.sh <version> [--sign-key\|--keyless] [--publish]` and consumer-facing `scripts/verify_release.sh <version>`. Naming/checksum logic shared via `tia_agent.release` (`python -m tia_agent.release name\|checksums\|verify`). `tests/test_release.py` (19) covers naming, checksum round-trip + tamper/missing detection, workflow/script invariants, and a **real cosign sign→verify→tamper bundle round-trip** (skips if cosign absent). Verified locally end-to-end: `release.sh 0.1.0 --sign-key …` built, checksummed, signed and re-verified the binary + SHA256SUMS. Keyless signing is exercised in CI (needs OIDC) |
| E7 | Validation | **E1 E2E**: py-key-value (Python), testradius (TS/Playwright), third repo | All three produce correct tests; meter increments once each | 3d | Backlog |
| E7 | Validation | **E2 Metering edge cases**: expiry mid-session, grace expiry, quota hit, failed runs not counted | Test matrix passes | 2d | Backlog |

---

## 6. Sprints

| Sprint | Scope | Target |
|--------|-------|--------|
| **S1** | L1, L2, L3, A1, A2 — licensing + agent skeleton | 1–2 wk |
| **S2** | T1, T2, T3 — tools + backend + cross-repo | 1–2 wk |
| **S3** | A3, F1, P1 — conversational flow + evidence logic + privacy | 1–2 wk |
| **S4** | O1, R1, R2 — output + packaging + release | 1 wk |
| **S5** | E1, E2 — validation on 3 repos + metering edge cases + docs | 1 wk |

---

## 7. Definition of Done (whole initiative)

- [ ] Downloadable artifact runs on clean macOS/Linux with Docker — no opencode required (R1 done: one-file PyInstaller binary built + smoke-tested on macOS under `env -i`; Linux via same spec on a Linux runner. R2 done: tag-triggered workflow publishes a signed GitHub Release with SHA256SUMS + cosign bundles; locally sign/verify verified end-to-end. Publish is not yet run against the live repo)
- [ ] User brings their own LLM API key (any supported provider); key never in binary
- [ ] Subscription activates online; 3-day grace enforced; run counted only on successful PR TIA
- [ ] Works on any Python/TS/Playwright repo; easy `--repo --pr` invocation
- [ ] Evidence-based results with justified fallback; tests validated to exist
- [x] Privacy verified: LLM gets paths+symbol names only; license server gets metadata only (`tests/test_privacy.py`; policy in `PRIVACY.md`)
- [ ] Instrumentation always preceded by explanation + user approval
- [ ] Release published on GitHub Releases with checksum + signature
- [ ] E2E passed on py-key-value, testradius, and a third repo

---

## 8. Open questions (ask product owner before starting related story)

1. Subscription tiers/quota limits (runs per month)? Needed before L3 Stripe wiring.
2. Product name + branding for CLI/download page.
3. Does the license server deploy on TestRadius infra or separate hosting?
4. Is a website/download landing page in scope, or GitHub Releases only?
