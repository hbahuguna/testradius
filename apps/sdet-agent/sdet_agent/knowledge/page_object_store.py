"""Page Object Store: discovers and parses Playwright Page Objects from the repo.

Extracts class names, locators, and methods from TypeScript files in the
`artifacts/e2e-tests/pages/` directory. This provides structured knowledge
about the existing automation surface (textbook Ch.1 Layer 4: Knowledge).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("sdet_agent.knowledge.po_store")


@dataclass
class LocatorInfo:
    name: str
    selector: str
    type: str # getByRole, locator, etc.
    line: int

@dataclass
class MethodInfo:
    name: str
    signature: str
    description: str = ""

@dataclass
class PageObjectInfo:
    name: str
    file_path: Path
    locators: list[LocatorInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    source_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file_path": str(self.file_path),
            "locators": [l.__dict__ for l in self.locators],
            "methods": [m.__dict__ for m in self.methods],
            "source_code": self.source_code,
        }


class PageObjectStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.pages_dir = repo_root / "artifacts" / "e2e-tests" / "pages"
        self._page_objects: dict[str, PageObjectInfo] = {}
        self.load_page_objects()

    def load_page_objects(self) -> None:
        if not self.pages_dir.exists():
            logger.warning("Page Objects directory not found: %s", self.pages_dir)
            return
        for ts_file in self.pages_dir.glob("*.ts"):
            try:
                content = ts_file.read_text(encoding="utf-8")
                po_info = self._parse_page_object(ts_file, content)
                if po_info:
                    self._page_objects[po_info.name] = po_info
            except Exception as exc: # noqa: BLE001
                logger.error("Error parsing page object %s: %s", ts_file, exc)
        logger.info("Loaded %d page objects", len(self._page_objects))

    def _parse_page_object(self, file_path: Path, content: str) -> Optional[PageObjectInfo]:
        class_match = re.search(r"export class (\w+) {[^}]*", content, re.DOTALL)
        if not class_match:
            return None
        po_name = class_match.group(1)
        locators: list[LocatorInfo] = []
        methods: list[MethodInfo] = []

        # Regex for locators (basic: this.foo = page.getByRole(...))
        for i, line in enumerate(content.splitlines()):
            # Example: readonly emailInput: Locator;
            prop_match = re.search(r"readonly (\w+): Locator;", line)
            if prop_match:
                locator_name = prop_match.group(1)
                # Try to find the assignment line for the selector
                assign_match = re.search(rf"this\.{locator_name}\s*=\s*(page\.(getBy\w+|locator)\(.*\));", content)
                if assign_match:
                    selector_code = assign_match.group(1)
                    locator_type_match = re.search(r"(getBy\w+|locator)", selector_code)
                    locators.append(LocatorInfo(name=locator_name,
                                                selector=selector_code,
                                                type=locator_type_match.group(1) if locator_type_match else "unknown",
                                                line=i+1))

            # Regex for methods (basic: async foo() { ... })
            method_match = re.search(r"(async\s+)?(\w+)\(([^)]*)\)(\s*:\s*\w+)?\s*{ ", line)
            if method_match:
                method_name = method_match.group(2)
                method_args = method_match.group(3)
                methods.append(MethodInfo(name=method_name, signature=f"{method_name}({method_args})"))

        return PageObjectInfo(name=po_name, file_path=file_path, locators=locators, methods=methods, source_code=content)

    def get_page_object(self, name: str) -> Optional[PageObjectInfo]:
        return self._page_objects.get(name)

    def list_page_objects(self) -> list[PageObjectInfo]:
        return list(self._page_objects.values())

    def to_formatted_string(self) -> str:
        """Return a readable string representation of all loaded P.O.s."""
        if not self._page_objects:
            return "No Page Objects loaded."
        parts: list[str] = ["=== Available Page Objects ==="]
        for po in self._page_objects.values():
            parts.append(f"\nFile: {po.file_path.relative_to(self.repo_root)}")
            parts.append(f"Class: {po.name}")
            if po.locators:
                parts.append("  Locators:")
                for loc in po.locators:
                    parts.append(f"    - {loc.name}: {loc.selector} (type: {loc.type})")
            if po.methods:
                parts.append("  Methods:")
                for meth in po.methods:
                    parts.append(f"    - {meth.signature}")
        return "\n".join(parts)
