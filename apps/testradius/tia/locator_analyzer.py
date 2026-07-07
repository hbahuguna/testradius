import re
from typing import Any, Optional


class LocatorSuggester:
    """Suggests stable Playwright locators for page elements.

    Uses heuristic rules by default. If a QwenClient is provided, it also
    returns model-generated locator suggestions.
    """

    def __init__(self, qwen_client=None):
        self.qwen = qwen_client

    def suggest(self, html: str = "", element_description: str = "") -> dict[str, Any]:
        suggestions = []

        if html:
            suggestions.extend(self._from_html(html))
        if element_description:
            suggestions.extend(self._from_description(element_description))
            if self.qwen:
                suggestions.extend(self._from_qwen(element_description))

        return {
            "suggestions": suggestions,
            "total": len(suggestions),
        }

    def _from_html(self, html: str) -> list[dict]:
        results = []
        seen = set()

        buttons = re.findall(
            r'<button[^>]*>([^<]+)</button>',
            html, re.IGNORECASE,
        )
        for text in buttons:
            text = text.strip()
            if text and text not in seen:
                seen.add(text)
                results.append({
                    "locator": f'page.getByRole("button", {{ name: "{text}" }})',
                    "type": "getByRole",
                    "target": text,
                    "reason": "Accessible role + name is the most resilient locator",
                })

        labels = re.findall(
            r'<label[^>]*>([^<]+)</label>',
            html, re.IGNORECASE,
        )
        for text in labels:
            text = text.strip()
            if text and text not in seen:
                seen.add(text)
                results.append({
                    "locator": f'page.getByLabel("{text}")',
                    "type": "getByLabel",
                    "target": text,
                    "reason": "getByLabel links to the associated input via for/id",
                })

        placeholders = re.findall(
            r'placeholder=["\']([^"\']+)["\']',
            html,
        )
        for ph in placeholders:
            if ph not in seen:
                seen.add(ph)
                results.append({
                    "locator": f'page.getByPlaceholder("{ph}")',
                    "type": "getByPlaceholder",
                    "target": ph,
                    "reason": "Placeholder text is stable if it doesn't change",
                })

        alt_texts = re.findall(
            r'alt=["\']([^"\']+)["\']',
            html,
        )
        for alt in alt_texts:
            if alt not in seen:
                seen.add(alt)
                results.append({
                    "locator": f'page.getByAltText("{alt}")',
                    "type": "getByAltText",
                    "target": alt,
                    "reason": "Alt text is accessible and stable",
                })

        test_ids = re.findall(
            r'data-testid=["\']([^"\']+)["\']',
            html,
        )
        for tid in test_ids:
            if tid not in seen:
                seen.add(tid)
                results.append({
                    "locator": f'page.getByTestId("{tid}")',
                    "type": "getByTestId",
                    "target": tid,
                    "reason": "data-testid is the most stable — intentionally added for testing",
                })

        return results

    def _from_description(self, desc: str) -> list[dict]:
        results = []
        desc_lower = desc.lower()

        if "button" in desc_lower or "link" in desc_lower or "click" in desc_lower:
            name = self._extract_name(desc)
            if name:
                results.append({
                    "locator": f'page.getByRole("button", {{ name: "{name}" }})',
                    "type": "getByRole (button)",
                    "target": name,
                    "reason": "Accessible role + name is preferred for buttons and links",
                })
                results.append({
                    "locator": f'page.locator("text={name}")',
                    "type": "text selector",
                    "target": name,
                    "reason": "Text selector as fallback if getByRole isn't supported",
                })

        if "input" in desc_lower or "field" in desc_lower or "text" in desc_lower or "type" in desc_lower:
            name = self._extract_name(desc)
            if name:
                results.append({
                    "locator": f'page.getByRole("textbox", {{ name: "{name}" }})',
                    "type": "getByRole (textbox)",
                    "target": name,
                    "reason": "Accessible role for text input fields",
                })
                results.append({
                    "locator": f'page.getByLabel("{name}")',
                    "type": "getByLabel",
                    "target": name,
                    "reason": "getByLabel works when label element is properly associated",
                })

        return results

    def _from_qwen(self, desc: str) -> list[dict]:
        if not self.qwen:
            return []
        prompt = (
            "You are an expert in Playwright test automation. "
            "Given this element description, suggest the 3 most stable locators:\n\n"
            f"Element: {desc}\n\n"
            "Return just the locator expressions, one per line, prefixed by priority: 1, 2, 3."
        )
        try:
            response = self.qwen.infer(prompt)
            text = response.get("response", "") if isinstance(response, dict) else str(response)
            results = []
            for line in text.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    results.append({
                        "locator": line.split(" ", 1)[-1] if line[0].isdigit() else line,
                        "type": "qwen-suggested",
                        "target": desc,
                        "reason": "Suggested by fine-tuned SDET model",
                    })
            return results
        except Exception:
            return []

    @staticmethod
    def _extract_name(text: str) -> Optional[str]:
        quotes = re.findall(r'[""]([^""]+)[""]', text)
        if quotes:
            return quotes[0]
        words = re.findall(r'"([^"]+)"', text)
        if words:
            return words[0]
        return None
