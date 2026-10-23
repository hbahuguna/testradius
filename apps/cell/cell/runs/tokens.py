"""Run-scoped tokens (ADR-003): HS256 JWT, short TTL, verified locally.

We build the JWT with the standard library so the cell does not need a crypto
wheel; the claims still match the ADR (iss/aud/sub/scope/exp/jti). Tokens are
bound to one run and cannot authorize a different run id.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class TokenError(Exception):
    pass


class RunTokenManager:
    def __init__(
        self,
        secret: str | None = None,
        ttl_seconds: int = 3600,
        issuer: str = "testradius-control-plane",
        audience: str = "testradius-cell",
    ):
        self._secret = (
            secret or os.environ.get("CELL_RUN_TOKEN_SECRET") or "dev-only-run-token-secret"
        ).encode("utf-8")
        self.ttl_seconds = ttl_seconds
        self.issuer = issuer
        self.audience = audience

    def _sign(self, signing_input: str) -> str:
        digest = hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return _b64url(digest)

    def issue(self, run_id: str) -> tuple[str, datetime]:
        expires = int(time.time()) + self.ttl_seconds
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": run_id,
            "scope": "run",
            "exp": expires,
            "jti": secrets.token_hex(8),
        }
        payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}"
        token = f"{signing_input}.{self._sign(signing_input)}"
        return token, datetime.fromtimestamp(expires, tz=UTC)

    def validate(self, token: str, run_id: str) -> bool:
        try:
            header_b64, payload_b64, signature = token.split(".")
            expected = self._sign(f"{header_b64}.{payload_b64}")
            if not hmac.compare_digest(signature, expected):
                return False
            header = json.loads(_b64url_decode(header_b64))
            claims = json.loads(_b64url_decode(payload_b64))
        except (
            AttributeError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
        ):
            return False
        if header.get("alg") != "HS256":
            return False
        if claims.get("sub") != run_id or claims.get("aud") != self.audience:
            return False
        if claims.get("iss") != self.issuer or "run" not in str(claims.get("scope", "")).split():
            return False
        try:
            expires = int(claims.get("exp", 0))
        except (TypeError, ValueError):
            return False
        return expires >= int(time.time())


def extract_bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
