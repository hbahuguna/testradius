import base64

import pytest


class TestProxyEndpoint:

    async def test_proxy_virtual_missing_path(self, client):
        response = await client.get("/v/")
        assert response.status_code == 400

    async def test_proxy_virtual_invalid_encoded_base(self, client):
        response = await client.get("/v/not-valid-base64/anything")
        assert response.status_code == 400

    async def test_proxy_virtual_unreachable(self, client):
        encoded = base64.urlsafe_b64encode(b"http://localhost:1").decode("ascii")
        response = await client.get(f"/v/{encoded}/")
        assert response.status_code in (502, 504)

    async def test_proxy_virtual_rewrites_links(self, client):
        encoded = base64.urlsafe_b64encode(b"https://example.com").decode("ascii")
        response = await client.get(f"/v/{encoded}/some-page")
        assert response.status_code in (200, 502, 504)
        if response.status_code == 200:
            html = response.text
            assert "/v/" in html
            assert encoded in html
            assert "ts-element-click" in html

    async def test_proxy_encode_roundtrip(self, client):
        import urllib.parse
        urls = [
            "https://testradius.dev",
            "https://example.com/path/to/page",
            "http://localhost:3000/",
        ]
        for url in urls:
            encoded = base64.urlsafe_b64encode(url.rstrip("/").encode("utf-8")).decode("ascii")
            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
            assert decoded == url.rstrip("/")


class TestPreviewEndpoint:
    async def test_preview_local_file(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "<html" in html
        assert "ts-inspect-highlight" in html
        assert "ts-element-click" in html
        assert "id=\"login\"" in html or "id='login'" in html

    async def test_preview_missing_file(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///tmp/nonexistent.html"},
        )
        assert response.status_code == 400

    async def test_preview_invalid_url(self, client):
        response = await client.get(
            "/preview",
            params={"url": "not-a-url"},
        )
        assert response.status_code == 400

    async def test_preview_missing_param(self, client):
        response = await client.get("/preview")
        assert response.status_code == 422

    async def test_preview_svg_elements(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///private/tmp/test-page-edge-cases.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "test-svg" in html
        assert "svg-rect" in html or "svg-rect" in html
        assert "svg-circle" in html or "svg-circle" in html
        assert "getCssPath" in html

    async def test_preview_script_element_skipped(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///private/tmp/test-page-edge-cases.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "skipTags" in html
        assert "script" in html or "script" in html

    async def test_preview_shadow_dom_detection(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///private/tmp/test-page-edge-cases.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "ShadowRoot" in html
        assert "inShadowDOM" in html
        assert "shadow-host" in html

    async def test_preview_script_injected_once(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 200
        html = response.text
        count = html.count("ts-element-click")
        assert count == 1, f"Expected 1 inspector script, found {count}"

    async def test_preview_file_uses_absolute_rewrite_not_proxy(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "/proxy?url=" not in html, "file:// URLs should use absolute URL rewrite, not proxy"

    async def test_preview_file_has_base_tag(self, client):
        response = await client.get(
            "/preview",
            params={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 200
        html = response.text
        assert "base" in html
        assert "file:///tmp/test-page.html" in html
        assert "/proxy?url=" not in html
