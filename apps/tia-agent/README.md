# tia-agent

**Standalone conversational TIA agent** — runs Test Impact Analysis on any repo/PR via a local TestRadius backend. No opencode required.

## Install

```bash
cd apps/tia-agent
uv venv .venv --python 3.12 && uv pip install -e .
```

Requires Python 3.12+ and Docker (for the TestRadius backend, see `docker compose` in the repo root).

## Usage

```bash
tia-agent                       # start the conversational REPL
tia-agent analyze --repo OWNER/REPO --pr 12 [--commit SHA] [--file-paths f1 f2] [--json]
tia-agent intake --repo OWNER/REPO --pr 12 [--path DIR] [--json]   # preview files + language
tia-agent activate --key TIA-XXXXXXXX-XXXXXXXX-XXXXXXXX
tia-agent status                # license status
tia-agent doctor                # license + backend connectivity
tia-agent config show           # effective configuration
tia-agent config set radius_url http://localhost:8000
tia-agent llm show              # provider / model / key source (never the key)
tia-agent llm set --provider openai --model gpt-4o-mini
tia-agent llm test              # one tiny completion to verify your key works
```

REPL commands: `analyze OWNER/REPO PR`, `activate KEY`, `status`, `llm`, `doctor`, `help`, `quit`.

## Bring your own LLM key (A2)

Supported providers: **openai**, **anthropic**, **google** (Gemini), **ollama** (local, no key).
On first interactive run the agent prompts for a provider and key; keys are stored in the
OS credential store — macOS Keychain, Linux libsecret (`secret-tool`), or a `0600` file at
`~/.tia-agent/credentials.json` as a fallback. **Keys never enter `config.json`, the source,
or the shipped artifact** (verified by a strings scan in `tests/test_no_keys.py`).
Keys are passed to the OS tools via stdin, never argv, so they don't leak into `ps`.

Env overrides: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`);
`OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` / `GOOGLE_BASE_URL` / `OLLAMA_HOST` retarget endpoints
(proxies, local mock servers). `TIA_CREDENTIALS_BACKEND=file` forces the file store (CI).

## Configuration

Effective config comes from `TIA_*` env vars (highest), then `~/.tia-agent/config.json`:

| Key | Env | Default |
|-----|-----|---------|
| `radius_url` | `TIA_RADIUS_URL` | `http://localhost:8000` |
| `radius_token` | `TIA_RADIUS_TOKEN` | `""` (demo mode) |
| `license_url` | `TIA_LICENSE_URL` | `http://localhost:8100` |
| `github_token` | `TIA_GITHUB_TOKEN` | `""` |
| `verbose` | `TIA_VERBOSE` | `0` |
| `llm_provider` | `TIA_LLM_PROVIDER` | `""` |
| `llm_model` | `TIA_LLM_MODEL` | provider default |

State (license activation, credentials) lives in `~/.tia-agent/` (honors `TIA_CONFIG_HOME`).

## Flow

1. **License gate** — daily validation / 3-day offline grace / graceful expiry (via `tia-license-client`).
2. **Resolve project** — maps `owner/repo` to a registered TestRadius project.
3. **analyze-pr** — symbol selection + existing-test reuse against the backend.
4. **Meter the run** — `POST /v1/runs` only after a successful analysis (failed runs are not counted).

## Conversational flow (A3)

Launch `tia-agent` (no args) for the LLM-guided REPL, or just describe the
request in plain English:

```
tia> which tests are affected by the cart change in acme/shop?
agent> Which PR number should I analyze?
you  > 42
agent> Run TIA on acme/shop#42? This uses one license quota unit. [y/N] y
agent> …step explanations…
agent> Run instrumentation for acme/shop now? It inspects your tests locally. [y/N]
```

- **Intake Q&A** — regex-first slot extraction (works offline), LLM-assisted for
  natural language; keeps asking until required inputs (`repo`, `pr_number`) are present.
