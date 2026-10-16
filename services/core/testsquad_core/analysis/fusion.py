"""Runtime + static test fusion (S2) with explainable provenance (V2).

Runtime coverage (``EVIDENCE`` edges) is precise but *incomplete*: a test that
statically reaches a changed symbol through the import/call graph but was not
executed against it during instrumentation would be silently dropped if we
looked at runtime evidence alone.

This module fuses two candidate sources for a changed symbol into one ranked,
de-duplicated set with a **per-test confidence** and a **reason path**:

* ``runtime`` — the test actually executed the symbol (``high`` confidence);
* ``static``  — the test only *statically reaches* the symbol via the
  import/call graph (``medium`` confidence).

Every candidate carries a ``reason`` string of the form
``changed_symbol:<name>@<file> -> <source(s)> -> <test>`` so a selection is
never opaque: it names the changed symbol that pulled the test in and the
evidence source(s) that justified it.

A test present in both keeps ``high`` confidence and lists both sources. No
candidate is ever dropped solely because it lacks runtime evidence.

Pure and dependency-free so it can be unit tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

CONFIDENCE_RUNTIME = "high"
CONFIDENCE_STATIC = "medium"

#: Source labels written into the fused per-test ``reason``.
SOURCE_RUNTIME = "runtime_evidence"
SOURCE_STATIC = "static_import"

#: Confidence ranking (higher wins) used when a test is selected for many symbols.
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def changed_symbol_reason(
    symbol_name: str,
    symbol_file: str,
    sources: Sequence[str],
    test_name: str,
) -> str:
    """Build the ``changed symbol -> test`` explanation path (V2).

    Always non-empty and machine-readable: the changed symbol, the file it
    lives in, the evidence source(s), and the selected test.
    """
    name = symbol_name or "?"
    path = symbol_file or "?"
    src = "+".join(sources) if sources else "selected"
    return f"changed_symbol:{name}@{path} -> {src} -> {test_name or path}"


@dataclass
class TestCandidate:
    """One selected test for a changed symbol, with its provenance (V2)."""

    test_name: str
    test_file: str
    confidence: str
    symbol_name: str = ""
    symbol_file: str = ""
    sources: List[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """The reason path, derived from the symbol + sources (never opaque)."""
        return changed_symbol_reason(
            self.symbol_name, self.symbol_file, self.sources, self.test_name
        )

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "test_file": self.test_file,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def fuse_symbol_tests(
    runtime: Iterable[Tuple[str, str]],
    static: Iterable[Tuple[str, str]],
    symbol_name: str,
    symbol_file: str,
) -> List[TestCandidate]:
    """Union runtime + static candidates for a single changed symbol.

    ``runtime`` and ``static`` are iterables of ``(test_name, test_file)``.
    Runtime membership wins on confidence; static-only candidates are ``medium``.
    Runtime candidates come first. Every candidate's reason names the changed
    symbol and the source(s) that selected it.
    """
    fused: dict = {}
    order: List[Tuple[str, str]] = []

    for name, file in runtime:
        key = (file, name)
        if key not in fused:
            fused[key] = TestCandidate(
                test_name=name,
                test_file=file,
                confidence=CONFIDENCE_RUNTIME,
                symbol_name=symbol_name,
                symbol_file=symbol_file,
                sources=[SOURCE_RUNTIME],
            )
            order.append(key)

    for name, file in static:
        key = (file, name)
        existing = fused.get(key)
        if existing is None:
            fused[key] = TestCandidate(
                test_name=name,
                test_file=file,
                confidence=CONFIDENCE_STATIC,
                symbol_name=symbol_name,
                symbol_file=symbol_file,
                sources=[SOURCE_STATIC],
            )
            order.append(key)
        elif SOURCE_STATIC not in existing.sources:
            # Reached both ways: keep high confidence, but record both sources
            # so the reason path shows the full provenance.
            existing.sources.append(SOURCE_STATIC)

    return [fused[key] for key in order]


def has_static_only(candidates: Sequence[TestCandidate]) -> bool:
    """True when at least one selected test is statically reached but not run."""
    return any(
        c.confidence == CONFIDENCE_STATIC
        and SOURCE_STATIC in c.sources
        and SOURCE_RUNTIME not in c.sources
        for c in candidates
    )


def static_only_count(candidates: Sequence[TestCandidate]) -> int:
    return sum(
        1
        for c in candidates
        if c.confidence == CONFIDENCE_STATIC and SOURCE_RUNTIME not in c.sources
    )
