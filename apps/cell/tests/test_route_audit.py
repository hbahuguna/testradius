from collections.abc import Iterator

from cell.contracts import CONTRACT_ROUTES, EXPECTED_REGISTERED_ROUTES
from cell.main import create_app


def iter_route_pairs(routes, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Flatten FastAPI's lazy router tree into (method, path) pairs."""

    for route in routes:
        include_context = getattr(route, "include_context", None)
        if include_context is not None:
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from iter_route_pairs(
                    nested.routes, prefix + (getattr(include_context, "prefix", "") or "")
                )
            continue

        nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            yield from iter_route_pairs(nested_routes, prefix)
            continue

        for method in getattr(route, "methods", set()) or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            yield method, prefix + route.path


def registered_routes() -> set[tuple[str, str]]:
    return set(iter_route_pairs(create_app().routes))


def test_registered_routes_equal_the_story_allowlist() -> None:
    assert registered_routes() == set(EXPECTED_REGISTERED_ROUTES)


def test_no_route_outside_the_contract_exists() -> None:
    outside = registered_routes() - set(CONTRACT_ROUTES)

    assert not outside, f"routes outside the cell contract: {sorted(outside)}"


def test_every_route_is_under_v1() -> None:
    for _method, path in registered_routes():
        assert path.startswith("/v1/"), path
