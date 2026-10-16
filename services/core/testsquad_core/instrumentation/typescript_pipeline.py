import os
import subprocess
import json
import logging
import concurrent.futures
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TypeScriptTestbedConfig:
    repo_url: str
    branch: str = "main"
    package_manager: str = "npm"
    install_command: str = "npm ci"
    test_command: str = "npx vitest run"
    test_dir: str = "src"
    test_pattern: str = "**/*.{test,spec}.{ts,tsx,js,jsx}"
    coverage_output: str = "testsquad-per-test-coverage.json"
    vitest_plugin: str = "@testsquad/vitest-plugin"


TYPESCRIPT_TESTBEDS = {
    "blacktrigram": TypeScriptTestbedConfig(
        repo_url="https://github.com/Hack23/blacktrigram.git",
        branch="main",
        package_manager="npm",
        install_command="npm ci",
        test_command="npx vitest run",
        test_dir="src",
        coverage_output="testsquad-per-test-coverage.json",
    ),
    "zod": TypeScriptTestbedConfig(
        repo_url="https://github.com/colinhacks/zod.git",
        branch="main",
        package_manager="npm",
        install_command="npm ci",
        test_command="npx vitest run",
        test_dir="src",
        coverage_output="testsquad-per-test-coverage.json",
    ),
    "hono": TypeScriptTestbedConfig(
        repo_url="https://github.com/honojs/hono.git",
        branch="main",
        package_manager="npm",
        install_command="npm ci",
        test_command="npx vitest run",
        test_dir="src",
        coverage_output="testsquad-per-test-coverage.json",
    ),
}


def detect_typescript_test_framework(repo_path: str) -> Optional[str]:
    pkg_json = os.path.join(repo_path, "package.json")
    if not os.path.exists(pkg_json):
        return None
    with open(pkg_json) as f:
        pkg = json.load(f)
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "vitest" in deps:
        return "vitest"
    if "jest" in deps:
        return "jest"
    if "mocha" in deps:
        return "mocha"
    return None


