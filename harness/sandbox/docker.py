"""Docker sandbox execution for Playwright runs."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional


PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.47.0-jammy"


@dataclass
class SandboxConfig:
    image: str = PLAYWRIGHT_IMAGE
    workdir: str = "/work"
    mounts: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    network: str = "bridge"
    shm_size: str = "1g"
    cpus: Optional[float] = None
    memory: Optional[str] = None
    remove: bool = True


class SandboxRunner:
    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()

    def build_cmd(self, command: List[str]) -> List[str]:
        cmd = ["docker", "run"]
        if self.config.remove:
            cmd.append("--rm")
        cmd += ["--ipc=host", f"--shm-size={self.config.shm_size}"]
        if self.config.network:
            cmd += ["--network", self.config.network]
        if self.config.cpus:
            cmd += ["--cpus", str(self.config.cpus)]
        if self.config.memory:
            cmd += ["--memory", self.config.memory]
        for m in self.config.mounts:
            cmd += ["-v", m]
        for k, v in self.config.env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += ["-w", self.config.workdir]
        cmd += [self.config.image]
        cmd += command
        return cmd

    def run(self, command: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        cmd = self.build_cmd(command)
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def make_mounts(repo_root: str, artifacts_dir: str, reports_dir: str) -> List[str]:
    return [
        f"{repo_root}:{repo_root}",
        f"{artifacts_dir}:{artifacts_dir}",
        f"{reports_dir}:{reports_dir}",
    ]
