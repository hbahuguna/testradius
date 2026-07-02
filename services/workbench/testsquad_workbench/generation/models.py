from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ElementInfo:
    tag: str
    attributes: dict[str, str]
    text: str
    role: str | None
    aria: dict[str, str]
    css_path: str
    xpath: str
    depth: int
    index: int
    children: list[ElementInfo] = field(default_factory=list)
    is_interactive: bool = False
    is_visible: bool = True


@dataclass
class DOMTree:
    url: str
    root: ElementInfo
    elements_by_selector: dict[str, ElementInfo] = field(default_factory=dict)
    soup: object | None = field(default=None, repr=False)
