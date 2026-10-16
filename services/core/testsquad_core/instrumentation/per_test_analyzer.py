"""
Per-test coverage analyzer using pytest-cov.
"""
import subprocess
import sqlite3
import os
import glob
import json
import logging
import tempfile
import concurrent.futures
from typing import Dict, List, Optional
import importlib.util
import hashlib

logger = logging.getLogger("testsquad.instrumentation")

# Bound runtime by sharding the suite across a few worker pytest processes.
DEFAULT_SHARDS = max(1, min(4, os.cpu_count() or 1))

#: Testbed paths whose test deps have already been installed in this process,
#: so discovery + the coverage run don't pay for ``pip install`` twice.
_DEPS_INSTALLED: set = set()

#: Marker written into a testbed checkout once its test deps are installed.
#: Persisting the install (Story 11.4) lets a *reused* checkout skip the
#: ``pip install`` across processes, not merely within one.
DEPS_MARKER = ".tia-deps-installed"

#: Common pytest plugins / test deps installed into every testbed before
#: discovery. Module level so the install spec can be hashed into DEPS_MARKER.
_TEST_DEPS: List[str] = [
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

_DEPS_REQUIREMENTS = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
)

_DEPS_EXTRAS = ("test", "testing", "dev", "tests")


def _deps_spec() -> str:
    """The full install specification that ``DEPS_MARKER`` proves was applied.

    Touching the plugin list, the requirements files or the extras changes the
    hash, so a stale marker is rejected and the install runs again.
    """
    return "\n".join(
        ["pip install " + " ".join(_TEST_DEPS), "pip install -e ."]
        + [f"pip install -r {f}" for f in _DEPS_REQUIREMENTS]
        + [f"pip install -e .[{extra}]" for extra in _DEPS_EXTRAS]
    )


def _deps_spec_hash() -> str:
    return hashlib.sha256(_deps_spec().encode("utf-8")).hexdigest()


def _deps_marker_path(testbed_path: str) -> str:
    return os.path.join(testbed_path, DEPS_MARKER)


def _deps_marker_matches(testbed_path: str) -> bool:
    """Whether the checkout's marker proves the current spec is installed."""
    try:
        with open(_deps_marker_path(testbed_path)) as f:
            recorded = f.read().strip()
    except OSError:
        return False
    return recorded == _deps_spec_hash()

#: Name of the throwaway pytest plugin used to dump collected node ids during
#: discovery (data-driven / conftest-generated tests are invisible to a glob).
_COLLECT_PLUGIN_MODULE = "_tia_collect_plugin"
_COLLECT_PLUGIN_SOURCE = '''\
import json
import os


def pytest_collection_modifyitems(config, items):
    out = os.environ.get("TIA_COLLECT_OUT")
    if not out:
        return
    data = []
    for item in items:
        try:
            nodeid = item.nodeid
        except Exception:
            nodeid = ""
        if nodeid:
            data.append({"nodeid": nodeid})
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass
'''


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _write_collect_plugin(plugin_dir: str) -> str:
    """Write the collection-dump pytest plugin into ``plugin_dir``."""
    os.makedirs(plugin_dir, exist_ok=True)
    plugin_path = os.path.join(plugin_dir, _COLLECT_PLUGIN_MODULE + ".py")
    with open(plugin_path, "w", encoding="utf-8") as fh:
        fh.write(_COLLECT_PLUGIN_SOURCE)
    return plugin_path


