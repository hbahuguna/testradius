from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urljoin, urlparse
import urllib.parse
import base64
import httpx
import mimetypes
from pathlib import Path
from bs4 import BeautifulSoup

from .schemas import (
    AnalyzeRequest, AnalyzeResponse,
    ComGenRequest, ComGenResponse,
    ComponentsResponse, ComponentInfo,
    PomGenRequest, PomGenResponse, PomGenFile, ElementNode,
    TestGenRequest, TestGenResponse, TestGenFile,
    SelectAreaRequest, SelectAreaResponse,
    SelectorAlternative, DomNode, HitElement,
    ValidatedSelector, FieldValidation,
    ValidateComRequest, ValidateComResponse,
    ValidateSelectorsRequest, ValidateSelectorsResponse,
)
from .generation.html_parser import parse_html, get_element_by_selector
from .generation.classifier import classify, ClassificationResult
from .generation.descriptors import build_descriptor
from .generation.template_engine import (
    render_com, render_pom, render_tests,
    render_action_pom, render_action_test, ComponentActionData,
    PageModel, ComReference,
)
from .generation.page_fetcher import fetch_page_html, find_element_at, validate_selectors_on_page, validate_arbitrary_selectors
from .generation.selector_strategy import generate_selectors, generate_relative_selectors

