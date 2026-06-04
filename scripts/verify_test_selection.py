"""Verify test selection scenarios against the TestSquad API.

Usage:
    python scripts/verify_test_selection.py [--scenario SCENARIO] [--all]

Runs against a running Docker API at http://localhost:8000.
Structural-only mode (no LLM needed) — only scenarios 7 (untested) and 10
require LLM generation.
"""

import os
import sys
import json
import time
import argparse
from typing import Dict, List, Optional, Tuple

import subprocess
import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
PROJECT_ID = 1237038652  # py-key-value (GitHub import, has File -> DEFINES chains)
COMMIT_SHA = "572d0ae03229d7986a5d19513ca9e24da5c73dcf"

# Per-symbol expected test counts from the graph (store_mappings, project_id=1237038652)
# Each symbol should match its known TESTS edge count within a tolerance
# Symbols from Path 2 (store_mappings, pid=1237038652) have TESTS edges.
# Symbols from Path 1 (ingestor, pid=None) have 0 TESTS edges.
# When scoping by file_paths, BOTH paths return results; the dedup keeps the
# Path 2 copy (higher pri) which has TESTS edges — unless Path 2 has no entry
# for that symbol (e.g., protocol/base-enum symbols are only in Path 1).
PER_SYMBOL_TESTS = {
    "BaseStore": (1000, 1200),
    "get": (700, 900),
    "put": (850, 1000),
    "setup": (1000, 1200),
    "setup_collection": (1000, 1200),
    "delete": (100, 150),
    "_calculate_delay": (5, 15),
    "async_retry_operation": (60, 90),
    "MemoryStore": (950, 1150),
    "_setup_collection": (950, 1150),
    "_delete_managed_entry": (150, 300),
    "BaseWrapper": (150, 250),
    "NullStore": (0, 0),
    "SerializationAdapter": (1000, 1200),
    "MemoryCollection": (950, 1150),
    "MemoryCacheEntry": (0, 0),
    "keys": (400, 600),
    "__init__": (950, 1150),
    "cull": (100, 200),
    "close": (400, 600),
    "collections": (400, 600),
    "destroy": (100, 150),
    "destroy_collection": (100, 150),
    "put_many": (100, 200),
    "delete_many": (80, 120),
    "get_many": (100, 180),
    "ttl": (30, 60),
    "ttl_many": (2, 10),
    "_seed_store": (1000, 1200),
    "_put_managed_entries": (100, 200),
    "_get_collection_or_raise": (950, 1150),
    "_setup": (950, 1150),
    "_get_managed_entry": (750, 950),
    "_memory_cache_ttu": (800, 950),
    "BasicSerializationAdapter": (1000, 1200),
    "parse_datetime_str": (800, 950),
    "dump_dict": (950, 1100),
    "key_must_be": (800, 950),
    "load_dict": (800, 950),
    "dump_json": (950, 1100),
    "load_json": (800, 950),
    "prepare_dump": (800, 950),
    "prepare_load": (800, 950),
    "BaseDestroyStore": (100, 200),
    "BaseCullStore": (100, 200),
    "BaseEnumerateCollectionsStore": (100, 200),
    "BaseEnumerateKeysStore": (100, 200),
    "BaseDestroyCollectionStore": (100, 200),
    "BaseContextManagerStore": (100, 200),
    "AsyncKeyValueProtocol": (0, 0),
    "AsyncCullProtocol": (0, 0),
    "AsyncKeyValue": (0, 0),
    "AsyncEnumerateKeysProtocol": (0, 0),
    "AsyncDestroyCollectionProtocol": (0, 0),
    "AsyncEnumerateCollectionsProtocol": (0, 0),
    "AsyncDestroyStoreProtocol": (0, 0),
}

