from bs4 import BeautifulSoup, Tag


INTERACTIVE_TAGS = {"a", "button", "input", "textarea", "select", "details", "summary"}
INPUT_TYPES = {"text", "email", "password", "search", "url", "number", "checkbox", "radio", "file"}


class DOMAnalyzer:
    """Parses HTML and extracts interactive elements for test generation."""

    def analyze(self, html: str, url: str = "") -> dict:
        soup = BeautifulSoup(html, "lxml")
        elements = self._extract_interactive(soup)
        return {
            "url": url,
            "title": soup.title.string.strip() if soup.title and soup.title.string else "",
            "element_count": len(elements),
            "elements": elements,
        }

    def _extract_interactive(self, soup: BeautifulSoup) -> list[dict]:
        results = []
        seen = set()

        for el in soup.find_all(INTERACTIVE_TAGS):
            tag = el.name
            el_type = el.get("type", "") if isinstance(el, Tag) else ""
            text = el.get_text(strip=True) if isinstance(el, Tag) else ""

            if tag == "input" and el_type not in INPUT_TYPES:
                continue

            selector = self._build_css_selector(el)
            dedup_key = (tag, text, selector)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            item = {
                "tag": tag,
                "type": el_type if tag == "input" else "",
                "text": text,
                "selector": selector,
                "attributes": dict(el.attrs) if isinstance(el, Tag) else {},
            }

            if tag == "a":
                item["href"] = el.get("href", "")
            elif tag in ("input", "textarea"):
                item["name"] = el.get("name", "")
                item["placeholder"] = el.get("placeholder", "")
                item["value"] = el.get("value", "")

            results.append(item)

        return results

    def _build_css_selector(self, el: Tag) -> str:
        parts = []

        if el.get("id"):
            return f"#{el['id']}"

        tag = el.name
        classes = el.get("class", [])
        selector = tag
        if classes:
            selector += "." + ".".join(classes)
        parts.append(selector)

        parent = el.parent
        while parent and parent.name not in (None, "html", "body"):
            sibling = parent.find_previous_sibling(parent.name)
            if sibling is not None:
                idx = 1
                for i, child in enumerate(parent.parent.find_all(parent.name, recursive=False)):
                    if child is parent:
                        break
                parts.insert(0, f"{parent.name}:nth-of-type({i + 1})")
            else:
                parts.insert(0, parent.name)
            parent = parent.parent

        return " > ".join(parts)
