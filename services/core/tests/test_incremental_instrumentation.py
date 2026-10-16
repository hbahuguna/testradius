"""Story 11.5 — incremental instrumentation planning.

The planner is pure: given the prior evidence graph (source file -> test files
that cover it) and the changed-file set between the prior anchor and the current
checkout, it decides which tests must be re-run and which evidence is carried
forward. Bugs here silently under-run a suite, so the cases are exhaustive.
"""
import os
import subprocess

import pytest


# --------------------------------------------------------------------------
# planner
# --------------------------------------------------------------------------

class TestPlanIncrementalRun:
    CURRENT = "a" * 40
    ANCHOR = "b" * 40

    def _plan(self, **overrides):
        from testsquad_core.instrumentation.incremental import plan_incremental_run

        kwargs = dict(
            anchor_sha=self.ANCHOR,
            current_sha=self.CURRENT,
            changed_files=["src/core.py"],
            universe=["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"],
            coverage_index={
                "src/core.py": ["tests/test_a.py"],
                "src/util.py": ["tests/test_b.py", "tests/test_c.py"],
            },
        )
        kwargs.update(overrides)
        return plan_incremental_run(**kwargs)

    def test_one_file_diff_runs_only_tests_covering_it(self):
        plan = self._plan()

        assert plan.is_incremental
        assert plan.tests_to_run == ["tests/test_a.py"]
        assert plan.carried_forward == ["tests/test_b.py", "tests/test_c.py"]
        assert plan.changed_source_files == ["src/core.py"]
        assert plan.changed_test_files == []

    def test_changed_test_file_is_always_run(self):
        plan = self._plan(changed_files=["tests/test_c.py"])

        assert plan.is_incremental
        assert plan.tests_to_run == ["tests/test_c.py"]
        assert plan.changed_test_files == ["tests/test_c.py"]
        assert plan.carried_forward == ["tests/test_a.py", "tests/test_b.py"]

    def test_changed_test_file_not_in_universe_is_treated_as_removed(self):
        plan = self._plan(
            changed_files=["tests/test_gone.py"],
            coverage_index={
                "src/core.py": ["tests/test_a.py"],
                "src/util.py": ["tests/test_gone.py"],
            },
        )

        assert plan.is_incremental
        assert plan.removed_test_files == ["tests/test_gone.py"]
        assert plan.tests_to_run == []
        assert plan.tests_to_drop == ["tests/test_gone.py"]

    def test_source_and_test_changes_are_unioned(self):
        plan = self._plan(changed_files=["src/core.py", "tests/test_b.py"])

        assert plan.tests_to_run == ["tests/test_a.py", "tests/test_b.py"]
        assert plan.carried_forward == ["tests/test_c.py"]

    def test_empty_diff_carries_everything_forward(self):
        plan = self._plan(changed_files=[])

        assert plan.is_incremental
        assert plan.tests_to_run == []
        assert plan.carried_forward == [
            "tests/test_a.py", "tests/test_b.py", "tests/test_c.py",
        ]
        assert plan.reason == "no_changes"

    def test_unknown_changed_source_file_runs_nothing_extra(self):
        plan = self._plan(changed_files=["src/brand_new.py"])

        assert plan.is_incremental
        assert plan.tests_to_run == []

    def test_no_prior_evidence_falls_back_to_full(self):
        plan = self._plan(coverage_index={})

        assert plan.mode == "full"
        assert plan.reason == "no_prior_evidence"
        assert plan.tests_to_run == []

    def test_missing_anchor_falls_back_to_full(self):
        plan = self._plan(anchor_sha=None)

        assert plan.mode == "full"
        assert plan.reason == "no_anchor"

    def test_missing_current_sha_falls_back_to_full(self):
        plan = self._plan(current_sha=None)

        assert plan.mode == "full"
        assert plan.reason == "no_current_sha"

    def test_unavailable_diff_falls_back_to_full(self):
        plan = self._plan(changed_files=None)

        assert plan.mode == "full"
        assert plan.reason == "diff_unavailable"

    def test_large_diff_falls_back_to_full(self):
        plan = self._plan(
            changed_files=["src/core.py", "src/util.py", "src/other.py"],
            coverage_index={
                "src/core.py": ["tests/test_a.py"],
                "src/util.py": ["tests/test_b.py"],
                "src/other.py": ["tests/test_c.py"],
                "src/stays.py": ["tests/test_c.py"],
            },
            fallback_fraction=0.5,
        )

        assert plan.mode == "full"
        assert plan.reason == "large_diff"

    def test_small_diff_within_fraction_stays_incremental(self):
        plan = self._plan(
            changed_files=["src/core.py"],
            coverage_index={
                "src/core.py": ["tests/test_a.py"],
                "src/util.py": ["tests/test_b.py"],
                "src/other.py": ["tests/test_c.py"],
                "src/stays.py": ["tests/test_c.py"],
            },
            fallback_fraction=0.5,
        )

        assert plan.is_incremental

    def test_fallback_fraction_is_configurable(self):
        # 1 of 2 known files = 0.5, which is NOT > 0.5 ...
        strict = self._plan(
            changed_files=["src/core.py"],
            coverage_index={"src/core.py": ["tests/test_a.py"], "src/util.py": ["tests/test_b.py"]},
            fallback_fraction=0.5,
        )
        assert strict.is_incremental

        # ... but is > 0.25.
        loose = self._plan(
            changed_files=["src/core.py"],
            coverage_index={"src/core.py": ["tests/test_a.py"], "src/util.py": ["tests/test_b.py"]},
            fallback_fraction=0.25,
        )
        assert loose.mode == "full"
        assert loose.reason == "large_diff"

    def test_fallback_fraction_read_from_env(self, monkeypatch):
        monkeypatch.setenv("TIA_INCREMENTAL_MAX_CHANGED_FRACTION", "0.25")
        plan = self._plan(
            changed_files=["src/core.py"],
            coverage_index={"src/core.py": ["tests/test_a.py"], "src/util.py": ["tests/test_b.py"]},
            fallback_fraction=None,
        )
        assert plan.mode == "full"

    def test_results_are_sorted_and_deduplicated(self):
        plan = self._plan(
            changed_files=["src/core.py", "src/util.py"],
            universe=["tests/test_b.py", "tests/test_a.py"],
            coverage_index={
                "src/core.py": ["tests/test_b.py", "tests/test_a.py", "tests/test_b.py"],
                "src/util.py": ["tests/test_b.py"],
                "src/stays.py": ["tests/test_b.py"],
            },
            fallback_fraction=1.0,
        )
        assert plan.tests_to_run == ["tests/test_a.py", "tests/test_b.py"]

    def test_no_prior_evidence_takes_precedence_over_missing_anchor(self):
        plan = self._plan(anchor_sha=None, coverage_index={})
        assert plan.mode == "full"
        assert plan.reason == "no_prior_evidence"


