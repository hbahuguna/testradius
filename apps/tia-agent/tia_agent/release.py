"""Release artifact helpers (E6/R2).

Names build outputs, produces a ``sha256sum``-compatible ``SHA256SUMS`` file, and
verifies it. Kept as a small reusable module so the release scripts and the tests
share one implementation:

    python -m tia_agent.release name --version 0.1.0
    python -m tia_agent.release checksums -o dist/SHA256SUMS dist/tia-agent-*
    python -m tia_agent.release verify -c dist/SHA256SUMS -d dist
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

#: Release artifact naming: tia-agent-<version>-<os>-<arch>
ARTIFACT_TEMPLATE = "tia-agent-{version}-{os}-{arch}"

_ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def os_name() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def arch_name() -> str:
    machine = platform.machine().lower()
    return _ARCH_ALIASES.get(machine, machine)


def artifact_name(version: str, os_: str | None = None, arch: str | None = None) -> str:
    return ARTIFACT_TEMPLATE.format(version=version, os=os_ or os_name(), arch=arch or arch_name())


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(paths: Iterable[str | Path], out: str | Path) -> Path:
    """Write a ``sha256sum``-compatible file (``<hex>  <name>``), sorted by name."""
    entries: List[Tuple[str, str]] = []
    for p in paths:
        path = Path(p)
        entries.append((path.name, sha256_file(path)))
    entries.sort(key=lambda e: e[0])
    out_path = Path(out)
    out_path.write_text("".join(f"{digest}  {name}\n" for name, digest in entries))
    return out_path


def parse_checksums(text: str) -> List[Tuple[str, str]]:
    """Parse checksum lines -> [(name, expected_hex)] (accepts ``*name``)."""
    entries: List[Tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        entries.append((name.lstrip("*"), digest.strip()))
    return entries


def verify_checksums(checksums: str | Path, base_dir: str | Path = ".") -> List[str]:
    """Return a list of problems; empty means every digest matched."""
    path = Path(checksums)
    base = Path(base_dir)
    problems: List[str] = []
    for name, expected in parse_checksums(path.read_text()):
        target = base / name
        if not target.exists():
            problems.append(f"missing: {name}")
            continue
        actual = sha256_file(target)
        if actual != expected:
            problems.append(f"checksum mismatch: {name} (expected {expected[:12]}…, got {actual[:12]}…)")
    return problems


def _cmd_name(args: argparse.Namespace) -> int:
    print(artifact_name(args.version, args.os, args.arch))
    return 0


def _cmd_checksums(args: argparse.Namespace) -> int:
    out = write_checksums(args.files, args.output)
    print(f"wrote {out} ({len(args.files)} entr{'y' if len(args.files) == 1 else 'ies'})")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    problems = verify_checksums(args.checksums, args.dir)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    print("OK: all checksums verified")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tia_agent.release", description="Release artifact helpers.")
    sub = p.add_subparsers(dest="command", required=True)

    name = sub.add_parser("name", help="Print the release artifact name")
    name.add_argument("--version", required=True)
    name.add_argument("--os", default=None)
    name.add_argument("--arch", default=None)
    name.set_defaults(func=_cmd_name)

    ck = sub.add_parser("checksums", help="Write a SHA256SUMS file")
    ck.add_argument("files", nargs="+")
    ck.add_argument("-o", "--output", default="SHA256SUMS")
    ck.set_defaults(func=_cmd_checksums)

    vr = sub.add_parser("verify", help="Verify a SHA256SUMS file")
    vr.add_argument("-c", "--checksums", default="SHA256SUMS")
    vr.add_argument("-d", "--dir", default=".")
    vr.set_defaults(func=_cmd_verify)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
