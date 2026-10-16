import json
import os
import posixpath
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Set, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _canonical_path(path: str, source_root: str = "") -> str:
    """Normalize a file path to a stable, repo-relative posix form.

    Handles Windows separators, ``./``/``..`` segments, and paths that are
    absolute under ``source_root`` (the analyzed checkout). Paths that are
    absolute but not under ``source_root`` (e.g. the instrumentation clone)
    keep their normalized absolute form; callers match those by suffix.
    """
    if not path:
        return ""
    p = path.replace("\\", "/").strip()
    if source_root:
        root = source_root.replace("\\", "/").rstrip("/")
        if p == root:
            return ""
        if p.startswith(root + "/"):
            p = p[len(root) + 1:]
    p = posixpath.normpath(p)
    if p == ".":
        return ""
    return p


def _paths_match(a: str, b: str) -> bool:
    """Return True when two normalized paths refer to the same file."""
    if not a or not b:
        return False
    a = a.replace("\\", "/").rstrip("/")
    b = b.replace("\\", "/").rstrip("/")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _symbol_fields(sym) -> Tuple[str, str, int, int, str]:
    """Extract (name, symbol_type, start_line, end_line, file_path) from a
    mapping symbol, accepting tuple/list, dict, or object forms."""
    if isinstance(sym, dict):
        return (
            sym.get("name", ""),
            sym.get("symbol_type") or sym.get("type", ""),
            int(sym.get("start_line") or 0),
            int(sym.get("end_line") or 0),
            sym.get("file_path") or sym.get("symbol_file") or "",
        )
    if isinstance(sym, (list, tuple)):
        return (
            sym[0] if len(sym) > 0 else "",
            sym[1] if len(sym) > 1 else "",
            int(sym[2]) if len(sym) > 2 else 0,
            int(sym[3]) if len(sym) > 3 else 0,
            sym[4] if len(sym) > 4 else "",
        )
    return (
        getattr(sym, "name", ""),
        getattr(sym, "symbol_type", ""),
        int(getattr(sym, "start_line", 0) or 0),
        int(getattr(sym, "end_line", 0) or 0),
        getattr(sym, "file_path", "") or "",
    )


def _qualified_name(module_path: str, name: str) -> str:
    """Build a module-qualified symbol name, e.g. ``src.pkg.mod.get``."""
    module = module_path.replace("\\", "/")
    if module.endswith(".py"):
        module = module[:-3]
    module = module.replace("/", ".").strip(".")
    return f"{module}.{name}" if module else name


_PYTHON_EXTENSIONS = {".py", ".pyi"}


def select_resolver(file_path: str):
    """Return a symbol resolver matching ``file_path``'s language.

    ``.py``/``.pyi`` use the Python AST resolver; everything else uses the
    tree-sitter resolver (``.ts``/``.tsx``/``.js``/``.jsx``). Imports are lazy
    so importing this module needs no language runtime.
    """
    ext = os.path.splitext(file_path or "")[1].lower()
    if ext in _PYTHON_EXTENSIONS:
        from .symbol_resolver import SymbolResolver
        return SymbolResolver()
    from .typescript_symbol_resolver import TypeScriptSymbolResolver
    return TypeScriptSymbolResolver()


class _LanguageDispatchResolver:
    """Default resolver: picks a resolver per file, based on its language."""

    def __init__(self):
        self._resolvers: Dict[str, object] = {}

    def _for(self, file_path: str):
        ext = os.path.splitext(file_path or "")[1].lower()
        key = "python" if ext in _PYTHON_EXTENSIONS else "typescript"
        if key not in self._resolvers:
            self._resolvers[key] = select_resolver(file_path)
        return self._resolvers[key]

    def get_symbols(self, file_path: str):
        return self._for(file_path).get_symbols(file_path)


@dataclass
class FileChange:
    path: str
    added_lines: Set[int]
    removed_lines: Set[int]


@dataclass
class TIARequest:
    diff_text: str
    test_method_map_path: str
    source_root: str


@dataclass
class TestImpact:
    test_file: str
    impacted_symbols: List[str]
    selected: bool


@dataclass
class TIAResult:
    impacted_tests: List[TestImpact]
    unimpacted_tests: List[TestImpact]
    changed_symbols: List[Dict]
    total_tests: int
    selected_count: int


