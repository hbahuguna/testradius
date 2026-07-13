from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class ElementNode(BaseModel):
    tag: str
    attributes: dict[str, str]
    text: str
    role: Optional[str] = None
    aria: dict[str, str] = {}
    accessible_name: str = ""
    css_path: str = ""
    xpath: str = ""
    depth: int = 0
    index: int = 0
    children: list["ElementNode"] = []
    is_interactive: bool = False
    is_visible: bool = True


class AnalyzeRequest(BaseModel):
    url: str


class AnalyzeResponse(BaseModel):
    url: str
    title: str
    root: ElementNode
    element_count: int


class ComGenRequest(BaseModel):
    url: str
    selector: str


class ComGenResponse(BaseModel):
    component_type: str
    confidence: float
    python_code: str


class ComponentInfo(BaseModel):
    selector: str
    component_type: str
    confidence: float
    tag: str
    text: str = ""


class ComponentsResponse(BaseModel):
    url: str
    components: list[ComponentInfo]


class PomGenFile(BaseModel):
    filename: str
    content: str
    type: str  # "com", "pom", "test"


class PomGenRequest(BaseModel):
    url: str
    selectors: list[str]
    suite_name: str = ""


class PomGenResponse(BaseModel):
    suite_name: str
    files: list[PomGenFile]


class ConditionSchema(BaseModel):
    type: str  # "element_visible" | "element_exists"
    selector: str = ""


class ActionStep(BaseModel):
    type: str
    value: str = ""


class TestGenComponent(BaseModel):
    name: str
    selector: str
    tag: str = ""
    text: str = ""
    actions: list[ActionStep] = []
    custom_code: str = ""
    condition: ConditionSchema | None = None


class TestGenRequest(BaseModel):
    url: str
    suite_name: str = ""
    components: list[TestGenComponent]


class TestGenFile(BaseModel):
    filename: str
    content: str
    type: str


class TestGenResponse(BaseModel):
    suite_name: str
    files: list[TestGenFile]


class UserComponentData(BaseModel):
    id: str
    name: str
    url: str
    selector: str
    tag: str = ""
    text: str = ""
    createdAt: float = 0.0


class ComponentLibrary(BaseModel):
    components: list[UserComponentData] = []


class SelectAreaRequest(BaseModel):
    url: str
    x: int
    y: int
    width: int
    height: int
    viewport_width: int = 1280
    viewport_height: int = 720


class SelectorAlternative(BaseModel):
    type: str
    selector: str
    description: str = ""


class DomNode(BaseModel):
    key: str
    tag: str
    id: str = ""
    classes: list[str] = []
    attributes: dict[str, str] = {}
    text: str = ""
    hasChildren: bool = False
    children: list[DomNode] = []
    depth: int = 0


class HitElement(BaseModel):
    css_path: str
    tag: str
    text: str = ""
    id: str = ""
    classes: list[str] = []
    child_count: int = 0
    interactive_children: int = 0


class SelectAreaResponse(BaseModel):
    css_path: str
    tag: str
    text: str = ""
    python_code: str
    component_type: str
    confidence: float
    alternatives: list[SelectorAlternative] = []
    dom_tree: DomNode | None = None
    elements: list[HitElement] = []


class ValidatedSelector(BaseModel):
    strategy: str
    selector: str
    type: str
    matches: int = 0
    sample_html: str = ""
    stability: str = ""


class FieldValidation(BaseModel):
    name: str
    current_selector: str
    candidates: list[ValidatedSelector] = []


class ValidateComRequest(BaseModel):
    url: str
    selector: str
    field_overrides: dict[str, str] = {}


class ValidateComResponse(BaseModel):
    python_code: str
    component_type: str
    confidence: float
    root_selectors: list[ValidatedSelector] = []
    fields: list[FieldValidation] = []


class ValidateSelectorsRequest(BaseModel):
    url: str
    selectors: list[str]
    context_selector: str = ""


class ValidateSelectorsResponse(BaseModel):
    results: list[ValidatedSelector] = []
