import json
import os


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            return json.dumps({"plan": ["Navigate to site", "Check homepage", "Capture evidence"], "note": "no_api_key_fallback"})
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(model=self.model, contents=prompt)
            text = getattr(resp, "text", None) or str(resp)
            return text
        except Exception as e:
            return json.dumps({"error": str(e), "fallback": ["Navigate", "Observe", "Capture"]})