class DiffParser:
    @staticmethod
    def parse_diff(diff_text: str) -> List[FileChange]:
        changes = []
        if not diff_text or not diff_text.strip():
            return changes

        current_file = None
        added_lines = set()
        removed_lines = set()
        old_line_num = 0
        new_line_num = 0

        for line in diff_text.split("\n"):
            if line.startswith("diff --git"):
                if current_file is not None:
                    changes.append(FileChange(
                        path=current_file,
                        added_lines=added_lines,
                        removed_lines=removed_lines,
                    ))
                added_lines = set()
                removed_lines = set()
                old_line_num = 0
                new_line_num = 0
                continue

            if line.startswith("--- "):
                path = line[4:]
                if path.startswith("a/"):
                    path = path[2:]
                current_file = path
                continue

            if line.startswith("+++ "):
                path = line[4:]
                if path.startswith("b/"):
                    path = path[2:]
                current_file = path
                continue

            if line.startswith("Binary files") or line.startswith("new file mode"):
                continue

            if line.startswith("@@"):
                parts = line.split(" ")
                for part in parts:
                    if part.startswith("-") and "," in part:
                        nums = part[1:].split(",")
                        old_line_num = int(nums[0])
                    elif part.startswith("+") and "," in part:
                        nums = part[1:].split(",")
                        new_line_num = int(nums[0])
                continue

            if line.startswith("+") and not line.startswith("+++"):
                added_lines.add(new_line_num)
                new_line_num += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed_lines.add(old_line_num)
                old_line_num += 1
            elif line.startswith(" ") or line == "":
                if old_line_num > 0:
                    old_line_num += 1
                if new_line_num > 0:
                    new_line_num += 1

        if current_file is not None:
            changes.append(FileChange(
                path=current_file,
                added_lines=added_lines,
                removed_lines=removed_lines,
            ))

        return changes

    @staticmethod
    def resolve_impacted_tests(
        diff_text: str,
        test_method_map_path: str,
        source_root: str,
        resolver=None,
    ) -> TIAResult:
        if resolver is None:
            # Use the resolver matching each changed file's language instead of
            # parsing every file as TypeScript (Story 11.3).
            resolver = _LanguageDispatchResolver()

        file_changes = DiffParser.parse_diff(diff_text)
        if not file_changes:
            return TIAResult(
                impacted_tests=[],
                unimpacted_tests=[],
                changed_symbols=[],
                total_tests=0,
                selected_count=0,
            )

        with open(test_method_map_path) as f:
            tmm = json.load(f)

        # Canonical form of each changed file path, used to scope symbol lookups.
        diff_canon = {fc.path: _canonical_path(fc.path, source_root) for fc in file_changes}

        def _map_file_key(raw_path: str) -> str:
            """Resolve a mapping symbol's file path to a changed-file key."""
            canon = _canonical_path(raw_path, source_root)
            for original, changed in diff_canon.items():
                if canon == changed or _paths_match(raw_path, original):
                    return changed
            return canon

        # Index test mappings by qualified identity, not bare name:
        #   exact  -> (file, name, start_line, end_line) disambiguates same-named
        #             symbols within a file (e.g. two classes each defining `get`)
        #   name   -> (file, name) fallback when line spans differ (refactors)
        symbol_to_tests: Dict[Tuple[str, str, int, int], Set[str]] = {}
        name_to_tests: Dict[Tuple[str, str], Set[str]] = {}
        all_test_files: Set[str] = set()
        for m in tmm["mappings"]:
            tf = m["test_file"]
            all_test_files.add(tf)
            for sym in m["symbols"]:
                name, _stype, start, end, sym_file = _symbol_fields(sym)
                if not name:
                    continue
                file_key = _map_file_key(sym_file or m.get("test_file", ""))
                symbol_to_tests.setdefault((file_key, name, start, end), set()).add(tf)
                name_to_tests.setdefault((file_key, name), set()).add(tf)

        changed_symbols: List[Dict] = []
        changed_with_tests: List[Tuple[Dict, Set[str]]] = []

        for fc in file_changes:
            full_path = os.path.join(source_root, fc.path)
            all_changed = fc.added_lines | fc.removed_lines
            if not all_changed:
                continue

            file_key = diff_canon[fc.path]
            for sym in resolver.get_symbols(full_path):
                # A symbol is changed if any changed line falls inside its span.
                # (No min/max containment shortcut: that missed symbols whose
                # only changed line was neither the min nor the max line.)
                if not any(sym.start_line <= line <= sym.end_line for line in all_changed):
                    continue

                tests_for_sym = symbol_to_tests.get(
                    (file_key, sym.name, sym.start_line, sym.end_line)
                )
                if tests_for_sym is None:
                    tests_for_sym = name_to_tests.get((file_key, sym.name), set())

                entry = {
                    "name": sym.name,
                    "qualified_name": _qualified_name(fc.path, sym.name),
                    "type": sym.symbol_type,
                    "file_path": fc.path,
                    "start_line": sym.start_line,
                    "end_line": sym.end_line,
                }
                changed_symbols.append(entry)
                changed_with_tests.append((entry, set(tests_for_sym)))

        impacted_test_set: Set[str] = set()
        for _entry, tests_for_sym in changed_with_tests:
            impacted_test_set.update(tests_for_sym)

        impacted = []
        unimpacted = []
        for tf in sorted(all_test_files):
            matching_syms = [
                entry["qualified_name"]
                for entry, tests_for_sym in changed_with_tests
                if tf in tests_for_sym
            ]
            entry = TestImpact(
                test_file=tf,
                impacted_symbols=matching_syms,
                selected=tf in impacted_test_set,
            )
            if tf in impacted_test_set:
                impacted.append(entry)
            else:
                unimpacted.append(entry)

        return TIAResult(
            impacted_tests=impacted,
            unimpacted_tests=unimpacted,
            changed_symbols=changed_symbols,
            total_tests=len(all_test_files),
            selected_count=len(impacted),
        )
