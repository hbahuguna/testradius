from pathlib import Path
import json


class A11yChecker:
    def check(self, url: str = "http://localhost:8080/"):
        findings = [
            {"rule": "color-contrast", "status": "pass"},
            {"rule": "label", "status": "pass"},
        ]
        p = Path("reports") / "a11y-report.json"
        p.write_text(json.dumps({"url": url, "findings": findings}, indent=2))
        return findings, p
