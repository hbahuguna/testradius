import json

from tia_agent.config import TiaConfig


def test_defaults():
    cfg = TiaConfig()
    assert cfg.radius_url.endswith(":8000")


def test_file_values_are_loaded(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"radius_url": "http://file:1234", "license_url": "http://lic:9"}))
    cfg = TiaConfig.load(path=p)
    assert cfg.radius_url == "http://file:1234"
    assert cfg.license_url == "http://lic:9"


def test_env_wins_over_file(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"radius_url": "http://file:1234"}))
    monkeypatch.setenv("TIA_RADIUS_URL", "http://env:5555")
    cfg = TiaConfig.load(path=p)
    assert cfg.radius_url == "http://env:5555"


def test_env_read_at_load_time(tmp_path, monkeypatch):
    """Env set after import must still apply (defaults are import-time)."""
    p = tmp_path / "config.json"
    p.write_text("{}")
    monkeypatch.setenv("TIA_LICENSE_URL", "http://lic-env:8100")
    cfg = TiaConfig.load(path=p)
    assert cfg.license_url == "http://lic-env:8100"


def test_verbose_coercion(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("{}")
    monkeypatch.setenv("TIA_VERBOSE", "true")
    cfg = TiaConfig.load(path=p)
    assert cfg.verbose is True


def test_unrelated_tia_env_does_not_mask_file(tmp_path, monkeypatch):
    """TIA_LICENSE_STATE_PATH etc must not block file values from applying."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"radius_url": "http://file:1234"}))
    monkeypatch.setenv("TIA_LICENSE_STATE_PATH", "/tmp/somewhere")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    cfg = TiaConfig.load(path=p)
    assert cfg.radius_url == "http://file:1234"