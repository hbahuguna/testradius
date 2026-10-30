from harness.policy.egress import EgressBlocked, EgressPolicy
from harness.policy.redaction import Redactor


def test_redact_api_key():
    r = Redactor()
    text = "GEMINI_API_KEY=sk-abc123def456ghi789jkl"
    out = r.redact(text)
    assert "sk-abc123def456" not in out
    assert "[REDACTED]" in out


def test_redact_bearer():
    r = Redactor()
    out = r.redact("Authorization: Bearer ya29.a0AfH6SMB...")
    assert "ya29" not in out


def test_egress_allows_testradius():
    p = EgressPolicy()
    assert p.is_allowed("https://testradius.dev/") is True
    assert p.enforce("https://www.testradius.dev/page") is True


def test_egress_blocks_unknown():
    p = EgressPolicy()
    try:
        p.enforce("https://evil.example.com/exfil")
        assert False
    except EgressBlocked:
        pass


def test_egress_allows_subdomains():
    p = EgressPolicy()
    assert p.is_allowed("https://api.testradius.dev/v1") is True