- **Step explanations** — one line per step (license, project, evidence, analyze, meter).
- **Instrumentation gate (D10)** — if evidence is stale/missing the agent explains what
  instrumentation does and asks. It is **never run without your explicit approval**.
- **Result evaluation** — confidence, fallback reason, a >30%-of-suite safety flag, and
  suggested run commands.

Without an LLM key the flow still runs, using deterministic template messages.
Only changed file paths + selected symbol names + counts ever reach the LLM (D11) —
enforced in `tia_agent/conversation/context.py` and covered by tests.

Result schema (also with `--json`):

```json
{
  "repo": "owner/repo", "pr_number": 12,
  "files_analyzed": 2, "symbols_selected": 3, "tests_selected": 2,
  "total_affected_tests": 6, "total_tests_in_repo": null,
  "fallback_used": false, "fallback_reason": null, "confidence": "high",
  "tests": [{"file": "...", "name": "...", "nodeid": "...", "language": "typescript", "reason": "symbol"}],
  "run_commands": ["npx playwright test ..."],
  "tia_run_id": "uuid", "notes": []
}
```

## TestRadius tools (E3/T1)

The four TestRadius operations are wrapped by `tia_agent.tools.TestRadiusTools`,
each returning a parsed dataclass from `tia_agent.tools.models` (never raw JSON):

| Tool | Endpoint | Returns |
|------|----------|---------|
| `resolve_project(repo)` | `GET /projects` | `ProjectInfo` (matched by `owner/repo`, basename, or remote URL) |
| `check_evidence(project, file_paths)` | `GET /projects/{id}/test-mapping` | `EvidenceStatus` (fresh if mappings cover the changed files) |
| `run_instrumentation(project, ...)` | `POST /projects/{id}/instrumentation/run` (SSE) | `InstrumentationResult` (`status`, `edges`, `error`, `events`) |
| `analyze_pr(project, full_name, pr_number, ...)` | `POST /projects/{id}/analyze-pr` | `AnalyzeResult` (`results[]` with reused tests, `pr_files`) |

Notes:

- **Evidence** has no dedicated endpoint, so freshness is derived from the
  existing `test-mapping` data: `known` = endpoint reachable, `fresh` = at least
  one mapping covers the changed files (or any mapping exists when no paths are
  given). Unknown/stale evidence makes the flow ask before instrumenting (D10).
- **Instrumentation** streams SSE; the client consumes the stream and reduces it
  to a terminal `status` (`COMPLETED`/`CANCELLED`/`ERROR`); an error is terminal.
- `run_instrumentation` enables the project's `instrumentation` feature flag first.
- `RadiusClient(..., transport=...)` accepts an httpx transport, used by the tests.

## Bundled backend (E3/T2)

`tia-agent` can start the local TestRadius stack (core + Postgres + Neo4j) itself:

```bash
tia-agent backend up --repo /path/to/your/repo   # compose up -d + health wait
tia-agent backend status
tia-agent backend down
```

- **Compose** is rendered into `~/.tia-agent/data/docker-compose.yml` (honors
  `TIA_CONFIG_HOME`); volumes live in `~/.tia-agent/data/{postgres,neo4j}`.
- **Repo mount**: the repo is bind-mounted at `/workdir/<name>` and advertised
  via `TESTRADIUS_LOCAL_PATH`; `tia_agent.backend.repo` normalizes paths both
  ways (strips `/workdir/<name>` / legacy `/testradius`).
- **Images**: pulls `TIA_BACKEND_CORE_IMAGE` (default
  `ghcr.io/testsquad/testradius-core:latest`); `--build <src>` builds from a
  local TestRadius checkout instead.
- `DEMO_MODE=1` by default so a fresh machine works without auth wiring.
- Everything external (docker CLI, HTTP health probe) is injectable, so the
  launcher is unit-tested without docker.

## Standalone binary (E6/R1)

Build a self-contained `tia-agent` (no Python needed on the target machine):

