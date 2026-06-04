import json
import os
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Set, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


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
    ) -> TIAResult:
        from testsquad_core.instrumentation.typescript_symbol_resolver import TypeScriptSymbolResolver

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

        symbol_to_tests: Dict[str, Set[str]] = {}
        all_test_files: Set[str] = set()
        for m in tmm["mappings"]:
            tf = m["test_file"]
            all_test_files.add(tf)
            for sym in m["symbols"]:
                name = sym[0]
                symbol_to_tests.setdefault(name, set()).add(tf)

        resolver = TypeScriptSymbolResolver()
        changed_symbols: List[Dict] = []

        for fc in file_changes:
            full_path = os.path.join(source_root, fc.path)
            all_changed = fc.added_lines | fc.removed_lines
            if not all_changed:
                continue

            symbols = resolver.get_symbols(full_path)
            for sym in symbols:
                if any(start <= line <= end for line in all_changed
                       for start, end in [(sym.start_line, sym.end_line)]):
                    if sym.start_line <= max(all_changed) <= sym.end_line or \
                       sym.start_line <= min(all_changed) <= sym.end_line:
                        changed_symbols.append({
                            "name": sym.name,
                            "type": sym.symbol_type,
                            "file_path": fc.path,
                            "start_line": sym.start_line,
                            "end_line": sym.end_line,
                        })

        impacted_symbol_names = {s["name"] for s in changed_symbols}
        impacted_test_set: Set[str] = set()
        for sym_name in impacted_symbol_names:
            impacted_test_set.update(symbol_to_tests.get(sym_name, set()))

        impacted = []
        unimpacted = []
        for tf in sorted(all_test_files):
            matching_syms = [
                s["name"] for s in changed_symbols
                if tf in symbol_to_tests.get(s["name"], set())
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

        test_name = os.path.basename(test_method_map_path).replace(".json", "")
        return TIAResult(
            impacted_tests=impacted,
            unimpacted_tests=unimpacted,
            changed_symbols=changed_symbols,
            total_tests=len(all_test_files),
            selected_count=len(impacted),
        )
