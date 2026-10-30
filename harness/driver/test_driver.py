from harness.driver import PlaywrightDriver


def test_driver_basic():
    d = PlaywrightDriver()
    assert "http://localhost:8080/" in d.navigate("/")
    assert d.click("#login")
    assert d.type("#user", "test")
    assert d.assert_text("body", "Sandbox")
    s = d.screenshot("login.png")
    assert s.exists()