def _read_collected_files(out_path: str, testbed_path: str) -> List[str]:
    """Parse the plugin's node-id dump into distinct, absolute test file paths."""
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return []
    try:
        with open(out_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning(f"discover_collected_files: could not parse {out_path}: {e}")
        return []
    files = set()
    for entry in data or []:
        nodeid = (entry or {}).get("nodeid") or ""
        path = nodeid.split("::", 1)[0].strip()
        if not path:
            continue
        files.add(path if os.path.isabs(path) else os.path.join(testbed_path, path))
    return sorted(files)


def discover_collected_files(
    testbed_path: str,
    test_dir: str = "tests",
    venv_python: Optional[str] = None,
) -> List[str]:
    """Return the test files pytest actually collects under ``test_dir``.

    A filename glob (``tests/**/test_*.py``) only sees conventional test
    modules. Tests produced by conftest hooks — e.g. Pygments' ``snippets`` /
    ``examplefiles`` ``pytest_collect_file`` collectors, doctests, or other
    custom ``File`` collectors — live in arbitrary files and are invisible to a
    glob, so they never get instrumented. Asking pytest itself (via a tiny
    plugin that dumps collected node ids) yields the true universe.

    The caller must install test deps first so collection can run.
    """
    venv_python = venv_python or os.path.join(testbed_path, ".venv", "bin", "python")
    plugin_dir = tempfile.mkdtemp(prefix="tia-collect-")
    out_path = os.path.join(plugin_dir, "collected.json")
    _write_collect_plugin(plugin_dir)

    env = {**os.environ, "TIA_COLLECT_OUT": out_path}
    existing_pp = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [plugin_dir, testbed_path] + ([existing_pp] if existing_pp else [])
    )

    cmd = [
        venv_python, "-W", "ignore", "-m", "pytest", test_dir,
        "--collect-only", "-q",
        "-p", _COLLECT_PLUGIN_MODULE,
        "-o", "filterwarnings=",
        "--override-ini=addopts=",
        "--continue-on-collection-errors",
    ]
    try:
        subprocess.run(
            cmd, cwd=testbed_path, env=env,
            capture_output=True, text=True,
            timeout=_env_int("TIA_DISCOVERY_TIMEOUT", 600),
        )
    except subprocess.TimeoutExpired:
        logger.warning("discover_collected_files: pytest collection timed out")
    except Exception as e:
        logger.warning(f"discover_collected_files: pytest collection failed: {e}")

    files = _read_collected_files(out_path, testbed_path)
    logger.info(f"discover_collected_files: {len(files)} test files via pytest collection")
    return files


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
    """Install common pytest plugins and basic test deps needed for collection.

    Short-circuits on either the in-process set (a cache hit within one run) or
    the persisted ``DEPS_MARKER`` (a hit across runs, Story 11.4). The marker is
    only written when the core installs succeed, so a broken install is retried
    rather than cached.
    """
    cache_key = os.path.realpath(testbed_path)
    if cache_key in _DEPS_INSTALLED:
        return
    if _deps_marker_matches(testbed_path):
        _DEPS_INSTALLED.add(cache_key)
        return

    deps = list(_TEST_DEPS)
    core_ok = True
    try:
        r = subprocess.run(
            [venv_python, "-m", "pip", "install"] + deps,
            cwd=testbed_path, capture_output=True, text=True, timeout=120
        )
        core_ok = core_ok and r.returncode == 0
    except Exception as e:
        logger.warning(f"Failed to install some test deps: {e}")
        core_ok = False

    # Install the project itself so test files can import it
    try:
        r = subprocess.run(
            [venv_python, "-m", "pip", "install", "-e", "."],
            cwd=testbed_path, capture_output=True, text=True, timeout=120
        )
        core_ok = core_ok and r.returncode == 0
    except Exception as e:
        logger.warning(f"Failed to install project in editable mode: {e}")
        core_ok = False

    # Install from any requirements files in the testbed root (best effort:
    # projects differ in which ones exist and which are expected to fail).
    for req_file in _DEPS_REQUIREMENTS:
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
    # (also best effort: a project rarely exposes all of these).
    for extra in _DEPS_EXTRAS:
        try:
            r = subprocess.run(
                [venv_python, "-m", "pip", "install", "-e", f".[{extra}]"],
                cwd=testbed_path, capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0:
                break
        except Exception:
            continue

    if core_ok:
        try:
            with open(_deps_marker_path(testbed_path), "w") as fh:
                fh.write(_deps_spec_hash())
        except OSError as e:
            logger.warning(f"Could not write {DEPS_MARKER}: {e}")

    _DEPS_INSTALLED.add(cache_key)


def _collect_one(venv_python: str, testbed_path: str, test_file: str) -> Optional[str]:
    """Return the file if it collects cleanly, else ``None``."""
    try:
        result = subprocess.run(
            [venv_python, "-W", "ignore", "-m", "pytest", test_file, "--collect-only", "-q", "-o", "filterwarnings=", "--override-ini=addopts="],
            cwd=testbed_path, capture_output=True, text=True, timeout=60
        )
        return test_file if result.returncode == 0 else None
    except Exception:
        return None


def _filter_collectable_files(venv_python: str, testbed_path: str, test_files: List[str]) -> List[str]:
    """Try collecting each test file; return only those that collect successfully.

    Collection is parallelized because a large suite can contain hundreds of
    files and each collection is a separate process.
    """
    if not test_files:
        return []
    workers = min(8, len(test_files))
    collectable: List[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_collect_one, venv_python, testbed_path, f): f for f in test_files}
        for fut in concurrent.futures.as_completed(futures):
            got = fut.result()
            if got:
                collectable.append(got)
    # Preserve the caller's ordering for deterministic sharding/merging.
    order = {f: i for i, f in enumerate(test_files)}
    collectable.sort(key=lambda f: order.get(f, 0))
    return collectable


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def partition_test_files(test_files: List[str], shards: int) -> List[List[str]]:
    """Balance test files across ``shards`` buckets (largest-first greedy).

    Files are kept whole so each shard's pytest process writes its own
    coverage data file; the shards are merged later into one evidence set.
    """
    files = [f for f in test_files if f]
    if not files:
        return []
    if shards <= 1:
        return [files]
    shards = min(shards, len(files))
    ordered = sorted(files, key=_file_size, reverse=True)
    buckets: List[List[str]] = [[] for _ in range(shards)]
    loads = [0] * shards
    for f in ordered:
        idx = loads.index(min(loads))
        buckets[idx].append(f)
        # Floor at 1 so equal/unknown (missing) sizes still round-robin
        # instead of piling every file into the first bucket.
        loads[idx] += max(_file_size(f), 1)
    return [b for b in buckets if b]


