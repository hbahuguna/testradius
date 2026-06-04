import os
import subprocess
import json
import logging
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
    for attempt, cmd_template in [(1, primary.get(pm)), (2, fallback.get(pm))]:
        if not cmd_template:
            continue
        try:
            result = subprocess.run(cmd_template, cwd=repo_path, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
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


def run_vitest_with_coverage(repo_path: str, config: TypeScriptTestbedConfig, max_files: int = 10) -> Dict:
    logger.info(f"Finding test files in {os.path.join(repo_path, config.test_dir)}...")
    test_files = find_test_files(repo_path, config.test_dir)
    if not test_files:
        return {"error": "No test files found", "output": "", "coverage": {}}

    files_to_run = test_files[:max_files]
    logger.info(f"Running {len(files_to_run)}/{len(test_files)} vitest test files with per-test coverage...")

    cov_dir = os.path.join(repo_path, ".testsquad-cov-tmp")
    os.makedirs(cov_dir, exist_ok=True)

    all_output = []
    per_test_coverage = {}
    success_count = 0

    for i, tf in enumerate(files_to_run):
        rel = os.path.relpath(tf, repo_path)
        logger.info(f"  [{i+1}/{len(files_to_run)}] {rel}")
        file_cov = run_single_vitest_test(repo_path, tf, cov_dir)
        if file_cov:
            per_test_coverage[rel] = file_cov
            success_count += 1
        all_output.append(f"[{i+1}/{len(files_to_run)}] {rel}: {'OK' if file_cov else 'SKIP'}")

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
    }


def run_typescript_pipeline(
    repo_path: str,
    config: TypeScriptTestbedConfig,
    max_files: int = 10,
) -> Dict:
    from testsquad_core.instrumentation.coverage_parser import CoverageParser
    from testsquad_core.instrumentation.typescript_symbol_resolver import TypeScriptSymbolResolver, Symbol

    logger.info(f"Installing dependencies for {repo_path}...")
    if not install_dependencies(repo_path, config):
        return {"error": "Dependency installation failed", "mappings": []}

    logger.info(f"Running vitest with per-test coverage (max {max_files} files)...")
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
                "symbols": [(s.name, s.symbol_type, s.start_line, s.end_line, s.file_path) for s in symbols],
            })

    logger.info(f"Pipeline complete: {len(mappings)} mappings from {len(coverage)} tests")
    return {
        "mappings": mappings,
        "test_count": len(mappings),
        "symbol_count": len({s[0] for m in mappings for s in m["symbols"]}),
        "test_result": test_result,
    }
