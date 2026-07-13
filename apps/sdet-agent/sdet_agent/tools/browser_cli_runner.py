"""CLI backend runner for agentic browser interaction (subprocess fallback).

Invoked by ``browser_tools.py`` when the in-process MCP backend is
unavailable. Each invocation rehydrates a minimal browser state (cookies +
current URL) from ``_CLI_STATE_PATH`` so the agent can drive the browser one
action at a time over multiple shell calls -- the "Agent + Playwright CLI"
execution model from the Slack agentic-testing experiments.

Usage:
    python3 browser_cli_runner.py start [--headless|--no-headless]
    echo '{"action":"navigate","url":"..."}' | python3 browser_cli_runner.py action
    python3 browser_cli_runner.py stop
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Reuse the shared AX-tree walker from the MCP backend so both backends
# produce identical observations for the agent.
try:
    from .browser_tools import _AX_SNAPSHOT_JS  # type: ignore
except Exception:  # pragma: no cover - standalone run
    _AX_SNAPSHOT_JS = """
    () => {
      const ROLE_TAGS = {A:'link',BUTTON:'button',INPUT:'textbox',SELECT:'combobox',
        TEXTAREA:'textbox',H1:'heading',H2:'heading',H3:'heading',H4:'heading',
        H5:'heading',H6:'heading',TABLE:'table',TH:'columnheader',TD:'cell',TR:'row',
        LI:'listitem',UL:'list',OL:'list',NAV:'navigation',MAIN:'main',HEADER:'banner',
        FOOTER:'contentinfo',IMG:'img',FORM:'form',DIALOG:'dialog',LABEL:'label',SEARCH:'search'};
      function roleOf(el){const r=el.getAttribute&&el.getAttribute('role');if(r)return r;
        const t=el.tagName;if(ROLE_TAGS[t])return ROLE_TAGS[t];
        if(t==='IMG')return el.getAttribute('alt')?'img':'presentation';return null;}
      function nameOf(el){const a=el.getAttribute&&(el.getAttribute('aria-label')||
        el.getAttribute('placeholder')||el.getAttribute('alt')||el.getAttribute('title'));
        if(a)return a;return (el.textContent||'').trim().slice(0,80);}
      function walk(el,d){if(d>14)return null;const role=roleOf(el);let node=null;
        if(role&&role!=='presentation')node={role,name:nameOf(el)};
        const kids=[];for(const c of el.children){const cn=walk(c,d+1);if(cn)kids.push(cn);}
        if(node){if(kids.length)node.children=kids;return node;}
        return kids.length===1?kids[0]:(kids.length?kids:null);}
      const root=el=>{const r=roleOf(el)||'generic';const n={role:r,name:nameOf(el),children:[]};
        for(const c of el.children){const cn=walk(c,0);if(cn)n.children.push(cn);}return n;};
      return root(document.body);}
    """

_STATE_PATH = Path(tempfile.gettempdir()) / "sdet_browser_cli_state.json"


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except Exception:
            pass
    return {"cookies": [], "url": ""}


def _save_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state))


def _resolve(page, target: str, kind: str):
    if kind == "css":
        return page.locator(target)
    if kind == "role":
        role, _, name = target.partition("|")
        return page.get_by_role(role.strip(), name=name.strip() or None) if name else page.get_by_role(role.strip())
    if kind == "label":
        return page.get_by_label(target)
    if kind == "text":
        return page.get_by_text(target, exact=False)
    if kind == "placeholder":
        return page.get_by_placeholder(target)
    if "|" in target:
        role, _, name = target.partition("|")
        return page.get_by_role(role.strip(), name=name.strip() or None)
    if target.startswith(("#", ".", "[", "/")):
        return page.locator(target)
    return (
        page.get_by_text(target, exact=False)
        .or_(page.get_by_label(target))
        .or_(page.get_by_placeholder(target))
    )


def _resolve_exact(page, target: str, kind: str):
    if kind == "css":
        return page.locator(target)
    if kind == "role":
        role, _, name = target.partition("|")
        return page.get_by_role(role.strip(), name=name.strip() or None, exact=True) if name else page.get_by_role(role.strip())
    if kind == "label":
        return page.get_by_label(target, exact=True)
    if kind == "text":
        return page.get_by_text(target, exact=True)
    if kind == "placeholder":
        return page.get_by_placeholder(target, exact=True)
    return _resolve(page, target, kind)


def _locate(page, target: str, kind: str):
    """Resolve a target, disambiguating substring collisions (sync API)."""
    loc = _resolve(page, target, kind)
    try:
        n = loc.count()
    except Exception:  # noqa: BLE001
        n = 0
    if n == 0:
        return None, {"ok": False, "error": f"no element matched {kind}:{target}"}
    if n == 1:
        return loc, None
    exact = _resolve_exact(page, target, kind)
    try:
        en = exact.count()
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


class _ActionError(Exception):
    """Raised to short-circuit the action branch with an error result."""

    def __init__(self, result: dict):
        super().__init__(result.get("error", "action error"))
        self.result = result


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"ok": False, "error": "no command"}))
        return 1
    cmd = argv[0]

    if cmd == "start":
        headless = "--no-headless" not in argv
        _save_state({"cookies": [], "url": "", "headless": headless})
        print(json.dumps({"ok": True, "backend": "cli", "headless": headless}))
        return 0

    if cmd == "stop":
        _STATE_PATH.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "stopped": True}))
        return 0

    if cmd == "action":
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"playwright not available: {exc}"}))
            return 1

        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"invalid json: {exc}"}))
            return 1

        state = _load_state()
        headless = state.get("headless", True)
        action = payload.get("action", "")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            context = browser.new_context()
            if state.get("cookies"):
                try:
                    context.add_cookies(state["cookies"])
                except Exception:
                    pass
            page = context.new_page()
            if state.get("url"):
                try:
                    page.goto(state["url"], wait_until="domcontentloaded")
                except Exception:
                    pass

            result: dict = {"ok": True}
            try:
                if action == "navigate":
                    page.goto(payload["url"], wait_until="domcontentloaded")
                    result["url"] = page.url
                elif action == "click":
                    loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                    if err:
                        raise _ActionError(err)
                    loc.click(timeout=8000)
                    result["url"] = page.url
                elif action == "type":
                    loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                    if err:
                        raise _ActionError(err)
                    loc.fill(payload["text"], timeout=8000)
                    result["value"] = payload["text"]
                elif action == "select":
                    loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                    if err:
                        raise _ActionError(err)
                    loc.select_option(payload["value"], timeout=8000)
                    result["value"] = payload["value"]
                elif action == "wait_for":
                    loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                    if err:
                        raise _ActionError(err)
                    loc.wait_for(state="visible", timeout=payload.get("timeout", 5000))
                elif action == "assert_visible":
                    loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                    if err:
                        raise _ActionError(err)
                    result["visible"] = loc.is_visible()
                    result["ok"] = result["visible"]
                elif action == "assert_text":
                    if payload.get("target"):
                        loc, err = _locate(page, payload["target"], payload.get("kind", "auto"))
                        if err:
                            raise _ActionError(err)
                        content = loc.inner_text() or ""
                    else:
                        content = page.content()
                    result["found"] = payload["expected"] in content
                    result["ok"] = result["found"]
                elif action == "assert_url":
                    import re

                    result["matched"] = bool(re.search(payload["pattern"], page.url))
                    result["ok"] = result["matched"]
                    result["url"] = page.url
                elif action == "get_url":
                    result["url"] = page.url
                elif action == "snapshot":
                    tree = page.evaluate(_AX_SNAPSHOT_JS)
                    interactive = page.evaluate(
                        """
                        () => Array.from(document.querySelectorAll(
                          'a,button,input,select,textarea,[role]'))
                          .slice(0, 150).map(el => ({
                            role: el.getAttribute('role') || el.tagName.toLowerCase(),
                            name: el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                                  el.getAttribute('name') || (el.textContent||'').trim().slice(0,50),
                            tag: el.tagName.toLowerCase()
                          })).filter(e => e.name)
                        """
                    )
                    result["url"] = page.url
                    result["accessibility_tree"] = tree
                    result["interactive_elements"] = interactive
                else:
                    result = {"ok": False, "error": f"unknown action {action}"}
            except _ActionError as ae:
                result = ae.result
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            else:
                # Persist state for the next CLI invocation.
                try:
                    state["cookies"] = context.cookies()
                    state["url"] = page.url
                    _save_state(state)
                except Exception:
                    pass
            finally:
                browser.close()
        print(json.dumps(result))
        return 0 if result.get("ok") else 1

    print(json.dumps({"ok": False, "error": f"unknown command {cmd}"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
