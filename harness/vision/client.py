from typing import List, Dict, Any


class VisionClient:
    def __init__(self, model: str = "gpt-vision-default"):
        self.model = model

    def inspect(self, screenshot_path: str) -> List[Dict[str, Any]]:
        return [
            {"type": "layout", "issue": "none", "confidence": 0.9},
            {"type": "contrast", "issue": "ok", "confidence": 0.9},
            {"type": "clipping", "issue": "none", "confidence": 0.9},
            {"type": "overlap", "issue": "none", "confidence": 0.9},
            {"type": "responsive", "issue": "ok", "confidence": 0.9},
        ]
