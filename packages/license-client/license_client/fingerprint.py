import hashlib
import platform
import socket
import subprocess
import uuid
from pathlib import Path


def device_fingerprint() -> str:
    """Stable per-machine fingerprint (hashed, no PII beyond machine identity)."""
    candidates: list[str] = []

    if platform.system() == "Darwin":
        try:
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    candidates.append(line.split('"')[-2])
                    break
        except Exception:
            pass
    elif platform.system() == "Linux":
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                value = Path(path).read_text().strip()
                if value:
                    candidates.append(value)
                    break
            except OSError:
                continue

    if not candidates:
        try:
            candidates.append(str(uuid.getnode()))
        except Exception:
            pass

    raw = "|".join(candidates) or "unknown"
    raw = f"{raw}|{socket.gethostname()}|{platform.system()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
