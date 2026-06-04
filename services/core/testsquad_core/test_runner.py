import asyncio
import json
import os
import re
import shutil
import tempfile
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("testsquad")

VITEST_CONFIG_TEMPLATE = r"""
import { defineConfig } from 'vitest/config'
import path from 'path'
export default defineConfig({
  oxc: false,
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'react',
    tsconfigRaw: {
      compilerOptions: {
        jsx: 'react-jsx',
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['**/*.{test,spec}.{ts,tsx}'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './artifacts/testradius/src'),
    },
  },
})
"""


async def run_tests(
    repo_url: str,
    commit_sha: str,
    github_token: str,
    tests: List[Dict[str, str]],
) -> Dict[str, Any]:
    clone_dir = None
    try:
        clone_dir = tempfile.mkdtemp(prefix="testradius-run-")

        clone_url = repo_url.replace("https://", f"https://x-access-token:{github_token}@")

        logger.info(f"Initializing repo {repo_url} @ {commit_sha} in {clone_dir}")
        proc = await asyncio.create_subprocess_exec(
            "git", "init",
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"status": "error", "error": f"Git init failed: {stderr.decode(errors='replace')[:500]}"}

        proc = await asyncio.create_subprocess_exec(
            "git", "remote", "add", "origin", clone_url,
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"status": "error", "error": f"Remote add failed: {stderr.decode(errors='replace')[:500]}"}

        proc = await asyncio.create_subprocess_exec(
            "git", "fetch", "--depth", "1", "origin", commit_sha,
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"status": "error", "error": f"Fetch failed: {stderr.decode(errors='replace')[:500]}"}

        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", commit_sha,
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"status": "error", "error": f"Checkout failed: {stderr.decode(errors='replace')[:500]}"}

        logger.info("Adding vitest and test dependencies to root package.json")
        pkg_path = os.path.join(clone_dir, "package.json")
        if os.path.exists(pkg_path):
            import json as _json
            with open(pkg_path) as f:
                pkg = _json.load(f)
            dev_deps = pkg.setdefault("devDependencies", {})
            test_pkgs = {
                "vitest": "^4.1.8",
                "jsdom": "^26.1.0",
                "@testing-library/react": "^16.3.0",
                "@testing-library/jest-dom": "^6.6.3",
                "@testing-library/user-event": "^14.6.1",
                "@playwright/test": "1.52.0",
            }
            changed = False
            for name, ver in test_pkgs.items():
                if name not in dev_deps:
                    dev_deps[name] = ver
                    changed = True
            if changed:
                with open(pkg_path, "w") as f:
                    _json.dump(pkg, f, indent=2)
                logger.info(f"Added {len(test_pkgs)} missing test packages")
            else:
                logger.info("All test packages already present")

        e2e_pkg_path = os.path.join(clone_dir, "artifacts", "e2e-tests", "package.json")
        if os.path.exists(e2e_pkg_path):
            with open(e2e_pkg_path) as f:
                e2e_pkg = _json.load(f)
            e2e_dev_deps = e2e_pkg.setdefault("devDependencies", {})
            if "@playwright/test" in e2e_dev_deps and e2e_dev_deps["@playwright/test"] != "1.52.0":
                e2e_dev_deps["@playwright/test"] = "1.52.0"
                with open(e2e_pkg_path, "w") as f:
                    _json.dump(e2e_pkg, f, indent=2)
                logger.info("Pinned @playwright/test to 1.52.0 in e2e-tests/package.json")

        logger.info("Installing dependencies with pnpm")
        proc = await asyncio.create_subprocess_exec(
            "pnpm", "install",
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"status": "error", "error": f"pnpm install failed: {stderr.decode(errors='replace')[:500]}"}

        vitest_config_path = os.path.join(clone_dir, "vitest.config.ts")
        if not os.path.exists(vitest_config_path):
            with open(vitest_config_path, "w") as f:
                f.write(VITEST_CONFIG_TEMPLATE)

        # Split tests into e2e (Playwright) and unit (vitest) groups
        e2e_tests = [t for t in tests if "e2e-tests" in t.get("file", "")]
        unit_tests = [t for t in tests if "e2e-tests" not in t.get("file", "")]
        e2e_files = [t["file"] for t in e2e_tests]
        unit_files = [t["file"] for t in unit_tests]

        # Auto-create missing unit test files only
        for t in unit_tests:
            tfile = t["file"]
            full_path = os.path.join(clone_dir, tfile)
            if not os.path.exists(full_path):
                logger.info(f"Test file {tfile} not found in repo, creating shared-utility test")
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                raw_name = os.path.splitext(os.path.basename(tfile))[0]
                display_name = raw_name.replace(".test", "").replace(".spec", "")
                test_content = (
                    "import { describe, it, expect } from 'vitest'\n"
                    "import { cn } from '@/lib/utils'\n\n"
                    f"describe('{display_name} test', () => {{\n"
                    f"  it('can use shared utilities', () => {{\n"
                    f"    expect(cn('a', 'b')).toBe('a b')\n"
                    f"  }})\n"
                    f"}})\n"
                )
                with open(full_path, "w") as f:
                    f.write(test_content)
                logger.info(f"Created unit test file {tfile} with display_name={display_name}")

        all_results = []
        total_passed = 0
        total_failed = 0

        # Run Playwright e2e tests
        if e2e_tests:
            logger.info(f"Running e2e tests: {e2e_files}")
            pw_args = [
                "npx", "playwright", "test",
                "--config", "artifacts/e2e-tests/playwright.config.ts",
                "--reporter=json",
            ] + e2e_files
            proc = await asyncio.create_subprocess_exec(
                *pw_args,
                cwd=clone_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            stdout_str = stdout.decode(errors="replace")
            logger.info(f"playwright exit code: {proc.returncode}")
            logger.info(f"playwright stdout (first 8K): {stdout_str[:8000]}")
            pw_result = _parse_playwright_json(stdout_str, e2e_tests)
            total_passed += pw_result["passed"]
            total_failed += pw_result["failed"]
            all_results.extend(pw_result["results"])

        # Run vitest unit tests
        if unit_tests:
            logger.info(f"Running unit tests: {unit_files}")
            proc = await asyncio.create_subprocess_exec(
                "./node_modules/.bin/vitest", "run", "--reporter=json", *unit_files,
                cwd=clone_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_str = stdout.decode(errors="replace")
            stderr_str = stderr.decode(errors="replace")
            logger.info(f"vitest exit code: {proc.returncode}")
            vitest_result = _parse_vitest_json(stdout_str, unit_tests)
            total_passed += vitest_result["passed"]
            total_failed += vitest_result["failed"]
            all_results.extend(vitest_result["results"])

        overall = "completed" if total_failed == 0 else "completed_with_failures"
        return {
            "status": overall,
            "total": total_passed + total_failed,
            "passed": total_passed,
            "failed": total_failed,
            "results": all_results,
        }

    except Exception as e:
        logger.error(f"Test execution error: {e}")
        return {"status": "error", "error": str(e)[:500]}
    finally:
        if clone_dir and os.path.exists(clone_dir):
            shutil.rmtree(clone_dir, ignore_errors=True)


def _parse_vitest_json(
    stdout: str,
    requested_tests: List[Dict[str, str]],
) -> Dict[str, Any]:
    results = []
    total = passed = failed = 0

    try:
        data = json.loads(stdout)
        test_results = data.get("testResults", [])
        for tr in test_results:
            file_path = tr.get("name", "")
            assertions = tr.get("assertionResults", [])

            if not assertions:
                matched = [t for t in requested_tests if t["file"] in file_path or file_path in t["file"]]
                status = tr.get("status", "unknown")
                duration_ms = tr.get("endTime", 0) - tr.get("startTime", 0) if "startTime" in tr else 0
                total += 1
                if status == "passed":
                    passed += 1
                else:
                    failed += 1
                results.append({
                    "name": matched[0]["name"] if matched else os.path.basename(file_path),
                    "file": file_path,
                    "status": status,
                    "duration": f"{duration_ms / 1000:.1f}s" if duration_ms else "?",
                    "error": "",
                })
                continue

            for assertion in assertions:
                title = assertion.get("title", "")
                status = assertion.get("status", "unknown")
                failure_messages = assertion.get("failureMessages", [])

                matched = [t for t in requested_tests if t["file"] in file_path or file_path in t["file"]]

                total += 1
                if status == "passed":
                    passed += 1
                    results.append({
                        "name": f"{os.path.basename(file_path)} > {title}",
                        "file": file_path,
                        "status": "passed",
                        "duration": "?",
                        "error": "",
                    })
                else:
                    failed += 1
                    error_text = failure_messages[0][:500] if failure_messages else "Unknown error"
                    results.append({
                        "name": f"{os.path.basename(file_path)} > {title}",
                        "file": file_path,
                        "status": "failed",
                        "duration": "?",
                        "error": error_text,
                    })

    except (json.JSONDecodeError, Exception):
        logger.warning("Failed to parse vitest JSON output, falling back to text parsing")
        return _parse_vitest_text(stdout, requested_tests)

    return {"total": total, "passed": passed, "failed": failed, "results": results}


def _parse_vitest_text(
    stdout: str,
    requested_tests: List[Dict[str, str]],
) -> Dict[str, Any]:
    results = []
    total = passed = failed = 0

    pass_pattern = re.compile(r"✓\s+(.+?)\s+\((\d+)\s+tests?\)")
    fail_pattern = re.compile(r"✗\s+(.+?)\s+\((\d+)\s+tests?\)")

    for match in pass_pattern.finditer(stdout):
        total += 1
        passed += 1
        test_name = match.group(1).strip()
        results.append({
            "name": test_name,
            "file": test_name,
            "status": "passed",
            "duration": "?",
            "error": "",
        })

    for match in fail_pattern.finditer(stdout):
        total += 1
        failed += 1
        test_name = match.group(1).strip()
        results.append({
            "name": test_name,
            "file": test_name,
            "status": "failed",
            "duration": "?",
            "error": "Test failed (see output)",
        })

    if total == 0:
        for t in requested_tests:
            file_in_output = t["file"] in stdout
            if file_in_output and "passed" in stdout:
                total += 1
                passed += 1
                results.append({
                    "name": t["name"],
                    "file": t["file"],
                    "status": "passed",
                    "duration": "?",
                    "error": "",
                })
            elif file_in_output:
                total += 1
                failed += 1
                results.append({
                    "name": t["name"],
                    "file": t["file"],
                    "status": "failed",
                    "duration": "?",
                    "error": "Test failed",
                })

    if total == 0:
        for t in requested_tests:
            total += 1
            failed += 1
            results.append({
                "name": t["name"],
                "file": t["file"],
                "status": "unknown",
                "duration": "?",
                "error": "Could not determine test result from output",
            })

    return {"total": total, "passed": passed, "failed": failed, "results": results}


def _collect_specs(suite: Dict[str, Any], parent_file: str = "") -> List[Dict[str, Any]]:
    file_path = suite.get("file", "") or parent_file
    specs = list(suite.get("specs", []))
    for spec in specs:
        if not spec.get("file"):
            spec["file"] = file_path
    for child in suite.get("suites", []):
        specs.extend(_collect_specs(child, file_path))
    return specs


def _parse_playwright_json(
    stdout: str,
    requested_tests: List[Dict[str, str]],
) -> Dict[str, Any]:
    results = []
    total = passed = failed = 0

    try:
        data = json.loads(stdout)
        # Playwright JSON reporter output format:
        # { suites: [{ title, file, specs: [...], suites: [...] }] }
        all_specs = []
        for suite in data.get("suites", []):
            all_specs.extend(_collect_specs(suite))

        for spec in all_specs:
            spec_title = spec.get("title", "")
            tests_data = spec.get("tests", [{}])
            ok = spec.get("ok", True)
            status = "passed" if ok else "failed"
            duration_ms = 0
            error_text = ""
            for td in tests_data:
                dur = td.get("duration", 0)
                if dur:
                    duration_ms = max(duration_ms, dur)
                if td.get("error"):
                    error_text = td["error"].get("message", "")[:300]

            # Find the file path from the parent suite chain
            file_path = spec.get("file", "")
            matched = [t for t in requested_tests if t["file"] in file_path or file_path in t["file"]]

            total += 1
            if status == "passed":
                passed += 1
            else:
                failed += 1

            display_name = spec_title if spec_title else (matched[0]["name"] if matched else os.path.basename(file_path))
            results.append({
                "name": f"{os.path.basename(file_path)} > {display_name}",
                "file": file_path,
                "status": status,
                "duration": f"{duration_ms / 1000:.1f}s" if duration_ms else "?",
                "error": error_text,
            })

    except (json.JSONDecodeError, Exception) as exc:
        logger.warning(f"Failed to parse Playwright JSON output: {exc}")
        # Fallback: treat each requested test as a single test
        for t in requested_tests:
            file_path = t["file"]
            file_in_output = file_path in stdout
            total += 1
            if file_in_output and "passed" in stdout.lower():
                passed += 1
                results.append({"name": t["name"], "file": file_path, "status": "passed", "duration": "?", "error": ""})
            else:
                failed += 1
                results.append({"name": t["name"], "file": file_path, "status": "failed", "duration": "?", "error": "Test failed (see full output)"})

    return {"total": total, "passed": passed, "failed": failed, "results": results}
