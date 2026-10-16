import os
import json
import logging
from typing import Dict, List, Optional, Generator, Any

logger = logging.getLogger(__name__)

# Import for type hints used in auto-detection
from testsquad_core.instrumentation.typescript_pipeline import TypeScriptTestbedConfig


def _repo_head_sha(repo_path: str) -> Optional[str]:
    """Return the HEAD commit SHA of a cloned testbed (None when unavailable)."""
    try:
        import git
        return str(git.Repo(repo_path).head.commit.hexsha)
    except Exception:
        logger.warning(f"Could not read HEAD SHA from {repo_path}")
        return None


def _with_built_at_sha(event: Dict[str, Any], built_at_sha: Optional[str]) -> Dict[str, Any]:
    """Attach ``built_at_sha`` to an event when we know it."""
    if built_at_sha:
        event["built_at_sha"] = built_at_sha
    return event


def detect_project_language(repo_path: str) -> str:
    if os.path.exists(os.path.join(repo_path, "package.json")):
        if os.path.exists(os.path.join(repo_path, "playwright.config.ts")) or \
           os.path.exists(os.path.join(repo_path, "playwright.config.js")):
            return "playwright"
        return "typescript"
    if os.path.exists(os.path.join(repo_path, "pyproject.toml")) or \
       os.path.exists(os.path.join(repo_path, "setup.py")) or \
       os.path.exists(os.path.join(repo_path, "setup.cfg")):
        return "python"
    return "python"


def mappings_from_pipeline_result(result: Dict) -> List[Dict]:
    from testsquad_core.instrumentation.symbol_resolver import Symbol

    mappings = []
    for m in result.get("mappings", []):
        symbols = []
        for s in m.get("symbols", []):
            if isinstance(s, tuple) or isinstance(s, list):
                symbols.append(Symbol(
                    name=s[0],
                    symbol_type=s[1],
                    file_path=s[4] if len(s) >= 5 else m.get("test_file", ""),
                    start_line=s[2],
                    end_line=s[3],
                ))
            else:
                symbols.append(s)
        mappings.append({
            "test_name": m["test_name"],
            "test_file": m["test_file"],
            "symbols": symbols,
        })
    return mappings


