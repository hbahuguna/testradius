"""D2: commit-pinned evidence freshness — classify stored mapping SHAs.

Mappings are stamped with the ``built_at_sha`` of the testbed commit they were
derived from. At analyze time the analyzed commit is compared against that: a
40-hex mismatch means the evidence may not reflect the code under analysis, so
selection must not be silently trusted.
"""
import sys
import types

sys.path.insert(0, "/Users/skaparwan/github/testradius/services/core/testsquad_core")


def _load_freshness():
    import importlib.util
    pkg = types.ModuleType("testsquad_core.analysis")
    pkg.__path__ = ["/Users/skaparwan/github/testradius/services/core/testsquad_core/analysis"]
    sys.modules["testsquad_core.analysis"] = pkg
    spec = importlib.util.spec_from_file_location(
        "testsquad_core.analysis.freshness",
        "/Users/skaparwan/github/testradius/services/core/testsquad_core/analysis/freshness.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


freshness = _load_freshness()


def test_is_commit_sha_accepts_full_hex():
    assert freshness.is_commit_sha("a" * 40)
    assert freshness.is_commit_sha(("0" * 39) + "f")
    assert freshness.is_commit_sha((( "a" * 40).upper()))


def test_is_commit_sha_rejects_branch_and_short_sha():
    for bad in ["main", "abc1234", "abc", "", None, 12345, "a" * 39, "z" * 40]:
        assert not freshness.is_commit_sha(bad), f"expected reject: {bad!r}"


def test_no_evidence_is_unversioned_not_stale():
    result = freshness.classify_evidence_freshness([], "main")
    assert result["evidence_unversioned"] is True
    assert result["stale_evidence"] is False
    assert result["stale_evidence_reason"] is None
    assert result["evidence_built_at_sha"] is None


def test_null_evidence_is_unversioned():
    result = freshness.classify_evidence_freshness([None, None], "main")
    assert result["evidence_unversioned"] is True
    assert result["stale_evidence"] is False


def test_single_sha_matching_head_is_fresh():
    sha = "f" * 40
    result = freshness.classify_evidence_freshness([sha], sha)
    assert result["stale_evidence"] is False
    assert result["evidence_built_at_sha"] == sha
    assert result["stale_evidence_reason"] is None


def test_single_sha_drifted_head_is_stale():
    built = "a" * 40
    analyzed = "b" * 40
    result = freshness.classify_evidence_freshness([built], analyzed)
    assert result["stale_evidence"] is True
    assert result["evidence_built_at_sha"] == built
    assert "evidence built at" in result["stale_evidence_reason"]
    assert analyzed[:12] in result["stale_evidence_reason"]


def test_single_sha_drifted_head_case_insensitive():
    built = "a" * 40
    analyzed = ("A" * 40)
    result = freshness.classify_evidence_freshness([built], analyzed)
    assert result["stale_evidence"] is False


def test_branch_name_is_not_comparable_not_stale():
    result = freshness.classify_evidence_freshness([("b" * 40)], "main")
    assert result["stale_evidence"] is False
    assert result["evidence_built_at_sha"] == "b" * 40


def test_multiple_distinct_shas_is_stale_mixed():
    result = freshness.classify_evidence_freshness([("a" * 40), ("b" * 40)], "main")
    assert result["stale_evidence"] is True
    assert "different commits" in result["stale_evidence_reason"]
    assert result["evidence_built_at_sha"] is None


def test_duplicate_shas_collapse_to_one():
    result = freshness.classify_evidence_freshness([("a" * 40), ("a" * 40)], "main")
    assert result["stale_evidence"] is False
    assert result["evidence_built_at_sha"] == "a" * 40