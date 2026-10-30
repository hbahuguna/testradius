import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


class PlaywrightRealDriver:
    def __init__(self, base_url: str = "https://testradius.dev", headless: bool = True, artifacts_dir: str = "artifacts", record_video: bool = True):
        self.base_url = base_url
        self.headless = headless
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.record_video = record_video
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        context_kwargs = {"viewport": {"width": 1280, "height": 720}}
        if record_video:
            context_kwargs["record_video_dir"] = str(self.artifacts_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 720}
        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()
        self.console_logs = []
        self.network_logs = []
        self.page.on("console", lambda msg: self.console_logs.append({"type": msg.type, "text": msg.text}))
        self.page.on("request", lambda req: self.network_logs.append({"url": req.url, "method": req.method}))
        self.page.on("response", lambda res: self.network_logs.append({"url": res.url, "status": res.status}))

    def navigate(self, path: str = "/"):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return self.page.url

    def screenshot(self, name: str = "screenshot.png"):
        p = self.artifacts_dir / name
        self.page.screenshot(path=str(p), full_page=True)
        return p

    def click(self, selector: str):
        self.page.click(selector)
        return True

    def type(self, selector: str, text: str):
        self.page.fill(selector, text)
        return True

    def evaluate(self, script: str):
        return self.page.evaluate(script)

    def save_traces(self, name: str = "trace.json"):
        p = self.artifacts_dir / name
        p.write_text(json.dumps({"console": self.console_logs, "network": self.network_logs[:200]}, indent=2))
        return p

    def close(self):
        try:
            video_path = self.page.video.path() if self.page.video else None
        except Exception:
            video_path = None
        try:
            self.context.close()
        except Exception:
            pass
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.playwright.stop()
        except Exception:
            pass
        return video_path
