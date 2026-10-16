# Story 11.4: Clone + Dependency-Install Caching

**Status**: Done
**Epic**: 11 — Instrumentation Hardening
**Effort**: 1d
**Priority**: P1
**Depends on**: —

---

## Summary

A second instrumentation run against an unchanged testbed must not re-clone the repo or re-install dependencies.

## Current behaviour (the problem)

- `TestbedManager.clone_testbed` (`testbed_manager.py:74`) accepts `use_cache` and `cache_ttl` but **ignores both** — it always clones into a new timestamped directory (`:92-104`).
- Because the path is new each run, the dependency-install cache in `per_test_analyzer._DEPS_INSTALLED` (keyed on `os.path.realpath(testbed_path)`, `:155`) **never hits**. Every run pays `pip install` for the full plugin set, `-e .`, and `requirements*.txt` / extras.

## Acceptance criteria

- [x] `clone_testbed(..., use_cache=True)` reuses an existing checkout for the same repo+commit instead of re-cloning.
- [x] Dependency install is skipped on a reused checkout whose deps are already installed (persisted marker or lockfile hash).
- [x] A cache miss / stale marker falls back to a clean clone + install (never a broken run).
- [x] `cache_ttl` is honoured (default `timedelta(hours=24)`, as before).
- [x] Second-run wall-clock time is measurably lower (recorded in the runbook).

## Implementation notes

### `testbed_manager.py` — stable checkout + sidecar marker

- `cache_path(config)` returns `<base>/testbed-cache/<repo-slug>-<branch>-<sha1(repo@branch#install_command)[:8]>`
  — no timestamp, so run N finds run N-1's directory.
  - `_canonical_clone_url` strips embedded credentials, so a rotated GitHub token does **not** bust the cache (important: `main.py:441` passes the raw URL while `pipeline_worker` passes a token-injected one).
- The install command is part of the key. This was not optional: the `detect-lang` clone in `main.py:441` uses `install_command=""` but resolves the **same** repo+branch as the pipeline's `custom`/`ts-temp` testbeds, so without it a clone-only checkout would be served where a venv is genuinely required.
- Sidecar `<path>.meta.json` records `{repo_url, branch, cloned_at, head_sha, installed}`. `_cache_usable` requires **all** of: valid `HEAD` on the checkout, URL/branch match, `installed == true`, age ≤ `cache_ttl`, and `HEAD == head_sha`.
  - **Deviation from the story's literal suggestion** (`<repo-slug>-<sha>`): the commit is unknowable *before* cloning without a network round-trip, which would defeat the cache. The SHA is therefore validated from the sidecar instead of encoded in the path — "same repo+commit" is still enforced, just at read time.
  - `installed` is `False` when `install_command` exits non-zero, so a half-installed checkout is retried instead of reused (AC "never a broken run").
- **Concurrency.** Stable paths made two simultaneous runs for one slot share a directory (the old timestamped paths did not). Fixed two ways:
  - clone + install happen in a private `<slot>.staging-*` dir that is moved into place with `os.rename`, so a reader never observes a half-cloned checkout;
  - an advisory `fcntl.flock` on `<slot>.lock` serializes the miss path, with a double-check after acquiring so the loser turns into a cache hit rather than a second clone.
- `pipeline_worker.py:447` — the default `py-key-value` testbed now passes `use_cache=not run_fresh` like the other two paths (it was hard-coded `False`), so the third path benefits too.

### `per_test_analyzer.py` — persisted install marker

- `DEPS_MARKER = ".tia-deps-installed"` written into the checkout containing `_deps_spec_hash()`, a SHA-256 over the plugin list + the requirements file names + the extras list (`_deps_spec()`).
- `_install_test_deps` short-circuits on either the in-process set **or** a matching marker; a mismatched marker (someone edited the plugin list) forces a reinstall.
- The marker is written **only when the two core installs succeed** (`pip install <plugins>` and `pip install -e .`). The requirements and extras installs stay best-effort, as they were — a project whose `.extras[dev]` legitimately doesn't exist would otherwise never get a marker at all.

### `typescript_pipeline.py` / `playwright_pipeline.py` — node deps

New shared helper `instrumentation/dep_marker.py`:

- `node_deps_ready` / `record_node_deps` skip `npm ci` (or yarn/pnpm/fallback) when `node_modules` exists **and** a marker matches a hash of the package manager + the exact commands + the contents of `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml`.
- A changed lockfile invalidates it; a failed install is never recorded.
- The marker is written **inside `node_modules`**, not the repo root, because the Playwright path (`pipeline_worker.py:320`) installs into a user's **local working copy** rather than a clone — a repo-root marker would show up in their `git status`.
- Guarded by `if not os.path.isdir("node_modules"): return False`, so first-time installs behave exactly as before.

### Not in scope / limitations

- `pipeline_worker.py:332-352` (the Linux-only `pnpm add @rollup/…` re-link) and `:358` (`npx playwright install`) still run every time.
- Two concurrent runs of the **same** project still share one checkout. The lock + atomic publish stop corruption and double-cloning, but `run_fresh: true` while another run is active can still replace the directory under it — there is no run-scoped lock, and adding one would need lock lifetime to span the whole pipeline. The UI/start-endpoint has no "already running" guard today either (only `_cancel_flags`); worth a dedicated follow-up if concurrent runs become a supported flow.

## Tests (TDD — write first)

`services/core/tests/test_testbed_cache.py` — **20 tests**, all written before the implementation (first run: 10 failed / 1 passed). The "remote" is a real local git repo on branch `main`, so the clone path is exercised for real with no network.

- `TestCloneCache` (12): reuses path without re-cloning; stable slug not a timestamp; `use_cache=False` re-clones clean; expired TTL re-clones; cache hit skips the install command; `HEAD` mismatch invalidates; missing checkout invalidates; failed install is not marked installed; a different `install_command` gets its own checkout; no staging dirs left behind; failed clone cleans up staging; two concurrent cold starts clone **once**.
- `TestNodeDepsInstallCache` (5): TS marker short-circuits; TS re-installs when the lockfile changes; TS re-installs without `node_modules`; Playwright marker short-circuits; marker lives in `node_modules`, not the repo root.
- `TestDepsInstallMarker` (3): the marker (not the in-process set) short-circuits; the marker is written only on a successful install; a stale marker is rejected.

## Verification

```bash
PYTHONPATH="services/core:packages/shared" python3.10 -m pytest \
  services/core/tests/test_testbed_cache.py \
  services/core/tests/test_test_discovery.py \
  services/core/tests/test_coverage_sharding.py \
  --override-ini='addopts=' --noconftest -v
# 51 passed
```

Regression sweep (Instrumentation Hardening relevant set) → **181 passed, 0 failed**.

Second-run timing is recorded in `docs/runbooks/tia-py-key-value.md` §2a, including the `/usr/bin/time -p` procedure for the end-to-end figure on a live backend.