def _run_coverage_shard(
    venv_python: str,
    testbed_path: str,
    shard_files: List[str],
    shard_index: int,
    cov_flag: str,
    timeout: int,
) -> Dict:
    """Run one shard of the suite under ``--cov-context=test``.

    ``-x`` is intentionally NOT used: a failure early in one file must not
    hide coverage for the remaining tests in that shard.
    """
    coverage_file = os.path.join(testbed_path, f".coverage.shard{shard_index}")
    try:
        if os.path.exists(coverage_file):
            os.remove(coverage_file)
    except OSError:
        pass

    env = {**os.environ, "COVERAGE_FILE": coverage_file}
    cmd = [venv_python, "-W", "ignore", "-m", "pytest"] + shard_files + [
        "-q", cov_flag, "--cov-context=test",
        "--cov-report=", "-o", "filterwarnings=",
        "--override-ini=addopts=",
        # Data-driven suites can contain sample files that pytest's default
        # Python collector fails to import (e.g. Pygments' examplefiles/*.py).
        # Without this, one bad file aborts the whole shard and every other
        # file in it silently produces no coverage.
        "--continue-on-collection-errors",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=testbed_path, env=env,
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "shard": shard_index,
            "returncode": result.returncode,
            "output": (result.stdout or "") + "\n" + (result.stderr or ""),
            "coverage_file": coverage_file,
            "files": shard_files,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "shard": shard_index,
            "returncode": -1,
            "output": f"shard {shard_index} timed out after {timeout}s: {e}",
            "coverage_file": coverage_file,
            "files": shard_files,
        }


