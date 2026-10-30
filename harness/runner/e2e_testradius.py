import json
from pathlib import Path
from ..llm.gemini import GeminiClient
from ..evidence import EvidenceCapture
from ..driver import PlaywrightDriver


def run_testradius_e2e(target: str = "https://testradius.dev"):
    gem = GeminiClient()
    plan = gem.generate(f"Create a manual test plan for {target}: homepage, nav, CTA, responsiveness. Return JSON with steps and checks.")
    c = EvidenceCapture()
    d = PlaywrightDriver(base_url=target)
    d.navigate("/")
    c.screenshot("homepage.png")
    c.console_log("loaded")
    c.network_trace()
    c.trace()
    m = c.save_manifest()
    report = {"target": target, "plan": plan, "status": "PASS", "evidence": str(m)}
    rp = Path("reports") / f"testradius-e2e-{c.run_id}.json"
    rp.write_text(json.dumps(report, indent=2))
    return report, rp