class TestNormalizePath:
    def test_relative_path_is_left_alone(self):
        from testsquad_core.instrumentation.incremental import normalize_path
        assert normalize_path("src/core.py") == "src/core.py"

    def test_absolute_path_under_root_becomes_relative(self):
        from testsquad_core.instrumentation.incremental import normalize_path
        assert normalize_path("/tmp/tb/src/core.py", "/tmp/tb") == "src/core.py"

    def test_leading_dot_slash_is_stripped(self):
        from testsquad_core.instrumentation.incremental import normalize_path
        assert normalize_path("./src/core.py") == "src/core.py"

    def test_backslashes_normalized(self):
        from testsquad_core.instrumentation.incremental import normalize_path
        assert normalize_path("src\\core.py") == "src/core.py"

    def test_absolute_path_outside_root_is_kept(self):
        from testsquad_core.instrumentation.incremental import normalize_path
        assert normalize_path("/other/src/core.py", "/tmp/tb") == "/other/src/core.py"


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------

def _init_repo(path):
    """Create a git repo at ``path`` with one commit on branch ``main``."""
    import git

    os.makedirs(path, exist_ok=True)
    repo = git.Repo.init(path)
    repo.git.checkout("-b", "main")
    with open(os.path.join(path, "core.py"), "w") as fh:
        fh.write("x = 1\n")
    os.makedirs(os.path.join(path, "tests"), exist_ok=True)
    with open(os.path.join(path, "tests", "test_core.py"), "w") as fh:
        fh.write("def test_x():\n    assert True\n")
    repo.index.add(["core.py", "tests/test_core.py"])
    repo.index.commit("init")
    return repo