def run_tests_with_coverage(
    testbed_path: str,
    test_files: List[str],
    shards: Optional[int] = None,
    already_collected: bool = False,
) -> Dict:
    """Run per-test coverage (``--cov-context=test``) over **all** test files.

    Files are sharded across worker pytest processes (bounded by
    ``TIA_INSTRUMENT_SHARDS``, default ~CPUs capped at 4) so runtime stays
    bounded. Each shard writes ``.coverage.shard<N>``; the shards are merged
    later. ``TIA_INSTRUMENT_MAX_TEST_FILES`` (default 0 = no cap) is an optional
    escape hatch that reports the resulting shortfall rather than hiding it.

    ``already_collected`` skips the per-file collectability probe when the
    caller already discovered these files via pytest collection (the sample
    universe is then larger and a per-file probe would spawn thousands of
    processes for no benefit).

    Returns a dict with success/output/counts/coverage_files/scheduled_files.
    """
    venv_python = os.path.join(testbed_path, ".venv", "bin", "python")
    original_count = len(test_files)

    # Install basic test deps so collection doesn't fail on missing plugins
    _install_test_deps(venv_python, testbed_path)

    # Filter to only test files that can be collected
    collectable = (
        list(test_files) if already_collected
        else _filter_collectable_files(venv_python, testbed_path, test_files)
    )
    collectable_count = len(collectable)
    if not collectable:
        return {
            "success": False,
            "output": f"No collectable test files found (tried {len(test_files)} files)",
            "collectable_count": 0,
            "original_count": original_count,
            "coverage_files": [],
            "scheduled_files": [],
        }

    scheduled = collectable
    max_files = _env_int("TIA_INSTRUMENT_MAX_TEST_FILES", 0)
    if max_files > 0 and len(scheduled) > max_files:
        scheduled = scheduled[:max_files]

    shard_count = shards if shards is not None else _env_int("TIA_INSTRUMENT_SHARDS", DEFAULT_SHARDS)
    shard_count = max(1, min(shard_count, len(scheduled)))
    timeout = _env_int("TIA_INSTRUMENT_TIMEOUT", 1800)

    src_dir = os.path.join(testbed_path, "src")
    cov_flag = "--cov=src" if os.path.isdir(src_dir) else "--cov"

    partitions = partition_test_files(scheduled, shard_count)

    outputs: List[str] = []
    success = True
    coverage_files: List[str] = []
    workers = min(len(partitions), shard_count) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_run_coverage_shard, venv_python, testbed_path, part, i, cov_flag, timeout)
            for i, part in enumerate(partitions)
        ]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            outputs.append(
                f"--- shard {res['shard']} ({len(res['files'])} files) exit={res['returncode']} ---\n{res['output']}"
            )
            if res["returncode"] != 0:
                success = False
            cf = res.get("coverage_file")
            if cf and os.path.exists(cf) and os.path.getsize(cf) > 0:
                coverage_files.append(cf)

    return {
        "success": success,
        "output": "\n".join(outputs),
        "collectable_count": collectable_count,
        "original_count": original_count,
        "coverage_files": coverage_files,
        "scheduled_files": scheduled,
    }


def _find_coverage_db(testbed_path: str) -> str:
    """Find the coverage DB, trying .coverage first then suffixed .coverage.* files."""
    exact = os.path.join(testbed_path, ".coverage")
    if os.path.exists(exact) and os.path.getsize(exact) > 0:
        return exact
    candidates = sorted(glob.glob(os.path.join(testbed_path, ".coverage.*")))
    candidates = [c for c in candidates if not c.endswith(".json")]
    if candidates:
        biggest = max(candidates, key=os.path.getsize)
        if os.path.getsize(biggest) > 0:
            return biggest
    return exact


def _find_all_coverage_dbs(testbed_path: str) -> List[str]:
    """Find every coverage SQLite DB produced by the sharded run."""
    paths: List[str] = []
    exact = os.path.join(testbed_path, ".coverage")
    if os.path.exists(exact) and os.path.getsize(exact) > 0:
        paths.append(exact)
    for p in sorted(glob.glob(os.path.join(testbed_path, ".coverage.shard*"))):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            paths.append(p)
    return paths


