from harness.sandbox.docker import SandboxConfig, SandboxRunner, make_mounts


def test_sandbox_build_cmd_includes_mounts_and_env():
    cfg = SandboxConfig(
        mounts=["/host/repo:/work/repo", "/host/artifacts:/work/artifacts"],
        env={"GEMINI_API_KEY": "x"},
        cpus=2,
        memory="4g",
    )
    runner = SandboxRunner(cfg)
    cmd = runner.build_cmd(["python", "-m", "harness", "testradius", "run"])
    assert "docker" in cmd
    assert "--rm" in cmd
    assert "-v" in cmd
    assert "-e" in cmd
    assert "--cpus" in cmd
    assert "--memory" in cmd
    assert cmd[-4:] == ["-m", "harness", "testradius", "run"]
    assert cmd[-5] == "python"


def test_make_mounts():
    mounts = make_mounts("/repo", "/repo/artifacts", "/repo/reports")
    assert len(mounts) == 3
    assert any("/repo/artifacts" in m for m in mounts)