def install_dependencies(repo_path: str, config: TypeScriptTestbedConfig) -> bool:
    primary = {"npm": ["npm", "ci"], "yarn": ["yarn", "install", "--frozen-lockfile"], "pnpm": ["pnpm", "install", "--frozen-lockfile"]}
    fallback = {"npm": ["npm", "install"], "yarn": ["yarn", "install"], "pnpm": ["pnpm", "install"]}
    pm = config.package_manager
    commands = [c for c in (primary.get(pm), fallback.get(pm)) if c]

    # Reused checkout (Story 11.4): skip the install when node_modules is
    # already there and the lockfile/commands still match the last install.
    try:
        from .dep_marker import node_deps_ready, record_node_deps
    except ImportError:  # loaded standalone by path (tests)
        from dep_marker import node_deps_ready, record_node_deps
    if node_deps_ready(repo_path, pm, commands):
        logger.info(f"Reusing installed node dependencies in {repo_path}")
        return True

    for attempt, cmd_template in [(1, primary.get(pm)), (2, fallback.get(pm))]:
        if not cmd_template:
            continue
        try:
            result = subprocess.run(cmd_template, cwd=repo_path, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                record_node_deps(repo_path, pm, commands)
                return True
            if attempt == 1:
                logger.warning(f"{' '.join(cmd_template)} failed, trying fallback: {result.stderr[:200]}")
        except Exception as e:
            if attempt == 1:
                logger.warning(f"Install exception (attempt {attempt}): {e}")
    logger.error(f"All install attempts failed for {repo_path}")
    return False


def find_test_files(repo_path: str, test_dir: str) -> List[str]:
    search_path = os.path.join(repo_path, test_dir)
    if not os.path.exists(search_path):
        return []
    try:
        result = subprocess.run(
            ["find", search_path, "(", "-name", "*.test.ts", "-o", "-name", "*.test.tsx",
             "-o", "-name", "*.spec.ts", "-o", "-name", "*.spec.tsx",
             "-o", "-name", "*.test.js", "-o", "-name", "*.test.jsx",
             ")", "-not", "-path", "*/node_modules/*"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return sorted(f for f in result.stdout.split("\n") if f)
    except Exception:
        return []


def run_single_vitest_test(repo_path: str, test_file_path: str, cov_dir: str) -> Dict[str, List[int]]:
    import json as _json
    rel_path = os.path.relpath(test_file_path, repo_path)
    test_tmp = os.path.join(cov_dir, os.path.basename(test_file_path).rsplit(".", 1)[0])
    os.makedirs(test_tmp, exist_ok=True)

    try:
        subprocess.run(
            ["npx", "vitest", "run", rel_path,
             "--reporter=verbose",
             "--coverage.enabled",
             "--coverage.provider=v8",
             f"--coverage.reportsDirectory={os.path.relpath(test_tmp, repo_path)}",
             "--coverage.reporter=json",
             "--coverage.clean=true",
             "--coverage.cleanOnRerun=true"],
            cwd=repo_path, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"  Timeout: {rel_path}")
        return {}
    except Exception as e:
        logger.warning(f"  Error: {rel_path}: {e}")
        return {}

    cov_file = os.path.join(test_tmp, "coverage-final.json")
    if not os.path.exists(cov_file):
        return {}

    try:
        with open(cov_file) as f:
            data = _json.load(f)
        from testsquad_core.instrumentation.coverage_parser import CoverageParser
        return CoverageParser.parse_istanbul(data)
    except Exception as e:
        logger.warning(f"  Parse error: {rel_path}: {e}")
        return {}


# --- sharding + file-cap helpers (Story 11.6) ------------------------------- #

_ENV_MAX_FILES = "TIA_TS_MAX_FILES"
_ENV_SHARDS = "TIA_TS_SHARDS"
_ENV_PLUGIN = "TIA_TS_PLUGIN"          # "0" disables the Vitest plugin path
_ENV_PLUGIN_CLI = "TIA_TS_PLUGIN_CLI"  # explicit CLI path override


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _default_shards() -> int:
    """~CPUs capped at 4, mirroring the Python path's ``DEFAULT_SHARDS``."""
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:  # macOS/Windows
        cpus = os.cpu_count() or 1
    return max(1, min(cpus, 4))


def _apply_file_cap(files: List[str], explicit: Optional[int], env_var: str) -> List[str]:
    """Resolve the file cap: explicit argument > env var > no cap (0 = none)."""
    cap = explicit
    if cap is None:
        cap = _env_int(env_var, 0)
    if cap and cap > 0:
        return files[:cap]
    return list(files)


def _shard_files(files: List[str], shards: int) -> List[List[str]]:
    """Round-robin partition ``files`` into at most ``shards`` non-empty lists."""
    if shards <= 1 or len(files) <= 1:
        return [list(files)]
    partitions: List[List[str]] = [[] for _ in range(min(shards, len(files)))]
    for i, f in enumerate(files):
        partitions[i % len(partitions)].append(f)
    return [p for p in partitions if p]


def resolve_vitest_plugin_cli(repo_path: str, config: TypeScriptTestbedConfig) -> Optional[str]:
    """Locate the built plugin CLI for ``config.vitest_plugin`` in the testbed.

    ``TypeScriptTestbedConfig.vitest_plugin`` is the npm package name (scoped
    packages like ``@testsquad/vitest-plugin`` are supported). The plugin is an
    *optional* accelerator: it collects per-test-file Istanbul coverage in one
    invocation. ``TIA_TS_PLUGIN_CLI`` overrides the path (used by tests).
    """
    override = os.environ.get(_ENV_PLUGIN_CLI)
    if override and os.path.exists(override):
        return override
    name = getattr(config, "vitest_plugin", "") or "@testsquad/vitest-plugin"
    parts = [p for p in name.split("/") if p]
    if not parts:
        return None
    for subdir in (("dist", "cli.js"), ("bin", "cli.js")):
        candidate = os.path.join(repo_path, "node_modules", *parts, *subdir)
        if os.path.exists(candidate):
            return candidate
    return None


def run_vitest_plugin(
    repo_path: str,
    config: TypeScriptTestbedConfig,
    cov_dir: str,
    max_files: int = 0,
) -> Optional[Dict]:
    """Invoke the Vitest plugin, returning ``{test_file: {src_file: [lines]}}``.

    Returns ``None`` (never raises) when the CLI is absent or fails, so the caller
    can fall back to the per-file spawn loop. The plugin emits the same Istanbul
    JSON shape the pipeline already consumes.
    """
    cli = resolve_vitest_plugin_cli(repo_path, config)
    if not cli:
        return None
    out_path = os.path.join(repo_path, config.coverage_output)
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass

    args = ["node", cli, "run", repo_path, config.test_dir, cov_dir]
    if max_files and max_files > 0:
        args.append(f"--max={max_files}")
    try:
        result = subprocess.run(
            args, cwd=repo_path, capture_output=True, text=True,
            timeout=_env_int("TIA_TS_TIMEOUT", 1800),
        )
    except Exception as e:
        logger.warning(f"Vitest plugin invocation failed: {e}")
        return None
    if result.returncode != 0 or not os.path.exists(out_path):
        logger.warning(f"Vitest plugin produced no coverage (rc={result.returncode})")
        return None
    try:
        with open(out_path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Vitest plugin output unreadable: {e}")
        return None


def _vitest_completeness(
    repo_path: str,
    test_files: List[str],
    files_to_run: List[str],
    coverage: Dict,
) -> Dict:
    """Coverage-completeness metrics for a Vitest run (Story 11.8).

    The denominator is the whole discovered suite, so a capped run
    (``max_files``/``TIA_TS_MAX_FILES``) reports the shortfall instead of a
    flattering 100%.
    """
    from testsquad_core.instrumentation.completeness import compute_completeness

    return compute_completeness(
        discovered=test_files,
        scheduled=files_to_run,
        covered=list(coverage or {}),
        testbed_path=repo_path,
    )


def run_vitest_with_coverage(
    repo_path: str,
    config: TypeScriptTestbedConfig,
    max_files: Optional[int] = None,
    shards: Optional[int] = None,
) -> Dict:
    """Run Vitest per test file with per-test coverage, sharded across workers.

    Parity with the Python path (Story 11.6):

    - **No cap by default.** ``max_files`` is ``None`` unless a caller passes one;
      ``TIA_TS_MAX_FILES`` (default ``0`` = no cap) bounds it from the environment.
      The previous hard-coded ``10`` silently instrumented only a fraction of the
      suite.
    - **Sharded execution.** Files are partitioned across ``TIA_TS_SHARDS`` workers
      (default: ~CPUs, capped at 4, mirroring ``TIA_INSTRUMENT_SHARDS``) and run in
      parallel threads, each spawning its own Vitest process per file.

    Returns the coverage dict plus ``shards`` and ``shard_assignments`` (the file
    list each worker ran) so callers/tests can observe the distribution.
    """
    logger.info(f"Finding test files in {os.path.join(repo_path, config.test_dir)}...")
    test_files = find_test_files(repo_path, config.test_dir)
    if not test_files:
        return {"error": "No test files found", "output": "", "coverage": {}}

    files_to_run = _apply_file_cap(test_files, max_files, _ENV_MAX_FILES)
    logger.info(
        f"Running {len(files_to_run)}/{len(test_files)} vitest test files with per-test coverage..."
    )

    shard_count = shards if shards is not None else _env_int(_ENV_SHARDS, _default_shards())
    shard_count = max(1, min(shard_count, len(files_to_run)))
    partitions = _shard_files(files_to_run, shard_count)
    if shard_count > 1:
        logger.info(
            "  sharding {} files across {} workers: {}".format(
                len(files_to_run), shard_count,
                ", ".join(f"w{i}={len(p)}" for i, p in enumerate(partitions)),
            )
        )

    cov_dir = os.path.join(repo_path, ".testsquad-cov-tmp")
    os.makedirs(cov_dir, exist_ok=True)

    # Preferred path: the Vitest plugin, when it is installed in the testbed. It
    # returns the same {test_file: {src_file: [lines]}} shape and replaces the
    # per-file spawn loop. Set TIA_TS_PLUGIN=0 to force the per-file path.
    if os.environ.get(_ENV_PLUGIN, "1") != "0":
        plugin_cov = run_vitest_plugin(
            repo_path, config, cov_dir, max_files=len(files_to_run),
        )
        if plugin_cov is not None:
            import shutil
            if os.path.exists(cov_dir):
                shutil.rmtree(cov_dir, ignore_errors=True)
            logger.info(f"Coverage collected via vitest-plugin: {len(plugin_cov)} test files")
            return {
                "success": bool(plugin_cov),
                "output": f"vitest-plugin: {len(plugin_cov)} test files",
                "coverage": plugin_cov,
                "test_count": len(plugin_cov),
                "coverage_completeness": _vitest_completeness(
                    repo_path, test_files, files_to_run, plugin_cov,
                ),
                "shards": 1,
                "shard_assignments": [[os.path.relpath(tf, repo_path) for tf in files_to_run]],
                "engine": "vitest-plugin",
            }

    all_output: List[str] = []
    per_test_coverage: Dict[str, Dict] = {}
    success_count = 0

    def _run_partition(part_idx: int, shard_files: List[str]):
        return [
            (tf, run_single_vitest_test(repo_path, tf, cov_dir))
            for tf in shard_files
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(partitions), shard_count)) as pool:
        futures = [
            pool.submit(_run_partition, i, p) for i, p in enumerate(partitions)
        ]
        for fut in concurrent.futures.as_completed(futures):
            for tf, file_cov in fut.result():
                if file_cov:
                    per_test_coverage[os.path.relpath(tf, repo_path)] = file_cov
                    success_count += 1
                    all_output.append(f"OK  {os.path.relpath(tf, repo_path)}")
                else:
                    all_output.append(f"SKIP  {os.path.relpath(tf, repo_path)}")

    import shutil
    if os.path.exists(cov_dir):
        shutil.rmtree(cov_dir, ignore_errors=True)

    output = "\n".join(all_output)
    logger.info(f"Coverage collected: {success_count}/{len(files_to_run)} test files")
    return {
        "success": success_count > 0,
        "output": output,
        "coverage": per_test_coverage,
        "test_count": len(per_test_coverage),
        "coverage_completeness": _vitest_completeness(
            repo_path, test_files, files_to_run, per_test_coverage,
        ),
        "shards": shard_count,
        "shard_assignments": [[os.path.relpath(tf, repo_path) for tf in p] for p in partitions],
        "engine": "per-file",
    }


def run_typescript_pipeline(
    repo_path: str,
    config: TypeScriptTestbedConfig,
    max_files: Optional[int] = None,
) -> Dict:
    from testsquad_core.instrumentation.coverage_parser import CoverageParser
    from testsquad_core.instrumentation.typescript_symbol_resolver import TypeScriptSymbolResolver, Symbol

    logger.info(f"Installing dependencies for {repo_path}...")
    if not install_dependencies(repo_path, config):
        return {"error": "Dependency installation failed", "mappings": []}

    logger.info(f"Running vitest with per-test coverage (max_files={max_files})...")
    test_result = run_vitest_with_coverage(repo_path, config, max_files=max_files)
    if "error" in test_result and not test_result.get("coverage"):
        return {"error": test_result["error"], "mappings": [], "output": test_result.get("output", "")}

    coverage = test_result.get("coverage", {})
    if not coverage:
        return {"error": "No coverage data produced", "mappings": [], "output": test_result.get("output", "")}

    logger.info(f"Resolving {len(coverage)} tests to symbols...")
    resolver = TypeScriptSymbolResolver()
    mappings = []

    for test_name, file_coverage in coverage.items():
        symbols = []
        for file_key, covered_lines in file_coverage.items():
            abs_path = os.path.join(repo_path, file_key.lstrip("./"))
            if not os.path.exists(abs_path):
                alt = os.path.join(repo_path, file_key)
                if os.path.exists(alt):
                    abs_path = alt
                else:
                    continue

            covered_dict = {abs_path: covered_lines}
            syms = resolver.resolve_symbols(abs_path, covered_dict)
            symbols.extend(syms)

        if symbols:
            mappings.append({
                "test_name": test_name,
                "test_file": test_name.split(" > ")[0] if " > " in test_name else test_name,
                "symbols": [
                    (
                        s.name, s.symbol_type, s.start_line, s.end_line,
                        s.file_path, s.covered_line_count, s.coverage_kind,
                    )
                    for s in symbols
                ],
            })

    logger.info(f"Pipeline complete: {len(mappings)} mappings from {len(coverage)} tests")
    return {
        "mappings": mappings,
        "test_count": len(mappings),
        "symbol_count": len({s[0] for m in mappings for s in m["symbols"]}),
        "coverage_completeness": test_result.get("coverage_completeness"),
        "test_result": test_result,
    }