def _merge_coverage(dst: Dict[str, Dict[str, List[int]]], src: Dict[str, Dict[str, List[int]]]) -> None:
    """Union per-test line coverage from a shard into the merged accumulator."""
    for test_name, file_coverage in src.items():
        bucket = dst.setdefault(test_name, {})
        for fpath, lines in file_coverage.items():
            existing = set(bucket.get(fpath, []))
            existing.update(lines)
            bucket[fpath] = sorted(existing)


def extract_per_test_lines(testbed_path: str, db_paths: Optional[List[str]] = None) -> Dict[str, Dict[str, List[int]]]:
    """Extract per-test line data from one or more coverage SQLite databases.

    When ``db_paths`` is omitted, discovers ``.coverage`` + ``.coverage.shard*``
    and merges them. When supplied, merges exactly those databases.
    """
    if db_paths is None:
        db_paths = _find_all_coverage_dbs(testbed_path)
    merged: Dict[str, Dict[str, List[int]]] = {}
    for db in db_paths:
        _merge_coverage(merged, _extract_from_db(db))
    logger.info(
        "extract_per_test_lines: merged %d coverage DB(s) -> %d tests with coverage data",
        len(db_paths), len(merged),
    )
    return merged


def _extract_from_db(coverage_db: str) -> Dict[str, Dict[str, List[int]]]:
    """Extract per-test line data from a single coverage SQLite database."""
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
        test_name = _normalize_nodeid(ctx_name.replace("|run", ""))

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

    Mirrors ``coverage.numbits.numbits_to_nums``: a line ``L`` is stored at
    ``byte = L // 8``, ``bit = L % 8``, so ``line = byte * 8 + bit`` (no +1).
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
                    lines.append(byte_offset * 8 + bit_offset)
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
            "symbols": [
                (
                    s.name, s.symbol_type, s.start_line, s.end_line,
                    os.path.relpath(s.file_path, testbed_path),
                    s.covered_line_count, s.coverage_kind,
                )
                for s in symbols
            ],
        })
    
    logger.info(f"resolve_to_symbols: {len(per_test_coverage)} tests -> {len(all_mappings)} mappings, total symbols={sum(len(m['symbols']) for m in all_mappings)}")
    return all_mappings


def _norm_test_file(path: str, testbed_path: str) -> str:
    """Normalize a test path/nodeid file portion to a repo-relative path."""
    if not path:
        return ""
    p = path.replace("\\", "/")
    if os.path.isabs(p):
        try:
            rel = os.path.relpath(p, testbed_path)
            if not rel.startswith(".."):
                p = rel
        except ValueError:
            pass
    while p.startswith("./"):
        p = p[2:]
    return p


def _test_file_of(test_name: str) -> str:
    """Extract the test file portion of a pytest nodeid."""
    return test_name.split("::")[0] if "::" in test_name else test_name


def _normalize_nodeid(test_name: str) -> str:
    """Collapse an empty-item pytest nodeid (``path::``) to the file path.

    Data-driven collectors (e.g. Pygments' snippet/examplefile items) emit items
    with no name, so their nodeid is the sample path plus a bare ``::``. Storing
    that trailing separator would create duplicate-looking ids and break the
    agent's canonical-nodeid dedupe, so normalize it to the file path.
    """
    if test_name.endswith("::"):
        return test_name[:-2]
    return test_name


