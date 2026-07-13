from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class InteractiveElement:
    tag: str
    type: Optional[str] = None
    label: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    placeholder: Optional[str] = None
    text: Optional[str] = None
    href: Optional[str] = None
    aria_label: Optional[str] = None


@dataclass
class PageSnapshot:
    url: str
    title: str
    elements: List[InteractiveElement] = field(default_factory=list)
    a11y_tree: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "elements": [asdict(e) for e in self.elements],
            "a11y_tree": self.a11y_tree,
            "viewport": self.viewport,
        }


_INTERACTIVE_SELECTOR = ", ".join([
    "button",
    "input",
    "select",
    "textarea",
    'a[href]',
    '[role="button"]',
    '[role="link"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="tab"]',
    '[role="combobox"]',
    '[role="listbox"]',
    '[role="option"]',
    '[role="menuitem"]',
    '[role="slider"]',
    '[role="switch"]',
    '[role="textbox"]',
    '[role="searchbox"]',
    '[role="spinbutton"]',
    '[role="treeitem"]',
    '[contenteditable="true"]',
])

_EXTRACT_ELEMENTS_JS = f"""
() => {{
    const seen = new Set();
    function ariaRole(el) {{
        const explicit = el.getAttribute && el.getAttribute('role');
        if (explicit) return explicit;
        const tag = (el.tagName || '').toLowerCase();
        if (tag === 'select') return 'combobox';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'img') return 'img';
        if (tag === 'input') {{
            const t = (el.getAttribute('type') || 'text').toLowerCase();
            if (t === 'checkbox') return 'checkbox';
            if (t === 'radio') return 'radio';
            return 'textbox';
        }}
        return tag;
    }}
    return [...document.querySelectorAll('{_INTERACTIVE_SELECTOR}')].filter(el => {{
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        if (rect.width === 0 || rect.height === 0) return false;
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return true;
    }}).map(el => {{
        const key = el.tagName + (el.id || '') + (el.name || '') + (el.textContent || '').trim().slice(0, 30);
        if (seen.has(key)) return null;
        seen.add(key);
        const label = el.labels?.[0]?.textContent?.trim()
            || el.getAttribute('aria-label')
            || el.placeholder
            || el.textContent?.trim().slice(0, 80)
            || '';
        return {{
            tag: el.tagName,
            type: el.type || null,
            label: label.slice(0, 120),
            id: el.id || null,
            name: el.getAttribute('name') || null,
            role: ariaRole(el),
            placeholder: el.placeholder || null,
            text: (el.textContent || '').trim().slice(0, 80) || null,
            href: el.getAttribute('href') || null,
            aria_label: el.getAttribute('aria-label') || null,
        }};
    }}).filter(Boolean);
}}
"""

_PAGE_TEXT_JS = """() => {
    const main = document.querySelector('main, [role="main"], article, .content, #content');
    const target = main || document.body;
    const clone = target.cloneNode(true);
    clone.querySelectorAll('script, style, nav, footer, header, aside, .sidebar').forEach(el => el.remove());
    return (clone.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 5000);
}"""


async def extract_interactive_elements(page: Any) -> List[Dict[str, Any]]:
    return await page.evaluate(_EXTRACT_ELEMENTS_JS)


async def extract_a11y_tree(page: Any) -> Optional[Dict[str, Any]]:
    try:
        return await page.accessibility.snapshot()
    except Exception:
        return None


class PageScraper:
    def __init__(
        self,
        headless: bool = True,
        viewport: Optional[Dict[str, int]] = None,
        timeout_ms: int = 30000,
    ):
        self._headless = headless
        self._viewport = viewport or {"width": 1280, "height": 720}
        self._timeout_ms = timeout_ms
        self._browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        await self._pw.stop()

    async def scrape(
        self,
        url: str,
        wait_until: str = "networkidle",
        extra_wait_ms: Optional[int] = None,
        auth_cookies: Optional[List[Dict[str, Any]]] = None,
    ) -> PageSnapshot:
        if not self._browser:
            raise RuntimeError("use 'async with PageScraper() as scraper:'")

        context = await self._browser.new_context(viewport=self._viewport)
        if auth_cookies:
            await context.add_cookies(auth_cookies)

        page = await context.new_page()
        page.set_default_timeout(self._timeout_ms)

        try:
            await page.goto(url, wait_until=wait_until, timeout=self._timeout_ms)

            if extra_wait_ms:
                await asyncio.sleep(extra_wait_ms / 1000)

            title = await page.title()
            elements = await extract_interactive_elements(page)
            a11y_tree = await extract_a11y_tree(page)
            text_content = await page.evaluate(_PAGE_TEXT_JS)
            vp = self._viewport

            return PageSnapshot(
                url=url,
                title=title,
                elements=[InteractiveElement(**el) for el in elements],
                a11y_tree=a11y_tree,
                text_content=text_content[:5000] if text_content else None,
                viewport=vp,
            )
        finally:
            await context.close()
