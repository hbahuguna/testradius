from ..context.loader import validate_context


class RiskPlanner:
    def generate(self, ctx_path: str = "samples/context_sample.json"):
        c = validate_context(ctx_path)
        plan = {
            "ticket": c.ticket_id,
            "priority": [
                {"area": "login", "risk": "high", "rationale": "auth critical"},
                {"area": "errors", "risk": "med", "rationale": "UX"},
            ],
            "coverage_gaps": []
        }
        return plan
