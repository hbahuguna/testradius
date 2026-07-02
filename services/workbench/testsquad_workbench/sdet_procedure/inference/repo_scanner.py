from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PageObject:
    class_name: str
    file_path: str
    selectors: Dict[str, str]
    methods: List[str]
    url_path: Optional[str] = None
    source_code: str = ""

    def summarize(self) -> str:
        parts = [f"class {self.class_name}:"]
        for name, selector in self.selectors.items():
            parts.append(f"  {name}: {selector}")
        for m in self.methods[:5]:
            parts.append(f"  {m}")
        return "\n".join(parts)


@dataclass
class UtilityFunction:
    name: str
    file_path: str
    signature: str
    body_summary: str
    source_code: str = ""

    def summarize(self) -> str:
        return f"export {self.signature}  // in {Path(self.file_path).name}"


@dataclass
class RepoContext:
    page_objects: List[PageObject] = field(default_factory=list)
    utilities: List[UtilityFunction] = field(default_factory=list)
    test_patterns: List[str] = field(default_factory=list)
    base_url: Optional[str] = None
    framework: str = "playwright"

    def is_empty(self) -> bool:
        return not self.page_objects and not self.utilities

    def summarize(self, max_chars: int = 2000) -> str:
        parts = [f"Automation Framework: {self.framework}"]
        if self.base_url:
            parts.append(f"Base URL: {self.base_url}")
        parts.append("")
        if self.page_objects:
            parts.append("=== Page Objects ===")
            for po in self.page_objects:
                po_text = po.summarize()
                if len("\n".join(parts)) + len(po_text) > max_chars:
                    remaining = len(self.page_objects) - self.page_objects.index(po)
                    parts.append(f"... and {remaining} more page objects")
                    break
                parts.append(po_text)
                parts.append("")
        if self.utilities:
            parts.append("=== Utilities ===")
            for u in self.utilities:
                u_text = u.summarize()
                if len("\n".join(parts)) + len(u_text) > max_chars:
                    remaining = len(self.utilities) - self.utilities.index(u)
                    parts.append(f"... and {remaining} more utilities")
                    break
                parts.append(u_text)
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text

    def format_with_source(self, task_description: str, max_chars: int = 8000) -> str:
        task_block = f"=== Task ===\n{task_description}"
        header_block = "=== Repo Context ==="
        if self.base_url:
            header_block += f"\nBase URL: {self.base_url}"

        body_parts: List[str] = []
        if self.page_objects:
            body_parts.append("\n=== Page Objects ===")
            for po in self.page_objects:
                code = po.source_code or po.summarize()
                body_parts.append(f"\nFile: {po.file_path}\n```typescript\n{code}\n```")

        if self.utilities:
            body_parts.append("\n=== Utilities ===")
            for u in self.utilities:
                code = u.source_code or u.summarize()
                body_parts.append(f"\nFile: {u.file_path}\n```typescript\n{code}\n```")

        body_text = "".join(body_parts)
        body_alloc = max_chars - len(header_block) - len(task_block) - 30

        if len(body_text) > body_alloc and body_alloc > 500:
            mid = body_alloc // 2
            body_text = body_text[:mid] + "\n... (truncated) ...\n" + body_text[-(body_alloc - mid - 30):]

        return f"{header_block}\n{body_text}\n\n{task_block}"


_CLASS_PATTERN = re.compile(
    r'export\s+(default\s+)?class\s+(\w+).*?\{',
    re.DOTALL,
)
_LOCATOR_PATTERN = re.compile(
    r'readonly\s+(\w+)\s*[:=].*?(getBy|locator|nth|first|last)',
)
_METHOD_PATTERN = re.compile(
    r'async\s+(\w+)\s*\([^)]*\)\s*[:{]',
)
_EXPORT_FUNC_PATTERN = re.compile(
    r'export\s+(async\s+)?function\s+(\w+)\s*\(',
)
_EXPORT_CONST_FUNC_PATTERN = re.compile(
    r'export\s+(const|let|var)\s+(\w+)\s*=.*?=>',
)
_SELECTOR_EXTRACT = re.compile(
    r'readonly\s+\w+\s*[:=]\s*(page\.\S+(?:\([^)]*\))+)',
)
_BASE_URL_PATTERN = re.compile(r'baseURL:\s*[\'"]([^\'"]+)[\'"]')
_DIR_PATTERNS = {
    'pages': 'page objects',
    'page-objects': 'page objects',
    'po': 'page objects',
    'utils': 'utilities',
    'helpers': 'utilities',
    'support': 'utilities',
    'tests': 'tests',
    'specs': 'tests',
    'e2e': 'tests',
}


