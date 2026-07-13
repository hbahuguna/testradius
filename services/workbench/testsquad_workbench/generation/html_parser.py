from __future__ import annotations

from bs4 import BeautifulSoup, Tag, NavigableString

from .models import DOMTree, ElementInfo

INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea",
    "details", "summary", "label", "option",
}
INTERACTIVE_ROLES = {
    "button", "link", "checkbox", "radio", "tab",
    "menuitem", "option", "switch", "textbox",
    "combobox", "listbox", "slider", "spinbutton",
}


def _compute_css_path(tag: Tag) -> str:
    parts = []
    for parent in tag.parents:
        if not isinstance(parent, Tag) or parent.name in ("[document]", "html"):
            continue
        selector = parent.name
        if parent.get("id"):
            selector = f"{selector}#{parent['id']}"
        else:
            classes = parent.get("class", [])
            if isinstance(classes, list) and classes:
                selector = f"{selector}.{'.'.join(classes)}"
        parts.append(selector)
    parts.append(tag.name)
    if tag.get("id"):
        parts[-1] = f"{tag.name}#{tag['id']}"
    else:
        classes = tag.get("class", [])
        if isinstance(classes, list) and classes:
            parts[-1] = f"{tag.name}.{'.'.join(classes)}"
    return " > ".join(parts)


def _compute_xpath(tag: Tag) -> str:
    parts = []
    for parent in tag.parents:
        if isinstance(parent, Tag):
            siblings = [s for s in parent.children if isinstance(s, Tag) and s.name == tag.name]
            if len(siblings) > 1:
                idx = 1
                for s in parent.children:
                    if isinstance(s, Tag) and s.name == tag.name:
                        if s == tag:
                            break
                        idx += 1
                parts.append(f"{tag.name}[{idx}]")
            else:
                parts.append(tag.name)
    parts.reverse()
    return "/" + "/".join(parts)


def _label_text_for(label_tag: Tag, control_tag: Tag) -> str:
    """Accessible name from a <label>, minus the control's own text.

    For wrapping labels like `<label>Name <input></label>` the control's own
    text must be stripped so we return "Name", not "Name <option text>".
    """
    label_text = label_tag.get_text(" ", strip=True)
    if control_tag.name not in ("input", "img", "br", "hr"):
        control_text = control_tag.get_text(" ", strip=True)
        if control_text:
            if label_text.startswith(control_text):
                label_text = label_text[len(control_text):].strip()
            elif label_text.endswith(control_text):
                label_text = label_text[: -len(control_text)].strip()
    return label_text


def _compute_accessible_name(tag: Tag, attrs: dict, aria: dict, text: str) -> str:
    """Compute an element's accessible name per HTML/ARIA spec order:

    aria-labelledby -> aria-label -> associated <label> (explicit for= or
    wrapping parent) -> title -> placeholder (inputs/textareas) -> text.
    """
    labelledby = aria.get("aria-labelledby") or attrs.get("aria-labelledby")
    if labelledby and labelledby.strip():
        parts: list[str] = []
        for ref_id in labelledby.split():
            ref = tag.find_previous(attrs={"id": ref_id})
            if ref is None:
                ref = tag.find(attrs={"id": ref_id})
            if ref is not None:
                parts.append(ref.get_text(" ", strip=True))
        joined = " ".join(p for p in parts if p).strip()
        if joined:
            return joined

    al = aria.get("aria-label") or attrs.get("aria-label")
    if al and al.strip():
        return al.strip()

    el_id = attrs.get("id")
    if el_id:
        label_tag = tag.find_previous("label", attrs={"for": el_id})
        if label_tag is not None:
            name = _label_text_for(label_tag, tag)
            if name:
                return name

    parent = tag.parent
    if parent is not None and getattr(parent, "name", None) == "label":
        name = _label_text_for(parent, tag)
        if name:
            return name

    title = attrs.get("title")
    if title and title.strip():
        return title.strip()

    if tag.name in ("input", "textarea"):
        ph = attrs.get("placeholder")
        if ph and ph.strip():
            return ph.strip()

    return text


def _extract_element_info(
    tag: Tag,
    depth: int,
    index: int,
    visible_only: bool = True,
) -> ElementInfo:
    attrs = dict(tag.attrs) if tag.attrs else {}

    aria = {}
    for key in list(attrs.keys()):
        if key.startswith("aria-"):
            aria[key] = attrs.pop(key)

    text = tag.get_text(strip=True)

    accessible_name = _compute_accessible_name(tag, attrs, aria, text)

    role = attrs.get("role") or aria.get("aria-role")
    if tag.name == "a" and tag.get("href"):
        role = role or "link"

    is_interactive = tag.name in INTERACTIVE_TAGS or role in INTERACTIVE_ROLES

    is_visible = True
    if visible_only:
        style = attrs.get("style", "")
        hidden = attrs.get("hidden")
        if "display:" in style and "none" in style:
            is_visible = False
        if "visibility:" in style and "hidden" in style:
            is_visible = False
        if hidden is not None:
            is_visible = False

    children = []
    child_idx = 1
    for child in tag.children:
        if isinstance(child, Tag):
            child_info = _extract_element_info(
                child, depth + 1, child_idx, visible_only
            )
            children.append(child_info)
            child_idx += 1

    css_path = _compute_css_path(tag)
    xpath = _compute_xpath(tag)

    return ElementInfo(
        tag=tag.name,
        attributes=attrs,
        text=text,
        role=role,
        accessible_name=accessible_name,
        aria=aria,
        css_path=css_path,
        xpath=xpath,
        depth=depth,
        index=index,
        children=children,
        is_interactive=is_interactive,
        is_visible=is_visible,
    )


def parse_html(html: str, url: str = "") -> DOMTree:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body") or soup
    root = _extract_element_info(body, depth=0, index=1)

    elements_by_selector: dict[str, ElementInfo] = {}
    _index_elements(elements_by_selector, root, seen=set())

    return DOMTree(url=url, root=root, elements_by_selector=elements_by_selector, soup=soup)


def _index_elements(
    mapping: dict[str, ElementInfo],
    element: ElementInfo,
    seen: set[str],
) -> None:
    key = element.css_path
    if key and key not in seen:
        mapping[key] = element
        seen.add(key)
    for child in element.children:
        _index_elements(mapping, child, seen)


def get_element_by_selector(dom_tree: DOMTree, selector: str) -> ElementInfo | None:
    if selector in dom_tree.elements_by_selector:
        return dom_tree.elements_by_selector[selector]

    soup = dom_tree.soup
    if soup is None:
        return None

    tags = soup.select(selector)
    if not tags:
        return None

    css_path = _compute_css_path(tags[0])
    return dom_tree.elements_by_selector.get(css_path)


def get_element_by_css(dom_tree: DOMTree, css_selector: str) -> ElementInfo | None:
    return get_element_by_selector(dom_tree, css_selector)
