import os
import re
from typing import List
from testsquad_shared.api import DiscoveryProbeResult, FrameworkLabel
from ..engine import DiscoveryProbe

class CodeSignatureProbe(DiscoveryProbe):
    async def probe(self, root_path: str) -> List[DiscoveryProbeResult]:
        results = []
        
        # Scaning top-level files for typical imports
        # We limit the depth to avoid heavy scanning
        for entry in os.scandir(root_path):
            if entry.is_file() and entry.name.endswith(('.py', '.js', '.ts')):
                try:
                    with open(entry.path, "r", errors="ignore") as f:
                        # Read first few KB
                        content = f.read(4096)
                        self._scan_content(content, results)
                except Exception:
                    continue
        
        return results

    def _scan_content(self, content: str, results: List[DiscoveryProbeResult]):
        signatures = {
            r"from\s+fastapi\s+import": FrameworkLabel.FASTAPI,
            r"import\s+fastapi": FrameworkLabel.FASTAPI,
            r"from\s+flask\s+import": FrameworkLabel.FLASK,
            r"import\s+react": FrameworkLabel.REACT,
            r"from\s+'react'": FrameworkLabel.REACT,
            r"import\s+pytest": FrameworkLabel.PYTEST,
            r"from\s+django": FrameworkLabel.DJANGO,
        }

        for pattern, label in signatures.items():
            if re.search(pattern, content, re.MULTILINE):
                # If we find a code signature, confidence is very high
                results.append(DiscoveryProbeResult(
                    label=label,
                    confidence=0.95,
                    source="code_signature"
                ))