SCENARIOS = {
    "base_class": {
        "file_paths": ["src/key_value/aio/stores/base.py"],
        "key_symbols": ["BaseStore", "put", "setup", "get", "setup_collection"],
        "expected_symbol_count_range": (8, 12),
        "description": "Base class change — top 10 base.py symbols by TESTS edge count",
    },
    "leaf_utility": {
        "file_paths": ["src/key_value/aio/_utils/retry.py"],
        "key_symbols": ["_calculate_delay", "async_retry_operation"],
        "expected_symbol_count_range": (1, 4),
        "description": "Leaf utility change (minimal impact) — 2 symbols in retry.py",
    },
    "shared_constant": {
        "file_paths": [
            "src/key_value/aio/stores/base.py",
            "src/key_value/aio/_utils/serialization.py",
        ],
        "key_symbols": ["BaseStore", "SerializationAdapter", "__init__"],
        "expected_symbol_count_range": (8, 12),
        "description": "Shared constant change — top 10 from base.py + serialization.py combined",
    },
    "concrete_store": {
        "file_paths": ["src/key_value/aio/stores/memory/store.py"],
        "key_symbols": ["MemoryStore", "_setup_collection", "put", "get"],
        "expected_symbol_count_range": (8, 15),
        "description": "Concrete store change — all MemoryStore symbols in memory/store.py",
    },
    "wrapper_base": {
        "file_paths": ["src/key_value/aio/wrappers/base.py"],
        "key_symbols": ["BaseWrapper"],
        "expected_symbol_count_range": (5, 15),
        "description": "Wrapper change — BaseWrapper and related symbols",
    },
    "protocol": {
        "file_paths": ["src/key_value/aio/protocols/key_value.py"],
        "key_symbols": ["AsyncKeyValueProtocol"],
        "expected_symbol_count_range": (8, 12),
        "description": "Protocol change — top 10 symbols (all 0 TESTS edges, structural-only)",
    },
    "untested": {
        "file_paths": ["src/key_value/aio/stores/null/store.py"],
        "key_symbols": ["NullStore"],
        "expected_symbol_count_range": (1, 2),
        "description": "Untested symbol — NullStore has 0 TESTS edges",
    },
    "async_func": {
        "file_paths": ["src/key_value/aio/stores/memory/store.py"],
        "key_symbols": ["MemoryStore", "_setup_collection", "_memory_cache_ttu"],
        "expected_symbol_count_range": (8, 12),
        "description": "Async function — top 10 MemoryStore symbols by TESTS edge count",
    },
    "diamond_inheritance": {
        "file_paths": ["src/key_value/aio/stores/base.py"],
        "key_symbols": ["BaseStore", "get", "setup"],
        "expected_symbol_count_range": (8, 12),
        "description": "Diamond inheritance — BaseStore + all base.py store_mappings symbols (top 10)",
    },
    "mixed_change": {
        "file_paths": [
            "src/key_value/aio/stores/base.py",
            "src/key_value/aio/_utils/retry.py",
        ],
        "key_symbols": ["BaseStore", "put"],
        "expected_symbol_count_range": (8, 12),
        "description": "Mixed change — base.py + retry.py combined (top 10 by pri, likely base.py symbols)",
    },
}


def start_run(project_id: int, file_paths: List[str], llm_model: str = "") -> int:
    """Start a test run and return run_id.
    
    Set llm_model="gemini-2.5-flash" to enable LLM test generation
    (requires GOOGLE_API_KEY in .env).
    """
    url = f"{API_BASE}/projects/{project_id}/runs"
    resp = requests.post(url, json={
        "commit_sha": COMMIT_SHA,
        "file_paths": file_paths,
        "llm_model": llm_model,
        "llm_provider": "Google",
    })
    resp.raise_for_status()
    return resp.json()["run_id"]


def stream_run(project_id: int, run_id: int, timeout: int = 90) -> List[Dict]:
    """Stream run events and collect all events.

    Uses curl via subprocess (SSE streaming with requests is unreliable).
    Falls back to the persisted events endpoint on failure.
    """
    url = f"{API_BASE}/projects/{project_id}/runs/{run_id}/stream"
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        events = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  Stream timed out")
        return _get_persisted_events(run_id)
    except Exception as e:
        print(f"  ⚠️  Stream error: {e}")
        persisted = _get_persisted_events(run_id)
        if persisted:
            return persisted
        raise


def _get_persisted_events(run_id: int) -> List[Dict]:
    """Fallback: fetch persisted events from the runs/{run_id}/events endpoint."""
    url = f"{API_BASE}/runs/{run_id}/events"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json().get("events", [])
    except Exception as e:
        print(f"  ⚠️  Could not fetch persisted events: {e}")
        return []