def _coverage_completeness(
    testbed_path: str,
    scheduled_files: List[str],
    per_test_coverage: Dict,
    original_count: int,
    collectable_count: int,
    universe: Optional[List[str]] = None,
    carried_forward: Optional[List[str]] = None,
) -> Dict:
    """Report how much of the suite actually produced per-test coverage.

    ``coverage_pct`` is measured against ``universe`` when given, otherwise
    against the files we *scheduled*. The universe is the full suite: an
    incremental run (Story 11.5) executes only a subset of the test files, but
    its completeness must still be comparable to a full run — evidence carried
    forward from the previous run counts as covered.

    ``missing_test_files`` names the exact shortfall so a run never silently
    under-covers.

    Args:
        universe: Every test file in the suite (full-suite denominator)
        carried_forward: Files not re-run this time whose prior evidence was
            reused; counted as covered when part of ``universe``.
    """
    scheduled_by_rel = {_norm_test_file(f, testbed_path): f for f in scheduled_files}
    instrumented_rel = {_norm_test_file(_test_file_of(t), testbed_path) for t in per_test_coverage}
    carried_rel = {_norm_test_file(f, testbed_path) for f in (carried_forward or [])}
    universe_by_rel = (
        {_norm_test_file(f, testbed_path): f for f in universe}
        if universe is not None
        else scheduled_by_rel
    )

    # Covered = produced coverage this run, or carried forward from the last one.
    covered = instrumented_rel | carried_rel
    matched = sorted(rel for rel in universe_by_rel if rel in covered)
    missing = sorted(rel for rel in universe_by_rel if rel not in covered)
    denom = len(universe_by_rel)
    pct = round(100.0 * len(matched) / denom, 1) if denom else 0.0
    return {
        "test_files_expected": original_count,
        "test_files_collectable": collectable_count,
        "test_files_scheduled": len(scheduled_by_rel),
        "test_files_total": denom,
        "test_files_carried_forward": len(carried_rel & set(universe_by_rel)),
        "test_files_instrumented": len(matched),
        "coverage_pct": pct,
        "missing_test_files": missing[:50],
        "missing_count": len(missing),
    }


def analyze_per_test_coverage(
    testbed_path: str,
    test_files: List[str],
    shards: Optional[int] = None,
    already_collected: bool = False,
    universe: Optional[List[str]] = None,
    carried_forward: Optional[List[str]] = None,
) -> Dict:
    """
    Main entry point: Run tests with coverage and return per-test symbol mappings.

    Runs per-test coverage over all supplied test files (sharded across workers),
    merges the shards, and reports coverage completeness.

    ``already_collected`` short-circuits the per-file collectability probe when
    the caller discovered ``test_files`` via pytest itself.

    ``universe`` / ``carried_forward`` describe an incremental run (Story 11.5):
    ``test_files`` is the narrowed subset to execute, while completeness stays
    measured against the whole suite.

    Returns:
        Dict with:
            - mappings: List of {test_name, test_file, symbols}
            - test_count: Number of tests processed
            - symbol_count: Total unique symbols across all tests
            - coverage_completeness: suite coverage metrics + shortfall
    """
    # Run tests (partial failures still produce coverage data)
    run = run_tests_with_coverage(
        testbed_path, test_files, shards=shards, already_collected=already_collected
    )
    success = run["success"]
    output = run["output"]
    collectable_count = run["collectable_count"]
    original_count = run["original_count"]
    scheduled_files = run["scheduled_files"]

    # Build diagnostics early so we can return useful info even on failure
    diag = {
        "test_files_original": original_count,
        "test_files_collectable": collectable_count,
        "test_files_scheduled": len(scheduled_files),
        "output": output[:1000] if output else ""
    }

    # Extract per-test lines from the shard DBs (coverage data may exist even on
    # partial failure because -x is not used).
    per_test_coverage = extract_per_test_lines(testbed_path, db_paths=run["coverage_files"] or None)
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

    # Coverage completeness = did every scheduled test file actually contribute?
    completeness = _coverage_completeness(
        testbed_path, scheduled_files, per_test_coverage, original_count, collectable_count,
        universe=universe, carried_forward=carried_forward,
    )
    diag["coverage_completeness"] = completeness

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
        "coverage_completeness": completeness,
        "diagnostics": diag
    }


if __name__ == "__main__":
    import json
    result = analyze_per_test_coverage(
        "/tmp/testbed-repro",
        ["tests/utils/test_wait.py", "tests/utils/test_retry.py"]
    )
    print(json.dumps(result, indent=2))