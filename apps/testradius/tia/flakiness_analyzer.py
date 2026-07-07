import re
from typing import Any


class FlakinessAnalyzer:
    """Static analysis of test code for common flakiness patterns."""

    PATTERNS: list[dict[str, Any]] = [
        {
            "id": "hardcoded-wait",
            "name": "Hardcoded sleep/wait",
            "severity": "high",
            "description": "Hardcoded wait detected. Prefer waitForSelector, waitForLoadState, or locator.waitFor() over fixed timeouts.",
            "pattern": re.compile(
                r"(?:timeout|sleep|waitForTimeout)\s*\(\s*\d{4,}",
                re.IGNORECASE,
            ),
        },
        {
            "id": "fragile-sleep",
            "name": "Short fragile sleep",
            "severity": "medium",
            "description": "Short sleep may cause flakiness on slow environments. Use automatic waiting instead.",
            "pattern": re.compile(
                r"(?:timeout|sleep|waitForTimeout)\s*\(\s*\d{1,3}\)",
                re.IGNORECASE,
            ),
        },
        {
            "id": "missing-assertion",
            "name": "Missing assertion after navigation",
            "severity": "high",
            "description": "Navigation without assertion. Add expect(page).toHaveURL() or expect(locator).toBeVisible() after navigation.",
            "pattern": re.compile(
                r"(?:goto|click|press)\s*\([^)]*\)(?:\s*;)?\s*\n(?!(?:\s*//.*\n)*\s*(?:expect|await\s+expect|\.waitFor|waitFor))",
            ),
        },
        {
            "id": "non-unique-selector",
            "name": "Potentially non-unique selector",
            "severity": "medium",
            "description": "Generic tag or class selector may match multiple elements. Use getByRole, getByTestId, or a more specific selector.",
            "pattern": re.compile(
                r'(?:page|locator|frame)\.(?:locator|querySelector)\s*\(\s*["\'](?:div|span|a|button|input|\.\w+|\w+)\s*["\']',
                re.IGNORECASE,
            ),
        },
        {
            "id": "missing-await",
            "name": "Missing await on async action",
            "severity": "critical",
            "description": "Async action without await. Add 'await' keyword before the action.",
            "pattern": re.compile(
                r"(?<!\bawait\s)(?:page|locator|frame|expect|response)\.(?!(?:on|once|addListener))"
                r"(?:click|fill|type|press|goto|check|uncheck|selectOption|hover|focus|blur|dblclick|tripleclick)\s*\(",
            ),
        },
        {
            "id": "to-contain-text-assertion",
            "name": "toContainText may match partial text",
            "severity": "low",
            "description": "toContainText matches substrings. Use toHaveText for exact match if the full text is known.",
            "pattern": re.compile(
                r"toContainText\s*\(",
                re.IGNORECASE,
            ),
        },
    ]

    def analyze(self, code: str, filename: str = "test") -> dict[str, Any]:
        issues = []
        for pat in self.PATTERNS:
            matches = list(pat["pattern"].finditer(code))
            for m in matches:
                line_num = code[: m.start()].count("\n") + 1
                snippet = code[max(0, m.start() - 20) : m.end() + 20].strip()
                issues.append({
                    "id": pat["id"],
                    "name": pat["name"],
                    "severity": pat["severity"],
                    "description": pat["description"],
                    "line": line_num,
                    "snippet": snippet,
                })

        severities = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for i in issues:
            severities[i["severity"]] += 1

        score = 10
        score -= severities["critical"] * 3
        score -= severities["high"] * 2
        score -= severities["medium"] * 1
        score -= severities["low"] * 0.5
        score = max(0, min(10, round(score, 1)))

        return {
            "file": filename,
            "analyzed_lines": len(code.splitlines()),
            "total_issues": len(issues),
            "flakiness_score": score,
            "severity_counts": severities,
            "issues": issues,
        }
