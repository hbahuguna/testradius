from .client import VisionClient


class SelfInspector:
    def __init__(self, rounds: int = 2):
        self.rounds = rounds
        self.v = VisionClient()

    def inspect(self, screenshot: str):
        log = []
        findings = []
        for r in range(1, self.rounds + 1):
            f = self.v.inspect(screenshot)
            log.append({"round": r, "findings": f})
            findings.extend(f)
        deduped = []
        seen = set()
        for x in findings:
            k = x["type"]
            if k in seen:
                continue
            seen.add(k)
            deduped.append(x)
        return {"rounds": log, "deduped": deduped}
