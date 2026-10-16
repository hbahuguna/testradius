#!/usr/bin/env python3
"""E7 live three-repo end-to-end validation for the tia-agent.

Drives the *real* ``AnalyzeRunner`` (license gate -> resolve project ->
analyze-pr -> validate -> meter) against a live TestRadius backend and a real
in-process license server, for three projects:

  * ``hbahuguna/py-key-value``  (Python)      -- evidence-derived changed files
  * ``hbahuguna/Test-Radius``   (TS/Playwright) -- evidence-derived changed files
  * ``psf/requests``            (Python)      -- real PR #7502 changed source file

For each repo it asserts:

  1. the analysis returns at least one impacted test, and
  2. every returned test is present in the backend's real evidence
     (i.e. the agent fabricated nothing), and
  3. the evidence-first path was used (no fallback),

and finally that the license server metered exactly one run per repo.

The backend is expected to already have the projects + instrumentation evidence
(the script can build it with ``--instrument``, which is slow). The license
server is started here as a throwaway subprocess with a temporary SQLite DB.

Run with the agent venv::

    .venv/bin/python scripts/e2e_three_repos.py --radius-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
LICENSE_SERVICE_DIR = REPO_ROOT / "services" / "license"
DEFAULT_LICENSE_PYTHON = LICENSE_SERVICE_DIR / ".venv" / "bin" / "python"


class RepoSpec:
    def __init__(
        self,
        repo: str,
        project_name: str,
        pr_number: int,
        *,
        instrument: Dict[str, object],
        changed_files: Optional[List[str]] = None,
        file_filter: Optional[Callable[[str], bool]] = None,
    ):
        self.repo = repo
        self.project_name = project_name
        self.pr_number = pr_number
        self.instrument = instrument
        self.changed_files = changed_files
        self.file_filter = file_filter or (lambda _f: True)


REPOS: List[RepoSpec] = [
    RepoSpec(
        repo="hbahuguna/py-key-value",
        project_name="hbahuguna/py-key-value",
        pr_number=1,
        instrument={"language": "python"},
        file_filter=lambda f: not f.startswith("/testradius/"),
    ),
    RepoSpec(
        repo="hbahuguna/Test-Radius",
        project_name="Test-Radius",
        pr_number=30,
        instrument={"language": "playwright", "local_path": "/testradius"},
        file_filter=lambda f: f.startswith("/testradius/"),
    ),
    RepoSpec(
        repo="psf/requests",
        project_name="psf/requests",
        pr_number=7502,
        instrument={"language": "python", "repo_url": "https://github.com/psf/requests.git"},
        # PR #7502's changed production file (the test file change carries no evidence).
        changed_files=["src/requests/models.py"],
    ),
]


# ---------------------------------------------------------------------------
# license server subprocess
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LicenseServer:
    def __init__(self, python: Path, admin_token: str = "e2e-admin", quota: int = 5):
        self.python = python
        self.admin_token = admin_token
        self.quota = quota
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._tmp = tempfile.mkdtemp(prefix="tia-e2e-license-")
        self.db_path = os.path.join(self._tmp, "license.db")
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        env = dict(os.environ)
        env.update(
            LICENSE_DATABASE_URL=f"sqlite:///{self.db_path}",
            LICENSE_ADMIN_TOKEN=self.admin_token,
            LICENSE_RUNS_PER_PERIOD=str(self.quota),
            LICENSE_GRACE_DAYS="3",
        )
        self.proc = subprocess.Popen(
            [
                str(self.python),
                "-m",
                "uvicorn",
                "license_server.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=str(LICENSE_SERVICE_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                import httpx

                if httpx.get(self.url + "/health", timeout=1.0).status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("license server failed to start")

    def create_license(self) -> str:
        import httpx

        r = httpx.post(
            self.url + "/v1/admin/licenses",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"runs_quota": self.quota},
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()["license_key"]

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def run_rows(self) -> List[Tuple[str, Optional[str]]]:
        """Read metered runs straight from the server's SQLite DB."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT run_id, metadata_json FROM runs").fetchall()
        finally:
            conn.close()
        out: List[Tuple[str, Optional[str]]] = []
        import json

        for run_id, meta in rows:
            repo_hash = None
            if meta:
                try:
                    repo_hash = (json.loads(meta) or {}).get("repo_hash")
                except json.JSONDecodeError:
                    pass
            out.append((run_id, repo_hash))
        return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ensure_project(radius, spec: RepoSpec) -> int:
    """Resolve the project by repo name, creating + enabling it if needed."""
    from tia_agent.tools.project import resolve_project_for_repo
    from tia_agent.errors import AnalysisError

    try:
        return resolve_project_for_repo(radius, spec.repo).id
    except AnalysisError:
        pass

    project = None
    for p in radius.list_projects():
        if p.name.strip("/") == spec.project_name:
            project = p
            break
    if project is None:
        project = radius.create_project(spec.project_name, description="E7 live E2E")
    radius.ensure_feature(project.id, "instrumentation")
    return project.id


