"""Unified scorer for test impact analysis using Bayesian evidence fusion."""
import math
from dataclasses import dataclass, field
from collections import defaultdict
from typing import List

from .calibrators import get_calibrator


DEFAULT_PRIOR = 0.01


@dataclass
class Evidence:
    source: str
    test_name: str
    test_file: str
    symbol_name: str
    confidence: float
    metadata: dict = field(default_factory=dict)


@dataclass
class ScoredTest:
    test_name: str
    test_file: str
    symbol_name: str
    confidence: float
    evidence_sources: List[str]


class UnifiedScorer:
    """Bayesian ensemble scorer that fuses evidence from multiple TIA sources."""

    def __init__(self, prior: float = DEFAULT_PRIOR):
        self.prior = prior
        self.log_prior = math.log(prior)
        self.log_complement = math.log(1.0 - prior)

    def score(self, symbol: str, evidence: List[Evidence]) -> ScoredTest:
        """Fuse all evidence for one (symbol, test) pair into a single score."""
        if not evidence:
            return ScoredTest(
                test_name="",
                test_file="",
                symbol_name=symbol,
                confidence=self.prior,
                evidence_sources=[],
            )

        first = evidence[0]
        log_odds = self.log_prior - self.log_complement
        sources = []
        for e in evidence:
            calibrator = get_calibrator(e.source)
            calibrated = calibrator(e.confidence)
            # Bayes factor: K = [p/(1-p)] * [(1-prior)/prior]
            p = max(min(calibrated, 1 - 1e-10), 1e-10)
            log_odds += math.log(p) - math.log(1.0 - p) + self.log_complement - self.log_prior
            sources.append(e.source)

        fused = 1.0 / (1.0 + math.exp(-log_odds))
        return ScoredTest(
            test_name=first.test_name,
            test_file=first.test_file,
            symbol_name=symbol,
            confidence=fused,
            evidence_sources=sources,
        )

    def score_all(
        self, evidence: List[Evidence]
    ) -> List[ScoredTest]:
        """Group evidence by (symbol, test, file), fuse each group, return sorted."""
        groups = defaultdict(list)
        for e in evidence:
            groups[(e.symbol_name, e.test_name, e.test_file)].append(e)

        results = []
        for (symbol, _, _), ev_list in groups.items():
            results.append(self.score(symbol, ev_list))

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results
