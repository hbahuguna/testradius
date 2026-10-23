"""The cell's complete external surface.

Only these routes may ever be registered. The architecture test compares the
live FastAPI router against this set, so adding an endpoint without updating
the contract fails CI. A route outside ``/v1/`` is never acceptable.
"""

CONTRACT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/v1/runs"),
        ("GET", "/v1/runs/{run_id}"),
        ("GET", "/v1/runs/{run_id}/events"),
        ("POST", "/v1/runs/{run_id}/cancel"),
        ("GET", "/v1/runs/{run_id}/evidence"),
        ("GET", "/v1/health"),
        ("POST", "/v1/policy/reload"),
    }
)

# Routes implemented so far, story by story. Sprint 1 delivers health only;
# Sprint 2 adds run lifecycle, events, cancel and policy reload.
EXPECTED_REGISTERED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/v1/health"),
    }
)
