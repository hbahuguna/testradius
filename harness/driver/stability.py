"""Playwright stability helpers: waits, navigation safety, error handling."""
from __future__ import annotations

from typing import Optional


DEFAULT_TIMEOUT_MS = 30000
NAVIGATION_TIMEOUT_MS = 60000


class NavigationError(Exception):
    pass


class StabilityConfig:
    def __init__(
        self,
        default_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        navigation_timeout_ms: int = NAVIGATION_TIMEOUT_MS,
        wait_for_network_idle: bool = True,
        wait_for_dom_content_loaded: bool = True,
        retries_on_nav: int = 2,
    ):
        self.default_timeout_ms = default_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.wait_for_network_idle = wait_for_network_idle
        self.wait_for_dom_content_loaded = wait_for_dom_content_loaded
        self.retries_on_nav = retries_on_nav


async def safe_goto(page, url: str, config: Optional[StabilityConfig] = None):
    config = config or StabilityConfig()
    page.set_default_timeout(config.default_timeout_ms)
    last_exc = None
    for attempt in range(config.retries_on_nav + 1):
        try:
            await page.goto(url, timeout=config.navigation_timeout_ms, wait_until="domcontentloaded")
            if config.wait_for_network_idle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            return page
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise NavigationError(f"Failed to navigate to {url}: {last_exc}") from last_exc
    raise NavigationError(f"Failed to navigate to {url}")


async def safe_wait_for_selector(page, selector: str, config: Optional[StabilityConfig] = None, **kwargs):
    config = config or StabilityConfig()
    timeout = kwargs.pop("timeout", config.default_timeout_ms)
    return await page.wait_for_selector(selector, timeout=timeout, **kwargs)


async def safe_click(page, selector: str, config: Optional[StabilityConfig] = None, **kwargs):
    config = config or StabilityConfig()
    timeout = kwargs.pop("timeout", config.default_timeout_ms)
    await page.wait_for_selector(selector, timeout=timeout, state="visible")
    return await page.click(selector, timeout=timeout, **kwargs)


def with_auto_wait():
    """Return recommended Playwright context options for stability."""
    return {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
        "java_script_enabled": True,
    }