def _commit(repo, name, content):
    path = os.path.join(repo.working_tree_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    repo.index.add([name])
    return repo.index.commit(f"change {name}")


class TestChangedFilesBetween:
    def test_reports_file_changed_between_two_commits(self, tmp_path):
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        first = repo.head.commit.hexsha
        _commit(repo, "core.py", "x = 2\n")

        changed = changed_files_between(repo.working_tree_dir, first, "HEAD")

        assert changed == ["core.py"]

    def test_includes_uncommitted_working_tree_edit(self, tmp_path):
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        first = repo.head.commit.hexsha
        with open(os.path.join(repo.working_tree_dir, "core.py"), "w") as fh:
            fh.write("x = 99\n")

        changed = changed_files_between(repo.working_tree_dir, first)

        assert changed == ["core.py"]

    def test_includes_untracked_new_file(self, tmp_path):
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        first = repo.head.commit.hexsha
        with open(os.path.join(repo.working_tree_dir, "brand_new.py"), "w") as fh:
            fh.write("y = 1\n")

        changed = changed_files_between(repo.working_tree_dir, first)

        assert "brand_new.py" in changed

    def test_identical_commits_produce_empty_change_set(self, tmp_path):
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        head = repo.head.commit.hexsha

        assert changed_files_between(repo.working_tree_dir, head, "HEAD") == []

    def test_unknown_anchor_returns_none(self, tmp_path):
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        assert changed_files_between(repo.working_tree_dir, "0" * 40, "HEAD") is None

    def test_ignores_run_artifacts_left_in_the_checkout(self, tmp_path):
        """Artifacts the run itself writes must not count as source changes.

        Story 11.4 leaves a dependency-install marker in the checkout, and the
        coverage run leaves coverage databases, ``coverage.json`` and
        ``.pytest_cache``. All of them are untracked, so the untracked sweep
        would report them as changed source files. That both pollutes the
        recorded change set and inflates the changed fraction enough to trip
        the large-diff guard, silently turning every incremental run into a
        full-suite run.
        """
        from testsquad_core.instrumentation.incremental import changed_files_between

        repo = _init_repo(str(tmp_path / "repo"))
        first = repo.head.commit.hexsha
        root = repo.working_tree_dir

        for name in (
            ".tia-deps-installed",
            ".coverage",
            ".coverage.shard0",
            ".coverage.shard1",
            "coverage.json",
        ):
            with open(os.path.join(root, name), "w") as fh:
                fh.write("{}")
        os.makedirs(os.path.join(root, ".pytest_cache"), exist_ok=True)
        with open(os.path.join(root, ".pytest_cache", "CACHEDIR.TAG"), "w") as fh:
            fh.write("Signature\n")
        # A genuine new source file alongside them must still be reported.
        with open(os.path.join(root, "brand_new.py"), "w") as fh:
            fh.write("y = 1\n")

        changed = changed_files_between(root, first)

        assert changed == ["brand_new.py"]

    def test_shallow_clone_can_still_diff_the_anchor(self, tmp_path):
        """A depth=1 clone has no history: the anchor must be fetched in."""
        from testsquad_core.instrumentation.incremental import (
            ensure_commit, changed_files_between,
        )
        import git

        origin = _init_repo(str(tmp_path / "origin"))
        anchor = origin.head.commit.hexsha
        _commit(origin, "core.py", "x = 3\n")

        clone_dir = str(tmp_path / "clone")
        # A local-path clone ignores ``depth``; a file:// URL forces a real
        # shallow transfer, which is how the pipeline clones.
        git.Repo.clone_from(
            "file://" + origin.working_tree_dir, clone_dir, branch="main", depth=1,
        )

        # The anchor commit is not in the shallow clone...
        clone = git.Repo(clone_dir)
        with pytest.raises(Exception):
            clone.commit(anchor)

        # ...but ensure_commit fetches it, after which the diff is available.
        assert ensure_commit(clone_dir, anchor) is True
        changed = changed_files_between(clone_dir, anchor, "HEAD")
        assert changed == ["core.py"]


# --------------------------------------------------------------------------
# Neo4j store: prior-evidence read + incremental write
# --------------------------------------------------------------------------

class TestGetCoverageSummary:
    def test_returns_anchor_and_edge_rows(self):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.query.side_effect = [
            [{"shas": ["c" * 40]}],
            [
                {"test_name": "tests/test_a.py::test_x", "test_file": "tests/test_a.py", "source_file": "src/core.py"},
                {"test_name": "tests/test_b.py::test_y", "test_file": "tests/test_b.py", "source_file": "src/util.py"},
            ],
        ]
        store = Neo4jStore(neo4j_client=client)

        summary = store.get_coverage_summary(7)

        assert summary["anchor_sha"] == "c" * 40
        assert summary["tests"] == [
            {"name": "tests/test_a.py::test_x", "file": "tests/test_a.py", "source_file": "src/core.py"},
            {"name": "tests/test_b.py::test_y", "file": "tests/test_b.py", "source_file": "src/util.py"},
        ]

    def test_mixed_shas_yield_no_anchor(self):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.query.side_effect = [
            [{"shas": ["a" * 40, "b" * 40]}],
            [],
        ]
        store = Neo4jStore(neo4j_client=client)

        summary = store.get_coverage_summary(7)

        assert summary["anchor_sha"] is None
        assert summary["tests"] == []

    def test_no_client_returns_empty_summary(self):
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        summary = Neo4jStore(neo4j_client=None).get_coverage_summary(7)

        assert summary == {"anchor_sha": None, "tests": []}

    def test_query_failure_is_tolerated(self):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.query.side_effect = RuntimeError("neo4j down")
        store = Neo4jStore(neo4j_client=client)

        summary = store.get_coverage_summary(7)

        assert summary == {"anchor_sha": None, "tests": []}


class TestApplyIncrementalMappings:
    SHA = "d" * 40

    def _symbol(self, name="core", file_path="src/core.py", start=1, end=5):
        from testsquad_core.instrumentation.symbol_resolver import Symbol
        return Symbol(name=name, symbol_type="function", file_path=file_path, start_line=start, end_line=end)

    def _store(self, results=None):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.run_in_transaction.return_value = results if results is not None else [
            [{"removed": 2}], [{"created": 1}], [{"cleared": 3}], [{"stamped": 4}], [{"stored": 1}],
        ]
        return Neo4jStore(neo4j_client=client), client

    def _mappings(self):
        return [{"test_name": "tests/test_a.py::test_x", "test_file": "tests/test_a.py", "symbols": [self._symbol()]}]

    def test_deletes_only_the_rerun_tests(self):
        store, client = self._store()

        store.apply_incremental_mappings(
            self._mappings(), 7, self.SHA, rerun_test_names=["tests/test_a.py::test_x"],
        )

        statements = client.run_in_transaction.call_args[0][0]
        delete_stmt, delete_params = statements[0]
        assert "DELETE ev" in delete_stmt
        assert delete_params["names"] == ["tests/test_a.py::test_x"]
        assert delete_params["project_id"] == 7

    def test_drop_names_are_deleted_too(self):
        store, client = self._store()

        store.apply_incremental_mappings(
            self._mappings(), 7, self.SHA,
            rerun_test_names=["tests/test_a.py::test_x"],
            drop_test_names=["tests/test_gone.py::test_z"],
        )

        statements = client.run_in_transaction.call_args[0][0]
        _, delete_params = statements[0]
        assert delete_params["names"] == ["tests/test_a.py::test_x", "tests/test_gone.py::test_z"]

    def test_restamps_all_coverage_edges_with_the_new_sha(self):
        store, client = self._store()

        store.apply_incremental_mappings(
            self._mappings(), 7, self.SHA, rerun_test_names=["tests/test_a.py::test_x"],
        )

        statements = client.run_in_transaction.call_args[0][0]
        joined = "\n".join(s for s, _ in statements)
        assert "SET t.built_at_sha = $built_at_sha" in joined
        assert "SET ev.built_at_sha = $built_at_sha" in joined
        # The restamp is not scoped to the rerun tests: carried-forward evidence
        # must also move to the new anchor.
        restamp_edge = [s for s, _ in statements if "SET ev.built_at_sha" in s][0]
        assert "names" not in restamp_edge
        assert "IN $names" not in restamp_edge

    def test_empty_mappings_still_restamps(self):
        store, client = self._store(results=[[{"removed": 0}], [{"cleared": 1}], [{"stamped": 2}]])

        count = store.apply_incremental_mappings([], 7, self.SHA, rerun_test_names=[])

        assert count == 0
        statements = client.run_in_transaction.call_args[0][0]
        joined = "\n".join(s for s, _ in statements)
        assert "SET ev.built_at_sha = $built_at_sha" in joined
        # No write/verify when nothing was re-run.
        assert "MERGE (t)-[ev:EVIDENCE" not in joined

    def test_returns_expected_edge_count(self):
        store, client = self._store()

        count = store.apply_incremental_mappings(
            self._mappings(), 7, self.SHA, rerun_test_names=["tests/test_a.py::test_x"],
        )

        assert count == 1

    def test_verification_mismatch_raises(self):
        import pytest
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore, PersistenceError

        class _FakeTx:
            def run_in_transaction(self, statements, verify=None):
                results = [[{"removed": 0}], [{"created": 1}], [{"cleared": 0}],
                           [{"stamped": 0}], [{"stored": 0}]]
                if verify is not None:
                    verify(results)
                return results

        store = Neo4jStore(neo4j_client=_FakeTx())

        with pytest.raises(PersistenceError):
            store.apply_incremental_mappings(
                self._mappings(), 7, self.SHA,
                rerun_test_names=["tests/test_a.py::test_x"],
            )

    def test_no_client_returns_zero(self):
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        assert Neo4jStore(neo4j_client=None).apply_incremental_mappings(
            self._mappings(), 7, self.SHA, rerun_test_names=[],
        ) == 0


# --------------------------------------------------------------------------
# coverage completeness — still measured against the full suite (AC3)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def analyzer():
    """Load per_test_analyzer by path (avoids importing the package __init__)."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "testsquad_core" / "instrumentation" / "per_test_analyzer.py"
    )
    spec = importlib.util.spec_from_file_location("pa_incremental", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestIncrementalCompleteness:
    def test_completeness_uses_full_suite_denominator(self, analyzer, tmp_path):
        scheduled = [str(tmp_path / "tests" / "test_a.py")]
        per_test = {"tests/test_a.py::test_one": {"src/a.py": [1]}}
        universe = [str(tmp_path / "tests" / f"test_{x}.py") for x in "abcd"]
        carried = [
            str(tmp_path / "tests" / "test_b.py"),
            str(tmp_path / "tests" / "test_c.py"),
        ]

        c = analyzer._coverage_completeness(
            str(tmp_path), scheduled, per_test, 4, 4,
            universe=universe, carried_forward=carried,
        )

        assert c["test_files_total"] == 4
        assert c["test_files_scheduled"] == 1
        assert c["test_files_carried_forward"] == 2
        # 1 run this round + 2 carried forward of 4 in the suite.
        assert c["test_files_instrumented"] == 3
        assert c["coverage_pct"] == 75.0
        assert c["missing_test_files"] == ["tests/test_d.py"]

    def test_without_universe_behaves_exactly_as_before(self, analyzer, tmp_path):
        scheduled = [
            str(tmp_path / "tests" / "test_a.py"),
            str(tmp_path / "tests" / "test_b.py"),
        ]
        per_test = {"tests/test_a.py::test_one": {"src/a.py": [1]}}

        c = analyzer._coverage_completeness(
            str(tmp_path), scheduled, per_test, original_count=2, collectable_count=2,
        )

        assert c["test_files_scheduled"] == 2
        assert c["test_files_total"] == 2
        assert c["test_files_carried_forward"] == 0
        assert c["test_files_instrumented"] == 1
        assert c["coverage_pct"] == 50.0
        assert c["missing_test_files"] == ["tests/test_b.py"]

    def test_analyze_passes_universe_through(self, analyzer, tmp_path, monkeypatch):
        """analyze_per_test_coverage must forward the universe + carry-forward."""
        seen = {}

        def _fake_run(testbed_path, test_files, shards=None, already_collected=False):
            seen["test_files"] = test_files
            return {
                "success": True, "output": "", "collectable_count": 1,
                "original_count": 1, "scheduled_files": test_files,
                "coverage_files": [],
            }

        monkeypatch.setattr(analyzer, "run_tests_with_coverage", _fake_run)
        monkeypatch.setattr(
            analyzer, "extract_per_test_lines",
            lambda *a, **k: {"tests/test_a.py::test_one": {"src/a.py": [1]}},
        )
        monkeypatch.setattr(analyzer, "resolve_to_symbols", lambda *a, **k: [])

        out = analyzer.analyze_per_test_coverage(
            str(tmp_path),
            [str(tmp_path / "tests" / "test_a.py")],
            universe=[str(tmp_path / "tests" / f"test_{x}.py") for x in "ab"],
            carried_forward=[str(tmp_path / "tests" / "test_b.py")],
        )

        assert seen["test_files"] == [str(tmp_path / "tests" / "test_a.py")]
        c = out["coverage_completeness"]
        assert c["test_files_total"] == 2
        assert c["test_files_carried_forward"] == 1
        assert c["coverage_pct"] == 100.0


# --------------------------------------------------------------------------
# pipeline wiring: turn prior evidence + git state into a run plan
# --------------------------------------------------------------------------

class _FakeStore:
    """Minimal stand-in for Neo4jStore (Story 11.5 only reads)."""

    def __init__(self, summary):
        self.summary = summary

    def get_coverage_summary(self, project_id):
        return self.summary


def _make_testbed(tmp_path, change_core=True, delete_test_b=False):
    """Local git repo with two commits; ``anchor`` is the first, HEAD the second."""
    import git

    repo = git.Repo.init(str(tmp_path))
    repo.git.checkout("-b", "main")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "core.py").write_text("def core():\n    return 1\n")
    (tmp_path / "src" / "other.py").write_text("def other():\n    return 2\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (tmp_path / "tests" / "test_b.py").write_text("def test_b():\n    pass\n")
    repo.index.add(["src/core.py", "src/other.py", "tests/test_a.py", "tests/test_b.py"])
    repo.index.commit("init")
    anchor = repo.head.commit.hexsha

    if change_core:
        (tmp_path / "src" / "core.py").write_text("def core():\n    return 3\n")
        repo.index.add(["src/core.py"])
        repo.index.commit("change core")
    if delete_test_b:
        (tmp_path / "tests" / "test_b.py").unlink()
        repo.index.remove(["tests/test_b.py"])
        repo.index.commit("drop test_b")

    return anchor, str(repo.head.commit.hexsha)


_SUMMARY_TWO_TESTS = lambda anchor: {
    "anchor_sha": anchor,
    "tests": [
        {"name": "tests/test_a.py::test_a", "file": "tests/test_a.py", "source_file": "src/core.py"},
        {"name": "tests/test_b.py::test_b", "file": "tests/test_b.py", "source_file": "src/other.py"},
    ],
}


class TestBuildIncrementalPlan:
    @pytest.fixture()
    def build(self):
        from testsquad_core.instrumentation.pipeline_worker import build_incremental_plan
        return build_incremental_plan

    def test_narrows_to_tests_covering_the_changed_file(self, build, tmp_path):
        anchor, head = _make_testbed(tmp_path)
        test_files = [str(tmp_path / "tests" / "test_a.py"), str(tmp_path / "tests" / "test_b.py")]

        plan, rerun, drop = build(
            7, _FakeStore(_SUMMARY_TWO_TESTS(anchor)), str(tmp_path), test_files,
            current_sha=head,
        )

        assert plan.is_incremental
        assert plan.tests_to_run == ["tests/test_a.py"]
        assert plan.carried_forward == ["tests/test_b.py"]
        assert rerun == ["tests/test_a.py::test_a"]
        assert drop == []

    def test_run_fresh_forces_a_full_run(self, build, tmp_path):
        anchor, head = _make_testbed(tmp_path)
        test_files = [str(tmp_path / "tests" / "test_a.py")]

        plan, rerun, drop = build(
            7, _FakeStore(_SUMMARY_TWO_TESTS(anchor)), str(tmp_path), test_files,
            current_sha=head, run_fresh=True,
        )

        assert plan.mode == "full"
        assert plan.reason == "run_fresh"
        assert rerun == [] and drop == []

    def test_no_evidence_store_disables_incremental(self, build, tmp_path):
        anchor, head = _make_testbed(tmp_path)

        plan, rerun, drop = build(
            7, None, str(tmp_path), [str(tmp_path / "tests" / "test_a.py")], current_sha=head,
        )

        assert plan.mode == "full"
        assert plan.reason == "disabled"

    def test_dropped_test_file_yields_drop_names(self, build, tmp_path):
        anchor, head = _make_testbed(tmp_path, delete_test_b=True)
        test_files = [str(tmp_path / "tests" / "test_a.py")]

        plan, rerun, drop = build(
            7, _FakeStore(_SUMMARY_TWO_TESTS(anchor)), str(tmp_path), test_files,
            current_sha=head,
        )

        assert plan.tests_to_run == ["tests/test_a.py"]
        assert plan.removed_test_files == ["tests/test_b.py"]
        assert drop == ["tests/test_b.py::test_b"]
        assert rerun == ["tests/test_a.py::test_a"]

    def test_unavailable_anchor_diff_falls_back_to_full(self, build, tmp_path):
        _make_testbed(tmp_path)
        # The graph points at a commit this checkout has never seen.
        summary = _SUMMARY_TWO_TESTS("f" * 40)

        plan, rerun, drop = build(
            7, _FakeStore(summary), str(tmp_path), [str(tmp_path / "tests" / "test_a.py")],
            current_sha="a" * 40,
        )

        assert plan.mode == "full"
        assert plan.reason == "diff_unavailable"
        assert rerun == []

    def test_nothing_changed_carries_everything_forward(self, build, tmp_path):
        anchor, head = _make_testbed(tmp_path, change_core=False)
        test_files = [str(tmp_path / "tests" / "test_a.py")]

        plan, rerun, drop = build(
            7, _FakeStore(_SUMMARY_TWO_TESTS(anchor)), str(tmp_path), test_files,
            current_sha=head,
        )

        assert plan.is_incremental
        assert plan.tests_to_run == []
        assert plan.carried_forward == ["tests/test_a.py"]
        assert rerun == []


class TestCountCoverageEdges:
    def test_counts_project_coverage_edges(self):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.query.return_value = [{"edges": 42}]
        store = Neo4jStore(neo4j_client=client)

        assert store.count_coverage_edges(7) == 42
        assert client.query.call_args[0][1] == {"project_id": 7}

    def test_no_client_is_zero(self):
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        assert Neo4jStore(neo4j_client=None).count_coverage_edges(7) == 0

    def test_query_failure_is_zero_not_a_crash(self):
        from unittest.mock import MagicMock
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        client = MagicMock()
        client.query.side_effect = RuntimeError("down")

        assert Neo4jStore(neo4j_client=client).count_coverage_edges(7) == 0


# --------------------------------------------------------------------------
# end-to-end: _run_python_pipeline actually narrows the suite it executes
# --------------------------------------------------------------------------

class _FakeAnalyzer:
    """Stands in for per_test_analyzer; records what the pipeline scheduled."""

    def __init__(self):
        self.calls = []

    def _install_test_deps(self, *args, **kwargs):
        return None

    def discover_collected_files(self, path, test_dir):
        return [
            os.path.join(path, "tests", "test_a.py"),
            os.path.join(path, "tests", "test_b.py"),
        ]

    def analyze_per_test_coverage(self, path, test_files, already_collected=False,
                                  universe=None, carried_forward=None):
        self.calls.append({
            "test_files": list(test_files),
            "universe": universe,
            "carried_forward": carried_forward,
        })
        return {
            "mappings": [],
            "test_count": 1,
            "symbol_count": 1,
            "per_test_coverage": {},
            "coverage_completeness": {"test_files_scheduled": len(test_files)},
            "diagnostics": {},
        }


class _FakeTM:
    """TestbedManager double: serves a prepared checkout instead of cloning."""

    def __init__(self, checkout, config):
        self.checkout = checkout
        self.config = config
        self.clone_calls = 0

    def register_testbed(self, name, config):
        self.config = config

    def clone_testbed(self, name, use_cache=True):
        from testsquad_core.instrumentation.testbed_manager import TestbedResult
        self.clone_calls += 1
        return TestbedResult(
            success=True, testbed_path=self.checkout, coverage_data=None,
            test_results=None, error_message=None, execution_time_seconds=0.0,
        )

    def get_testbed(self, name):
        return self.config


def _prepare_pipeline(tmp_path, monkeypatch, change_core=True):
    """Origin repo + a cloned checkout, with fakes injected into the worker."""
    import git
    from testsquad_core.instrumentation import pipeline_worker as pw
    from testsquad_core.instrumentation.testbed_manager import TestbedConfig

    origin = tmp_path / "origin"
    origin.mkdir()
    anchor, head = _make_testbed(origin, change_core=change_core)

    checkout = tmp_path / "checkout"
    git.Repo.clone_from(str(origin), str(checkout), branch="main")

    config = TestbedConfig(
        repo_url=str(origin), branch="main", test_command="true",
        install_command="", test_dir="tests", coverage_output="coverage.json",
    )
    tm = _FakeTM(str(checkout), config)
    analyzer = _FakeAnalyzer()
    monkeypatch.setattr(pw, "_load_per_test_analyzer", lambda: analyzer)
    return pw, tm, analyzer, anchor, str(checkout)


class TestRunPythonPipelineNarrowsTheRun:
    def test_schedules_only_the_tests_covering_a_changed_file(
        self, tmp_path, monkeypatch
    ):
        pw, tm, analyzer, anchor, checkout = _prepare_pipeline(tmp_path, monkeypatch)

        events = list(pw._run_python_pipeline(
            7, tm.config.repo_url, False, tm, {},
            evidence_store=_FakeStore(_SUMMARY_TWO_TESTS(anchor)),
        ))

        assert analyzer.calls, "analyzer was never invoked"
        call = analyzer.calls[0]
        # AC1: only tests covering the changed file run...
        assert call["test_files"] == [os.path.join(checkout, "tests", "test_a.py")]
        # ...against the full-suite denominator (AC3): every discovered file.
        assert call["universe"] == [
            os.path.join(checkout, "tests", "test_a.py"),
            os.path.join(checkout, "tests", "test_b.py"),
        ]
        assert call["carried_forward"] == ["tests/test_b.py"]

        mappings = [e for e in events if e["event"] == "mappings"][-1]
        assert mappings["incremental"]["rerun_test_names"] == ["tests/test_a.py::test_a"]
        assert mappings["incremental"]["carried_forward"] == ["tests/test_b.py"]
        assert mappings["incremental"]["changed_source_files"] == ["src/core.py"]

    def test_run_fresh_runs_everything_without_a_universe(
        self, tmp_path, monkeypatch
    ):
        pw, tm, analyzer, anchor, checkout = _prepare_pipeline(tmp_path, monkeypatch)

        events = list(pw._run_python_pipeline(
            7, tm.config.repo_url, True, tm, {},
            evidence_store=_FakeStore(_SUMMARY_TWO_TESTS(anchor)),
        ))

        call = analyzer.calls[0]
        assert call["test_files"] == [
            os.path.join(checkout, "tests", "test_a.py"),
            os.path.join(checkout, "tests", "test_b.py"),
        ]
        assert call["universe"] is None
        mappings = [e for e in events if e["event"] == "mappings"][-1]
        assert "incremental" not in mappings

    def test_no_evidence_store_runs_everything(self, tmp_path, monkeypatch):
        pw, tm, analyzer, anchor, checkout = _prepare_pipeline(tmp_path, monkeypatch)

        events = list(pw._run_python_pipeline(
            7, tm.config.repo_url, False, tm, {}, evidence_store=None,
        ))

        assert len(analyzer.calls[0]["test_files"]) == 2
        mappings = [e for e in events if e["event"] == "mappings"][-1]
        assert "incremental" not in mappings

    def test_nothing_changed_skips_execution_and_carries_evidence(
        self, tmp_path, monkeypatch
    ):
        pw, tm, analyzer, anchor, checkout = _prepare_pipeline(
            tmp_path, monkeypatch, change_core=False,
        )

        events = list(pw._run_python_pipeline(
            7, tm.config.repo_url, False, tm, {},
            evidence_store=_FakeStore(_SUMMARY_TWO_TESTS(anchor)),
        ))

        # No suite was executed at all: everything carried forward.
        assert analyzer.calls == []
        mappings = [e for e in events if e["event"] == "mappings"][-1]
        assert mappings["data"] == []
        assert mappings["incremental"]["tests_to_run"] == []
        assert mappings["incremental"]["carried_forward"] == ["tests/test_a.py", "tests/test_b.py"]

        completeness = [e for e in events if e["event"] == "coverage_completeness"][-1]["data"]
        assert completeness["test_files_total"] == 2
        assert completeness["test_files_carried_forward"] == 2
        assert completeness["coverage_pct"] == 100.0

    def test_error_path_still_surfaces(self, tmp_path, monkeypatch):
        pw, tm, analyzer, anchor, checkout = _prepare_pipeline(tmp_path, monkeypatch)
        analyzer.analyze_per_test_coverage = lambda *a, **k: {"error": "boom"}

        events = list(pw._run_python_pipeline(
            7, tm.config.repo_url, False, tm, {},
            evidence_store=_FakeStore(_SUMMARY_TWO_TESTS(anchor)),
        ))

        assert [e for e in events if e["event"] == "error"]
