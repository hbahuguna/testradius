import os
import json
import tomllib
from typing import List
from testsquad_shared.api import DiscoveryProbeResult, FrameworkLabel
from ..engine import DiscoveryProbe

class DependencyProbe(DiscoveryProbe):
    async def probe(self, root_path: str) -> List[DiscoveryProbeResult]:
        results = []
        
        # 1. Check requirements.txt
        req_path = os.path.join(root_path, "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r") as f:
                content = f.read().lower()
                self._check_python_deps(content, "requirements.txt", results)

        # 2. Check pyproject.toml
        pyproject_path = os.path.join(root_path, "pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                poetry_data = data.get("tool", {}).get("poetry", {})
                
                # Check main dependencies
                deps = str(poetry_data.get("dependencies", {})).lower()
                
                # Check all dependency groups (dev, etc.)
                groups = poetry_data.get("group", {})
                for group_name, group_data in groups.items():
                    deps += " " + str(group_data.get("dependencies", {})).lower()
                
                self._check_python_deps(deps, "pyproject.toml", results)

        # 3. Check package.json
        pkg_path = os.path.join(root_path, "package.json")
        if os.path.exists(pkg_path):
            with open(pkg_path, "r") as f:
                data = json.load(f)
                deps = str(data.get("dependencies", {})).lower()
                deps += str(data.get("devDependencies", {})).lower()
                self._check_js_deps(deps, "package.json", results)

        return results

    def _check_python_deps(self, content: str, source: str, results: List[DiscoveryProbeResult]):
        framework_map = {
            "fastapi": FrameworkLabel.FASTAPI,
            "flask": FrameworkLabel.FLASK,
            "django": FrameworkLabel.DJANGO,
            "pytest": FrameworkLabel.PYTEST,
            "alembic": FrameworkLabel.ALEMBIC,
            "sqlalchemy": FrameworkLabel.SQLALCHEMY,
        }
        for key, label in framework_map.items():
            if key in content:
                results.append(DiscoveryProbeResult(
                    label=label,
                    confidence=0.9,
                    source=source
                ))

    def _check_js_deps(self, content: str, source: str, results: List[DiscoveryProbeResult]):
        framework_map = {
            "react": FrameworkLabel.REACT,
            "vue": FrameworkLabel.VUE,
            "next": FrameworkLabel.NEXTJS,
            "express": FrameworkLabel.EXPRESS,
        }
        for key, label in framework_map.items():
            if key in content:
                results.append(DiscoveryProbeResult(
                    label=label,
                    confidence=0.9,
                    source=source
                ))