def run_pipeline(
    project_id: int,
    repo_url: Optional[str] = None,
    local_path: Optional[str] = None,
    language: Optional[str] = None,
    testbed_name: Optional[str] = None,
    run_fresh: bool = False,
    cancel_flags: Optional[Dict[int, bool]] = None,
    github_token: Optional[str] = None,
    evidence_store: Optional[Any] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Run the appropriate instrumentation pipeline.

    Yields event dicts: {'event': str, 'data': any}
    Events: progress, error, mappings, status(COMPLETED/CANCELLED)

    ``evidence_store`` (a ``Neo4jStore``) enables incremental instrumentation
    (Story 11.5): prior evidence is read to decide which tests actually need to
    re-run. Without it — or under ``run_fresh`` — the suite runs in full.
    """
    if cancel_flags is None:
        cancel_flags = {}

    from testsquad_core.instrumentation.testbed_manager import TestbedManager, TestbedConfig

    tm = TestbedManager(base_dir="/tmp")
    lang = language or "python"

    if lang == "typescript":
        yield from _run_typescript_pipeline(project_id, repo_url, testbed_name, run_fresh, tm, cancel_flags, github_token)
    elif lang == "playwright":
        yield from _run_playwright_pipeline(project_id, local_path, testbed_name, cancel_flags)
    else:
        yield from _run_python_pipeline(
            project_id, repo_url, run_fresh, tm, cancel_flags, github_token,
            evidence_store=evidence_store,
        )

    return


def _scan_workspace_for_framework(repo_path: str, workspace_globs: list) -> dict:
    """Scan workspace packages for test framework presence."""
    result = {"has_playwright": False, "has_vitest": False, "has_jest": False}
    for glob_pattern in workspace_globs:
        base_dir = glob_pattern.replace("/*", "")
        full_dir = os.path.join(repo_path, base_dir)
        if not os.path.isdir(full_dir):
            continue
        try:
            for entry in os.listdir(full_dir):
                ws_pkg = os.path.join(full_dir, entry, "package.json")
                if os.path.exists(ws_pkg):
                    with open(ws_pkg) as f:
                        import json
                        wpkg = json.load(f)
                    deps = str({**wpkg.get("dependencies", {}), **wpkg.get("devDependencies", {})})
                    if "playwright" in deps:
                        result["has_playwright"] = True
                    if "vitest" in deps:
                        result["has_vitest"] = True
                    if "jest" in deps:
                        result["has_jest"] = True
        except (PermissionError, OSError):
            continue
    return result


def _detect_typescript_config(repo_path: str, repo_url: str, base_config) -> TypeScriptTestbedConfig:
    """Auto-detect TypeScript project structure and build a dynamic config."""
    from copy import deepcopy
    from testsquad_core.instrumentation.typescript_pipeline import detect_typescript_test_framework

    config = deepcopy(base_config)
    config.repo_url = repo_url

    pkg_json = os.path.join(repo_path, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json) as f:
                import json
                pkg = json.load(f)
            workspace = pkg.get("workspaces", [])
            scripts = pkg.get("scripts", {})
            has_playwright = "playwright" in str(pkg.get("devDependencies", {})) or \
                             "playwright" in str(pkg.get("dependencies", {}))
            has_vitest = "vitest" in str(pkg.get("devDependencies", {})) or \
                          "vitest" in str(pkg.get("dependencies", {}))
            has_jest = "jest" in str(pkg.get("devDependencies", {})) or \
                        "jest" in str(pkg.get("dependencies", {}))
            framework = detect_typescript_test_framework(repo_path)

            # Scan workspace packages for additional framework detection
            if workspace:
                ws_result = _scan_workspace_for_framework(repo_path, workspace)
                has_playwright = has_playwright or ws_result["has_playwright"]
                has_vitest = has_vitest or ws_result["has_vitest"]
                has_jest = has_jest or ws_result["has_jest"]

            # Detect test directory from common locations
            if os.path.isdir(os.path.join(repo_path, "tests")):
                config.test_dir = "tests"
            elif os.path.isdir(os.path.join(repo_path, "test")):
                config.test_dir = "test"
            elif os.path.isdir(os.path.join(repo_path, "__tests__")):
                config.test_dir = "__tests__"
            elif workspace:
                # Monorepo: search for test dirs in workspaces
                for ws in workspace if isinstance(workspace, list) else [workspace]:
                    ws_dir = ws.replace("/*", "")
                    if os.path.isdir(os.path.join(repo_path, ws_dir, "src")):
                        config.test_dir = f"{ws_dir}/src"
                        break

            # Detect package manager from lock files
            if os.path.exists(os.path.join(repo_path, "pnpm-lock.yaml")):
                config.package_manager = "pnpm"
            elif os.path.exists(os.path.join(repo_path, "yarn.lock")):
                config.package_manager = "yarn"

            # Detect install command
            if config.package_manager == "pnpm":
                config.install_command = "pnpm install"
            elif config.package_manager == "yarn":
                config.install_command = "yarn install --frozen-lockfile"
            elif os.path.exists(os.path.join(repo_path, "package-lock.json")):
                config.install_command = "npm ci"
            else:
                config.install_command = "npm install"

            # Detect test command
            if has_playwright:
                config.test_command = "npx playwright test"
            elif has_vitest:
                config.test_command = "npx vitest run"
            elif has_jest:
                config.test_command = "npx jest"
            elif scripts:
                for cmd in ["test:ci", "test:unit", "test"]:
                    if cmd in scripts:
                        config.test_command = f"npx {cmd.replace(':', ' ').replace('test', 'vitest run')}"
                        break

            # Detect test pattern
            if has_playwright:
                config.test_pattern = "**/*.spec.{ts,tsx}"
            elif has_vitest:
                config.test_pattern = "**/*.{test,spec}.{ts,tsx,js,jsx}"
            elif has_jest:
                config.test_pattern = "**/*.{test,spec}.{ts,tsx,js,jsx}"

        except Exception as e:
            logger.warning(f"Auto-detection failed: {e}")

    return config, has_playwright


def _inject_token_into_url(url: str, token: Optional[str]) -> str:
    if token and "https://" in url:
        return url.replace("https://", f"https://x-access-token:{token}@")
    return url


def _run_typescript_pipeline(
    project_id: int, repo_url: Optional[str], testbed_name: Optional[str],
    run_fresh: bool, tm, cancel_flags: Dict[int, bool],
    github_token: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    from testsquad_core.instrumentation.testbed_manager import TestbedConfig
    from testsquad_core.instrumentation.typescript_pipeline import (
        TYPESCRIPT_TESTBEDS, run_typescript_pipeline as run_ts,
        TypeScriptTestbedConfig,
    )

    is_custom = bool(repo_url) and (testbed_name is None or testbed_name not in TYPESCRIPT_TESTBEDS)
    ts_name = testbed_name or "blacktrigram"
    if ts_name not in TYPESCRIPT_TESTBEDS:
        ts_name = "blacktrigram"

    ts_config = TYPESCRIPT_TESTBEDS[ts_name]
    clone_url = repo_url or ts_config.repo_url
    yield {"event": "progress", "data": f"Cloning TypeScript repository: {clone_url}"}
    clone_url = _inject_token_into_url(clone_url, github_token)

    clone_config = TestbedConfig(
        repo_url=clone_url, branch=ts_config.branch if not is_custom else "main",
        install_command="", test_dir=".",
    )
    tm.register_testbed("ts-temp", clone_config)
    clone_result = tm.clone_testbed("ts-temp", use_cache=not run_fresh)

    if not clone_result.success:
        yield {"event": "error", "data": f"Clone failed: {clone_result.error_message}"}
        return

    yield {"event": "progress", "data": f"Testbed cloned to {clone_result.testbed_path}"}
    built_at_sha = _repo_head_sha(clone_result.testbed_path)

    # For custom repos, auto-detect config from cloned repo structure
    if is_custom:
        ts_config, has_playwright = _detect_typescript_config(clone_result.testbed_path, repo_url, ts_config)
        yield {"event": "progress", "data": f"Auto-detected config: test_dir={ts_config.test_dir}, pm={ts_config.package_manager}, cmd={ts_config.test_command}, playwright={has_playwright}"}

        # If the cloned repo is a Playwright project, route to Playwright pipeline
        if has_playwright or os.path.exists(os.path.join(clone_result.testbed_path, "playwright.config.ts")) or \
                            os.path.exists(os.path.join(clone_result.testbed_path, "playwright.config.js")):
            yield {"event": "progress", "data": f"Detected Playwright project. Installing dependencies with {ts_config.package_manager}..."}
            from testsquad_core.instrumentation.typescript_pipeline import install_dependencies as ts_install
            if not ts_install(clone_result.testbed_path, ts_config):
                yield {"event": "error", "data": "Dependency installation failed for Playwright project"}
                return
            yield {"event": "progress", "data": "Dependencies installed, routing to Playwright pipeline..."}
            yield from _run_playwright_pipeline(project_id, clone_result.testbed_path, "testradius", cancel_flags)
            return

    if cancel_flags.get(project_id):
        yield {"event": "status", "data": {"status": "CANCELLED"}}
        return

    yield {"event": "progress", "data": "Running TypeScript TIA pipeline..."}
    if cancel_flags.get(project_id):
        yield {"event": "status", "data": {"status": "CANCELLED"}}
        return

    result = run_ts(clone_result.testbed_path, ts_config)
    if "error" in result:
        yield {"event": "error", "data": f"TS pipeline failed: {result['error']}"}
        return

    mappings = mappings_from_pipeline_result(result)
    tc = result.get("test_count", 0)
    sc = result.get("symbol_count", 0)
    yield {"event": "progress", "data": f"TS analysis: {tc} tests, {sc} unique symbols"}

    for m in mappings:
        snames = [s.name for s in m.get("symbols", [])]
        logger.info(f"  Test: {m['test_name']} -> {len(snames)} symbols: {', '.join(snames[:5])}")

    yield {"event": "progress", "data": f"Generated {len(mappings)} test-symbol mappings"}
    for m in mappings:
        sd = {s.name: f"{s.start_line}-{s.end_line}" for s in m.get("symbols", [])}
        yield {"event": "mapping", "data": {"test_name": m["test_name"], "symbols": sd}}

    yield _with_built_at_sha({"event": "mappings", "data": mappings}, built_at_sha)


def _run_playwright_pipeline(
    project_id: int, local_path: Optional[str], testbed_name: Optional[str],
    cancel_flags: Dict[int, bool],
) -> Generator[Dict[str, Any], None, None]:
    from testsquad_core.instrumentation.playwright_pipeline import (
        PLAYWRIGHT_TESTBEDS, run_playwright_pipeline as run_pw,
    )

    pw_name = testbed_name or "testradius"
    if pw_name not in PLAYWRIGHT_TESTBEDS:
        valid = list(PLAYWRIGHT_TESTBEDS.keys())
        yield {"event": "error", "data": f"Unknown Playwright testbed: {pw_name}. Valid: {valid}"}
        return

    pw_config = PLAYWRIGHT_TESTBEDS[pw_name]
    pw_path = local_path or os.environ.get("TESTRADIUS_LOCAL_PATH", "")

    if not pw_path or not os.path.isdir(pw_path):
        yield {"event": "error", "data": f"Playwright testbed path not found: {pw_path}"}
        return

    yield {"event": "progress", "data": f"Installing dependencies on {pw_path}..."}
    from testsquad_core.instrumentation.playwright_pipeline import install_dependencies as pw_install
    if not pw_install(pw_path, pw_config):
        yield {"event": "error", "data": "Dependency installation failed for Playwright pipeline"}
        return

    import platform, subprocess
    if platform.system() == "Linux":
        yield {"event": "progress", "data": "Installing Linux platform-native deps..."}
        for pkg in ["@rollup/rollup-linux-x64-gnu@4.60.1", "lightningcss-linux-x64-gnu@^1.32.0"]:
            r = subprocess.run(
                ["pnpm", "--filter", "@workspace/testradius", "add", "-D", pkg],
                cwd=pw_path, capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                logger.warning(f"Failed to install {pkg}: {r.stderr[:200]}")
            else:
                logger.info(f"Installed {pkg}: {r.stdout[:200]}")
        r2 = subprocess.run(["pnpm", "install"], cwd=pw_path, capture_output=True, text=True, timeout=60)
        logger.info(f"pnpm install re-link: {r2.stdout[:200]}")
        # Verify the package exists
        r3 = subprocess.run(
            ["node", "-e", "console.log(require.resolve('@rollup/rollup-linux-x64-gnu'))"],
            cwd=os.path.join(pw_path, "artifacts", "testradius"),
            capture_output=True, text=True, timeout=10,
        )
        logger.info(f"rollup-linux-x64-gnu resolve: {r3.stdout.strip() or r3.stderr.strip()}")

    yield {"event": "progress", "data": "Dependencies installed"}

    pw_test_dir = os.path.join(pw_path, pw_config.test_dir)
    if os.path.exists(os.path.join(pw_test_dir, "playwright.config.ts")):
        yield {"event": "progress", "data": "Installing Playwright browsers..."}
        r = subprocess.run(
            ["npx", "playwright", "install", "chromium", "--with-deps"],
            cwd=pw_test_dir, capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            logger.warning(f"Playwright browser install output: {r.stdout[-300:]}")
            logger.warning(f"Playwright browser install stderr: {r.stderr[-300:]}")
        else:
            logger.info(f"Playwright browser install: {r.stdout[-200:]}")

    result = run_pw(pw_path, pw_config)
    if "error" in result:
        yield {"event": "error", "data": f"Playwright pipeline failed: {result['error']}"}
        return

    mappings = mappings_from_pipeline_result(result)
    tc = result.get("test_count", 0)
    sc = result.get("symbol_count", 0)
    built_at_sha = _repo_head_sha(pw_path)
    yield {"event": "progress", "data": f"Playwright analysis: {tc} tests, {sc} unique symbols"}

    for m in mappings:
        snames = [s.name for s in m.get("symbols", [])]
        logger.info(f"  Test: {m['test_name']} -> {len(snames)} symbols: {', '.join(snames[:5])}")

    yield {"event": "progress", "data": f"Generated {len(mappings)} test-symbol mappings"}
    for m in mappings:
        sd = {s.name: f"{s.start_line}-{s.end_line}" for s in m.get("symbols", [])}
        yield {"event": "mapping", "data": {"test_name": m["test_name"], "symbols": sd}}

    yield _with_built_at_sha({"event": "mappings", "data": mappings}, built_at_sha)


def _detect_default_branch(repo_url: str) -> str:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", repo_url, "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.splitlines():
            if "ref:" in line and "HEAD" in line:
                branch = line.split("ref:")[1].split("HEAD")[0].strip().replace("refs/heads/", "")
                return branch
    except Exception:
        pass
    return "main"


def _load_per_test_analyzer():
    """Load ``per_test_analyzer`` by path without importing the package.

    Importing ``testsquad_core.instrumentation.per_test_analyzer`` would run the
    package ``__init__`` (Neo4j/FastAPI deps) just to reach a stdlib-only module.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "per_test_analyzer",
        os.path.join(os.path.dirname(__file__), "per_test_analyzer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_incremental_plan(
    project_id: int,
    evidence_store: Optional[Any],
    testbed_path: str,
    test_files: List[str],
    current_sha: Optional[str] = None,
    run_fresh: bool = False,
):
    """Decide which tests this run must execute (Story 11.5).

    Reads the prior evidence (anchor SHA + coverage index) from
    ``evidence_store``, diffs the checkout against the anchor, and narrows the
    suite to the tests that actually cover changed files. It falls back to
    ``mode="full"`` whenever narrowing could be wrong: no evidence, no anchor,
    no current commit, an unavailable diff, or a diff so large that the
    bookkeeping costs more than it saves.

    Args:
        evidence_store: Object exposing ``get_coverage_summary(project_id)``,
            or None when incremental instrumentation is unavailable.
        testbed_path: The checkout (used to normalize paths and run git).
        test_files: Discovered test files, absolute or repo-relative.
        current_sha: Commit the checkout sits on (the new anchor).
        run_fresh: When True the caller wants a from-scratch run, never a
            narrowed one.

    Returns:
        ``(plan, rerun_test_names, drop_test_names)`` — the names being prior
        test node ids the store must replace (re-run) or drop (file removed).
    """
    from testsquad_core.instrumentation.incremental import (
        IncrementalPlan, changed_files_between, normalize_path, plan_incremental_run,
    )

    if evidence_store is None:
        return IncrementalPlan(mode="full", reason="disabled"), [], []
    if run_fresh:
        return IncrementalPlan(mode="full", reason="run_fresh"), [], []

    summary = evidence_store.get_coverage_summary(project_id) or {}
    anchor = summary.get("anchor_sha")
    prior = summary.get("tests") or []

    # Build {source_file: {test_file}} plus a file -> prior node ids lookup.
    index: Dict[str, set] = {}
    names_by_file: Dict[str, set] = {}
    for row in prior:
        source_file = normalize_path(row.get("source_file") or "", testbed_path)
        test_file = normalize_path(row.get("file") or "", testbed_path)
        if not source_file or not test_file:
            continue
        index.setdefault(source_file, set()).add(test_file)
        if row.get("name"):
            names_by_file.setdefault(test_file, set()).add(row["name"])

    universe = sorted({normalize_path(f, testbed_path) for f in (test_files or []) if f})

    # ``changed_files_between`` fetches the anchor when the shallow clone does
    # not have it, and returns None when that is impossible -> full run.
    changed = changed_files_between(testbed_path, anchor) if anchor else None

    plan = plan_incremental_run(
        anchor_sha=anchor,
        current_sha=current_sha,
        changed_files=changed,
        universe=universe,
        coverage_index=index,
    )
    rerun = sorted(name for tf in plan.tests_to_run for name in names_by_file.get(tf, ()))
    drop = sorted(name for tf in plan.tests_to_drop for name in names_by_file.get(tf, ()))
    return plan, rerun, drop


def _carried_completeness(universe: List[str], plan) -> Dict[str, Any]:
    """Completeness for a run that re-executed nothing: all evidence carried."""
    universe_set = set(universe)
    carried = universe_set & set(plan.carried_forward)
    missing = sorted(universe_set - carried)
    denom = len(universe_set)
    return {
        "test_files_expected": denom,
        "test_files_collectable": denom,
        "test_files_scheduled": 0,
        "test_files_total": denom,
        "test_files_carried_forward": len(carried),
        "test_files_instrumented": len(carried),
        "coverage_pct": round(100.0 * len(carried) / denom, 1) if denom else 0.0,
        "missing_test_files": missing[:50],
        "missing_count": len(missing),
    }


def _run_python_pipeline(
    project_id: int, repo_url: Optional[str], run_fresh: bool,
    tm, cancel_flags: Dict[int, bool],
    github_token: Optional[str] = None,
    evidence_store: Optional[Any] = None,
) -> Generator[Dict[str, Any], None, None]:
    from testsquad_core.instrumentation.testbed_manager import TestbedConfig

    if repo_url:
        branch = _detect_default_branch(repo_url)
        testbed_name = "custom"
        custom_config = TestbedConfig(
            repo_url=_inject_token_into_url(repo_url, github_token), branch=branch,
            test_command=".venv/bin/python -m pytest tests/ -v --cov --cov-report=json",
            install_command="python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/pip install -e '.[all,test,dev,memory]' 2>/dev/null; .venv/bin/pip install pytest pytest-cov",
            test_dir="tests", coverage_output="coverage.json",
        )
        tm.register_testbed(testbed_name, custom_config)
        yield {"event": "progress", "data": f"Cloning repository: {repo_url}"}
        clone_result = tm.clone_testbed(testbed_name, use_cache=not run_fresh)
    else:
        testbed_name = "py-key-value"
        yield {"event": "progress", "data": "Cloning testbed repository..."}
        clone_result = tm.clone_testbed(testbed_name, use_cache=not run_fresh)

    if not clone_result.success:
        yield {"event": "error", "data": f"Clone failed: {clone_result.error_message}"}
        return

    yield {"event": "progress", "data": f"Testbed cloned to {clone_result.testbed_path}"}
    built_at_sha = _repo_head_sha(clone_result.testbed_path)
    if built_at_sha:
        logger.info(f"Evidence will be pinned to testbed commit {built_at_sha[:12]}")
        yield {"event": "built_at_sha", "data": built_at_sha}
    if cancel_flags.get(project_id):
        yield {"event": "status", "data": {"status": "CANCELLED"}}
        return

    config = tm.get_testbed(testbed_name)

    analyzer_module = _load_per_test_analyzer()

    discovery_collected = False
    if repo_url:
        venv_python = os.path.join(clone_result.testbed_path, ".venv", "bin", "python")
        try:
            analyzer_module._install_test_deps(venv_python, clone_result.testbed_path)
        except Exception as e:
            logger.warning(f"Test dep install before discovery failed: {e}")
        yield {"event": "progress", "data": "Discovering test files via pytest collection..."}
        test_files = analyzer_module.discover_collected_files(
            clone_result.testbed_path, config.test_dir,
        )
        discovery_collected = bool(test_files)
        if not test_files:
            import glob as _glob
            test_dir_path = os.path.join(clone_result.testbed_path, config.test_dir)
            test_files = _glob.glob(os.path.join(test_dir_path, "**/test_*.py"), recursive=True)
        if not test_files:
            yield {"event": "error", "data": "No test files found in repository"}
            return
        test_files.sort()
        how = "pytest collection" if discovery_collected else "filename glob (collection fallback)"
        yield {"event": "progress", "data": f"Discovered {len(test_files)} test files in {config.test_dir}/ via {how} (running all, sharded)"}
    else:
        test_files = ["tests/utils/test_wait.py", "tests/utils/test_retry.py"]

    # Story 11.5: narrow the suite to tests covering files that changed since
    # the prior instrumentation anchor; everything else carries forward.
    from testsquad_core.instrumentation.incremental import normalize_path

    plan, rerun_names, drop_names = build_incremental_plan(
        project_id, evidence_store, clone_result.testbed_path, test_files,
        current_sha=built_at_sha, run_fresh=run_fresh,
    )
    universe_rel = sorted({
        normalize_path(f, clone_result.testbed_path) for f in test_files if f
    })

    run_files = test_files
    incremental_meta = None
    if plan.is_incremental:
        planned = set(plan.tests_to_run)
        run_files = [
            f for f in test_files
            if normalize_path(f, clone_result.testbed_path) in planned
        ]
        incremental_meta = {
            "anchor_sha": plan.anchor_sha,
            "changed_files": plan.changed_files,
            "changed_source_files": plan.changed_source_files,
            "tests_to_run": plan.tests_to_run,
            "carried_forward": plan.carried_forward,
            "rerun_test_names": rerun_names,
            "drop_test_names": drop_names,
        }
        yield {"event": "progress", "data": (
            f"Incremental run: {len(run_files)} of {len(universe_rel)} test files scheduled, "
            f"{len(plan.carried_forward)} carried forward "
            f"({len(plan.changed_source_files)} source file(s) changed since "
            f"{(plan.anchor_sha or '')[:12]})"
        )}
        if not run_files:
            # Nothing covers the change: re-stamp prior evidence and stop, rather
            # than asking the analyzer to run an empty suite (which errors out).
            yield {"event": "coverage_completeness", "data": _carried_completeness(universe_rel, plan)}
            yield _with_built_at_sha(
                {"event": "mappings", "data": [], "incremental": incremental_meta},
                built_at_sha,
            )
            return
    else:
        yield {"event": "progress", "data": f"Running full suite ({plan.reason})"}

    yield {"event": "progress", "data": "Running per-test coverage over scheduled test files..."}
    if cancel_flags.get(project_id):
        yield {"event": "status", "data": {"status": "CANCELLED"}}
        return

    try:
        per_test_result = analyzer_module.analyze_per_test_coverage(
            clone_result.testbed_path, run_files,
            already_collected=discovery_collected,
            # AC3: completeness stays measured against the full suite even
            # though only a subset ran this round. ``universe`` is the whole
            # discovered set (never narrowed) and `_coverage_completeness`
            # normalizes it the same way as ``run_files``.
            universe=test_files if plan.is_incremental else None,
            carried_forward=plan.carried_forward if plan.is_incremental else None,
        )
        if "error" in per_test_result:
            diag = per_test_result.get("diagnostics", {})
            output = per_test_result.get("output", "")
            if diag:
                yield {"event": "progress", "data": f"Diagnostics: {str(diag)[:500]}"}
            if output:
                yield {"event": "progress", "data": f"Test output: {output[:2000]}"}
            yield {"event": "error", "data": f"Per-test analysis failed: {per_test_result['error']}"}
            return

        mappings = mappings_from_pipeline_result(per_test_result)
        tc = per_test_result.get("test_count", 0)
        sc = per_test_result.get("symbol_count", 0)
        yield {"event": "progress", "data": f"Per-test analysis: {tc} tests, {sc} unique symbols"}

        completeness = per_test_result.get("coverage_completeness") or {}
        if completeness:
            yield {"event": "coverage_completeness", "data": completeness}
            yield {"event": "progress", "data": (
                f"Coverage: {completeness.get('test_files_instrumented')}/"
                f"{completeness.get('test_files_scheduled')} scheduled test files "
                f"({completeness.get('coverage_pct')}%)"
            )}
            if completeness.get("missing_count"):
                preview = ", ".join(completeness.get("missing_test_files", [])[:10])
                yield {"event": "progress", "data": (
                    f"Shortfall: {completeness.get('missing_count')} test file(s) produced no "
                    f"coverage: {preview}"
                )}

        diag = per_test_result.get("diagnostics", {})
        if diag:
            yield {"event": "progress", "data": f"Diagnostics: {str(diag)[:500]}"}

        if tc == 0:
            ptc = per_test_result.get("per_test_coverage", {})
            if ptc:
                sample = {}
                for i, (tn, fcov) in enumerate(ptc.items()):
                    if i >= 3:
                        break
                    sample[tn[:60]] = {f: len(ls) for f, ls in fcov.items()}
                yield {"event": "progress", "data": f"Coverage has data but 0 mappings. Sample: {str(sample)[:300]}"}
            else:
                yield {"event": "progress", "data": "Coverage data is EMPTY"}

    except Exception as e:
        logger.error(f"Per-test analysis failed: {e}")
        yield {"event": "error", "data": f"Per-test analysis failed: {e}"}
        return

    for m in mappings:
        snames = [s.name for s in m.get("symbols", [])]
        logger.info(f"  Test: {m['test_name']} -> {len(snames)} symbols: {', '.join(snames[:5])}")

    yield {"event": "progress", "data": f"Generated {len(mappings)} test-symbol mappings"}
    for m in mappings:
        sd = {s.name: f"{s.start_line}-{s.end_line}" for s in m.get("symbols", [])}
        yield {"event": "mapping", "data": {"test_name": m["test_name"], "symbols": sd}}

    final_event: Dict[str, Any] = {"event": "mappings", "data": mappings}
    if incremental_meta is not None:
        # Tells the store writer to replace only these tests' edges (and drop
        # removed ones) instead of wiping the project, then re-stamp the rest.
        final_event["incremental"] = incremental_meta
    yield _with_built_at_sha(final_event, built_at_sha)
