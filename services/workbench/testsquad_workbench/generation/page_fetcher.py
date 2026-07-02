from __future__ import annotations

from pathlib import Path


async def fetch_page_html(url: str) -> str:
    if url.startswith("file://"):
        path = url[len("file://"):]
        return Path(path).read_text(encoding="utf-8")

    if url == "--stdin":
        import sys
        return sys.stdin.read()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is required to fetch pages from URLs. "
            "Install with: pip install playwright && playwright install chromium"
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)
        html = await page.content()
        await browser.close()

    return html


async def find_element_at(
    url: str,
    x: int,
    y: int,
    width: int,
    height: int,
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> dict:
    center_x = x + width // 2
    center_y = y + height // 2

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("Playwright is required for element selection")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)

        result = await page.evaluate("""({cx, cy}) => {
            const allEls = document.elementsFromPoint(cx, cy).filter(function(e) {
                var t = e.tagName.toLowerCase();
                return t !== 'html' && t !== 'body';
            });
            if (!allEls || allEls.length === 0) return null;

            function getBestSelector(_el) {
                var tag = _el.tagName.toLowerCase();

                for (var attr of ['data-testid', 'data-test-id', 'data-test', 'data-cy']) {
                    var val = _el.getAttribute(attr);
                    if (val) return '[' + attr + '="' + val + '"]';
                }

                if (_el.id) {
                    if (/^[a-zA-Z][\\w\\-]*$/.test(_el.id)) return '#' + _el.id;
                }

                var ariaLabel = _el.getAttribute('aria-label');
                if (ariaLabel) return tag + '[aria-label="' + ariaLabel + '"]';

                var name = _el.getAttribute('name');
                if (name) return tag + '[name="' + name + '"]';

                var role = _el.getAttribute('role');
                if (role) return tag + '[role="' + role + '"]';

                var stableClasses = [];
                for (var cls of _el.classList) {
                    if (/^[a-zA-Z][\\w\\-]*$/.test(cls) &&
                        !/^[a-z]{1,3}$/.test(cls) &&
                        !/^css-/.test(cls) &&
                        !/^sc-/.test(cls)) {
                        stableClasses.push(cls);
                    }
                }
                if (stableClasses.length > 0) {
                    return tag + '.' + stableClasses.slice(0, 2).join('.');
                }

                var text = (_el.textContent || '').trim().substring(0, 40);
                if (text && (tag === 'button' || tag === 'a' || tag === 'label')) {
                    return tag + ':has-text("' + text.replace(/"/g, '\\\\"') + '")';
                }

                var type = _el.getAttribute('type');
                if (type) return tag + '[type="' + type + '"]';

                var placeholder = _el.getAttribute('placeholder');
                if (placeholder) return tag + '[placeholder="' + placeholder + '"]';

                var parts = [];
                while (_el && _el.nodeType === 1) {
                    var sel = _el.tagName.toLowerCase();
                    if (_el.id) { parts.unshift(sel + '#' + _el.id); break; }
                    var parent = _el.parentElement;
                    if (parent) {
                        var siblings = Array.from(parent.children).filter(function(c) { return c.tagName === _el.tagName; });
                        if (siblings.length > 1) {
                            sel += ':nth-child(' + (Array.from(parent.children).indexOf(_el) + 1) + ')';
                        }
                    }
                    parts.unshift(sel);
                    _el = parent;
                }
                return parts.join(' > ');
            }

            function getXPath(_el) {
                if (_el.id) return '//' + _el.tagName.toLowerCase() + '[@id="' + _el.id + '"]';
                if (_el === document.body || !_el.parentElement) return '/' + _el.tagName.toLowerCase();
                var siblings = Array.from(_el.parentElement.children).filter(function(c) { return c.tagName === _el.tagName; });
                var idx = siblings.indexOf(_el) + 1;
                return getXPath(_el.parentElement) + '/' + _el.tagName.toLowerCase() + '[' + idx + ']';
            }

            function getAllAlternatives(_el) {
                var alts = [];
                var tag = _el.tagName.toLowerCase();

                for (var attr of ['data-testid', 'data-test-id', 'data-test', 'data-cy']) {
                    var val = _el.getAttribute(attr);
                    if (val) alts.push({type: 'data-testid', selector: '[' + attr + '="' + val + '"]', description: attr + '="' + val + '"'});
                }

                if (_el.id && /^[a-zA-Z][\\w\\-]*$/.test(_el.id)) {
                    alts.push({type: 'id', selector: '#' + _el.id, description: '#' + _el.id});
                }

                var ariaLabel = _el.getAttribute('aria-label');
                if (ariaLabel) alts.push({type: 'aria-label', selector: tag + '[aria-label="' + ariaLabel + '"]', description: 'aria-label="' + ariaLabel + '"'});

                var name = _el.getAttribute('name');
                if (name) alts.push({type: 'name', selector: tag + '[name="' + name + '"]', description: 'name="' + name + '"'});

                var role = _el.getAttribute('role');
                if (role) alts.push({type: 'role', selector: tag + '[role="' + role + '"]', description: 'role="' + role + '"'});

                for (var cls of _el.classList) {
                    if (/^[a-zA-Z][\\w\\-]*$/.test(cls) && !/^[a-z]{1,3}$/.test(cls) && !/^css-/.test(cls) && !/^sc-/.test(cls)) {
                        alts.push({type: 'class', selector: '.' + cls, description: '.' + cls});
                        break;
                    }
                }

                var type = _el.getAttribute('type');
                if (type) alts.push({type: 'attribute', selector: tag + '[type="' + type + '"]', description: 'type="' + type + '"'});

                var placeholder = _el.getAttribute('placeholder');
                if (placeholder) alts.push({type: 'placeholder', selector: tag + '[placeholder="' + placeholder + '"]', description: 'placeholder="' + placeholder + '"'});

                alts.push({type: 'xpath', selector: getXPath(_el), description: 'XPath'});

                return alts;
            }

            function buildDomTree(node, depth, keyCounter) {
                if (!node || node.nodeType !== 1) return null;
                var MAX_DEPTH = 3;
                var MAX_CHILDREN = 25;
                if (depth > MAX_DEPTH) return {key: '_more', tag: '...', children: [], hasChildren: true, depth: depth, text: '', id: '', classes: [], attributes: {}};

                var children = [];
                for (var i = 0; i < node.children.length && i < MAX_CHILDREN; i++) {
                    var c = buildDomTree(node.children[i], depth + 1, keyCounter);
                    if (c) children.push(c);
                }

                var key = 'n' + (keyCounter.n++);

                function getAttr(n, a) { var v = n.getAttribute(a); return v || ''; }

                return {
                    key: key,
                    tag: node.tagName.toLowerCase(),
                    id: node.id || '',
                    classes: Array.from(node.classList).slice(0, 3),
                    attributes: {
                        type: getAttr(node, 'type'),
                        name: getAttr(node, 'name'),
                        placeholder: getAttr(node, 'placeholder'),
                        href: getAttr(node, 'href'),
                        src: getAttr(node, 'src'),
                    },
                    text: (node.textContent || '').trim().substring(0, 80),
                    hasChildren: node.children.length > 0,
                    children: children,
                    depth: depth,
                };
            }

            function elementInfo(_el) {
                return {
                    cssPath: getBestSelector(_el),
                    tag: _el.tagName.toLowerCase(),
                    text: (_el.textContent || '').trim().substring(0, 200),
                    outerHtml: _el.outerHTML.substring(0, 2000),
                    id: _el.id || '',
                    classes: Array.from(_el.classList).slice(0, 5),
                    childCount: _el.children.length,
                    interactiveChildren: Array.from(_el.querySelectorAll('input, button, select, textarea, a, label')).length,
                };
            }

            // Primary element: prefer the outermost element that has direct interactive children
            // (likely the form/container the user intended), fallback to last non-html element
            var best = allEls[allEls.length - 1];
            for (var i = allEls.length - 1; i >= 0; i--) {
                var e = allEls[i];
                var info = elementInfo(e);
                if (info.interactiveChildren > 0 || e.querySelectorAll('input, button, select, textarea').length > 0) {
                    best = e;
                    break;
                }
            }
            // If best has no children at all, use the parent
            if (best.children.length === 0 && best.parentElement && best.parentElement.tagName.toLowerCase() !== 'html') {
                best = best.parentElement;
            }

            var bestInfo = elementInfo(best);
            var alts = getAllAlternatives(best);

            var elements = allEls.map(function(e) { return elementInfo(e); });

            return {
                cssPath: bestInfo.cssPath,
                elements: elements,
                alternatives: alts,
                domTree: buildDomTree(best, 0, {n: 1}),
                tag: bestInfo.tag,
                text: bestInfo.text,
                outerHtml: bestInfo.outerHtml,
            };
        }""", {"cx": center_x, "cy": center_y})

        html = await page.content()
        await browser.close()

    if result is None:
        raise RuntimeError("No element found at the selected coordinates")

    result["html"] = html
    return result