class RepoScanner:
    def __init__(self, repo_path: str):
        self._repo_path = Path(repo_path)

    def scan(self) -> RepoContext:
        ctx = RepoContext()
        if not self._repo_path.is_dir():
            return ctx
        ts_files = list(self._repo_path.rglob("*.ts")) + list(self._repo_path.rglob("*.tsx"))
        js_files = list(self._repo_path.rglob("*.js")) + list(self._repo_path.rglob("*.jsx"))
        all_files = ts_files + js_files

        config_file = self._repo_path / "playwright.config.ts"
        if config_file.exists():
            ctx.base_url = self._extract_base_url(config_file.read_text())
        else:
            config_js = self._repo_path / "playwright.config.js"
            if config_js.exists():
                ctx.base_url = self._extract_base_url(config_js.read_text())

        for fp in all_files:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = fp.relative_to(self._repo_path)
            parent_dir = rel.parent.as_posix().split("/")[0].lower()

            if parent_dir in ("pages", "page-objects", "po"):
                po = self._parse_page_object(text, str(fp))
                if po:
                    ctx.page_objects.append(po)
            elif parent_dir in ("utils", "helpers", "support"):
                funcs = self._parse_utilities(text, str(fp))
                ctx.utilities.extend(funcs)
            elif parent_dir in ("tests", "specs", "e2e"):
                self._collect_test_pattern(text, ctx)

        for fp in all_files:
            if fp in [f for f in all_files if self._is_in_root(f)]:
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                rel = fp.relative_to(self._repo_path)
                parent = rel.parent.as_posix()
                if parent == "." and "page" in fp.stem.lower():
                    po = self._parse_page_object(text, str(fp))
                    if po and po.class_name not in {p.class_name for p in ctx.page_objects}:
                        ctx.page_objects.append(po)

        return ctx

    def _is_in_root(self, fp: Path) -> bool:
        rel = fp.relative_to(self._repo_path)
        return rel.parent.as_posix() == "."

    def _extract_base_url(self, text: str) -> Optional[str]:
        m = _BASE_URL_PATTERN.search(text)
        return m.group(1) if m else None

    def _parse_page_object(self, text: str, file_path: str) -> Optional[PageObject]:
        class_match = _CLASS_PATTERN.search(text)
        if not class_match:
            return None
        class_name = class_match.group(2)

        selectors: Dict[str, str] = {}
        for m in _SELECTOR_EXTRACT.finditer(text):
            selectors[m.group(1)] = m.group(1)

        if not selectors:
            for m in _LOCATOR_PATTERN.finditer(text):
                selectors[m.group(1)] = m.group(0).strip()

        methods = list(set(m.group(1) for m in _METHOD_PATTERN.finditer(text)))

        url_path = None
        goto_match = re.search(r'await\s+this\.page\.goto\(\s*[\'"]([^\'"]+)[\'"]', text)
        if goto_match:
            url_path = goto_match.group(1)

        return PageObject(
            class_name=class_name,
            file_path=file_path,
            selectors=selectors,
            methods=methods,
            url_path=url_path,
            source_code=text.strip(),
        )

    def _parse_utilities(self, text: str, file_path: str) -> List[UtilityFunction]:
        funcs: List[UtilityFunction] = []
        for m in _EXPORT_FUNC_PATTERN.finditer(text):
            name = m.group(2)
            sig_match = re.search(
                rf'export\s+(async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)',
                text,
            )
            sig = sig_match.group(0) if sig_match else f"function {name}(...)"
            body_lines = []
            start = m.end()
            depth = 0
            brace_found = False
            for ch in text[start:]:
                if ch == "{":
                    depth += 1
                    brace_found = True
                elif ch == "}":
                    depth -= 1
                    if brace_found and depth == 0:
                        break
                if brace_found and depth > 0:
                    body_lines.append(ch)
            summary = " ".join("".join(body_lines).split())[:80].strip()
            funcs.append(UtilityFunction(
                name=name,
                file_path=file_path,
                signature=sig,
                body_summary=summary,
                source_code=text.strip(),
            ))
        for m in _EXPORT_CONST_FUNC_PATTERN.finditer(text):
            name = m.group(2)
            funcs.append(UtilityFunction(
                name=name,
                file_path=file_path,
                signature=f"const {name} = (...) => ...",
                body_summary="arrow function",
                source_code=text.strip(),
            ))
        return funcs

    def _collect_test_pattern(self, text: str, ctx: RepoContext) -> None:
        test_patterns = re.findall(
            r"test\(['\"]([^'\"]+)['\"]",
            text,
        )
        for tp in test_patterns[:5]:
            ctx.test_patterns.append(tp)
