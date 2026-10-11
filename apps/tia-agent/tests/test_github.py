"""E3/T3: GitHub PR intake client + source-file filtering (httpx MockTransport)."""

import httpx
import pytest

from tia_agent.errors import GitHubAuthError, GitHubError
from tia_agent.tools.github import (
    GitHubClient,
    PrFile,
    filter_source_files,
    is_source_file,
)


def _client(handler, token="tok"):
    return GitHubClient(
        token=token, base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )


# ---------------------------------------------------------------------------
# source-file filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "src/key_value/aio/_utils/time_to_live.py",
    "tests/test_ttl.py",
    "src/cart.ts",
    "tests/home.spec.ts",
    "backend/main.go",
])
def test_is_source_file_accepts_source(path):
    assert is_source_file(path)


@pytest.mark.parametrize("path", [
    "",
    "node_modules/left-pad/index.js",
    "vendor/github.com/pkg/errors/errors.go",
    "dist/bundle.js",
    "build/out.js",
    "docs/guide.md",
    "README.md",
    "assets/logo.png",
    ".git/config",
    "package-lock.json",
    "poetry.lock",
    "src/.hidden.py",
    "config/settings.yaml",
])
def test_is_source_file_rejects_non_source(path):
    assert not is_source_file(path)


def test_filter_source_files_dedupes_and_orders():
    files = [
        PrFile("src/a.py", "modified"),
        PrFile("README.md", "modified"),
        PrFile("src/a.py", "modified"),          # duplicate
        PrFile("src/b.py", "added"),
        PrFile("src/old.py", "removed"),         # deleted -> skipped
        PrFile("node_modules/x.js", "added"),
    ]
    assert filter_source_files(files) == ["src/a.py", "src/b.py"]


def test_pr_file_from_raw():
    f = PrFile.from_raw(
        {"filename": "src/a.py", "status": "added", "additions": 3, "deletions": 1}
    )
    assert (f.filename, f.status, f.additions, f.deletions) == ("src/a.py", "added", 3, 1)
    assert f.to_dict()["filename"] == "src/a.py"


# ---------------------------------------------------------------------------
# GitHubClient
# ---------------------------------------------------------------------------

def _files_response(items):
    return httpx.Response(200, json=items)


def test_get_pr_files_parses_fields():
    def handler(request):
        assert request.url.path == "/repos/acme/shop/pulls/42/files"
        assert request.url.params["per_page"] == "100"
        return _files_response([
            {"filename": "src/a.py", "status": "modified", "additions": 2, "deletions": 0},
            {"filename": "docs/x.md", "status": "added", "additions": 9, "deletions": 0},
        ])

    with _client(handler) as gh:
        files = gh.get_pr_files("acme/shop", 42)
    assert [f.filename for f in files] == ["src/a.py", "docs/x.md"]
    assert files[0].additions == 2


def test_get_pr_files_paginates():
    seen_pages = []

    def handler(request):
        page = int(request.url.params["page"])
        seen_pages.append(page)
        if page == 1:
            return _files_response([{"filename": f"src/f{i}.py"} for i in range(100)])
        return _files_response([{"filename": "src/last.py"}])

    with _client(handler) as gh:
        files = gh.get_pr_files("acme/shop", 1)
    assert len(files) == 101
    assert seen_pages == [1, 2]


def test_get_pr_changed_files_filters():
    def handler(request):
        return _files_response([
            {"filename": "src/a.py", "status": "modified"},
            {"filename": "README.md", "status": "modified"},
            {"filename": "src/b.py", "status": "removed"},
        ])

    with _client(handler) as gh:
        assert gh.get_pr_changed_files("acme/shop", 1) == ["src/a.py"]


def test_401_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"message": "Bad credentials"})

    with _client(handler) as gh:
        with pytest.raises(GitHubAuthError) as e:
            gh.get_pr_files("acme/shop", 1)
    assert e.value.needs_token is True


def test_404_raises_error():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    with _client(handler) as gh:
        with pytest.raises(GitHubError):
            gh.get_pr_files("acme/private", 1)


def test_403_rate_limit_without_token_is_auth_error():
    def handler(request):
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"},
                              json={"message": "rate limit"})

    with _client(handler, token="") as gh:
        with pytest.raises(GitHubAuthError):
            gh.get_pr_files("acme/shop", 1)


def test_403_with_token_is_plain_error():
    def handler(request):
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"},
                              json={"message": "rate limit"})

    with _client(handler, token="tok") as gh:
        with pytest.raises(GitHubError) as e:
            gh.get_pr_files("acme/shop", 1)
    assert not isinstance(e.value, GitHubAuthError)


def test_get_repo_and_is_private():
    def handler(request):
        assert request.url.path == "/repos/acme/shop"
        return httpx.Response(200, json={"full_name": "acme/shop", "private": True})

    with _client(handler) as gh:
        assert gh.get_repo("acme/shop")["full_name"] == "acme/shop"
        assert gh.is_private("acme/shop") is True


def test_network_error_is_wrapped():
    def handler(request):
        raise httpx.ConnectError("nope", request=request)

    with _client(handler) as gh:
        with pytest.raises(GitHubError):
            gh.get_pr_files("acme/shop", 1)
