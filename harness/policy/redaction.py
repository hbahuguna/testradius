"""Secret redaction for logs and artifacts."""
from __future__ import annotations

import re
from typing import Dict


PATTERNS = {
    "api_key": re.compile(r"(?i)\b(api[_-]?key|apikey)\b\s*[:= ]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?"),
    "bearer": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*"),
    "aws": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "token": re.compile(r"(?i)\b(token|secret|password|passwd|access[_-]?token|refresh[_-]?token)\b\s*[:= ]\s*['\"]?([^\s'\",;]{8,})['\"]?"),
}


class Redactor:
    def __init__(self, patterns: Dict[str, re.Pattern] | None = None, replacement: str = "[REDACTED]"):
        self.patterns = patterns or PATTERNS
        self.replacement = replacement

    def redact(self, text: str) -> str:
        if not text:
            return text
        result = text
        for name, pat in self.patterns.items():
            result = pat.sub(self.replacement, result)
        return result

    def redact_dict(self, d: Dict) -> Dict:
        out = {}
        for k, v in d.items():
            if isinstance(v, str):
                out[k] = self.redact(v)
            elif isinstance(v, dict):
                out[k] = self.redact_dict(v)
            elif isinstance(v, list):
                out[k] = [self.redact(x) if isinstance(x, str) else x for x in v]
            else:
                out[k] = v
        return out
