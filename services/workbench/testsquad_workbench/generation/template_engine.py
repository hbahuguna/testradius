from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .descriptors import ComponentDescriptor

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class ComReference:
    name: str
    class_name: str
    selector: str
    has_test_actions: bool = False
    action_hint: str = ""


class PageModel:
    def __init__(
        self,
        class_name: str,
        description: str,
        components: list[ComReference],
        url: str = "",
    ) -> None:
        self.class_name = class_name
        self.description = description
        self.components = components
        self.url = url
        self.com_imports = sorted(set(c.class_name for c in components))


def render_com(descriptor: ComponentDescriptor) -> str:
    template = _ENV.get_template("com_template.j2")
    return template.render(
        class_name=descriptor.class_name,
        component_type=descriptor.component_type,
        root_selector=descriptor.root_selector,
        confidence=f"{descriptor.confidence:.1f}",
        fields=descriptor.fields,
    )


def render_pom(page_model: PageModel) -> str:
    template = _ENV.get_template("pom_template.j2")
    return template.render(
        class_name=page_model.class_name,
        description=page_model.description,
        com_imports=page_model.com_imports,
        components=page_model.components,
    )


def render_tests(page_model: PageModel) -> str:
    template = _ENV.get_template("test_template.j2")
    return template.render(
        class_name=page_model.class_name,
        description=page_model.description,
        components=page_model.components,
    )


@dataclass
class ActionStepData:
    description: str
    is_action: bool = True
    method: str = ""
    value: str = ""
    code: str = ""
    selector: str = ""
    condition: dict | None = None


@dataclass
class ComponentActionData:
    name: str
    class_name: str
    selector: str
    actions: list[dict]  # [{type: str, value: str}]
    custom_code: str = ""
    condition: dict | None = None


def _method_name(component_name: str, action_type: str) -> str:
    return f"{component_name}_{action_type}"


def render_action_pom(
    suite_name: str,
    url: str,
    components: list[ComponentActionData],
) -> str:
    comps_with_fill = []
    comps_with_select = []
    comps_with_hover = []
    for c in components:
        for a in c.actions:
            if a["type"] == "type":
                if c not in comps_with_fill:
                    comps_with_fill.append(c)
            elif a["type"] == "select":
                if c not in comps_with_select:
                    comps_with_select.append(c)
            elif a["type"] == "hover":
                if c not in comps_with_hover:
                    comps_with_hover.append(c)

    template = _ENV.get_template("action_pom_template.j2")
    return template.render(
        suite_name=suite_name,
        class_name=suite_name,
        url=url,
        components=components,
        components_with_fill=comps_with_fill,
        components_with_select=comps_with_select,
        components_with_hover=comps_with_hover,
    )


def render_action_test(
    suite_name: str,
    test_name: str,
    url: str,
    components: list[ComponentActionData],
    global_steps: list[ActionStepData] | None = None,
) -> str:
    steps: list[ActionStepData] = []

    for i, comp in enumerate(components):
        for action in comp.actions:
            method = _method_name(comp.name, action["type"])
            val = f'"{action["value"]}"' if action.get("value") else ""
            cond = comp.condition
            if cond and isinstance(cond, dict):
                cond = {k: v for k, v in cond.items() if v}
            steps.append(ActionStepData(
                description=f"{action['type'].replace('_', ' ').title()} {comp.name}",
                method=method,
                value=val,
                selector=comp.selector,
                condition=cond,
            ))

    if global_steps:
        steps = global_steps + steps

    template = _ENV.get_template("action_test_template.j2")
    return template.render(
        suite_name=suite_name,
        class_name=_to_pascal_case(suite_name),
        steps=steps,
    )


def _to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())