async def validate_selectors_on_page(
    url: str,
    root_selector: str,
    selectors_to_check: list[dict],
) -> list[dict]:
    """Validate a list of selectors against a live Playwright page.

    Each item in selectors_to_check:
        {"key": str, "strategy": str, "selector": str, "type": str, "relative": bool}
    If relative=True, selector is scoped under root_selector.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("Playwright is required for selector validation")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)

        results = []
        for item in selectors_to_check:
            try:
                if item.get("relative"):
                    locator = page.locator(root_selector).locator(item["selector"])
                else:
                    locator = page.locator(item["selector"])
                count = await locator.count()
                sample_html = ""
                if count > 0:
                    sample_html = await locator.first.evaluate(
                        "el => el.outerHTML.substring(0, 500)"
                    )
            except Exception:
                count = 0
                sample_html = ""

            stability = "good" if count == 1 else ("ambiguous" if count > 1 else "broken")

            results.append({
                "key": item["key"],
                "strategy": item["strategy"],
                "selector": item["selector"],
                "type": item["type"],
                "matches": count,
                "sample_html": sample_html,
                "stability": stability,
            })

        await browser.close()

    return results


async def validate_arbitrary_selectors(
    url: str,
    selectors: list[str],
    context_selector: str = "",
) -> list[dict]:
    """Validate a flat list of selectors. Returns match counts and sample HTML."""
    items = [
        {"key": f"sel_{i}", "strategy": "custom", "selector": s, "type": "css", "relative": bool(context_selector)}
        for i, s in enumerate(selectors)
    ]
    root_sel = context_selector or "html"
    return await validate_selectors_on_page(url, root_sel, items)
