"""Browser interaction tools: the agent's hands for live UI exploration.

Wraps Playwright in a persistent browser session and exposes synchronous tool
functions suitable for the ``ToolRegistry``. Interaction uses accessible
locators (``getByRole`` / ``getByLabel`` / ``getByText`` / ``getByPlaceholder``),
mirroring the locator strategy the agent already recommends in generated code
and matching what Playwright MCP returns.

Two backends are supported:

* ``mcp`` (primary, in-process) -- a live ``playwright`` session on a dedicated
  event loop. Structured accessibility-tree snapshots are returned on every
  observation, exactly like the Playwright MCP server surface.
* ``cli`` (fallback) -- when the in-process session cannot be started, browser
  actions are delegated to a subprocess runner (``browser_cli_runner.py``) that
  drives Playwright via the shell, one step at a time. This mirrors the
  "Agent + Playwright CLI" execution model described in the Slack agentic
  testing experiments, where the agent shells out to Playwright per step.

The ``BrowserSession`` keeps a single persistent page so the agent can
explore, observe, and adapt -- the core of agentic testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Any, Optional

try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Locator,
        Page,
        async_playwright,
    )

    _HAVE_PW = True
except Exception:  # pragma: no cover - playwright is an optional dependency
    _HAVE_PW = False

logger = logging.getLogger("sdet_agent.tools.browser")

# Locator priority used by the "auto" resolution strategy. Mirrors the agent's
# preferred locator ordering from guardrails/locator_checker.py.
_LOCATOR_PRIORITY = ("role", "label", "text", "placeholder", "css")

# Accessibility-tree snapshot expressed as a DOM walker. Playwright removed
# ``page.accessibility.snapshot()`` in recent versions, so we build a
# role/name nested tree ourselves -- the canonical observation the agent
# reasons over (equivalent to what the Playwright MCP server returns).
_AX_SNAPSHOT_JS = """
() => {
  const ROLE_TAGS = {
    A: 'link', BUTTON: 'button', INPUT: 'textbox', SELECT: 'combobox',
    TEXTAREA: 'textbox', H1: 'heading', H2: 'heading', H3: 'heading',
    H4: 'heading', H5: 'heading', H6: 'heading', TABLE: 'table',
    TH: 'columnheader', TD: 'cell', TR: 'row', LI: 'listitem',
    UL: 'list', OL: 'list', NAV: 'navigation', MAIN: 'main',
    HEADER: 'banner', FOOTER: 'contentinfo', IMG: 'img', FORM: 'form',
    DIALOG: 'dialog', LABEL: 'label', SEARCH: 'search'
  };
  function roleOf(el) {
    const r = el.getAttribute && el.getAttribute('role');
    if (r) return r;
    const t = el.tagName;
    if (ROLE_TAGS[t]) return ROLE_TAGS[t];
    if (t === 'IMG') return el.getAttribute('alt') ? 'img' : 'presentation';
    return null;
  }
  function nameOf(el) {
    const a = el.getAttribute && (el.getAttribute('aria-label') ||
      el.getAttribute('alt') || el.getAttribute('title'));
    if (a) return a;
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
      // Prefer the associated <label> text -- this is exactly what
      // Playwright's getByLabel() resolves against, so locators stay
      // stable (e.g. label "First Name", not the placeholder "Jane").
      const lbl = el.labels && el.labels[0] && (el.labels[0].textContent || '').trim();
      if (lbl) return lbl;
      const ph = el.getAttribute && el.getAttribute('placeholder');
      if (ph) return ph;
    }
    const t = (el.textContent || '').trim().slice(0, 80);
    return t;
  }
  function walk(el, depth) {
    if (depth > 14) return null;
    const role = roleOf(el);
    let node = null;
    if (role && role !== 'presentation') {
      node = { role: role, name: nameOf(el) };
    }
    const kids = [];
    for (const c of el.children) {
      const cn = walk(c, depth + 1);
      if (cn) kids.push(cn);
    }
    if (node) {
      if (kids.length) node.children = kids;
      return node;
    }
    return kids.length === 1 ? kids[0] : (kids.length ? kids : null);
  }
  const root = el => {
    const r = roleOf(el) || 'generic';
    const n = { role: r, name: nameOf(el), children: [] };
    for (const c of el.children) { const cn = walk(c, 0); if (cn) n.children.push(cn); }
    return n;
  };
  return root(document.body);
}
"""


def _split_role(target: str) -> tuple[str, Optional[str], str]:
    """Split ``role|name|context`` into (role, name, context).
    
    Context is the optional third pipe-separated segment used for
    disambiguation (e.g. "Most Popular", "tier:growth"). It is NOT used
    for Playwright locator resolution — only for trace_to_code scoped
    locator generation.
    """
    parts = target.split("|")
    role = parts[0].strip()
    name = parts[1].strip() if len(parts) > 1 else None
    context = parts[2].strip() if len(parts) > 2 else ""
    return role, name or None, context


class BrowserSession:
    """Persistent Playwright session living on its own event loop / thread."""

    def __init__(self, headless: bool = True, backend: str = "mcp"):
        self.headless = headless
        # backend: "mcp" (in-process) or "cli" (subprocess fallback)
        self.backend = backend if backend in ("mcp", "cli") else "mcp"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._started = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> dict[str, Any]:
        if self._started:
            return {"status": "already_started", "backend": self.backend}
        if not _HAVE_PW:
            return {"status": "error", "error": "playwright not installed", "backend": self.backend}
        if self.backend == "cli":
            ok = _cli_start(self.headless)
            if not ok.get("ok"):
                return {"status": "error", "error": ok.get("error", "cli start failed"), "backend": "cli"}
            self._started = True
            return {"status": "started", "backend": "cli", "mode": "cli"}
        # mcp backend (in-process)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(self._astart(), self._loop)
        try:
            return fut.result(timeout=30)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc), "backend": "mcp"}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _astart(self) -> dict[str, Any]:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        self._started = True
        return {"status": "started", "backend": "mcp", "mode": "mcp"}

    def stop(self) -> dict[str, Any]:
        if not self._started:
            return {"status": "not_started", "backend": self.backend}
        if self.backend == "cli":
            _cli_stop()
            self._started = False
            return {"status": "stopped", "backend": "cli"}
        fut = asyncio.run_coroutine_threadsafe(self._astop(), self._loop)
        try:
            res = fut.result(timeout=30)
        finally:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
        return res

    async def _astop(self) -> dict[str, Any]:
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        finally:
            self._started = False
        return {"status": "stopped", "backend": "mcp"}

    # ------------------------------------------------------------------ #
    # Dispatch helpers
    # ------------------------------------------------------------------ #
    def _run(self, coro):
        if not self._started or self._loop is None:
            raise RuntimeError("browser not started")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=30)

    def _dispatch(self, action: str, **params) -> dict[str, Any]:
        """Route an action to the active backend."""
        if self.backend == "cli":
            return _cli_action({"action": action, **params})
        handler = getattr(self, f"_a_{action}", None)
        if handler is None:
            return {"ok": False, "error": f"unknown action {action}"}
        return self._run(handler(**params))

    # ------------------------------------------------------------------ #
    # MCP (in-process) action handlers
    # ------------------------------------------------------------------ #
    async def _a_navigate(self, url: str) -> dict[str, Any]:
        await self._page.goto(url, wait_until="domcontentloaded")
        return {"ok": True, "url": self._page.url}

    async def _a_click(self, target: str, kind: str = "auto") -> dict[str, Any]:
        loc, err = await self._locate(target, kind)
        if err:
            return err
        await loc.click(timeout=8000)
        return {"ok": True, "target": target, "url": self._page.url}

    async def _a_type(self, target: str, text: str, kind: str = "auto") -> dict[str, Any]:
        loc, err = await self._locate(target, kind)
        if err:
            return err
        # Auto-detect <select> elements and route to select_option instead of fill
        tag = await loc.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            await loc.wait_for(state="visible", timeout=10000)
            await loc.select_option(text, timeout=15000)
            return {"ok": True, "target": target, "value": text, "routed": "select_option"}
        await loc.fill(text, timeout=15000)
        return {"ok": True, "target": target, "value": text}

    async def _a_select(self, target: str, value: str, kind: str = "auto") -> dict[str, Any]:
        loc, err = await self._locate(target, kind)
        if err:
            return err
        await loc.select_option(value, timeout=8000)
        return {"ok": True, "target": target, "value": value}

    async def _a_wait_for(self, target: str, kind: str = "auto", timeout: int = 5000) -> dict[str, Any]:
        loc, err = await self._locate(target, kind)
        if err:
            return err
        await loc.wait_for(state="visible", timeout=timeout)
        return {"ok": True, "target": target}

    async def _a_assert_visible(self, target: str, kind: str = "auto") -> dict[str, Any]:
        # Visibility tolerates ambiguity: if ANY matching element is visible the
        # assertion holds (e.g. both a <Label> and its <select> match the name).
        loc = self._resolve(self._page, target, kind)
        try:
            n = await loc.count()
        except Exception:  # noqa: BLE001
            n = 0
        if n == 0:
            return {"ok": False, "error": f"no element matched {kind}:{target}"}
        if n == 1:
            visible = await loc.first.is_visible()
            return {"ok": visible, "target": target, "visible": visible}
        for i in range(n):
            try:
                if await loc.nth(i).is_visible():
                    return {"ok": True, "target": target, "visible": True}
            except Exception:  # noqa: BLE001
                continue
        return {"ok": False, "error": f"ambiguous: {n} elements match {kind}:{target}; none visible"}

    async def _a_assert_text(self, expected: str, target: str = "", kind: str = "auto") -> dict[str, Any]:
        if target:
            loc, err = await self._locate(target, kind)
            if err:
                return err
            content = (await loc.inner_text()) or ""
        else:
            content = await self._page.content()
        found = expected in content
        return {"ok": found, "expected": expected, "found": found, "url": self._page.url}

    async def _a_assert_url(self, pattern: str) -> dict[str, Any]:
        import re

        matched = bool(re.search(pattern, self._page.url))
        return {"ok": matched, "pattern": pattern, "url": self._page.url, "matched": matched}

    async def _a_get_url(self) -> dict[str, Any]:
        return {"ok": True, "url": self._page.url}

    async def _a_snapshot(self) -> dict[str, Any]:
        tree = await self._page.evaluate(_AX_SNAPSHOT_JS)
        interactive = await self._page.evaluate(
            """
            () => {
              const TAG_ROLE = {
                a: 'link', button: 'button', textarea: 'textbox',
                select: 'combobox', img: 'img',
              };
              function ariaRole(el) {
                const explicit = el.getAttribute && el.getAttribute('role');
                if (explicit) return explicit;
                const tag = (el.tagName || '').toLowerCase();
                if (TAG_ROLE[tag]) return TAG_ROLE[tag];
                if (tag === 'input') {
                  const t = (el.getAttribute('type') || 'text').toLowerCase();
                  if (t === 'checkbox') return 'checkbox';
                  if (t === 'radio') return 'radio';
                  return 'textbox';
                }
                return tag;
              }
              function accessibleName(el) {
                const a = el.getAttribute && el.getAttribute('aria-label');
                if (a) return a.trim();
                // Prefer the associated <label> -- this is exactly what
                // Playwright's getByLabel() resolves against, so locators stay
                // stable (label "First Name", not the placeholder "Jane").
                const id = el.id;
                if (id) {
                  const lab = document.querySelector('label[for="' + id + '"]');
                  if (lab) return lab.textContent.trim();
                }
                const wrap = el.closest && el.closest('label');
                if (wrap) {
                  let lab = wrap.textContent || '';
                  const own = (el.textContent || '').trim();
                  if (own) {
                    const idx = lab.indexOf(own);
                    if (idx === 0) lab = lab.slice(own.length);
                    else if (idx > 0) lab = lab.slice(0, idx) + lab.slice(idx + own.length);
                  }
                  return lab.replace(/[*:]/g, '').trim();
                }
                const ph = el.getAttribute && el.getAttribute('placeholder');
                if (ph) return ph.trim();
                const nm = el.getAttribute && el.getAttribute('name');
                if (nm) return nm;
                const txt = (el.textContent || '').trim();
                return txt.slice(0, 50);
              }
              const els = Array.from(document.querySelectorAll(
                'a,button,input,select,textarea,[role]'));
              const raw = els.slice(0, 150).map(el => {
                const role = ariaRole(el);
                let name = accessibleName(el);
                // Give switches/checkboxes a synthetic name if they have none
                if (!name && (role === 'switch' || role === 'checkbox')) {
                  const lbl = el.getAttribute('aria-label') || el.getAttribute('name') || role;
                  name = lbl;
                }
                return {role, name, tag: el.tagName.toLowerCase(), el};
              }).filter(e => e.name);

              // Detect duplicates and enrich with parent context
              const seen = {};
              raw.forEach(e => {
                const key = e.role + '|' + e.name;
                seen[key] = (seen[key] || 0) + 1;
              });

              return raw.map(e => {
                const key = e.role + '|' + e.name;
                const out = {role: e.role, name: e.name, tag: e.tag};
                if (seen[key] > 1) {
                  // Strategy: walk UP from the element and find the nearest
                  // ancestor that uniquely identifies this instance. Priority:
                  // 1. data-tier / data-* attribute (most specific)
                  // 2. sibling heading (h1-h6) that is NOT the button's own text
                  // Stop as soon as we find something unique.
                  let cur = e.el;
                  let ctx = '';
                  for (let i = 0; i < 8 && cur && cur !== document.body; i++) {
                    cur = cur.parentElement;
                    if (!cur) break;
                    // Check data attributes first (most reliable)
                    const attrs = cur.attributes || {};
                    for (const attr of Array.from(attrs)) {
                      if (attr.name.startsWith('data-') && attr.name !== 'data-testid') {
                        ctx = attr.name + '=' + attr.value;
                        break;
                      }
                    }
                    if (ctx) break;
                    // Check for a heading that is a direct child (not nested deeper)
                    const children = Array.from(cur.children || []);
                    for (const child of children) {
                      const tag = (child.tagName || '').toLowerCase();
                      if (/^h[1-6]$/.test(tag)) {
                        const hText = (child.textContent || '').trim().slice(0, 60);
                        if (hText && hText !== e.name && hText.length > 1) {
                          ctx = hText;
                          break;
                        }
                      }
                    }
                    if (ctx) break;
                  }
                  if (ctx) {
                    out.context = ctx;
                  }
                }
                return out;
              });
            }
            """
        )
        return {
            "ok": True,
            "url": self._page.url,
            "accessibility_tree": tree,
            "interactive_elements": interactive,
        }

    @staticmethod
    def _resolve(page: Page, target: str, kind: str) -> Locator:
        """Resolve a target string into a Playwright locator using the
        accessible-locator priority. ``kind`` may be one of role/label/text/
        placeholder/css/auto."""
        if kind == "css":
            return page.locator(target)
        if kind == "role":
            role, name, _ctx = _split_role(target)
            return page.get_by_role(role, name=name) if name else page.get_by_role(role)
        if kind == "label":
            return page.get_by_label(target)
        if kind == "text":
            return page.get_by_text(target, exact=False)
        if kind == "placeholder":
            return page.get_by_placeholder(target)
        # auto: try the priority chain
        if "|" in target:
            role, name, _ctx = _split_role(target)
            return page.get_by_role(role, name=name)
        if target.startswith(("#", ".", "[", "/")):
            return page.locator(target)
        return (
            page.get_by_text(target, exact=False)
            .or_(page.get_by_label(target))
            .or_(page.get_by_placeholder(target))
            # Also match form controls by their accessible name (the snapshot
            # reports these as role|name, e.g. combobox|Applying For). This lets
            # a plain assertion target like "Applying For" resolve to the field.
            .or_(page.get_by_role("combobox", name=target))
            .or_(page.get_by_role("textbox", name=target))
            .or_(page.get_by_role("button", name=target))
            .or_(page.get_by_role("link", name=target))
        )

    @staticmethod
    def _resolve_exact(page: Page, target: str, kind: str) -> Locator:
        """Exact-match variant used to disambiguate substring collisions."""
        if kind == "css":
            return page.locator(target)
        if kind == "role":
            role, name, _ctx = _split_role(target)
            return page.get_by_role(role, name=name, exact=True) if name else page.get_by_role(role)
        if kind == "label":
            return page.get_by_label(target, exact=True)
        if kind == "text":
            return page.get_by_text(target, exact=True)
        if kind == "placeholder":
            return page.get_by_placeholder(target, exact=True)
        return BrowserSession._resolve(page, target, kind)

    async def _locate(self, target: str, kind: str) -> tuple[Locator, Optional[dict[str, Any]]]:
        """Resolve a target, disambiguating substring collisions.

        Returns (locator, None) on success, or (None, error_dict) when the
        target matches nothing or is ambiguous (e.g. placeholder "Jane" also
        matches "jane@example.com"). Ambiguity is resolved in favour of an
        exact match; otherwise a clear error is returned so the agent adapts.
        """
        loc = self._resolve(self._page, target, kind)
        try:
            n = await loc.count()
        except Exception:  # noqa: BLE001
            n = 0
        if n == 0:
            return None, {"ok": False, "error": f"no element matched {kind}:{target}"}
        if n == 1:
            return loc, None
        # Ambiguous: prefer an exact match if it uniquely resolves.
        exact = self._resolve_exact(self._page, target, kind)
        try:
            en = await exact.count()
        except Exception:  # noqa: BLE001
            en = 0
        if en == 1:
            return exact, None
        return None, {
            "ok": False,
            "error": (
                f"ambiguous: {n} elements match {kind}:{target} "
                f"(exact match resolved to {en}); provide a more specific target"
            ),
        }


# ---------------------------------------------------------------------- #
# CLI backend (subprocess fallback)
# ---------------------------------------------------------------------- #
_CLI_STATE_PATH = "/tmp/sdet_browser_cli_state.json"


def _cli_runner_path() -> str:
    return os.path.join(os.path.dirname(__file__), "browser_cli_runner.py")


def _cli_python() -> str:
    """Use the same interpreter that runs the agent so the subprocess picks
    up the active venv's dependencies (Playwright), not a bare system python."""
    return sys.executable or "python3"


