"""D2: evidence freshness — classify stored mapping SHAs vs the analyzed commit.

Mappings are stamped with the ``built_at_sha`` of the testbed commit they were
derived from. At analyze time we compare that against the analyzed commit: a
mismatch means the evidence may not reflect the code being analyzed, so the
selection must not be silently trusted (the caller falls back with a
``stale_evidence`` reason).
"""
import re
from typing import Any, Dict, List, Optional

_HEX_SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def is_commit_sha(value: Any) -> bool:
    """Whether ``value`` is a concrete full Git SHA (40 hex chars).

    Branch names like ``main`` and short SHAs are not comparable, so freshness
    cannot be asserted against them.
    """
    return bool(_HEX_SHA.match(str(value or "")))


def classify_evidence_freshness(
    evidence_shas: Optional[List[Optional[str]]],
    analyzed_commit: Any,
) -> Dict[str, Any]:
    """Classify stored evidence freshness against the analyzed commit.

    Args:
        evidence_shas: distinct non-null ``built_at_sha`` values recorded on the
            project's ``TestSymbol`` nodes (each run stamps every node it writes).
        analyzed_commit: the ``commit_sha`` passed to ``analyze-pr`` (may be a
            branch ref like ``main`` when no SHA is available).

    Returns:
        Dict with:
        - ``evidence_built_at_sha`` (str or None; None when unversioned/mixed),
        - ``stale_evidence`` (bool),
        - ``stale_evidence_reason`` (str or None),
        - ``evidence_unversioned`` (bool — evidence predates SHA stamping).
    """
    result: Dict[str, Any] = {
        "evidence_built_at_sha": None,
        "stale_evidence": False,
        "stale_evidence_reason": None,
        "evidence_unversioned": False,
    }

    distinct = sorted({s for s in (evidence_shas or []) if s})
    if not distinct:
        result["evidence_unversioned"] = True
        return result

    if len(distinct) > 1:
        result["stale_evidence"] = True
        preview = ", ".join(s[:10] for s in distinct[:3])
        result["stale_evidence_reason"] = (
            f"evidence was built across {len(distinct)} different commits "
            f"({preview}); cannot pin it to a single head"
        )
        return result

    built = distinct[0]
    result["evidence_built_at_sha"] = built

    if not is_commit_sha(analyzed_commit):
        # A branch/ref is not comparable; do not claim freshness either way.
        return result

    if str(analyzed_commit).lower() != built.lower():
        result["stale_evidence"] = True
        result["stale_evidence_reason"] = (
            f"evidence built at {built[:12]} but analyzing "
            f"{str(analyzed_commit)[:12]}"
        )
    return result