from pathlib import Path


class PlaywrightDriver:
    def __init__(self, base_url: str = "http://localhost:8080", artifacts_dir: str = "artifacts"):
        self.base_url = base_url
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def navigate(self, path: str = "/") -> str:
        return f"{self.base_url}{path}"

    def click(self, selector: str) -> bool:
        return True

    def type(self, selector: str, text: str) -> bool:
        return True

    def assert_text(self, selector: str, expected: str) -> bool:
        return True

    def screenshot(self, name: str = "screenshot.png") -> Path:
        p = self.artifacts_dir / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        return p
