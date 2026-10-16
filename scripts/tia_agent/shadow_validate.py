#!/usr/bin/env python3
"""V1 shadow-validation harness.

Runs TIA test selection and the full test suite on the same commit and asserts
the selected subset is a superset of the tests that actually failed, across a
corpus of at least ``--min-prs`` changes. Emits a coverage-gap report (with
suggested new EVIDENCE edges) and exits non-zero if any failing test was
unselected.

Scope note (board open question #2): V1 runs in our CI corpus, not inside the
product. This harness is stdlib-only so it can be dropped into the core-ml
container next to a checkout whose venv has pytest.

Exit codes:
    0  no failing test was missed (or no failing test was attributable)
    1  at least one attributable failing test was not selected (a MISMATCH)
    2  harness/runtime error (backend unreachable, bad checkout, etc.)
    3  corpus smaller than --min-prs (the "runs on >=10 PRs" AC is not met)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #

EVENT_EDGE_STATUS = "EVIDENCE"


def parse_pytest_failures(text: str) -> List[str]:
    """Extract canonical nodeids of failed tests from pytest output.

    Only ``FAILED `` summary lines count (collection ERRORs are environment
    noise, not regressions, and are deliberately excluded).
    """
    failures: List[str] = []
    seen = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("FAILED "):
            continue
        token = stripped[len("FAILED "):].split(" - ", 1)[0].strip()
        if token and token not in seen:
            seen.add(token)
            failures.append(token)
    return failures


def normalize_path(path: str) -> str:
    path = (path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


@dataclass
class CorpusEntry:
    label: str
    files: List[str]
    sha: Optional[str] = None
    pr_number: Optional[int] = None
    kind: str = "history"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "kind": self.kind,
            "sha": self.sha,
            "pr_number": self.pr_number,
            "files": list(self.files),
        }


@dataclass
class TestEdge:
    test: str
    symbol: str
    symbol_file: str

    def to_dict(self) -> dict:
        return {"test": self.test, "symbol": self.symbol, "symbol_file": self.symbol_file}


def edges_for_test(mapping_rows: Iterable[dict]) -> List[TestEdge]:
    """Keep only EVIDENCE edges for the exact queried test nodeid."""
    edges: List[TestEdge] = []
    for row in mapping_rows:
        if row.get("status") != EVENT_EDGE_STATUS:
            continue
        test = row.get("test_symbol") or ""
        symbol = row.get("product_symbol") or ""
        symbol_file = normalize_path(row.get("product_file") or "")
        if test and symbol:
            edges.append(TestEdge(test=test, symbol=symbol, symbol_file=symbol_file))
    return edges


def attributable_failures(
    failing_tests: Sequence[str],
    entry_files: Sequence[str],
    edges_by_test: Dict[str, List[TestEdge]],
) -> List[str]:
    """Failing tests whose EVIDENCE edge points into one of the entry's files."""
    changed = {normalize_path(f) for f in entry_files}
    result: List[str] = []
    for test in failing_tests:
        for edge in edges_by_test.get(test, []):
            if edge.symbol_file in changed:
                result.append(test)
                break
    return result


def suggested_edges(
    test: str,
    changed_symbols_by_file: Dict[str, List[str]],
    entry_files: Sequence[str],
    limit: int = 3,
) -> List[dict]:
    """Suggest new EVIDENCE edges from ``test`` to symbols in changed files."""
    suggestions: List[dict] = []
    seen = set()
    for path in entry_files:
        norm = normalize_path(path)
        for symbol in changed_symbols_by_file.get(norm, []):
            key = (test, symbol)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({"test": test, "symbol": symbol, "symbol_file": norm})
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def evaluate_entry(
    entry: CorpusEntry,
    selected_tests: Sequence[str],
    failing_tests: Sequence[str],
    edges_by_test: Dict[str, List[TestEdge]],
    changed_symbols_by_file: Dict[str, List[str]],
) -> dict:
    selected = set(selected_tests)
    attributable = attributable_failures(failing_tests, entry.files, edges_by_test)
    missed = [t for t in attributable if t not in selected]
    unselected = [t for t in failing_tests if t not in selected]
    gaps = []
    for test in unselected:
        gaps.append(
            {
                "test": test,
                "attributable": test in attributable,
                "suggested_edges": suggested_edges(test, changed_symbols_by_file, entry.files),
            }
        )
    return {
        "label": entry.label,
        "kind": entry.kind,
        "sha": entry.sha,
        "pr_number": entry.pr_number,
        "files": list(entry.files),
        "selected_test_count": len(selected),
        "attributable_failures": attributable,
        "missed": missed,
        "unselected_failures": unselected,
        "gaps": gaps,
    }