```bash
cd apps/tia-agent
./scripts/build_binary.sh        # -> dist/tia-agent  (+ SHA256)
```

The script provisions a dedicated `.venv-build` (via `uv`, `[build]` extra =
`pyinstaller`), runs `pyinstaller tia-agent.spec`, then smoke-tests the artifact
under a stripped environment (`env -i PATH=/usr/bin:/bin`) so a clean machine is
approximated.

- **One file, no data files.** Compose is *rendered at runtime*
  (`tia_agent.backend.compose`) and config/credentials live under
  `~/.tia-agent`, so nothing needs bundling — this is what keeps "compose +
  config bundled" true inside a one-file executable.
- **Hidden imports are discovered, not hand-listed** —
  `tia_agent.packaging.hidden_imports()` walks every `tia_agent` /
  `license_client` module (plus installed third-party extras) and the spec
  consumes it, so a new module can't be silently omitted.
- **Entry point** — the spec uses `pyi_entry.py` (absolute imports) because
  `tia_agent/__main__.py`'s relative import can't run as PyInstaller's top-level
  `__main__`; `python -m tia_agent` still works.
- **Cross-platform** — the same spec builds on macOS and Linux; build on the
  target OS/arch (PyInstaller is not a cross-compiler).

Verified on macOS x86_64: 11 MB binary, `--version/--help/config/llm/status/doctor`
all run with no Python on `PATH` (and `doctor` reaches the live backend through
the bundled `httpx`). `tests/test_packaging.py` enforces the invariants and
smoke-runs the frozen binary when present.

## Release (E6/R2)

Releases are tagged `tia-agent-v<version>` and shipped as a GitHub Release with
per-artifact SHA256 checksums and **cosign (sigstore)** signatures.

- **CI** (`.github/workflows/tia-agent-release.yml`) builds the macOS + Linux
  matrix (`macos-13` x86_64, `macos-14` arm64, `ubuntu-latest` x86_64) with the
  same R1 build, writes `SHA256SUMS`, **keyless-signs** every file (GitHub OIDC,
  no long-lived key), verifies the signatures, then publishes the release. Assets
  are `tia-agent-<version>-<os>-<arch>`, `SHA256SUMS`, and a
  `<asset>.sigstore.json` signature bundle for each.
- **Locally**:

  ```bash
  ./scripts/release.sh 0.1.0 --sign-key cosign.key      # build + checksums + sign + verify
  ./scripts/release.sh 0.1.0 --keyless --publish        # keyless (needs OIDC) + gh release
  ```

- **Verify a published release** (downloads assets, checks SHA256SUMS, verifies
  each cosign bundle):

  ```bash
  ./scripts/verify_release.sh 0.1.0 --key cosign.pub
  ./scripts/verify_release.sh 0.1.0                     # keyless (workflow identity)
  ```

Artifact naming, checksum generation/verification live in `tia_agent.release`
(`python -m tia_agent.release name|checksums|verify`); `tests/test_release.py`
covers naming, the checksum round-trip (incl. tamper/missing detection), the
workflow/script invariants, and a real `cosign` sign→verify→tamper round-trip
when `cosign` is installed.

## Cross-repo PR intake (E3/T3)

Any Python or TypeScript/Playwright repo works, public or private:

- **PR file fetch** — `tia_agent.tools.github.GitHubClient` calls the GitHub
  REST API directly (paginated `GET /repos/{owner}/{repo}/pulls/{n}/files`).
  `filter_source_files` keeps changed source (Python/TS/Go/…) and drops
  docs, vendor/deps, build output, assets, lockfiles and config.
- **Language / testbed** — `tia_agent.tools.language` infers `python`,
  `typescript`, or `playwright` from a checkout (`--path`), scanning the root
  and workspace `package.json` files plus `playwright.config.*`; when only file
  paths are known it decides from extensions (`.spec.ts` → playwright).
