"""
Per-test coverage analyzer using pytest-cov.
"""
import subprocess
import sqlite3
import os
import logging
from typing import Dict, List
import importlib.util

logger = logging.getLogger("testsquad.instrumentation")


def load_symbol_resolver():
    """Load SymbolResolver without triggering full instrumentation import."""
    resolver_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "symbol_resolver.py"
    )
    spec = importlib.util.spec_from_file_location("symbol_resolver", resolver_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SymbolResolver, module.Symbol


def _install_test_deps(venv_python: str, testbed_path: str) -> None:
    """Install common pytest plugins and basic test deps needed for collection."""
    deps = [
        "pytest-asyncio>=1.2.0",
        "pytest-xdist>=3.8.0",
        "inline-snapshot>=0.30.1",
        "pytest-timeout>=2.4.0",
        "pytest-dotenv>=0.5.2",
        "pytest-mock>=3.15.1",
        "pytest-cov>=5.0.0",
        "coverage>=7.0.0",
        "dirty-equals>=0.6",
        "pydantic>=2.0.0",
    ]
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install"] + deps,
            cwd=testbed_path, capture_output=True, text=True, timeout=120
        )
    except Exception as e:
        logger.warning(f"Failed to install some test deps: {e}")

    # Install the project itself so test files can import it
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "-e", "."],
            cwd=testbed_path, capture_output=True, text=True, timeout=120
        )
    except Exception as e:
        logger.warning(f"Failed to install project in editable mode: {e}")

    # Install from any requirements files in the testbed root
    for req_file in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "dev-requirements.txt", "test-requirements.txt"):
        req_path = os.path.join(testbed_path, req_file)
        if os.path.isfile(req_path):
            try:
                subprocess.run(
                    [venv_python, "-m", "pip", "install", "-r", req_file],
                    cwd=testbed_path, capture_output=True, text=True, timeout=120
                )
            except Exception as e:
                logger.warning(f"Failed to install {req_file}: {e}")

    # Try common test extras so project-specific test deps are available
    for extra in ("test", "testing", "dev", "tests"):
        try:
            r = subprocess.run(
                [venv_python, "-m", "pip", "install", "-e", f".[{extra}]"],
                cwd=testbed_path, capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0:
                break
        except Exception:
            continue


def _filter_collectable_files(venv_python: str, testbed_path: str, test_files: List[str]) -> List[str]:
    """Try collecting each test file; return only those that collect successfully."""
    collectable = []
    for f in test_files:
        try:
            result = subprocess.run(
                [venv_python, "-W", "ignore", "-m", "pytest", f, "--collect-only", "-q", "-o", "filterwarnings=", "--override-ini=addopts="],
                cwd=testbed_path, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                collectable.append(f)
        except Exception:
            pass
    return collectable


def run_tests_with_coverage(testbed_path: str, test_files: List[str]) -> tuple:
    """Run tests with --cov-context=test.

    Installs test deps, filters to collectable files, and runs coverage.
    Returns (success: bool, output: str, collectable_count: int, original_count: int).
    """
    venv_python = os.path.join(testbed_path, ".venv", "bin", "python")
    coverage_db = os.path.join(testbed_path, ".coverage")

    if os.path.exists(coverage_db):
        os.remove(coverage_db)

    # Install basic test deps so collection doesn't fail on missing plugins
    _install_test_deps(venv_python, testbed_path)

    # Filter to only test files that can be collected
    filtered = _filter_collectable_files(venv_python, testbed_path, test_files)
    if not filtered:
        return False, f"No collectable test files found (tried {len(test_files)} files)", 0, len(test_files)

    src_dir = os.path.join(testbed_path, "src")
    cov_flag = "--cov=src" if os.path.isdir(src_dir) else "--cov"

    coverage_target = os.path.join(testbed_path, ".coverage")
    env = {**os.environ, "COVERAGE_FILE": coverage_target}

    cmd = [venv_python, "-W", "ignore", "-m", "pytest"] + filtered + [
        "-x", "-v", cov_flag, "--cov-context=test",
        "--cov-report=", "-o", "filterwarnings=",
        "--override-ini=addopts=",
    ]

    result = subprocess.run(cmd, cwd=testbed_path, env=env, capture_output=True, text=True, timeout=600)
    return result.returncode == 0, result.stdout + "\n" + result.stderr, len(filtered), len(test_files)


def _find_coverage_db(testbed_path: str) -> str:
    """Find the coverage DB, trying .coverage first then suffixed .coverage.* files."""
    exact = os.path.join(testbed_path, ".coverage")
    if os.path.exists(exact) and os.path.getsize(exact) > 0:
        return exact
    import glob as _glob
    candidates = sorted(_glob.glob(os.path.join(testbed_path, ".coverage.*")))
    if candidates:
        biggest = max(candidates, key=os.path.getsize)
        if os.path.getsize(biggest) > 0:
            return biggest
    return exact


def extract_per_test_lines(testbed_path: str) -> Dict[str, Dict[str, List[int]]]:
    """Extract per-test line data from coverage SQLite database."""
    coverage_db = _find_coverage_db(testbed_path)

    if not os.path.exists(coverage_db) or os.path.getsize(coverage_db) == 0:
        logger.warning(f"extract_per_test_lines: .coverage file missing or empty at {coverage_db}")
        return {}

    conn = sqlite3.connect(coverage_db)
    cursor = conn.cursor()

    # Check schema has the context table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='context'")
    if not cursor.fetchone():
        logger.warning(f"extract_per_test_lines: .coverage DB at {coverage_db} has no 'context' table")
        conn.close()
        return {}

    cursor.execute("""
        SELECT id, context FROM context 
        WHERE context != '' AND context LIKE '%|run'
    """)
    contexts = cursor.fetchall()
    logger.info(f"extract_per_test_lines: found {len(contexts)} contexts in {coverage_db}")
    if contexts:
        logger.info(f"  sample contexts: {[c[1][:80] for c in contexts[:5]]}")

    results = {}
    for ctx_id, ctx_name in contexts:
        test_name = ctx_name.replace("|run", "")

        cursor.execute("""
            SELECT f.path, lb.numbits
            FROM line_bits lb
            JOIN file f ON lb.file_id = f.id
            WHERE lb.context_id = ?
        """, (ctx_id,))

        file_rows = cursor.fetchall()
        file_lines = {}
        for row in file_rows:
            file_path = row[0].replace("/private/", "/")
            numbits = row[1]
            lines = _bits_to_lines(numbits)
            logger.info(f"  ctx={ctx_id} file={file_path} numbits_len={len(bytes(numbits)) if numbits else 0} lines={lines[:10]}{'...' if len(lines) > 10 else ''}")

            if lines:
                file_lines[file_path] = lines

        if file_lines:
            results[test_name] = file_lines

    conn.close()
    logger.info(f"extract_per_test_lines: returning {len(results)} tests with coverage data")
    return results


def _bits_to_lines(numbits) -> List[int]:
    """Convert numbits blob to line numbers using coverage.py's bit encoding.
    
    Each byte represents 8 lines: byte 0 = lines 1-8, byte 1 = lines 9-16, etc.
    Bit 0 of each byte = lowest line in that block, bit 7 = highest.
    """
    if not numbits:
        return []
    
    try:
        data = bytes(numbits)
        if not data:
            return []
        lines = []
        for byte_offset, byte in enumerate(data):
            for bit_offset in range(8):
                if byte & (1 << bit_offset):
                    lines.append(byte_offset * 8 + bit_offset + 1)
        return lines
    except Exception:
        pass
    return []


def _resolve_coverage_path(file_path: str, testbed_path: str) -> str:
    """Resolve a path from coverage DB, trying absolute then relative to testbed."""
    if os.path.exists(file_path):
        return file_path
    joined = os.path.join(testbed_path, file_path)
    if os.path.exists(joined):
        return joined
    if file_path.startswith("/private/"):
        stripped = file_path.replace("/private/", "/", 1)
        if os.path.exists(stripped):
            return stripped
    return file_path


def resolve_to_symbols(testbed_path: str, per_test_coverage: Dict) -> List[Dict]:
    """Resolve coverage lines to AST symbols."""
    SymbolResolver, Symbol = load_symbol_resolver()
    resolver = SymbolResolver()
    
    all_mappings = []
    for test_name, file_coverage in per_test_coverage.items():
        symbols = []
        for raw_path, covered_lines in file_coverage.items():
            file_path = _resolve_coverage_path(raw_path, testbed_path)
            file_exists = os.path.exists(file_path)
            if not file_exists:
                logger.warning(f"  resolve: file NOT FOUND: {raw_path} (tried {file_path})")
                continue
            
            # Skip test files — only resolve symbols from production code
            rel_path = os.path.relpath(file_path, testbed_path)
            if rel_path.startswith("tests") or "/tests/" in rel_path:
                continue
            
            covered_dict = {file_path: covered_lines}
            syms = resolver.resolve_symbols(file_path, covered_dict)
            logger.info(f"  resolve: {file_path} -> {len(syms)} symbols")
            symbols.extend(syms)
        
        all_mappings.append({
            "test_name": test_name,
            "test_file": test_name.split("::")[0] if "::" in test_name else test_name,
            "symbols": [(s.name, s.symbol_type, s.start_line, s.end_line, os.path.relpath(s.file_path, testbed_path)) for s in symbols]
        })
    
    logger.info(f"resolve_to_symbols: {len(per_test_coverage)} tests -> {len(all_mappings)} mappings, total symbols={sum(len(m['symbols']) for m in all_mappings)}")
    return all_mappings


def analyze_per_test_coverage(testbed_path: str, test_files: List[str]) -> Dict:
    """
    Main entry point: Run tests with coverage and return per-test symbol mappings.
    
    Returns:
        Dict with:
            - mappings: List of {test_name, test_file, symbols}
            - test_count: Number of tests processed
            - symbol_count: Total unique symbols across all tests
    """
    # Run tests (partial failures still produce coverage data)
    success, output, collectable_count, original_count = run_tests_with_coverage(testbed_path, test_files)
    
    # Build diagnostics early so we can return useful info even on failure
    diag = {
        "test_files_original": original_count,
        "test_files_collectable": collectable_count,
        "output": output[:1000] if output else ""
    }
    
    # Extract per-test lines (coverage DB may have data even on partial failure)
    per_test_coverage = extract_per_test_lines(testbed_path)
    if not per_test_coverage:
        if not success:
            return {"error": "Test execution failed and no coverage data", "mappings": [], "diagnostics": diag, "output": output[:2000]}
        return {"error": "No coverage data produced", "mappings": [], "diagnostics": diag}
    
    if not success:
        diag["output"] = output[:1000] if output else ""
    
    # Resolve to symbols
    mappings = resolve_to_symbols(testbed_path, per_test_coverage)
    
    # Count unique symbols
    all_symbols = set()
    for m in mappings:
        for s in m["symbols"]:
            all_symbols.add(s[0])  # symbol name
    
    # Build diagnostic summary from first 3 coverage entries
    coverage_sample = {}
    for i, (tname, fcov) in enumerate(per_test_coverage.items()):
        if i >= 3:
            break
        sample_files = {}
        for fpath, lines in fcov.items():
            sample_files[os.path.basename(fpath)] = {"line_count": len(lines), "first_10": lines[:10]}
        coverage_sample[tname[:60]] = sample_files
    diag["coverage_tests_with_data"] = len(per_test_coverage)
    diag["coverage_sample"] = coverage_sample
    
    return {
        "mappings": mappings,
        "test_count": len(mappings),
        "symbol_count": len(all_symbols),
        "per_test_coverage": per_test_coverage,
        "diagnostics": diag
    }


if __name__ == "__main__":
    import json
    result = analyze_per_test_coverage(
        "/tmp/testbed-repro",
        ["tests/utils/test_wait.py", "tests/utils/test_retry.py"]
    )
    print(json.dumps(result, indent=2))