def analyze_events(events: List[Dict]) -> Dict:
    """Extract symbol selections and test counts from stream events."""
    result = {
        "symbols_found": [],
        "symbols_with_tests": [],
        "status": "unknown",
    }

    for event in events:
        ev = event.get("event", "")
        data = event.get("data", "")

        if ev == "status":
            status_data = data if isinstance(data, dict) else {}
            result["status"] = status_data.get("status", "unknown")

        elif ev == "reasoning" and isinstance(data, str):
            if "Analyzing symbol:" in data:
                sym = data.split("**")[1] if "**" in data else data
                result["symbols_found"].append(sym)

            if "Reusing" in data and "existing test(s)" in data:
                import re
                m = re.search(r'Reusing (\d+) existing test', data)
                if m:
                    count = int(m.group(1))
                    if result["symbols_found"]:
                        sym = result["symbols_found"][-1]
                        result["symbols_with_tests"].append({
                            "symbol": sym,
                            "test_count": count,
                        })

    return result


def verify_scenario(scenario_name: str, config: dict) -> bool:
    """Run one scenario and verify results."""
    all_pass = True

    print(f"\n{'='*60}")
    print(f"Scenario: {scenario_name} — {config['description']}")
    print(f"{'='*60}")

    file_list = config.get("file_paths", [])
    print(f"  Files: {', '.join(file_list)}")
    print(f"  Key symbols to verify: {', '.join(config['key_symbols'])}")

    run_id = start_run(PROJECT_ID, file_list)
    print(f"  Run ID: {run_id}")

    events = stream_run(PROJECT_ID, run_id)

    analysis = analyze_events(events)

    print(f"  Status: {analysis['status']}")
    print(f"  Symbols found ({len(analysis['symbols_found'])} total):")
    for sym in analysis["symbols_found"]:
        print(f"    - {sym}")
    print(f"  Symbols with tests:")
    for swt in analysis["symbols_with_tests"]:
        print(f"    - {swt['symbol']}: {swt['test_count']} tests")

    # Check symbol count
    sym_count = len(analysis["symbols_found"])
    sym_range = config.get("expected_symbol_count_range")
    if sym_range:
        in_range = sym_range[0] <= sym_count <= sym_range[1]
        print(f"  {'✅' if in_range else '❌'} Symbol count: {sym_count} "
              f"{'in' if in_range else 'outside'} range {sym_range}")
        if not in_range:
            all_pass = False

    # Check per-symbol test counts
    swt_map = {s["symbol"]: s["test_count"] for s in analysis["symbols_with_tests"]}
    print(f"  Per-symbol test count verification:")
    for key_sym in config["key_symbols"]:
        if key_sym in PER_SYMBOL_TESTS:
            expected = PER_SYMBOL_TESTS[key_sym]
            actual = swt_map.get(key_sym, 0)
            in_range = expected[0] <= actual <= expected[1]
            print(f"    {'✅' if in_range else '❌'} {key_sym}: {actual} tests "
                  f"{'in' if in_range else 'outside'} range ({expected[0]}-{expected[1]})")
            if not in_range:
                all_pass = False
        elif key_sym in analysis["symbols_found"]:
            print(f"    ⚠️  {key_sym}: found but no expected range defined")
        else:
            print(f"    ⚠️  {key_sym}: not found in selected symbols")
            all_pass = False

    if all_pass:
        print(f"  ✅ PASS: {scenario_name}")
    else:
        print(f"  ❌ FAIL: {scenario_name}")

    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Verify test selection scenarios")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()),
                        help="Run specific scenario")
    parser.add_argument("--all", action="store_true",
                        help="Run all scenarios")
    args = parser.parse_args()

    if args.scenario:
        configs = {args.scenario: SCENARIOS[args.scenario]}
    elif args.all:
        configs = SCENARIOS
    else:
        parser.print_help()
        return

    results = {}
    for name, config in configs.items():
        results[name] = verify_scenario(name, config)

    print(f"\n{'='*60}")
    print("Summary:")
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"  Passed: {passed}/{len(results)}")
    if failed:
        print(f"  Failed: {failed}/{len(results)}")
        for name, ok in results.items():
            if not ok:
                print(f"    ❌ {name}")
        sys.exit(1)
    else:
        print(f"  All passed!")


if __name__ == "__main__":
    main()
