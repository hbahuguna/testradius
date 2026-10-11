# tia-agent Privacy Policy (written policy — E5/P1)

This is the enforceable data-handling policy for the standalone `tia-agent`.
It is the human-readable companion to the machine-enforced allowlists in
`apps/tia-agent/tia_agent/privacy.py` (imported by the LLM context builder and
the license guard). If this document and the code ever disagree, the code in
`privacy.py` is authoritative and a bug exists — see "Enforcement" below.

Decisions: **D11** (LLM) and **D12** (licensing) in `AGILE-BOARD.md`.

## Principles

1. **Code never leaves the machine.** Repository source, diffs, patches, file
   contents, and test bodies are never transmitted to the LLM provider, the
   license server, or any TestRadius service operated by us. TestRadius analysis
   itself runs locally (bundled backend) against the user's checkout.
2. **Metadata only to the license server.** Metering is limited to opaque
   identifiers and aggregate counts needed for billing.
3. **Paths + symbol names only to the LLM.** The LLM guides the conversation; it
   does not need, and never receives, code.
4. **User's own LLM key.** The user supplies the provider API key; it is stored
   in the OS keychain / credentials file and never embedded in the binary (D3).

## Data flow 1 — LLM provider (D11)

When an LLM is configured, the agent sends chat messages to the **user's chosen
provider** using the **user's own API key**. The only repository-derived facts
placed in those messages are:

| Field | Example | Notes |
|-------|---------|-------|
| `repo` | `acme/shop` | identifier |
| `pr_number` | `42` | identifier |
| `changed_files` | `["src/cart.ts"]` | **paths only** |
| `symbols` | `["applyDiscount"]` | **symbol names only** |
| `tests_selected` | `3` | count |
| `total_affected_tests` | `7` | count |
| `total_tests_in_repo` | `1846` | count |
| `fallback_used` / `fallback_reason` | `true` / `"no mappings…"` | agent-generated text |
| `confidence` | `high` | enum |
| `instrumented` / `evidence_fresh` | `true` / `false` | booleans |

This set is the **complete allowlist** (`LLM_CONTEXT_ALLOWED`). Anything else —
including test names, test bodies, file contents, diffs, and patches — is
rejected before a request is built.

## Data flow 2 — License server (D12)

The agent meters **one successful TIA run** (never errored/failed runs — D1) by
calling the license server's `POST /v1/runs`. The payload contains only:

| Field | Example | Notes |
|-------|---------|-------|
| `repo_hash` | `9f2c…` (sha256) | **opaque**; the repo name is never sent |
| `file_count` | `2` | count of changed files |
| `test_count` | `7` | count of affected tests |
| `language` | `python` | enum |
| `duration_seconds` | `1.234` | timing |
| `os` | `darwin` | platform |
| `agent_version` | `0.1.0` | build id |

Device identity is carried by the activation token, not the metering payload.
This is the **complete allowlist** (`LICENSE_METADATA_ALLOWED`). The license
server independently re-applies the same allowlist on receipt
(`services/license/license_server/service.py::_metadata_allowlist`).

## Never sent (anywhere)

- Source code, file contents, diffs, patches, snippets
- Test file contents or test names
- Repository name in plaintext to the license server (only `repo_hash`)
- The user's LLM API key (stored locally; used only to authenticate the user's
  own provider calls)
- The user's GitHub token (stored locally; used only for GitHub API calls)

## Enforcement

Three independent layers, so a future edit cannot silently start leaking:

1. **Mingled allowlist** — `tia_agent/privacy.py` defines `LLM_CONTEXT_ALLOWED`
   and `LICENSE_METADATA_ALLOWED`; both the context builder and the license guard
   import from it (no divergent copies).
2. **Rejection at build** — `conversation.context.build_context` /
   `assert_d11_safe` raise `PrivacyError` on any non-allowlisted or
   content-bearing field, and `conversation.prompts.explain_messages` /
   `evaluate_messages` assert D11-safety at the prompt boundary.
3. **Egress filters** — `license_guard.record_run` strips non-allowlisted
   metadata via `filter_license_metadata` before the request leaves the process;
   the license server filters again server-side.

### How to verify

```bash
cd apps/tia-agent
.venv/bin/python -m pytest tests/test_privacy.py -q
```

`tests/test_privacy.py` asserts, against the **actual outbound payloads**:

- every LLM message built by the flow (intake, per-step explanations, result
  evaluation) embeds only allowlisted context keys and no code/test names;
- the license `record_run` payload contains only allowlisted metadata, and
  attempts to inject extra fields (e.g. `code`, `changed_files`) are stripped.
