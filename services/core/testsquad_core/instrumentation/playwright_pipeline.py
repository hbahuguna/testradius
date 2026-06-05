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
    try:
        result = subprocess.run(
            config.install_command.split(),
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
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


def run_playwright_coverage(
    repo_path: str,
    config: PlaywrightTestbedConfig,
    max_files: int = 10,
) -> Dict:
    test_dir = os.path.join(repo_path, config.test_dir)
    test_files = find_playwright_test_files(repo_path, config.test_dir)
    if not test_files:
        return {"error": "No test files found", "output": "", "coverage": {}}

    files_to_run = test_files[:max_files]
    logger.info(f"Running {len(files_to_run)}/{len(test_files)} Playwright test files with per-file coverage...")

    all_output = []
    per_file_coverage = {}
    success_count = 0

    for i, tf in enumerate(files_to_run):
        rel = os.path.relpath(tf, test_dir)
        logger.info(f"  [{i+1}/{len(files_to_run)}] {rel}")
        file_cov = run_single_playwright_file(repo_path, tf, config)
        if file_cov:
            per_file_coverage[rel] = file_cov
            success_count += 1
        all_output.append(f"[{i+1}/{len(files_to_run)}] {rel}: {'OK' if file_cov else 'SKIP'}")

    output = "\n".join(all_output)
    logger.info(f"Coverage collected: {success_count}/{len(files_to_run)} test files")
    return {
        "success": success_count > 0,
        "output": output,
        "coverage": per_file_coverage,
        "test_count": len(per_file_coverage),
    }


def run_playwright_pipeline(
    repo_path: str,
    config: PlaywrightTestbedConfig,
    max_files: int = 10,
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