- **Private token** — `tia_agent.interfaces.github_auth` resolves a token from
  `TIA_GITHUB_TOKEN`/config, else the credential store (provider `github`),
  else prompts hidden and stores it. The conversational flow prompts once on a
  `GitHubAuthError` and retries; failure is non-fatal (the backend can fetch).

```bash
tia-agent intake --repo hbahuguna/py-key-value --pr 1 --path ~/src/py-key-value
# language      : python (high) -> python
# source files  : 1
#   - src/key_value/aio/stores/memory/store.py
```

Preview only — `intake` fetches and classifies but never runs TIA or meters a
license unit.

## Evidence-first + fallback (E4/F1)

`AnalyzeRunner.to_result` turns the backend response into a validated result:

1. **Evidence-first** — use `analyze_pr` mappings verbatim (never invent tests).
2. **Dedupe** — collapse results by `(test_file, test_name)`.
3. **Fallback decision** — empty/sparse evidence (e.g. new files) sets
   `fallback_used=true` with a reason.
4. **Existence check** — `tia_agent.tools.fs.validate_tests` drops any reported
   test file not present in the local checkout (container paths like
   `/workdir/<repo>/...` are resolved).
5. **Deterministic discovery** — when evidence yields nothing, a read-only scan
   (`discover_tests_fallback`) lists local tests (tests related to the changed
   files first, else the full local suite); confidence is forced to `low`.

Point the agent at a checkout with `--repo-path` (or `TIA_REPO_PATH`) to enable
validation and fallback:

```bash
tia-agent analyze --repo hbahuguna/py-key-value --pr 1 \
  --repo-path ~/src/py-key-value
```

## Structured output + run commands + safety cap (E5/O1)

`TiaResult.to_dict()` emits the v1.0 contract defined in
`tia_agent/output/schema.py` (`OUTPUT_SCHEMA`). `validate_output` is hand-rolled
(no `jsonschema` dependency) and the CLI validates every `--json` result before
printing it, exiting non-zero with an `errors` list if the shape drifts.

- **Run commands** (`tia_agent/output/commands.py`): python → `pytest <nodeid>`;
  Playwright `.spec.*` (or a checkout declaring `@playwright/test`) →
  `npx playwright test <file>`; Vitest/Jest detected from `package.json` →
  `npx vitest run <file>` / `npx jest <file>`. Deduped, first-seen order.
- **Safety cap**: with a `--repo-path`, `total_tests_in_repo` is counted from the
  local suite (`count_test_cases`); when affected tests exceed 30% of it the
  result sets `safety_flag=true` and recommends a full run. Suppressed on
  fallback runs (they already run the whole suite).

```bash
tia-agent analyze --repo hbahuguna/Test-Radius --pr 30 \
  --repo-path /tmp/testsquad-workspaces/hbahuguna_Test-Radius --json
```

The `--json` payload includes `schema_version`, `changed_files`, `safety_flag`,
and `impacted_ratio` alongside the tests and run commands.

## Privacy enforcement (E5/P1)

Two data flows leave the machine, both allowlisted in `tia_agent/privacy.py`
(the single source of truth, imported by the LLM context builder and the license
guard):

- **LLM provider (D11)** — only changed file paths, selected symbol names,
  counts/confidence, and the conversation. `conversation.context.build_context` /
  `assert_d11_safe` reject anything else, and `explain_messages` /
  `evaluate_messages` assert D11-safety at the prompt boundary.
- **License server (D12)** — only opaque `repo_hash`, `file_count`, `test_count`,
  `language`, `duration_seconds`, `os`, `agent_version`. `license_guard.record_run`
  strips anything else before egress (the server filters again server-side).

Written policy: `docs/project/tia-commercial-agent/PRIVACY.md`.
`tests/test_privacy.py` asserts the **actual outbound payloads** (LLM messages and
license metadata) contain only allowlisted fields and no code/test names.

## Tests

```bash
cd apps/tia-agent
.venv/bin/python -m pytest tests/ -q
```
