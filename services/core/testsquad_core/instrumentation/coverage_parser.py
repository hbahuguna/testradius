import os
import json
import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


class CoverageParser:
    FORMAT_ISTANBUL = "istanbul"
    FORMAT_PER_TEST = "per_test"

    @staticmethod
    def detect_format(data: dict) -> str:
        if not data:
            return CoverageParser.FORMAT_ISTANBUL
        first_val = next(iter(data.values()))
        if isinstance(first_val, dict) and any(
            k in first_val for k in ("statementMap", "s", "path")
        ):
            return CoverageParser.FORMAT_ISTANBUL
        return CoverageParser.FORMAT_PER_TEST

    @staticmethod
    def parse_istanbul(istanbul_data: dict) -> Dict[str, List[int]]:
        result: Dict[str, List[int]] = {}
        for file_path, file_cov in istanbul_data.items():
            if not isinstance(file_cov, dict):
                continue
            s = file_cov.get("s", {})
            sm = file_cov.get("statementMap", {})
            if not s or not sm:
                continue
            covered_lines: Set[int] = set()
            for stmt_id, hit_count in s.items():
                if hit_count and hit_count > 0:
                    stmt = sm.get(stmt_id)
                    if stmt:
                        start_line = stmt.get("start", {}).get("line", 0)
                        end_line = stmt.get("end", {}).get("line", start_line)
                        for line in range(start_line, end_line + 1):
                            covered_lines.add(line)
            if covered_lines:
                result[file_path] = sorted(covered_lines)
        return result

    @staticmethod
    def parse_per_test(per_test_data: dict) -> Dict[str, Dict[str, List[int]]]:
        result: Dict[str, Dict[str, List[int]]] = {}
        for test_name, file_map in per_test_data.items():
            parsed_files: Dict[str, List[int]] = {}
            for file_path, coverage_value in file_map.items():
                if isinstance(coverage_value, list):
                    parsed_files[file_path] = sorted(coverage_value)
                elif isinstance(coverage_value, dict):
                    s = coverage_value.get("s", {})
                    sm = coverage_value.get("statementMap", {})
                    if s and sm:
                        covered: Set[int] = set()
                        for stmt_id, hit in s.items():
                            if hit and hit > 0:
                                stmt = sm.get(stmt_id)
                                if stmt:
                                    sl = stmt.get("start", {}).get("line", 0)
                                    el = stmt.get("end", {}).get("line", sl)
                                    for line in range(sl, el + 1):
                                        covered.add(line)
                        if covered:
                            parsed_files[file_path] = sorted(covered)
            if parsed_files:
                result[test_name] = parsed_files
        return result

    @classmethod
    def parse_file(cls, file_path: str) -> Dict:
        if not os.path.exists(file_path):
            logger.warning(f"Coverage file not found: {file_path}")
            return {}
        with open(file_path, "r") as f:
            data = json.load(f)
        fmt = cls.detect_format(data)
        if fmt == cls.FORMAT_ISTANBUL:
            return {"format": "istanbul", "coverage": cls.parse_istanbul(data)}
        else:
            return {"format": "per_test", "per_test_coverage": cls.parse_per_test(data)}

    @classmethod
    def parse_lines(cls, file_path: str) -> Dict[str, Dict[str, List[int]]]:
        result = cls.parse_file(file_path)
        fmt = result.get("format")
        if fmt == "per_test":
            return result.get("per_test_coverage", {})
        cov = result.get("coverage", {})
        test_name = os.path.basename(os.path.dirname(file_path)) or "default"
        return {test_name: cov}