def _derive_changed_files(radius, project_id: int, spec: RepoSpec) -> Tuple[List[str], set]:
    mappings = radius.list_test_mappings(project_id, limit=5000)
    if spec.changed_files:
        changed = list(spec.changed_files)
    else:
        changed = sorted({m.product_file for m in mappings if m.product_file and spec.file_filter(m.product_file)})
    expected = {
        (m.test_file, m.test_symbol)
        for m in mappings
        if m.product_file in set(changed)
    }
    return changed, expected


def check_result(
    repo: str,
    returned: set,
    expected: set,
    fallback_used: bool,
    fallback_reason: Optional[str] = None,
) -> List[str]:
    """Return the list of correctness failures for one repo's analysis.

    Pure so it can be unit-tested without a backend: the run is correct when it
    produced tests, every test comes from real evidence, and it did not fall
    back despite having evidence.
    """
    failures: List[str] = []
    if not returned:
        failures.append(f"{repo}: analysis returned no tests")
    fabricated = returned - expected
    if fabricated:
        failures.append(f"{repo}: fabricated tests not in evidence: {sorted(fabricated)[:5]}")
    if fallback_used:
        failures.append(f"{repo}: fell back despite evidence ({fallback_reason})")
    return failures


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius-url", default=os.environ.get("TIA_RADIUS_URL", "http://localhost:8000"))
    parser.add_argument("--quota", type=int, default=5)
    parser.add_argument("--license-python", default=str(DEFAULT_LICENSE_PYTHON))
    parser.add_argument(
        "--instrument",
        action="store_true",
        help="Run backend instrumentation for projects lacking evidence (slow).",
    )
    args = parser.parse_args(argv)

    from tia_agent.analyze import AnalyzeRunner
    from tia_agent.config import TiaConfig
    from tia_agent.license_guard import LicenseGuard
    from tia_agent.radius_client import RadiusClient

    license_python = Path(args.license_python)
    if not license_python.exists():
        print(f"license server python not found: {license_python}", file=sys.stderr)
        return 2

    server = LicenseServer(license_python, quota=args.quota)
    server.start()
    exit_code = 1
    try:
        license_key = server.create_license()

        config_home = tempfile.mkdtemp(prefix="tia-e2e-config-")
        os.environ.update(
            TIA_RADIUS_URL=args.radius_url,
            TIA_RADIUS_TOKEN="",
            TIA_LICENSE_URL=server.url,
            TIA_CONFIG_HOME=config_home,
            TIA_LICENSE_STATE_PATH=os.path.join(config_home, "license.json"),
            TIA_GITHUB_TOKEN="",
        )

        config = TiaConfig.load()
        guard = LicenseGuard(config)
        guard.activate(license_key)
        print(f"license server : {server.url}  (quota={args.quota})")
        print(f"radius backend : {args.radius_url}")
        print()

        runner = AnalyzeRunner.build(config)
        failures: List[str] = []
        results: List[Tuple[str, int, int, bool]] = []

        for spec in REPOS:
            radius = runner.radius
            project_id = _ensure_project(radius, spec)

            mappings = radius.list_test_mappings(project_id, limit=5000)
            if not mappings and args.instrument:
                print(f"[{spec.repo}] no evidence — running instrumentation ({spec.instrument}) ...")
                radius.run_instrumentation(project_id, **spec.instrument)
                mappings = radius.list_test_mappings(project_id, limit=5000)

            if not mappings:
                failures.append(f"{spec.repo}: no evidence for project {project_id}; run with --instrument")
                print(f"[{spec.repo}] FAIL no evidence")
                continue

            changed, expected = _derive_changed_files(radius, project_id, spec)
            if not changed or not expected:
                failures.append(f"{spec.repo}: could not derive changed files/expected tests")
                print(f"[{spec.repo}] FAIL no derivable changed files")
                continue

            result = runner.run(spec.repo, spec.pr_number, file_paths=changed)
            returned = {(t["file"], t["name"]) for t in result.tests}

            repo_failures = check_result(
                spec.repo, returned, expected, result.fallback_used, result.fallback_reason
            )
            failures.extend(repo_failures)

            results.append((spec.repo, len(changed), len(returned), not repo_failures))
            status = "ok" if not repo_failures else "FAIL"
            print(
                f"[{spec.repo}] project={project_id} changed={len(changed)} "
                f"symbols={result.symbols_selected} tests={len(returned)} "
                f"fallback={result.fallback_used} -> {status}"
            )

        server.stop()

        runs = server.run_rows()
        distinct_run_ids = {r[0] for r in runs}
        distinct_hashes = {r[1] for r in runs if r[1]}
        metered_ok = (
            len(runs) == len(REPOS)
            and len(distinct_run_ids) == len(REPOS)
            and len(distinct_hashes) == len(REPOS)
        )
        print()
        print(f"metered runs : {len(runs)} (distinct run_id={len(distinct_run_ids)}, distinct repo_hash={len(distinct_hashes)})")
        if not metered_ok:
            failures.append(
                f"expected exactly {len(REPOS)} metered runs (one per repo), got {len(runs)}"
            )

        print()
        if failures:
            print("E7 FAILED:")
            for f in failures:
                print(f"  - {f}")
        else:
            print("E7 PASSED: all three repos returned correct tests; one meter increment each.")
            exit_code = 0
    finally:
        server.stop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
