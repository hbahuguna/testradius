import os
import subprocess
import json
import logging
import time
import shutil
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PlaywrightTestbedConfig:
    repo_url: str = ""
    branch: str = "main"
    package_manager: str = "pnpm"
    install_command: str = "pnpm install"
    test_command: str = "npx playwright test"
    test_dir: str = "artifacts/e2e-tests"
    source_dir: str = "artifacts/testradius/src"
    dev_server_command: str = "COVERAGE=true pnpm --filter @workspace/testradius run dev"
    dev_server_port: int = 19143
    coverage_raw_dir: str = ".coverage-raw"


PLAYWRIGHT_TESTBEDS = {
    "testradius": PlaywrightTestbedConfig(
        package_manager="pnpm",
        install_command="pnpm install",
        test_command="npx playwright test",
        test_dir="artifacts/e2e-tests",
        source_dir="artifacts/testradius/src",
        dev_server_command="COVERAGE=true pnpm --filter @workspace/testradius run dev",
        dev_server_port=19143,
        coverage_raw_dir=".coverage-raw",
    ),
}


def start_dev_server(repo_path: str, config: PlaywrightTestbedConfig) -> Optional[subprocess.Popen]:
    import urllib.request
    env = os.environ.copy()
    env["COVERAGE"] = "true"
    env["PORT"] = str(config.dev_server_port)
    env["BASE_PATH"] = "/"

    proc = subprocess.Popen(
        config.dev_server_command,
        cwd=repo_path,
        env=env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    server_url = f"http://localhost:{config.dev_server_port}"
    for i in range(60):
        try:
            urllib.request.urlopen(server_url)
            logger.info(f"Dev server ready at {server_url}")
            return proc
        except Exception:
            time.sleep(1)

    logger.error("Dev server failed to start within 60s")
    _, stderr = proc.communicate(timeout=5)
    if stderr:
        for line in stderr.decode().splitlines()[-20:]:
            logger.error(f"Dev server stderr: {line}")
    try:
        proc.kill()
    except Exception:
        pass
    return None


def install_dependencies(repo_path: str, config: PlaywrightTestbedConfig) -> bool:
    commands = [config.install_command.split()]

    # Reused checkout (Story 11.4): skip the install when node_modules is
    # already there and the lockfile/command still match the last install.
    try:
        from .dep_marker import node_deps_ready, record_node_deps
    except ImportError:  # loaded standalone by path (tests)
        from dep_marker import node_deps_ready, record_node_deps
    pm = getattr(config, "package_manager", "")
    if node_deps_ready(repo_path, pm, commands):
        logger.info(f"Reusing installed node dependencies in {repo_path}")
        return True

    try:
        result = subprocess.run(
            commands[0],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            record_node_deps(repo_path, pm, commands)
            return True
        logger.warning(f"Install failed: {result.stderr[:200]}")
        return False
    except Exception as e:
        logger.error(f"Install exception: {e}")
        return False


def find_playwright_test_files(repo_path: str, test_dir: str) -> List[str]:
    search_path = os.path.join(repo_path, test_dir)
    if not os.path.exists(search_path):
        return []
    try:
        result = subprocess.run(
            ["find", search_path, "-name", "*.spec.ts", "-not", "-path", "*/node_modules/*"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return sorted(f for f in result.stdout.split("\n") if f)
    except Exception:
        return []


def run_single_playwright_file(
    repo_path: str,
    test_file_path: str,
    config: PlaywrightTestbedConfig,
) -> Dict[str, List[int]]:
    test_dir = os.path.join(repo_path, config.test_dir)
    raw_cov_dir = os.path.join(test_dir, config.coverage_raw_dir)

    if os.path.exists(raw_cov_dir):
        shutil.rmtree(raw_cov_dir)

    rel_path = os.path.relpath(test_file_path, test_dir)

    try:
        result = subprocess.run(
            ["npx", "playwright", "test", rel_path, "--reporter=list"],
            cwd=test_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning(f"  Test FAILED ({result.returncode}): {rel_path}")
            for line in result.stdout.splitlines()[-10:]:
                logger.warning(f"  PW stdout: {line}")
            for line in result.stderr.splitlines()[-5:]:
                logger.warning(f"  PW stderr: {line}")
    except subprocess.TimeoutExpired:
        logger.warning(f"  Timeout: {rel_path}")
        return {}
    except Exception as e:
        logger.warning(f"  Error: {rel_path}: {e}")
        return {}

    if not os.path.exists(raw_cov_dir):
        logger.warning(f"  No .coverage-raw dir after: {rel_path}")
        return {}

    cov_files = [f for f in os.listdir(raw_cov_dir) if f.endswith(".json")]
    if not cov_files:
        logger.warning(f"  Empty .coverage-raw dir after: {rel_path}")

    from testsquad_core.instrumentation.coverage_parser import CoverageParser

    merged_coverage: Dict[str, List[int]] = {}
    raw_files = sorted(f for f in os.listdir(raw_cov_dir) if f.endswith(".json"))
    for rf in raw_files:
        rf_path = os.path.join(raw_cov_dir, rf)
        try:
            with open(rf_path) as f:
                raw_data = json.load(f)
            parsed = CoverageParser.parse_istanbul(raw_data)
            for file_key, lines in parsed.items():
                if file_key in merged_coverage:
                    merged_coverage[file_key] = sorted(set(merged_coverage[file_key] + lines))
                else:
                    merged_coverage[file_key] = lines
        except Exception as e:
            logger.warning(f"  Parse error {rf}: {e}")

    return merged_coverage


# --- sharding + file-cap helpers (Story 11.6) ------------------------------- #

_PW_ENV_MAX_FILES = "TIA_PW_MAX_FILES"
_PW_ENV_SHARDS = "TIA_PW_SHARDS"


def _pw_env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _pw_apply_file_cap(files: List[str], explicit: Optional[int], env_var: str) -> List[str]:
    """Resolve the file cap: explicit argument > env var > no cap (0 = none)."""
    cap = explicit
    if cap is None:
        cap = _pw_env_int(env_var, 0)
    if cap and cap > 0:
        return files[:cap]
    return list(files)


def _pw_shard_files(files: List[str], shards: int) -> List[List[str]]:
    """Round-robin partition ``files`` into at most ``shards`` non-empty lists."""
    if shards <= 1 or len(files) <= 1:
        return [list(files)]
    partitions: List[List[str]] = [[] for _ in range(min(shards, len(files)))]
    for i, f in enumerate(files):
        partitions[i % len(partitions)].append(f)
    return [p for p in partitions if p]


def run_playwright_coverage(
    repo_path: str,
    config: PlaywrightTestbedConfig,
    max_files: Optional[int] = None,
    shards: Optional[int] = None,
) -> Dict:
    """Run Playwright per test file with per-file coverage, cap lifted (Story 11.6).

    No cap by default (``max_files=None``; env ``TIA_PW_MAX_FILES``, ``0`` = none) —
    the old hard-coded ``10`` only instrumented a fraction of the suite.

    The file list is sharded (``TIA_PW_SHARDS``) but executed **serially**: the
    testbed's browser coverage collector writes to one shared
    ``<test_dir>/.coverage-raw`` directory that it clears per file, so parallel
    workers would clobber each other. Parallel Playwright shards need per-worker
    coverage directories in the testbed (documented follow-up).
    """
    test_dir = os.path.join(repo_path, config.test_dir)
    test_files = find_playwright_test_files(repo_path, config.test_dir)
    if not test_files:
        return {"error": "No test files found", "output": "", "coverage": {}}

    files_to_run = _pw_apply_file_cap(test_files, max_files, _PW_ENV_MAX_FILES)
    logger.info(
        f"Running {len(files_to_run)}/{len(test_files)} Playwright test files with per-file coverage..."
    )

    # Playwright coverage is dumped by the testbed's browser collector into a
    # single, shared ``<test_dir>/.coverage-raw`` directory that is cleared before
    # each file. Running files in parallel threads would clobber each other, so the
    # file list is sharded for bookkeeping but executed **serially**. Parallel
    # Playwright shards require per-worker coverage dirs in the testbed (follow-up).
    shard_count = shards if shards is not None else _pw_env_int(_PW_ENV_SHARDS, 1)
    shard_count = max(1, min(shard_count, len(files_to_run)))
    partitions = _pw_shard_files(files_to_run, shard_count)

    all_output: List[str] = []
    per_file_coverage: Dict[str, Dict] = {}
    success_count = 0

    for shard_idx, shard_files in enumerate(partitions):
        if len(partitions) > 1:
            logger.info(f"  shard {shard_idx + 1}/{len(partitions)} ({len(shard_files)} files)")
        for tf in shard_files:
            rel = os.path.relpath(tf, test_dir)
            file_cov = run_single_playwright_file(repo_path, tf, config)
            if file_cov:
                per_file_coverage[rel] = file_cov
                success_count += 1
                all_output.append(f"OK  {rel}")
            else:
                all_output.append(f"SKIP  {rel}")

    output = "\n".join(all_output)
    logger.info(f"Coverage collected: {success_count}/{len(files_to_run)} test files")
    return {
        "success": success_count > 0,
        "output": output,
        "coverage": per_file_coverage,
        "test_count": len(per_file_coverage),
        "shards": shard_count,
        "shard_assignments": [[os.path.relpath(tf, test_dir) for tf in p] for p in partitions],
    }


def run_playwright_pipeline(
    repo_path: str,
    config: PlaywrightTestbedConfig,
    max_files: Optional[int] = None,
) -> Dict:
    from testsquad_core.instrumentation.typescript_symbol_resolver import TypeScriptSymbolResolver

    logger.info(f"Starting Playwright pipeline for {repo_path}...")

    source_dir = os.path.join(repo_path, config.source_dir)
    if not os.path.exists(source_dir):
        return {"error": f"Source directory not found: {source_dir}", "mappings": []}

    test_dir = os.path.join(repo_path, config.test_dir)
    if not os.path.exists(test_dir):
        return {"error": f"Test directory not found: {test_dir}", "mappings": []}

    logger.info(f"Source: {source_dir}, Tests: {test_dir}")

    vite_config = os.path.join(source_dir, "..", "vite.config.ts")
    vite_config = os.path.normpath(vite_config)
    if os.path.exists(vite_config):
        with open(vite_config) as f:
            content = f.read()
        if 'include: "src/*"' in content:
            content = content.replace('include: "src/*"', 'include: "src/**"')
            with open(vite_config, "w") as f:
                f.write(content)
            logger.info("Patched vite.config.ts Istanbul include: src/* -> src/**")

    logger.info("Starting Vite dev server with Istanbul coverage...")
    dev_proc = start_dev_server(repo_path, config)
    if not dev_proc:
        return {"error": "Dev server failed to start", "mappings": []}

    try:
        test_result = run_playwright_coverage(repo_path, config, max_files=max_files)
        if "error" in test_result and not test_result.get("coverage"):
            return {
                "error": test_result["error"],
                "mappings": [],
                "output": test_result.get("output", ""),
            }

        coverage = test_result.get("coverage", {})
        if not coverage:
            return {
                "error": "No coverage data produced",
                "mappings": [],
                "output": test_result.get("output", ""),
            }

        logger.info(f"Resolving {len(coverage)} test files to symbols...")
        resolver = TypeScriptSymbolResolver()
        mappings = []

        for test_name, file_coverage in coverage.items():
            symbols = []
            for file_key, covered_lines in file_coverage.items():
                abs_path = file_key if os.path.isabs(file_key) else os.path.join(repo_path, file_key.lstrip("./"))
                if not os.path.exists(abs_path):
                    alt = os.path.join(source_dir, os.path.basename(file_key))
                    if os.path.exists(alt):
                        abs_path = alt
                    else:
                        continue

                covered_dict = {abs_path: covered_lines}
                syms = resolver.resolve_symbols(abs_path, covered_dict)
                symbols.extend(syms)

            test_file = os.path.join(config.test_dir, test_name)
            if symbols:
                mappings.append({
                    "test_name": test_name,
                    "test_file": test_file,
                    "symbols": [(s.name, s.symbol_type, s.start_line, s.end_line, s.file_path) for s in symbols],
                })

        logger.info(f"Pipeline complete: {len(mappings)} mappings from {len(coverage)} tests")
        return {
            "mappings": mappings,
            "test_count": len(mappings),
            "symbol_count": len({s[0] for m in mappings for s in m["symbols"]}),
            "test_result": test_result,
        }

    finally:
        if dev_proc:
            dev_proc.terminate()
            try:
                dev_proc.wait(timeout=5)
            except Exception:
                try:
                    dev_proc.kill()
                except Exception:
                    pass

        raw_cov_dir = os.path.join(repo_path, config.test_dir, config.coverage_raw_dir)
        if os.path.exists(raw_cov_dir):
            shutil.rmtree(raw_cov_dir, ignore_errors=True)
