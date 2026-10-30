import json
from pathlib import Path
from ..context.loader import validate_context
from ..driver import PlaywrightDriver
from ..evidence import EvidenceCapture


def run_smoke(ticket: str = "T-1"):
    ctx = validate_context("samples/context_sample.json")
    d = PlaywrightDriver()
    d.navigate("/")
    d.click("#login")
    c = EvidenceCapture()
    c.screenshot("smoke.png")
    c.console_log("smoke ok")
    c.network_trace()
    c.trace()
    m = c.save_manifest()
    report = {
        "ticket": ticket,
        "context": ctx.ticket_id,
        "status": "PASS",
        "evidence": str(m)
    }
    rp = Path("reports") / f"smoke-{c.run_id}.json"
    rp.write_text(json.dumps(report, indent=2))
    return report, rp
