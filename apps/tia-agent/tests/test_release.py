"""E6/R2: release tooling (artifact naming, checksums, cosign signing)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tia_agent import release
from tia_agent.release import (
    arch_name,
    artifact_name,
    main,
    os_name,
    parse_checksums,
    sha256_file,
    verify_checksums,
    write_checksums,
)

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tia-agent-release.yml"
RELEASE_SCRIPT = APP_DIR / "scripts" / "release.sh"
VERIFY_SCRIPT = APP_DIR / "scripts" / "verify_release.sh"

COSIGN = shutil.which("cosign")


# ---------------------------------------------------------------------------
# artifact naming + platform detection
# ---------------------------------------------------------------------------

def test_artifact_name_format():
    assert artifact_name("1.2.3", "darwin", "arm64") == "tia-agent-1.2.3-darwin-arm64"
    assert artifact_name("0.1.0", "linux", "x86_64") == "tia-agent-0.1.0-linux-x86_64"


def test_artifact_name_defaults_to_host_platform():
    name = artifact_name("9.9.9")
    assert name.startswith("tia-agent-9.9.9-")
    assert os_name() in name and arch_name() in name


def test_arch_aliases_normalized():
    # Whatever the machine reports, the release arch is one of our canonical values.
    assert arch_name() in {"x86_64", "arm64"}


def test_os_name_is_supported():
    assert os_name() in {"darwin", "linux"}


# ---------------------------------------------------------------------------
# checksums
# ---------------------------------------------------------------------------

def test_write_and_verify_checksums_roundtrip(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"bravo")
    (tmp_path / "a.bin").write_bytes(b"alpha")
    out = write_checksums([tmp_path / "b.bin", tmp_path / "a.bin"], tmp_path / "SHA256SUMS")

    lines = out.read_text().splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.bin", "b.bin"]  # sorted by name
    assert all(len(line.split("  ")[0]) == 64 for line in lines)
    assert verify_checksums(out, tmp_path) == []


def test_verify_detects_tampering(tmp_path):
    target = tmp_path / "artifact"
    target.write_bytes(b"original")
    out = write_checksums([target], tmp_path / "SHA256SUMS")
    target.write_bytes(b"tampered")
    problems = verify_checksums(out, tmp_path)
    assert len(problems) == 1 and "mismatch" in problems[0]


def test_verify_detects_missing(tmp_path):
    target = tmp_path / "artifact"
    target.write_bytes(b"data")
    out = write_checksums([target], tmp_path / "SHA256SUMS")
    target.unlink()
    problems = verify_checksums(out, tmp_path)
    assert problems and "missing" in problems[0]


def test_sha256_file_matches_known_value(tmp_path):
    import hashlib

    target = tmp_path / "x"
    target.write_bytes(b"hello")
    assert sha256_file(target) == hashlib.sha256(b"hello").hexdigest()


def test_parse_checksums_accepts_binary_star_prefix():
    entries = parse_checksums("deadbeef  a\ncafe *bin/b\n# comment\n\n")
    assert entries == [("a", "deadbeef"), ("bin/b", "cafe")]


# ---------------------------------------------------------------------------
# module CLI
# ---------------------------------------------------------------------------

def test_cli_name(capsys):
    assert main(["name", "--version", "2.0.0", "--os", "linux", "--arch", "arm64"]) == 0
    assert capsys.readouterr().out.strip() == "tia-agent-2.0.0-linux-arm64"


def test_cli_checksums_then_verify(tmp_path, capsys):
    (tmp_path / "f").write_bytes(b"payload")
    assert main(["checksums", "-o", str(tmp_path / "SHA256SUMS"), str(tmp_path / "f")]) == 0
    assert main(["verify", "-c", str(tmp_path / "SHA256SUMS"), "-d", str(tmp_path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_verify_failure_returns_nonzero(tmp_path):
    (tmp_path / "f").write_bytes(b"payload")
    main(["checksums", "-o", str(tmp_path / "SHA256SUMS"), str(tmp_path / "f")])
    (tmp_path / "f").write_bytes(b"changed")
    assert main(["verify", "-c", str(tmp_path / "SHA256SUMS"), "-d", str(tmp_path)]) == 1


# ---------------------------------------------------------------------------
# workflow + scripts
# ---------------------------------------------------------------------------

def test_release_workflow_exists():
    assert WORKFLOW.is_file(), "release workflow missing"


def test_release_workflow_triggers_on_tags_and_is_manual():
    text = WORKFLOW.read_text()
    assert "tia-agent-v*" in text
    assert "workflow_dispatch" in text


def test_release_workflow_permissions_for_publish_and_oidc():
    text = WORKFLOW.read_text()
    assert "contents: write" in text       # create the release
    assert "id-token: write" in text       # keyless cosign


def test_release_workflow_builds_matrix_and_signs():
    text = WORKFLOW.read_text()
    for os_name_ in ("darwin", "linux"):
        assert os_name_ in text
    assert "scripts/build_binary.sh" in text      # reuses R1 build
    assert "sha256sum" in text and "SHA256SUMS" in text
    assert "cosign sign-blob" in text             # signs each artifact + checksums
    assert "cosign verify-blob" in text           # verifies before publishing
    assert "gh release create" in text


def test_release_scripts_exist_and_executable():
    for script in (RELEASE_SCRIPT, VERIFY_SCRIPT):
        assert script.is_file(), f"{script} missing"
        assert script.stat().st_mode & 0o111, f"{script} not executable"


def test_verify_script_verifies_checksums_and_signatures():
    text = VERIFY_SCRIPT.read_text()
    assert "tia_agent.release verify" in text
    assert "cosign verify-blob" in text
    assert "gh release download" in text


# ---------------------------------------------------------------------------
# real cosign round-trip (needs the cosign binary; skips otherwise)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(COSIGN is None, reason="cosign not installed")
def test_cosign_bundle_sign_verify_roundtrip(tmp_path):
    artifact = tmp_path / "tia-agent-0.1.0-test-x86_64"
    artifact.write_bytes(b"pretend binary")
    env = {**__import__("os").environ, "COSIGN_PASSWORD": ""}

    subprocess.run([COSIGN, "generate-key-pair"], cwd=tmp_path, check=True,
                   capture_output=True, env=env)
    bundle = tmp_path / "artifact.sigstore.json"
    subprocess.run(
        [COSIGN, "sign-blob", "--yes", "--key", "cosign.key",
         "--bundle", str(bundle), artifact.name],
        cwd=tmp_path, check=True, capture_output=True, env=env,
    )
    assert bundle.is_file()

    verify = subprocess.run(
        [COSIGN, "verify-blob", "--key", "cosign.pub",
         "--bundle", str(bundle), artifact.name],
        cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    assert verify.returncode == 0, verify.stderr

    artifact.write_bytes(b"tampered binary")
    bad = subprocess.run(
        [COSIGN, "verify-blob", "--key", "cosign.pub",
         "--bundle", str(bundle), artifact.name],
        cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    assert bad.returncode != 0
