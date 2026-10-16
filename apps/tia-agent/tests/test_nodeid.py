"""E5/O1: canonical pytest nodeids — no ``path::path::Class::method`` doubling.

The backend returns ``test_file`` (the ``path`` part) and ``test_name`` which is
already a collected nodeid (``path::Class::method[param]``). ``canonical_nodeid``
must combine them exactly once, and the emitted nodeid must be one ``pytest`` can
actually select.
"""
import subprocess
import sys

from tia_agent.output import canonical_nodeid
from tia_agent.output.nodeid import canonical_nodeid as _impl


def _run(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ---------------------------------------------------------------------------
# canonical_nodeid (pure)
# ---------------------------------------------------------------------------

def test_prefixed_name_is_kept_not_doubled():
    # The live py-key-value shape: test_name is already path::Class::method.
    file = "tests/stores/wrappers/test_prefix_key.py"
    name = "tests/stores/wrappers/test_prefix_key.py::TestPrefixKeyWrapper::test_negative_ttl"
    assert canonical_nodeid(file, name) == name
    assert canonical_nodeid(file, name).count("test_prefix_key.py") == 1


def test_absolute_vs_relative_file_prefix_is_kept():
    # Legacy/container test_file is absolute; the nodeid is repo-relative.
    file = "/testradius/tests/stores/wrappers/test_prefix_key.py"
    name = "tests/stores/wrappers/test_prefix_key.py::TestClass::test_a"
    assert canonical_nodeid(file, name) == name


def test_basename_only_match_keeps_name():
    file = "/workdir/py-key-value/tests/test_ttl.py"
    name = "tests/test_ttl.py::test_prepare_ttl"
    assert canonical_nodeid(file, name) == name


def test_method_name_gets_file_prefix():
    assert canonical_nodeid("tests/test_ttl.py", "test_prepare_ttl") == (
        "tests/test_ttl.py::test_prepare_ttl"
    )


def test_class_and_method_get_file_prefix():
    assert canonical_nodeid("tests/test_base.py", "TestBase::test_x") == (
        "tests/test_base.py::TestBase::test_x"
    )


def test_parametrized_nodeid_preserved():
    name = "tests/stores/wrappers/test_statistics.py::TestStatisticsWrapper::test_get_large_put_get[large-data-string]"
    file = "tests/stores/wrappers/test_statistics.py"
    assert canonical_nodeid(file, name) == name
    assert "[large-data-string]" in canonical_nodeid(file, name)


def test_module_parametrized_nodeid_preserved():
    name = "tests/test_utils.py::test_multi[case-1]"
    assert canonical_nodeid("tests/test_utils.py", name) == name


def test_empty_name_returns_file():
    assert canonical_nodeid("tests/test_a.py", "") == "tests/test_a.py"
    assert canonical_nodeid("tests/test_a.py", None) == "tests/test_a.py"


def test_data_driven_name_equal_file_not_doubled():
    # Conftest-generated items (e.g. Pygments snippet/examplefile tests) report
    # name == file with no item component. Must not become ``path::path``.
    for path in ("tests/snippets/scheme/numbers.txt",
                 "tests/examplefiles/ocaml/format.ml"):
        assert canonical_nodeid(path, path) == path
        assert canonical_nodeid(path, path).count(path) == 1


def test_data_driven_absolute_vs_relative_not_doubled():
    file = "/repo/tests/snippets/scheme/numbers.txt"
    name = "tests/snippets/scheme/numbers.txt"
    assert canonical_nodeid(file, name) == file


def test_empty_file_returns_name():
    assert canonical_nodeid("", "tests/test_a.py::test_1") == "tests/test_a.py::test_1"


def test_does_not_needle_local_import_path_guards():
    # A method named like a file must not be misread as a prefix.
    assert canonical_nodeid("tests/test_files.py", "test_files") == (
        "tests/test_files.py::test_files"
    )


# ---------------------------------------------------------------------------
# regression: the emitted nodeid must be selectable by pytest ("run_commands
# execute") — with a real, fresh checkout in a tmp dir.
# ---------------------------------------------------------------------------

def test_emitted_nodeid_is_executable_by_pytest(tmp_path):
    _run(tmp_path / "tests" / "test_ttl.py",
         "class TestTtl:\n    def test_negative_ttl(self):\n        assert True\n")
    _run(tmp_path / "tests" / "test_utils.py",
         "def test_multi(v):\n    assert v\n\nimport pytest\n"
         "@pytest.mark.parametrize('v', ['case-1', 'case-2'])\n"
         "def test_param(v):\n    assert v\n")

    nodeid = canonical_nodeid(
        "tests/test_ttl.py",
        "tests/test_ttl.py::TestTtl::test_negative_ttl",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", nodeid],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert nodeid in proc.stdout

    # A doubled ``file::file::Class::method`` nodeid must NOT select anything.
    doubled = f"tests/test_ttl.py::{nodeid}"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", doubled],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert "no tests collected" in proc.stdout.lower()
    assert "TestTtl" not in proc.stdout


def test_parametrized_nodeid_is_executable_by_pytest(tmp_path):
    _run(tmp_path / "tests" / "test_utils.py",
         "import pytest\n"
         "@pytest.mark.parametrize('v', ['case-1', 'case-2'])\n"
         "def test_param(v):\n    assert v\n")
    nodeid = canonical_nodeid(
        "tests/test_utils.py",
        "tests/test_utils.py::test_param[case-1]",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", nodeid],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 test" in proc.stdout or nodeid in proc.stdout


def test_end_to_end_result_nodeid_is_canonical(tmp_path):
    """Regression: `tia-agent analyze --json` nodeids are well-formed (no
    ``file::file::``), and ``run_commands`` reference that canonical nodeid."""
    from tia_agent.analyze import AnalyzeRunner
    from tia_agent.config import TiaConfig
    from tia_agent.radius_client import ProjectInfo

    _run(tmp_path / "tests" / "test_ttl.py",
         "def test_prepare_ttl():\n    assert True\n")

    class _Radius:
        base_url = "http://radius:8000"

        def list_projects(self):
            return [ProjectInfo(id=1, name="acme/shop")]

        def analyze_pr(self, **kwargs):
            return {
                "pr_files_analyzed": 1,
                "pr_files": ["src/a.py"],
                "symbols_selected": 1,
                "tests_selected": 1,
                "total_tests_reused": 1,
                "results": [{
                    "symbol_name": "f",
                    "existing_tests": [{
                        "test_name": "tests/test_ttl.py::test_prepare_ttl",
                        "test_file": "tests/test_ttl.py",
                    }],
                }],
            }

    class _Guard:
        def ensure_valid(self):
            pass

        def record_run(self, *a, **k):
            pass

    runner = AnalyzeRunner(TiaConfig(), _Guard(), _Radius())
    res = runner.run(repo="acme/shop", pr_number=1, repo_path=str(tmp_path))

    nodeid = res.tests[0]["nodeid"]
    assert nodeid == "tests/test_ttl.py::test_prepare_ttl"
    assert "test_ttl.py::tests/test_ttl.py" not in nodeid
    assert nodeid in res.run_commands[0]