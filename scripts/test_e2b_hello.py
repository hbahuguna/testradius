#!/usr/bin/env python3
"""Hello world test for E2B sandbox.

Self-hosted: set E2B_DOMAIN=<domain>:3002 (e.g. 8.231.230.69.nip.io:3002).
"""
import os
import time

from e2b import Sandbox
from e2b import connection_config as _e2b_cc

# HTTP patch for self-hosted proxy with domain:port
if not getattr(_e2b_cc, "_tr_http_patched", False):
    _orig_host = _e2b_cc.ConnectionConfig.get_host

    def _http_url(self, sandbox_id, sandbox_domain, port=None):
        port = self.envd_port if port is None else port
        if self._sandbox_url:
            return self._sandbox_url
        host = _orig_host(self, sandbox_id, sandbox_domain, port)
        return f"http://{host}"

    _e2b_cc.ConnectionConfig.get_sandbox_url = _http_url
    _e2b_cc.ConnectionConfig.get_sandbox_direct_url = _http_url
    _e2b_cc._tr_http_patched = True


def main():
    kwargs = {"timeout": 300}
    domain = os.environ.get("E2B_DOMAIN")
    if domain:
        kwargs["domain"] = domain
    print(f"Creating sandbox (domain={domain})...")
    sandbox = Sandbox.create(**kwargs)
    print(f"Sandbox created: {sandbox.sandbox_id} host={sandbox.get_host(49983)}")
    try:
        time.sleep(10)
        result = sandbox.commands.run('echo "Hello from the Manual QA Harness!"', timeout=60)
        out = getattr(result, "stdout", "") or ""
        print(f"Command output: {out.strip()}")
        if "Hello from the Manual QA Harness" not in out:
            raise RuntimeError(f"Unexpected output: {out!r}")
        print("✓ Command execution OK")
    finally:
        sandbox.kill()
        print("Sandbox killed.")


if __name__ == "__main__":
    main()
