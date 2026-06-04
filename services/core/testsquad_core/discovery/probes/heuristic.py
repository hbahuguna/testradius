import os
from typing import List
from testsquad_shared.api import DiscoveryProbeResult, FrameworkLabel
from ..engine import DiscoveryProbe

class HeuristicProbe(DiscoveryProbe):
    async def probe(self, root_path: str) -> List[DiscoveryProbeResult]:
        results = []
        
        # Landmark files
        landmarks = {
            "manage.py": FrameworkLabel.DJANGO,
            "alembic.ini": FrameworkLabel.ALEMBIC,
            "tailwind.config.js": FrameworkLabel.GENERIC, # Could be more specific
            "docker-compose.yml": FrameworkLabel.GENERIC,
            "next.config.js": FrameworkLabel.NEXTJS,
            "vite.config.ts": FrameworkLabel.GENERIC,
        }

        for filename, label in landmarks.items():
            if os.path.exists(os.path.join(root_path, filename)):
                results.append(DiscoveryProbeResult(
                    label=label,
                    confidence=0.8,
                    source=f"heuristic:{filename}"
                ))

        return results
