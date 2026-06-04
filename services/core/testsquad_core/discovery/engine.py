import os
import json
from abc import ABC, abstractmethod
from typing import List, Optional
from testsquad_shared.api import FrameworkDiscovery, DiscoveryProbeResult, LanguageLabel

class DiscoveryProbe(ABC):
    @abstractmethod
    async def probe(self, root_path: str) -> List[DiscoveryProbeResult]:
        pass

from .aggregator import ResultAggregator

class DiscoveryEngine:
    def __init__(self, probes: List[DiscoveryProbe]):
        self.probes = probes
        self.aggregator = ResultAggregator()

    async def discover(self, root_path: str) -> FrameworkDiscovery:
        all_results = []
        repo_structure = "monorepo" if "services" in os.listdir(root_path) else "flat"
        
        # Recursively find all directories that might contain framework signals
        paths_to_probe = set()
        paths_to_probe.add(root_path)
        
        for root, dirs, files in os.walk(root_path):
            # Limit depth to avoid deep-walking large repos (e.g. node_modules, .git)
            if ".git" in dirs: dirs.remove(".git")
            if "node_modules" in dirs: dirs.remove("node_modules")
            if "venv" in dirs: dirs.remove("venv")
            if ".venv" in dirs: dirs.remove(".venv")

            depth = root[len(root_path):].count(os.sep)
            if depth > 5: # Max depth 5
                del dirs[:]
                continue
            
            # If a directory has manifest files or code, it's a candidate
            probe_this = False
            for f in files:
                if f in ["package.json", "requirements.txt", "pyproject.toml", "manage.py", "alembic.ini"]:
                    probe_this = True
                    break
                if f.endswith(('.py', '.js', '.ts', '.jsx', '.tsx')):
                    probe_this = True
                    break
            
            if probe_this:
                paths_to_probe.add(root)

        for path in paths_to_probe:
            for probe in self.probes:
                results = await probe.probe(path)
                all_results.extend(results)

        primary_lang = LanguageLabel.UNKNOWN
        for root, dirs, files in os.walk(root_path):
            if any(f.endswith('.py') for f in files):
                primary_lang = LanguageLabel.PYTHON
                break
            if any(f.endswith(('.js', '.ts', 'jsx', 'tsx')) for f in files):
                primary_lang = LanguageLabel.JAVASCRIPT
                break

        discovery = self.aggregator.aggregate(primary_lang, list(all_results))
        discovery.repo_structure = repo_structure
        return discovery
