from typing import List, Dict
from testsquad_shared.api import FrameworkDiscovery, DiscoveryProbeResult, FrameworkLabel, LanguageLabel

class ResultAggregator:
    def aggregate(self, primary_lang: LanguageLabel, results: List[DiscoveryProbeResult]) -> FrameworkDiscovery:
        # Group by label and pick highest confidence
        best_per_label: Dict[FrameworkLabel, DiscoveryProbeResult] = {}
        
        for res in results:
            if res.label not in best_per_label or res.confidence > best_per_label[res.label].confidence:
                best_per_label[res.label] = res
        
        return FrameworkDiscovery(
            primary_language=primary_lang,
            detected_frameworks=list(best_per_label.values())
        )
