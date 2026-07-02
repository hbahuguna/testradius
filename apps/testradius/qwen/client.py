import httpx


QWEN_API_URL = "https://hbahuguna--qwen-3-8b-sdet-qwensdet-generate.modal.run"


class QwenClient:
    """Client for the fine-tuned Qwen3-8B SDET model on Modal."""

    def __init__(self, api_url: str = QWEN_API_URL, timeout: int = 60):
        self.api_url = api_url
        self._client = httpx.Client(timeout=timeout)

    def infer(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        try:
            resp = self._client.post(
                f"{self.api_url}/generate",
                json={"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except httpx.RequestError as e:
            return f"[Qwen error: {e}]"

    def health(self) -> bool:
        try:
            resp = self._client.get(f"{self.api_url}/health")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def close(self):
        self._client.close()
