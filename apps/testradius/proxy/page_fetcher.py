import httpx


class PageFetcher:
    """Fetches page HTML via HTTP proxy."""

    def __init__(self):
        self._client = httpx.AsyncClient(follow_redirects=True, timeout=30)

    async def fetch(self, url: str) -> dict:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return {
                "success": True,
                "url": str(response.url),
                "status": response.status_code,
                "headers": dict(response.headers),
                "html": response.text,
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
        except httpx.RequestError as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        await self._client.aclose()
