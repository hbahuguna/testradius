"""Scoped import/call resolution for the production knowledge graph (G3).

Resolves Python import statements to real modules (packages, relative imports,
aliases, re-exports) and scopes ``CALLS`` edges to the *resolved* target
module/symbol instead of matching bare symbol names project-wide.

This module is intentionally dependency-free (stdlib only) so it can be unit
tested in isolation. Parsing of ``__init__.py`` re-exports is injected via
``parse_imports`` to avoid pulling tree-sitter into this module.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Set, Tuple

DEFAULT_IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache",
    "lib", "site-packages", "bin", "include", "share", "dist", "build", "out",
    "docs", "public", "assets", "scripts", "tools", "benchmarks", "website",
    "coverage", ".next", ".cache", "logs", "tests", "test",
}

Binding = Dict[str, object]  # {"kind": "module"|"name", "module": str, "level": int, "orig": str}


def _norm(path: str) -> str:
    return path.replace("\\", "/")


class ImportResolver:
    """Builds a module index for a repo and resolves imports/calls against it."""

    def __init__(
        self,
        repo_root: str,
        source_root: Optional[str] = None,
        ignored_dirs: Optional[Set[str]] = None,
        parse_imports: Optional[Callable[[str], List[Dict]]] = None,
    ):
        self.repo_root = os.path.abspath(repo_root)
        self.source_root = os.path.abspath(source_root) if source_root else self.repo_root
        self.ignored_dirs = set(ignored_dirs if ignored_dirs is not None else DEFAULT_IGNORED_DIRS)
        self.parse_imports = parse_imports
        self._index: Dict[str, List[str]] = {}
        self._imports_cache: Dict[str, List[Dict]] = {}
        self._built = False

    # ------------------------------------------------------------------ index
    def build_index(self) -> None:
        if self._built:
            return
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [
                d for d in dirs
                if d not in self.ignored_dirs and not d.startswith(".")
            ]
            for f in files:
                if not f.endswith(".py"):
                    continue
                rel = _norm(os.path.relpath(os.path.join(root, f), self.repo_root))
                for dotted in self._module_names(rel):
                    bucket = self._index.setdefault(dotted, [])
                    if rel not in bucket:
                        bucket.append(rel)
        for key in self._index:
            # Packages (__init__.py) win over same-named modules; then shallowest,
            # then lexicographic for determinism.
            self._index[key].sort(
                key=lambda p: (0 if p.endswith("__init__.py") else 1, p.count("/"), p)
            )
        self._built = True

    def _module_names(self, rel: str) -> List[str]:
        names: List[str] = []
        for variant in self._path_variants(rel):
            noext = variant[:-3] if variant.endswith(".py") else variant
            if noext.endswith("/__init__"):
                noext = noext[: -len("/__init__")]
            if noext == "__init__":
                noext = ""
            if noext:
                names.append(noext.replace("/", "."))
        # de-dup preserving order
        seen: Set[str] = set()
        out: List[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def _path_variants(self, rel: str) -> List[str]:
        variants = [rel]
        sr = _norm(os.path.relpath(self.source_root, self.repo_root))
        if sr and sr != "." and (rel == sr or rel.startswith(sr + "/")):
            sub = rel[len(sr):].lstrip("/")
            if sub:
                variants.append(sub)
        return variants

    # -------------------------------------------------------------- resolve
    def resolve_module(self, dotted: str, from_rel: Optional[str] = None) -> Optional[str]:
        """Resolve a dotted module path to a repo-relative file path."""
        self.build_index()
        if not dotted:
            return None
        candidates = self._index.get(dotted)
        if not candidates:
            return None
        if len(candidates) == 1 or not from_rel:
            return candidates[0]
        return self._best(candidates, from_rel) or candidates[0]

    def _best(self, candidates: List[str], from_rel: str) -> Optional[str]:
        fdir = _norm(os.path.dirname(from_rel))

        def score(path: str) -> Tuple[int, int]:
            pdir = _norm(os.path.dirname(path))
            a = fdir.split("/") if fdir else []
            b = pdir.split("/") if pdir else []
            common = 0
            for x, y in zip(a, b):
                if x == y:
                    common += 1
                else:
                    break
            return (common, -path.count("/"))

        return max(candidates, key=score)

    def resolve_import(self, module: str, level: int, from_rel: str) -> Optional[str]:
        """Resolve ``import module`` / ``from module import ...`` to a file path.

        ``level`` is the number of leading dots for relative imports (0 = absolute).
        """
        module = module or ""
        if level and level > 0:
            base = _norm(os.path.dirname(from_rel))
            parts = base.split("/") if base else []
            up = level - 1
            if up > 0:
                parts = parts[:-up] if up <= len(parts) else []
            base_dotted = ".".join(parts)
            dotted = f"{base_dotted}.{module}" if module else base_dotted
        else:
            dotted = module
        return self.resolve_module(dotted, from_rel)

    def resolve_from_import(
        self,
        module_path: Optional[str],
        name: str,
        _seen: Optional[Set[Tuple[str, str]]] = None,
    ) -> Tuple[Optional[str], str]:
        """Resolve ``from module import name``.

        Returns ``(target_file, target_symbol)``. Handles submodules and
        re-exports through ``__init__.py`` (e.g. ``from pkg import x`` where
        ``pkg/__init__.py`` does ``from .a import x``).
        """
        if not module_path or name == "*":
            return (module_path, name)

        if module_path.endswith("__init__.py"):
            base_dir = _norm(os.path.dirname(module_path))

            # 1. `name` may be a submodule of the package.
            for candidate in self._child_paths(base_dir, name):
                if os.path.exists(os.path.join(self.repo_root, candidate)):
                    return (candidate, name)

            # 2. `name` may be re-exported by the package __init__.
            reexport = self._reexport_target(module_path, name, _seen)
            if reexport is not None:
                return reexport

        # 3. Otherwise the object lives in the module file itself.
        return (module_path, name)

    def _child_paths(self, base_dir: str, name: str) -> List[str]:
        prefix = f"{base_dir}/" if base_dir else ""
        return [f"{prefix}{name}.py", f"{prefix}{name}/__init__.py"]

    def _reexport_target(
        self,
        module_path: str,
        name: str,
        _seen: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[Tuple[Optional[str], str]]:
        seen = _seen if _seen is not None else set()
        key = (module_path, name)
        if key in seen:
            return None
        seen.add(key)

        for imp in self._imports_of(module_path):
            if imp.get("type") != "from_import":
                continue
            imported = [orig for orig, _alias in imp.get("names", [])]
            if name not in imported:
                continue
            sub_module = self.resolve_import(
                imp.get("module", ""), imp.get("level", 0), module_path
            )
            if sub_module:
                return self.resolve_from_import(sub_module, name, seen)
        return None

    def _imports_of(self, rel: str) -> List[Dict]:
        if rel in self._imports_cache:
            return self._imports_cache[rel]
        imports: List[Dict] = []
        if self.parse_imports is not None:
            abs_path = os.path.join(self.repo_root, rel)
            try:
                with open(abs_path, "r", errors="ignore") as fh:
                    content = fh.read()
                imports = self.parse_imports(rel, content) or []
            except Exception:
                imports = []
        self._imports_cache[rel] = imports
        return imports

    # ------------------------------------------------------------- bindings
    def build_bindings(self, imports: List[Dict]) -> Dict[str, Binding]:
        """Map local names introduced by imports to their source identities."""
        bindings: Dict[str, Binding] = {}
        for imp in imports or []:
            itype = imp.get("type")
            if itype == "import":
                module = imp.get("module") or imp.get("target") or ""
                alias = imp.get("alias")
                local = alias or module.split(".")[0]
                if not local:
                    continue
                # For `import pkg.mod` the bound name is the top package.
                bindings[local] = {"kind": "module", "module": module, "level": 0, "orig": local}
            elif itype == "from_import":
                module = imp.get("module", "")
                level = imp.get("level", 0)
                for entry in imp.get("names", []) or []:
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        orig, alias = entry
                    else:
                        orig, alias = entry, None
                    if not orig or orig == "*":
                        continue
                    local = alias or orig
                    bindings[local] = {
                        "kind": "name", "module": module, "level": level, "orig": orig,
                    }
        return bindings

    def _binding_home(self, binding: Binding, from_rel: str) -> Optional[str]:
        """File that defines the object bound to a local name."""
        module_file = self.resolve_import(
            binding.get("module", ""), int(binding.get("level", 0) or 0), from_rel
        )
        if binding.get("kind") == "module":
            return module_file
        target_file, _name = self.resolve_from_import(module_file, str(binding.get("orig")))
        return target_file

    # ----------------------------------------------------------------- calls
    def resolve_call(
        self,
        from_rel: str,
        callee_text: str,
        local_symbols: Set[str],
        bindings: Dict[str, Binding],
        lsp: Optional[Callable[[str, int, int], Optional[Tuple[str, str]]]] = None,
        line: Optional[int] = None,
        character: Optional[int] = None,
    ) -> Optional[Tuple[str, str]]:
        """Resolve a call expression's callee to ``(target_file, target_symbol)``.

        Returns ``None`` when the target cannot be resolved (which prevents a
        bare-name project-wide ``CALLS`` edge — the source of cross-module
        false positives on duplicate names).
        """
        if not callee_text:
            return None
        parts = callee_text.split(".")
        head, rest = parts[0], parts[1:]
        local_symbols = local_symbols or set()

        # Bare name: local definition, then imported name, else unresolved.
        if not rest:
            if head in local_symbols:
                return (from_rel, head)
            binding = bindings.get(head)
            if binding and binding.get("kind") == "name":
                home = self._binding_home(binding, from_rel)
                if home:
                    return (home, str(binding.get("orig")))
            return self._lsp_fallback(lsp, from_rel, line, character)

        # self.method() / cls.method(): same-file method resolution.
        if head in ("self", "cls"):
            if rest[-1] in local_symbols:
                return (from_rel, rest[-1])
            return self._lsp_fallback(lsp, from_rel, line, character)

        # head.attr...: descend through modules/attributes to the final symbol.
        binding = bindings.get(head)
        if binding:
            home = self._binding_home(binding, from_rel)
            if home:
                cur_file = home
                segments = list(rest)
                while len(segments) > 1:
                    child = self._child_module(cur_file, segments[0])
                    if child is None:
                        break
                    cur_file = child
                    segments = segments[1:]
                return (cur_file, segments[-1])

        # Locally-defined class/object: Class.method() -> same file.
        if head in local_symbols:
            return (from_rel, rest[-1])

        # Ambiguous (e.g. obj.method()): defer to the LSP resolver if present.
        return self._lsp_fallback(lsp, from_rel, line, character)

    def _child_module(self, file_path: str, seg: str) -> Optional[str]:
        base_dir = _norm(os.path.dirname(file_path))
        for candidate in self._child_paths(base_dir, seg):
            if os.path.exists(os.path.join(self.repo_root, candidate)):
                return candidate
        return None

    @staticmethod
    def _lsp_fallback(
        lsp: Optional[Callable[[str, int, int], Optional[Tuple[str, str]]]],
        from_rel: str,
        line: Optional[int],
        character: Optional[int],
    ) -> Optional[Tuple[str, str]]:
        if lsp is None or line is None or character is None:
            return None
        try:
            result = lsp(from_rel, line, character)
        except Exception:
            return None
        if result and len(result) == 2:
            return (result[0], result[1])
        return None