def _cli_start(headless: bool) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [_cli_python(), _cli_runner_path(), "start", "--headless" if headless else "--no-headless"],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[:500]}
        return json.loads(proc.stdout or "{}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _cli_action(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [_cli_python(), _cli_runner_path(), "action"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[:500]}
        return json.loads(proc.stdout or "{}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _cli_stop() -> None:
    try:
        subprocess.run(
            [_cli_python(), _cli_runner_path(), "stop"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------- #
# Module-level singleton + tool functions for the registry
# ---------------------------------------------------------------------- #
_SESSION: Optional[BrowserSession] = None


def _get_session() -> BrowserSession:
    global _SESSION
    if _SESSION is None:
        _SESSION = BrowserSession()
    return _SESSION


def browser_start(headless: bool = True, backend: str = "mcp") -> dict[str, Any]:
    """Start a live browser session (mcp in-process or cli subprocess)."""
    global _SESSION
    if _SESSION is not None and _SESSION._started:
        _SESSION.stop()
    _SESSION = BrowserSession(headless=headless, backend=backend)
    return _SESSION.start()


def browser_stop() -> dict[str, Any]:
    """Close the live browser session."""
    global _SESSION
    if _SESSION is None:
        return {"status": "not_started"}
    res = _SESSION.stop()
    _SESSION = None
    return res


def browser_navigate(url: str) -> dict[str, Any]:
    return _get_session()._dispatch("navigate", url=url)


def browser_click(target: str, kind: str = "auto") -> dict[str, Any]:
    return _get_session()._dispatch("click", target=target, kind=kind)


def browser_type(target: str, text: str, kind: str = "auto") -> dict[str, Any]:
    return _get_session()._dispatch("type", target=target, text=text, kind=kind)


def browser_select(target: str, value: str, kind: str = "auto") -> dict[str, Any]:
    return _get_session()._dispatch("select", target=target, value=value, kind=kind)


def browser_wait_for(target: str, kind: str = "auto", timeout: int = 5000) -> dict[str, Any]:
    return _get_session()._dispatch("wait_for", target=target, kind=kind, timeout=timeout)


def browser_assert_visible(target: str, kind: str = "auto") -> dict[str, Any]:
    return _get_session()._dispatch("assert_visible", target=target, kind=kind)


def browser_assert_text(expected: str, target: str = "", kind: str = "auto") -> dict[str, Any]:
    return _get_session()._dispatch("assert_text", expected=expected, target=target, kind=kind)


def browser_assert_url(pattern: str) -> dict[str, Any]:
    return _get_session()._dispatch("assert_url", pattern=pattern)


def browser_get_url() -> dict[str, Any]:
    return _get_session()._dispatch("get_url")


def browser_snapshot() -> dict[str, Any]:
    """Capture the current accessibility tree + interactive elements."""
    return _get_session()._dispatch("snapshot")
