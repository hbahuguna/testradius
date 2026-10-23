import base64
import json

from cell.runs.tokens import RunTokenManager, extract_bearer_token


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_token_is_a_run_scoped_hs256_jwt():
    manager = RunTokenManager("unit-secret", ttl_seconds=60, issuer="cp", audience="cell")

    token, expires_at = manager.issue("run_abc")
    claims = _claims(token)

    assert claims["iss"] == "cp"
    assert claims["aud"] == "cell"
    assert claims["sub"] == "run_abc"
    assert claims["scope"] == "run"
    assert claims["jti"]
    assert int(expires_at.timestamp()) == claims["exp"]
    assert manager.validate(token, "run_abc")
    assert not manager.validate(token, "run_other")


def test_expired_and_tampered_tokens_are_rejected():
    manager = RunTokenManager("unit-secret", ttl_seconds=-1)
    expired, _ = manager.issue("run_abc")
    assert not manager.validate(expired, "run_abc")

    manager = RunTokenManager("unit-secret", ttl_seconds=60)
    token, _ = manager.issue("run_abc")
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}AA"
    assert not manager.validate(tampered, "run_abc")
    assert not manager.validate("not-a-token", "run_abc")


def test_extract_bearer_token():
    assert extract_bearer_token("Bearer abc") == "abc"
    assert extract_bearer_token("bearer abc") == "abc"
    assert extract_bearer_token("Basic abc") is None
    assert extract_bearer_token(None) is None