app = FastAPI(title="TestRadius Workbench", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _element_to_node(element) -> ElementNode:
    attrs = {}
    for k, v in element.attributes.items():
        if isinstance(v, str):
            attrs[k] = v
        elif isinstance(v, bytes):
            attrs[k] = v.decode()
        else:
            try:
                attrs[k] = " ".join(str(x) for x in v)
            except TypeError:
                attrs[k] = str(v)
    return ElementNode(
        tag=element.tag,
        attributes=attrs,
        text=element.text,
        role=element.role,
        aria=element.aria,
        css_path=element.css_path,
        xpath=element.xpath,
        depth=element.depth,
        index=element.index,
        children=[_element_to_node(c) for c in element.children],
        is_interactive=element.is_interactive,
        is_visible=element.is_visible,
    )


def _extract_title(dom_tree) -> str:
    if dom_tree.soup:
        title_tag = dom_tree.soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()
    return dom_tree.url


_INSPECTOR_SCRIPT = r"""
<script>
(function() {
  var currentHighlight = null;
  var currentSelected = null;
  var style = document.createElement('style');
  style.textContent = [
    '.ts-inspect-highlight{outline:2px solid #4488ff!important;outline-offset:-1px!important;background:rgba(68,136,255,0.08)!important}',
    '.ts-inspect-selected{outline:3px solid #ff6644!important;outline-offset:-1px!important;background:rgba(255,102,68,0.12)!important}',
  ].join('');
  document.head.appendChild(style);

  function resolveCssPath(path) {
    if (!path) return null;
    var parts = path.split(' > ');
    var current = document.body || document.documentElement;
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      var tag = part.split(/[.#]/)[0];
      var m = part.match(/#([^.#]+)/);
      var id = m ? m[1] : null;
      var classes = [];
      var re = /\.([^.#]+)/g;
      var match;
      while ((match = re.exec(part)) !== null) classes.push(match[1]);
      var children = current.children;
      var found = null;
      for (var j = 0; j < children.length; j++) {
        var child = children[j];
        if (child.tagName.toLowerCase() !== tag) continue;
        if (id && child.id !== id) continue;
        if (classes.length > 0) {
          var allMatch = classes.every(function(c) { return child.classList.contains(c); });
          if (!allMatch) continue;
        }
        found = child;
        break;
      }
      if (!found) return null;
      current = found;
    }
    return current;
  }

  document.addEventListener('mouseover', function(e) {
    var el = e.target;
    if (el === document.body || el === document.documentElement) return;
    if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
    currentHighlight = el;
    el.classList.add('ts-inspect-highlight');
    e.stopPropagation();
  }, true);

  document.addEventListener('mouseout', function(e) {
    if (currentHighlight) {
      currentHighlight.classList.remove('ts-inspect-highlight');
      currentHighlight = null;
    }
  }, true);

  var skipTags = ['script','style','meta','link','base','head'];
  var inputValues = {};

  document.addEventListener('input', function(e) {
    var el = e.target;
    var tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      inputValues[el.id || el.name || getCssPath(el)] = el.value;
    }
  }, true);

  document.addEventListener('click', function(e) {
    var el = e.target;
    if (el === document.body || el === document.documentElement) return;
    if (skipTags.indexOf(el.tagName.toLowerCase()) !== -1) return;
    e.preventDefault();
    e.stopPropagation();

    if (currentSelected) currentSelected.classList.remove('ts-inspect-selected');
    if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
    currentHighlight = null;
    currentSelected = el;
    el.classList.add('ts-inspect-selected');

    var inShadow = false;
    var targetEl = el;
    var root = el.getRootNode ? el.getRootNode() : document;
    if (root && root instanceof ShadowRoot) {
      inShadow = true;
      targetEl = root.host;
    }

    var path = getCssPath(targetEl);
    var tag = targetEl.tagName.toLowerCase();
    var text = (targetEl.textContent || '').trim().substring(0, 100);
    var id = targetEl.id || '';
    var cls = Array.from(targetEl.classList).join('.');

    var trackId = targetEl.id || targetEl.name || path;
    var value = (tag === 'input' || tag === 'textarea' || tag === 'select') ? (inputValues[trackId] || targetEl.value) : undefined;

    window.parent.postMessage({
      type: 'ts-element-click',
      cssPath: path,
      tag: tag,
      text: text,
      id: id,
      classes: cls,
      inShadowDOM: inShadow,
      value: value
    }, '*');
  }, true);

  window.addEventListener('message', function(e) {
    var msg = e.data;
    if (!msg || !msg.type) return;

    if (msg.type === 'ts-highlight' && msg.cssPath) {
      if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
      var el = resolveCssPath(msg.cssPath);
      if (el) {
        currentHighlight = el;
        el.classList.add('ts-inspect-highlight');
      }
      return;
    }

    if (msg.type === 'ts-clear-highlight') {
      if (currentHighlight) {
        currentHighlight.classList.remove('ts-inspect-highlight');
        currentHighlight = null;
      }
      return;
    }

    if (msg.type === 'ts-select' && msg.cssPath) {
      if (currentSelected) currentSelected.classList.remove('ts-inspect-selected');
      if (currentHighlight) currentHighlight.classList.remove('ts-inspect-highlight');
      currentHighlight = null;
      var el = resolveCssPath(msg.cssPath);
      if (el) {
        currentSelected = el;
        el.classList.add('ts-inspect-selected');
      }
      return;
    }
  });

  function getCssPath(el) {
    if (el.id) return el.tagName.toLowerCase() + '#' + el.id;
    var parts = [];
    while (el && el.nodeType === 1) {
      var selector = el.tagName.toLowerCase();
      if (el.id) { parts.unshift(selector + '#' + el.id); break; }
      var parent = el.parentElement;
      if (parent) {
        var siblings = Array.from(parent.children).filter(function(c) { return c.tagName === el.tagName; });
        if (siblings.length > 1) {
          var idx = siblings.indexOf(el) + 1;
          selector += ':nth-child(' + (Array.from(parent.children).indexOf(el) + 1) + ')';
        }
      }
      parts.unshift(selector);
      el = parent;
    }
    return parts.join(' > ');
  }
})();
</script>
"""


def _strip_security_meta(soup: BeautifulSoup) -> None:
    for meta in soup.find_all("meta", attrs={"http-equiv": True}):
        equiv = meta.get("http-equiv", "").lower()
        if equiv in ("content-security-policy", "x-frame-options", "x-content-type-options"):
            meta.decompose()


def _rewrite_urls(soup: BeautifulSoup, base_url: str) -> None:
    url_attrs = [
        ("img", "src"), ("img", "srcset"),
        ("link", "href"),
        ("script", "src"),
        ("source", "src"), ("source", "srcset"),
        ("video", "src"), ("video", "poster"),
        ("audio", "src"),
        ("iframe", "src"),
        ("object", "data"),
        ("embed", "src"),
    ]
    for tag, attr in url_attrs:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if val and not val.startswith(("http://", "https://", "//", "data:", "blob:", "javascript:", "mailto:")):
                el[attr] = urljoin(base_url, val)

    for tag in ["img", "source"]:
        for el in soup.find_all(tag):
            val = el.get("srcset")
            if val:
                entries = [u.strip() for u in val.split(",")]
                rewritten = []
                for entry in entries:
                    parts = entry.split()
                    if parts and not parts[0].startswith(("http://", "https://", "//", "data:", "blob:")):
                        parts[0] = urljoin(base_url, parts[0])
                    rewritten.append(" ".join(parts))
                el["srcset"] = ", ".join(rewritten)

    for a in soup.find_all("a"):
        href = a.get("href")
        if href and not href.startswith(("http://", "https://", "//", "mailto:", "#", "javascript:")):
            a["href"] = urljoin(base_url, href)


def _inject_inspector(soup: BeautifulSoup) -> None:
    inspector = BeautifulSoup(_INSPECTOR_SCRIPT, "html.parser")
    head = soup.find("head")
    if head:
        head.append(inspector)
    else:
        html_tag = soup.find("html")
        if html_tag:
            if not soup.find("head"):
                new_head = soup.new_tag("head")
                new_head.append(inspector)
                html_tag.insert(0, new_head)
            else:
                soup.find("head").append(inspector)
        else:
            soup.insert(0, inspector)


proxy_router = APIRouter()

_ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;
    background:#1a1a2e;color:#ccc;display:flex;align-items:center;justify-content:center;
    min-height:100vh;margin:0;}}
  .box{{text-align:center;padding:2rem;max-width:400px;}}
  .code{{font-size:3rem;color:#e05;font-weight:700;margin-bottom:.5rem;}}
  .msg{{color:#999;line-height:1.5;}}
</style></head>
<body><div class="box">
  <div class="code">&#x26A0;</div>
  <div class="msg">{message}</div>
</div></body></html>"""


def _proxy_error_html(title: str, message: str) -> str:
    return _ERROR_HTML.format(title=title, message=message)


def _proxy_encode(url: str) -> str:
    return base64.urlsafe_b64encode(url.rstrip("/").encode("utf-8")).decode("ascii")


def _rewrite_to_proxy_v(soup: BeautifulSoup, base_url: str, resource_path: str = "") -> str:
    """Rewrite all resource URLs to /v/<encoded-base>/<path>. Returns the encoded base."""
    encoded = _proxy_encode(base_url)
    prefix = f"/v/{encoded}/"

    # SPA fix: make the SPA router see the original resource path instead of the
    # proxy URL path. Resource URLs still resolve correctly via <base>.
    root_script = soup.new_tag("script")
    spa_path = resource_path if resource_path and resource_path != "/" else ""
    root_script.string = f"history.replaceState(null,'','/{spa_path}')"
    head = soup.find("head")
    if head:
        head.insert(1, root_script)

    def _extract_path(full_url: str) -> str:
        return urllib.parse.urlparse(full_url).path

    url_attrs = [
        ("img", "src"), ("img", "srcset"),
        ("link", "href"),
        ("script", "src"),
        ("source", "src"), ("source", "srcset"),
        ("video", "src"), ("video", "poster"),
        ("audio", "src"),
        ("iframe", "src"),
        ("object", "data"),
        ("embed", "src"),
    ]
    for tag, attr in url_attrs:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if val and not val.startswith(("http://", "https://", "//", "data:", "blob:", "javascript:", "mailto:")):
                full = urljoin(base_url, val)
                path = _extract_path(full)
                el[attr] = prefix + path.lstrip("/")

    for tag in ["img", "source"]:
        for el in soup.find_all(tag):
            val = el.get("srcset")
            if val:
                entries = []
                for entry in val.split(","):
                    entry = entry.strip()
                    parts = entry.split()
                    if parts and not parts[0].startswith(("http://", "https://", "//", "data:", "blob:")):
                        full = urljoin(base_url, parts[0])
                        path = _extract_path(full)
                        parts[0] = prefix + path.lstrip("/")
                    entries.append(" ".join(parts))
                el["srcset"] = ", ".join(entries)

    for a in soup.find_all("a"):
        href = a.get("href")
        if href and not href.startswith(("http://", "https://", "//", "mailto:", "#", "javascript:")):
            full = urljoin(base_url, href)
            path = _extract_path(full)
            a["href"] = prefix + path.lstrip("/")

    # Add <base> tag at the start of <head>
    base_tag = soup.new_tag("base", href=prefix)
    head = soup.find("head")
    if head:
        head.insert(0, base_tag)
    else:
        html_tag = soup.find("html")
        if html_tag:
            new_head = soup.new_tag("head")
            new_head.insert(0, base_tag)
            html_tag.insert(0, new_head)

    return encoded


@proxy_router.get("/v/{path:path}")
async def proxy_virtual(path: str, request: Request):
    """Reverse proxy for all proxied resources under /v/<encoded-base>/<resource-path>."""
    if "/" not in path:
        raise HTTPException(status_code=400, detail="Invalid proxy path")
    encoded, resource = path.split("/", 1)
    try:
        missing_padding = 4 - len(encoded) % 4
        if missing_padding != 4:
            encoded += "=" * missing_padding
        base_url = base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid encoded base URL")

    # Separate origin from path to handle two encoding schemes:
    #   A) /v/<encoded-origin>/<resource-path>      (origin in base64)
    #   B) /v/<encoded-origin+path>/                 (full URL in base64)
    parsed_base = urllib.parse.urlparse(base_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    site_path = parsed_base.path.rstrip("/")
    spa_resource_path = resource if resource else site_path.lstrip("/")

    if base_url.startswith("file://"):
        file_base = base_url[len("file://"):]
        if resource:
            target_path = str(Path(file_base).parent / resource)
        else:
            target_path = file_base
        target_file = Path(target_path)
        if not target_file.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {target_path}")
        if not resource or target_file.suffix in (".html", ".htm"):
            raw = target_file.read_text(encoding="utf-8")
            soup = BeautifulSoup(raw, "lxml")
            _strip_security_meta(soup)
            _rewrite_to_proxy_v(soup, base_url, spa_resource_path)
            _inject_inspector(soup)
            return HTMLResponse(str(soup))
        ct, _ = mimetypes.guess_type(target_path)
        return Response(content=target_file.read_bytes(), media_type=ct or "application/octet-stream")

    # Resource paths are relative to origin (not base_url which may include path)
    if resource:
        target = origin.rstrip("/") + "/" + resource
    else:
        target = base_url.rstrip("/") + "/"
    if request.url.query:
        target += "?" + request.url.query

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(
                target,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                },
            )
            ct = (resp.headers.get("content-type") or "").lower()
            if "text/html" in ct:
                soup = BeautifulSoup(resp.text, "lxml")
                _strip_security_meta(soup)
                _rewrite_to_proxy_v(soup, base_url, spa_resource_path)
                _inject_inspector(soup)
                return HTMLResponse(str(soup))
            return Response(content=resp.content, media_type=ct)
    except httpx.TimeoutException:
        return HTMLResponse(
            _proxy_error_html("Proxy request timed out", "The server took too long to respond."),
            status_code=504,
        )
    except Exception as e:
        err_msg = str(e)
        if "Name or service not known" in err_msg or "nodename nor servname provided" in err_msg:
            friendly = "This website could not be found. Check that the URL is correct."
            if "www." in target:
                friendly += " Try removing the 'www.' prefix."
        else:
            friendly = f"Could not load this page. {err_msg[:120]}"
        return HTMLResponse(
            _proxy_error_html("Proxy Error", friendly),
            status_code=502,
        )


app.include_router(proxy_router)


@app.get("/preview", response_class=HTMLResponse)
async def preview(url: str = Query(..., description="URL to preview and inspect")):
    try:
        html = await fetch_page_html(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    _strip_security_meta(soup)

    if url.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(url)
        _rewrite_to_proxy_v(soup, url, parsed.path.lstrip("/"))
    else:
        base_tag = soup.new_tag("base", href=url)
        head = soup.find("head")
        if head:
            head.insert(0, base_tag)
        else:
            html_tag = soup.find("html")
            if html_tag:
                new_head = soup.new_tag("head")
                new_head.insert(0, base_tag)
                html_tag.insert(0, new_head)
        _rewrite_urls(soup, url)

    _inject_inspector(soup)

    return str(soup)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    try:
        html = await fetch_page_html(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = parse_html(html, url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    title = _extract_title(tree)
    root_node = _element_to_node(tree.root)
    element_count = len(tree.elements_by_selector)

    return AnalyzeResponse(
        url=req.url,
        title=title,
        root=root_node,
        element_count=element_count,
    )


@app.post("/com-gen")
async def com_gen(req: ComGenRequest):
    try:
        html = await fetch_page_html(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = parse_html(html, url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    element = get_element_by_selector(tree, req.selector)

    if element is None:
        raise HTTPException(
            status_code=404,
            detail=f"Selector '{req.selector}' not found on page",
        )

    classification = classify(element)
    descriptor = build_descriptor(element, classification)
    python_code = render_com(descriptor)

    return ComGenResponse(
        component_type=classification.component_type,
        confidence=classification.confidence,
        python_code=python_code,
    )


def _tag_to_minimal_info(tag):
    """Extract attributes, text, aria from a BeautifulSoup Tag for selector gen."""
    from .generation.models import ElementInfo
    attrs = dict(tag.attrs) if tag.attrs else {}
    text = tag.get_text(strip=True)
    aria = {}
    for key in list(attrs.keys()):
        if key.startswith("aria-"):
            aria[key] = attrs.pop(key)
    role = attrs.get("role") or aria.get("aria-role")
    return ElementInfo(
        tag=tag.name,
        attributes=attrs,
        text=text,
        role=role,
        aria=aria,
        css_path="",
        xpath="",
        depth=0,
        index=0,
    )


@app.post("/validate-com")
async def validate_com(req: ValidateComRequest):
    try:
        html = await fetch_page_html(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = parse_html(html, url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    element = get_element_by_selector(tree, req.selector)
    if element is None:
        raise HTTPException(status_code=404, detail=f"Selector '{req.selector}' not found on page")

    classification = classify(element)
    descriptor = build_descriptor(element, classification)

    for field in descriptor.fields:
        if field.name in req.field_overrides:
            field.selector_value = req.field_overrides[field.name]

    python_code = render_com(descriptor)

    root_candidates_raw = generate_selectors(element)
    root_candidates_data = [
        {"key": f"root:{c['strategy']}", "strategy": c["strategy"], "selector": c["value"], "type": c["type"], "relative": False}
        for c in root_candidates_raw
    ]

    fields_data = []
    selectors_to_check = list(root_candidates_data)
    soup = tree.soup

    for field in descriptor.fields:
        child_candidates = []
        child_selectors_to_check = []

        if soup is not None:
            full_sel = f"{req.selector} {field.selector_value}"
            matched_tags = soup.select(full_sel)
            if matched_tags:
                child_info = _tag_to_minimal_info(matched_tags[0])
                raw_candidates = generate_relative_selectors(child_info)
                for rc in raw_candidates:
                    kid = f"field:{field.name}:{rc['strategy']}"
                    child_candidates.append({
                        "strategy": rc["strategy"],
                        "selector": rc["selector"],
                        "type": rc["type"],
                    })
                    child_selectors_to_check.append({
                        "key": kid,
                        "strategy": rc["strategy"],
                        "selector": rc["selector"],
                        "type": rc["type"],
                        "relative": True,
                    })
                selectors_to_check.extend(child_selectors_to_check)

        fields_data.append({
            "name": field.name,
            "current_selector": field.selector_value,
            "candidates": child_candidates,
        })

    validation_results = []
    if selectors_to_check:
        try:
            validation_results = await validate_selectors_on_page(req.url, req.selector, selectors_to_check)
        except Exception:
            validation_results = []

    root_selectors = []
    for rc in root_candidates_data:
        match = next(
            (r for r in validation_results if r.get("key") == rc["key"]),
            None,
        )
        root_selectors.append(ValidatedSelector(
            strategy=rc["strategy"],
            selector=match["selector"] if match else rc["selector"],
            type=rc["type"],
            matches=match["matches"] if match else 0,
            sample_html=match.get("sample_html", "") if match else "",
            stability=match.get("stability", "broken") if match else "broken",
        ))

    field_validations = []
    for fd in fields_data:
        fcandidates = []
        for fc in fd["candidates"]:
            kid = f"field:{fd['name']}:{fc['strategy']}"
            match = next(
                (r for r in validation_results if r.get("key") == kid),
                None,
            )
            fcandidates.append(ValidatedSelector(
                strategy=fc["strategy"],
                selector=match["selector"] if match else fc["selector"],
                type=fc["type"],
                matches=match["matches"] if match else 0,
                sample_html=match.get("sample_html", "") if match else "",
                stability=match.get("stability", "broken") if match else "broken",
            ))
        field_validations.append(FieldValidation(
            name=fd["name"],
            current_selector=fd["current_selector"],
            candidates=fcandidates,
        ))

    return ValidateComResponse(
        python_code=python_code,
        component_type=classification.component_type,
        confidence=classification.confidence,
        root_selectors=root_selectors,
        fields=field_validations,
    )


@app.post("/validate-selectors")
async def validate_selectors(req: ValidateSelectorsRequest):
    try:
        results = await validate_arbitrary_selectors(req.url, req.selectors, req.context_selector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ValidateSelectorsResponse(
        results=[ValidatedSelector(**r) for r in results]
    )


def _find_significant_components(tree, max_components: int = 8):
    results = []
    seen_selectors: set[str] = set()

    def walk(element):
        if len(results) >= max_components:
            return
        cls_result = classify(element)
        if cls_result.confidence > 0 and cls_result.component_type != "GenericComponent":
            sel = element.css_path
            if sel not in seen_selectors:
                seen_selectors.add(sel)
                results.append((element, cls_result))
        for child in element.children:
            walk(child)

    walk(tree.root)
    return results


@app.post("/components")
async def components(req: AnalyzeRequest):
    try:
        html = await fetch_page_html(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = parse_html(html, url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    found = _find_significant_components(tree)

    component_list = [
        ComponentInfo(
            selector=el.css_path,
            component_type=cls.component_type,
            confidence=cls.confidence,
            tag=el.tag,
            text=(el.text or "").strip()[:80],
        )
        for el, cls in found
    ]

    return ComponentsResponse(url=req.url, components=component_list)


@app.post("/pom-gen")
async def pom_gen(req: PomGenRequest):
    if not req.selectors:
        raise HTTPException(status_code=400, detail="At least one selector required")

    try:
        html = await fetch_page_html(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = parse_html(html, url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    suite_name = req.suite_name.strip() or "PageSuite"
    suite_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in suite_name)

    com_refs: list[ComReference] = []
    files: list[PomGenFile] = []

    for selector in req.selectors:
        element = get_element_by_selector(tree, selector)
        if element is None:
            continue

        cls_result = classify(element)
        descriptor = build_descriptor(element, cls_result)
        com_code = render_com(descriptor)

        var_name = descriptor.class_name[0].lower() + descriptor.class_name[1:]
        com_refs.append(
            ComReference(
                name=var_name,
                class_name=descriptor.class_name,
                selector=descriptor.root_selector,
                has_test_actions=len(descriptor.fields) > 0,
            )
        )
        files.append(PomGenFile(
            filename=f"{descriptor.class_name}.py",
            content=com_code,
            type="com",
        ))

    if not com_refs:
        raise HTTPException(status_code=400, detail="None of the selectors matched any elements")

    page_model = PageModel(
        class_name=suite_name,
        description=suite_name,
        components=com_refs,
        url=req.url,
    )

    pom_code = render_pom(page_model)
    test_code = render_tests(page_model)

    files.insert(0, PomGenFile(
        filename=f"{suite_name}.py",
        content=pom_code,
        type="pom",
    ))
    files.insert(1, PomGenFile(
        filename=f"test_{suite_name}.py",
        content=test_code,
        type="test",
    ))

    return PomGenResponse(suite_name=suite_name, files=files)


@app.post("/generate-test")
async def generate_test(req: TestGenRequest):
    suite_name = req.suite_name.strip() or "TestSuite"
    suite_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in suite_name)
    suite_name = _to_pascal_case(suite_name)

    comps = []
    for comp in req.components:
        actions_data = [{"type": a.type, "value": a.value} for a in comp.actions]
        cond = comp.condition
        comps.append(ComponentActionData(
            name=comp.name,
            class_name=_to_pascal_case(comp.name),
            selector=comp.selector,
            actions=actions_data,
            custom_code=comp.custom_code,
            condition=cond.model_dump() if cond else None,
        ))

    pom_code = render_action_pom(suite_name, req.url, comps)
    test_code = render_action_test(suite_name, suite_name, req.url, comps)

    files = [
        TestGenFile(filename=f"{suite_name}.py", content=pom_code, type="pom"),
        TestGenFile(filename=f"test_{suite_name}.py", content=test_code, type="test"),
    ]
    return TestGenResponse(suite_name=suite_name, files=files)


@app.post("/select-area")
async def select_area(req: SelectAreaRequest):
    try:
        info = await find_element_at(
            req.url, req.x, req.y, req.width, req.height,
            req.viewport_width, req.viewport_height,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not info.get("cssPath"):
        raise HTTPException(status_code=404, detail="No element found at that position")

    try:
        tree = parse_html(info["html"], url=req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    element = get_element_by_selector(tree, info["cssPath"])
    if element is None:
        raise HTTPException(status_code=404, detail=f"Element '{info['cssPath']}' not found in parsed tree")

    classification = classify(element)
    descriptor = build_descriptor(element, classification)
    python_code = render_com(descriptor)

    alternatives = [
        SelectorAlternative(type=a["type"], selector=a["selector"], description=a.get("description", ""))
        for a in info.get("alternatives", [])
    ] if info.get("alternatives") else []

    dom_tree = info.get("domTree")
    dom_node = None
    if dom_tree:
        dom_node = DomNode(**dom_tree)

    elements_list = [
        HitElement(
            css_path=e["cssPath"],
            tag=e["tag"],
            text=e.get("text", ""),
            id=e.get("id", ""),
            classes=e.get("classes", []),
            child_count=e.get("childCount", 0),
            interactive_children=e.get("interactiveChildren", 0),
        )
        for e in info.get("elements", [])
    ]

    return SelectAreaResponse(
        css_path=info["cssPath"],
        tag=info["tag"],
        text=info.get("text", ""),
        python_code=python_code,
        component_type=classification.component_type,
        confidence=classification.confidence,
        alternatives=alternatives,
        dom_tree=dom_node,
        elements=elements_list,
    )


def _to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())