def summarize(entry_reports: Sequence[dict], failing_tests: Sequence[str]) -> dict:
    attributable_total = sum(len(e["attributable_failures"]) for e in entry_reports)
    missed_total = sum(len(e["missed"]) for e in entry_reports)
    gaps_total = sum(len(e["gaps"]) for e in entry_reports)
    coverage = None
    if attributable_total:
        coverage = round(1.0 - (missed_total / attributable_total), 4)
    return {
        "entries_run": len(entry_reports),
        "failing_tests_total": len(failing_tests),
        "attributable_total": attributable_total,
        "missed_total": missed_total,
        "gaps_total": gaps_total,
        "coverage": coverage,
    }


def resolve_exit_code(summary: dict, corpus_size: int, min_prs: int) -> int:
    if corpus_size < min_prs:
        return 3
    if summary.get("missed_total", 0) > 0:
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Corpus discovery
# --------------------------------------------------------------------------- #


def discover_history_corpus(
    checkout: str,
    product_dir: str = "src/",
    max_entries: int = 12,
) -> List[CorpusEntry]:
    """Each non-merge commit that touches product_dir becomes a synthetic PR."""
    log = subprocess.run(
        [
            "git",
            "-C",
            checkout,
            "log",
            "--no-merges",
            "--format=@@@%H\x1f%s",
            "--name-only",
            "--",
            product_dir,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    entries: List[CorpusEntry] = []
    current: Optional[CorpusEntry] = None
    for raw in log.splitlines():
        line = raw.strip()
        if line.startswith("@@@"):
            if current is not None and current.files:
                entries.append(current)
                if len(entries) >= max_entries:
                    break
            sha, _, subject = line[3:].partition("\x1f")
            current = CorpusEntry(
                label=f"{sha[:8]} {subject}".strip(),
                sha=sha,
                files=[],
                kind="history",
            )
        elif line and current is not None:
            current.files.append(normalize_path(line))
    if current is not None and current.files and len(entries) < max_entries:
        entries.append(current)
    entries = entries[:max_entries]
    for index, entry in enumerate(entries):
        if entry.pr_number is None:
            entry.pr_number = 1000 + index
    return entries


def discover_file_corpus(path: str) -> List[CorpusEntry]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    entries: List[CorpusEntry] = []
    for i, item in enumerate(data):
        files = item.get("files") or []
        entries.append(
            CorpusEntry(
                label=item.get("label") or f"entry-{i}",
                files=[normalize_path(f) for f in files],
                sha=item.get("sha"),
                pr_number=item.get("pr_number") or (1000 + i),
                kind=item.get("kind", "file"),
            )
        )
    return entries


def discover_github_corpus(
    full_name: str,
    token: Optional[str],
    max_entries: int = 12,
) -> List[CorpusEntry]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base = f"https://api.github.com/repos/{full_name}"
    prs = _http_get_json(f"{base}/pulls?state=closed&per_page=100", headers)
    entries: List[CorpusEntry] = []
    for pr in prs:
        if not pr.get("merged_at"):
            continue
        number = pr["number"]
        files = _http_get_json(f"{base}/pulls/{number}/files?per_page=300", headers)
        entries.append(
            CorpusEntry(
                label=f"PR #{number} {pr.get('title', '')}".strip(),
                files=[normalize_path(f["filename"]) for f in files],
                sha=(pr.get("merge_commit_sha") or "")[:40] or None,
                pr_number=number,
                kind="github",
            )
        )
        if len(entries) >= max_entries:
            break
    return entries


# --------------------------------------------------------------------------- #
# Full suite + backend
# --------------------------------------------------------------------------- #


def run_full_suite(
    checkout: str,
    venv_python: str,
    test_dir: str = "tests/",
    timeout: int = 1800,
) -> dict:
    cmd = [
        venv_python,
        "-m",
        "pytest",
        test_dir,
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:xdist",
        "-o",
        "addopts=",
        "--continue-on-collection-errors",
        "--tb=no",
        "-rf",
    ]
    started = time.time()
    proc = subprocess.run(
        cmd, cwd=checkout, capture_output=True, text=True, timeout=timeout
    )
    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return {
        "failures": parse_pytest_failures(raw),
        "exit_code": proc.returncode,
        "duration_s": round(time.time() - started, 2),
        "command": " ".join(cmd),
    }


class Backend:
    """Interface: selection + graph edge lookups."""

    def select_tests(self, entry: CorpusEntry, anchor: str) -> dict:  # pragma: no cover
        raise NotImplementedError

    def edges_for_test(self, nodeid: str, limit: int = 1000) -> List[TestEdge]:  # pragma: no cover
        raise NotImplementedError

    def symbols_in_file(self, path: str, limit: int = 500) -> List[str]:  # pragma: no cover
        raise NotImplementedError


class HttpBackend(Backend):
    def __init__(
        self,
        base_url: str,
        token: str,
        project_id: int,
        full_name: str,
        max_symbols: int = 0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.project_id = project_id
        self.full_name = full_name
        self.max_symbols = max_symbols

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _get(self, url: str) -> object:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            raise RuntimeError(f"GET {url} failed: {exc.code} {exc.read()[:300]!r}") from exc

    def _post(self, url: str, payload: dict) -> object:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            raise RuntimeError(f"POST {url} failed: {exc.code} {exc.read()[:300]!r}") from exc

    def select_tests(self, entry: CorpusEntry, anchor: str) -> dict:
        pr_number = entry.pr_number
        if not pr_number:
            pr_number = 1000 + (int(entry.sha or "0", 16) % 900000)
        payload = {
            "full_name": self.full_name,
            "pr_number": pr_number,
            "commit_sha": anchor,
            "file_paths": list(entry.files),
            "max_symbols": self.max_symbols,
        }
        url = f"{self.base_url}/projects/{self.project_id}/analyze-pr"
        resp = self._post(url, payload)
        selected: List[str] = []
        seen = set()
        for result in resp.get("results", []):
            for test in result.get("existing_tests", []):
                nodeid = test.get("test_name") or ""
                if nodeid and nodeid not in seen:
                    seen.add(nodeid)
                    selected.append(nodeid)
        return {
            "selected_tests": selected,
            "symbols_selected": resp.get("symbols_selected"),
            "symbols_total": resp.get("symbols_total"),
            "truncated": resp.get("truncated"),
            "truncation_dropped_tests": resp.get("truncation_dropped_tests"),
            "stale_evidence": resp.get("stale_evidence"),
            "evidence_built_at_sha": resp.get("evidence_built_at_sha"),
        }

    def edges_for_test(self, nodeid: str, limit: int = 1000) -> List[TestEdge]:
        query = urllib.parse.quote(nodeid)
        url = (
            f"{self.base_url}/projects/{self.project_id}/test-mapping"
            f"?limit={limit}&query={query}"
        )
        rows = self._get(url)
        return [e for e in edges_for_test(rows) if e.test == nodeid]

    def symbols_in_file(self, path: str, limit: int = 500) -> List[str]:
        query = urllib.parse.quote(path)
        url = (
            f"{self.base_url}/projects/{self.project_id}/test-mapping"
            f"?limit={limit}&query={query}"
        )
        rows = self._get(url)
        norm = normalize_path(path)
        symbols: List[str] = []
        seen = set()
        for row in rows:
            if normalize_path(row.get("product_file") or "") != norm:
                continue
            symbol = row.get("product_symbol") or ""
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        return symbols


class SelfTestBackend(Backend):
    """Wraps a backend and forces one attributable failing test to be missed.

    It finds the first failing test that has a real EVIDENCE edge, then reports
    an empty selection for any entry whose files include that edge's symbol
    file. Deterministically proves the harness exits non-zero on a miss.
    """

    def __init__(self, inner: Backend, failing_tests: Sequence[str]):
        self.inner = inner
        self.failing_tests = list(failing_tests)
        self.marker_file: Optional[str] = None
        self.marker_test: Optional[str] = None
        self._find_marker()

    def _find_marker(self) -> None:
        for test in self.failing_tests:
            edges = self.inner.edges_for_test(test)
            if edges:
                self.marker_test = test
                self.marker_file = edges[0].symbol_file
                return

    def select_tests(self, entry: CorpusEntry, anchor: str) -> dict:
        result = self.inner.select_tests(entry, anchor)
        if self.marker_file and self.marker_file in {normalize_path(f) for f in entry.files}:
            result = dict(result)
            result["selected_tests"] = []
            result["_selftest_sabotaged"] = True
        return result

    def edges_for_test(self, nodeid: str, limit: int = 1000) -> List[TestEdge]:
        return self.inner.edges_for_test(nodeid, limit)

    def symbols_in_file(self, path: str, limit: int = 500) -> List[str]:
        return self.inner.symbols_in_file(path, limit)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _http_get_json(url: str, headers: dict) -> object:  # pragma: no cover - network
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_shadow(
    entries: Sequence[CorpusEntry],
    failing_tests: Sequence[str],
    backend: Backend,
    anchor: str,
    full_suite: Optional[dict] = None,
    corpus_source: str = "history",
) -> dict:
    edges_by_test: Dict[str, List[TestEdge]] = {}
    for test in failing_tests:
        edges_by_test[test] = backend.edges_for_test(test)

    symbol_cache: Dict[str, List[str]] = {}

    def cached_symbols(path: str) -> List[str]:
        norm = normalize_path(path)
        if norm not in symbol_cache:
            try:
                symbol_cache[norm] = backend.symbols_in_file(norm)
            except Exception:
                symbol_cache[norm] = []
        return symbol_cache[norm]

    entry_reports = []
    for entry in entries:
        selection = backend.select_tests(entry, anchor)
        changed_symbols_by_file = {normalize_path(f): cached_symbols(f) for f in entry.files}
        report = evaluate_entry(
            entry,
            selection.get("selected_tests", []),
            failing_tests,
            edges_by_test,
            changed_symbols_by_file,
        )
        report.update(
            {
                "symbols_selected": selection.get("symbols_selected"),
                "truncated": selection.get("truncated"),
                "truncation_dropped_tests": selection.get("truncation_dropped_tests"),
                "stale_evidence": selection.get("stale_evidence"),
                "evidence_built_at_sha": selection.get("evidence_built_at_sha"),
            }
        )
        entry_reports.append(report)

    return {
        "anchor_sha": anchor,
        "corpus_source": corpus_source,
        "corpus_size": len(entries),
        "full_suite": full_suite or {"failures": list(failing_tests)},
        "entries": entry_reports,
        "summary": summarize(entry_reports, failing_tests),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="V1 TIA shadow-validation harness")
    parser.add_argument("--checkout", required=True, help="path to the testbed checkout")
    parser.add_argument("--venv-python", default=".venv/bin/python", help="testbed python with pytest")
    parser.add_argument("--test-dir", default="tests/")
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--token", default=os.environ.get("TIA_TOKEN", "dev-admin-token"))
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--full-name", default="hbahuguna/py-key-value")
    parser.add_argument("--anchor-sha", default=None, help="analyzed/evidence commit (default: git HEAD)")
    parser.add_argument("--commit-sha", default=None, help="alias for --anchor-sha")
    parser.add_argument("--corpus", choices=["history", "github", "file"], default="history")
    parser.add_argument("--corpus-file", default=None)
    parser.add_argument("--product-dir", default="src/")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--max-prs", type=int, default=12)
    parser.add_argument("--min-prs", type=int, default=10)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = unlimited selection")
    parser.add_argument("--skip-full-suite", action="store_true")
    parser.add_argument("--report", default=None, help="write JSON report to this path")
    parser.add_argument("--self-test", action="store_true", help="inject a miss and assert exit 1")
    args = parser.parse_args(argv)

    def emit(exit_code: int, report: Optional[dict] = None, message: str = "") -> int:
        if report is not None:
            summary = report.get("summary", {})
            print("=" * 72)
            print(f"V1 shadow validation — {report.get('corpus_source')} corpus")
            print(f"  anchor:      {report.get('anchor_sha')}")
            print(f"  entries:     {summary.get('entries_run')}")
            print(f"  failing:     {summary.get('failing_tests_total')}")
            print(f"  attributable:{' ' + str(summary.get('attributable_total'))}")
            print(f"  missed:      {summary.get('missed_total')}")
            print(f"  coverage:    {summary.get('coverage')}")
            print(f"  gaps:        {summary.get('gaps_total')}")
            print(f"  exit:        {exit_code}")
            print("=" * 72)
            if args.report:
                with open(args.report, "w", encoding="utf-8") as fh:
                    json.dump(report, fh, indent=2)
                print(f"report written to {args.report}")
        if message:
            print(message)
        return exit_code

    anchor = args.anchor_sha or args.commit_sha

    if args.corpus == "history":
        entries = discover_history_corpus(args.checkout, args.product_dir, args.max_prs)
    elif args.corpus == "file":
        if not args.corpus_file:
            return emit(2, message="--corpus-file is required for --corpus file")
        entries = discover_file_corpus(args.corpus_file)
    else:
        entries = discover_github_corpus(args.full_name, args.github_token, args.max_prs)

    if len(entries) < args.min_prs:
        return emit(
            3,
            message=(
                f"corpus has {len(entries)} entries but --min-prs is {args.min_prs}; "
                "the '>=10 changes' acceptance criterion is not met"
            ),
        )

    if not anchor:
        try:
            anchor = subprocess.run(
                ["git", "-C", args.checkout, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            anchor = "HEAD"

    full_suite = None
    if not args.skip_full_suite:
        venv_python = args.venv_python
        if not os.path.isabs(venv_python):
            venv_python = os.path.join(args.checkout, venv_python)
        full_suite = run_full_suite(args.checkout, venv_python, args.test_dir)
        print(f"[suite] {len(full_suite['failures'])} failing test(s): {full_suite['failures']}")
    failing_tests = (full_suite or {}).get("failures", [])

    backend: Backend = HttpBackend(
        args.backend, args.token, args.project_id, args.full_name, args.max_symbols
    )
    if args.self_test:
        backend = SelfTestBackend(backend, failing_tests)
        if not backend.marker_file:
            return emit(2, message="self-test skipped: no failing test had an EVIDENCE edge")

    report = run_shadow(
        entries,
        failing_tests,
        backend,
        anchor,
        full_suite=full_suite,
        corpus_source=args.corpus,
    )
    code = resolve_exit_code(report["summary"], len(entries), args.min_prs)
    report["exit_code"] = code

    if args.self_test:
        if code != 1:
            return emit(2, report, "SELF-TEST FAILED: expected exit 1 when a failing test is unselected")
        report["self_test"] = {"injected_miss_test": backend.marker_test, "marker_file": backend.marker_file}
        print(f"SELF-TEST OK: injected miss on {backend.marker_test} -> exit 1")
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
            print(f"report written to {args.report}")
        return 1
    return emit(code, report)


if __name__ == "__main__":
    sys.exit(main())
