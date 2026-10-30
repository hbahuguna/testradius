from harness.driver.stability import StabilityConfig, with_auto_wait


def test_stability_config_defaults():
    cfg = StabilityConfig()
    assert cfg.default_timeout_ms == 30000
    assert cfg.navigation_timeout_ms == 60000
    assert cfg.wait_for_network_idle is True
    assert cfg.retries_on_nav == 2


def test_with_auto_wait_options():
    opts = with_auto_wait()
    assert opts["viewport"]["width"] == 1920
    assert opts["ignore_https_errors"] is True
