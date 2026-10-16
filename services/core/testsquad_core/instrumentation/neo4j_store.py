import os
import json
from typing import List, Dict, Any, Optional
from .symbol_resolver import Symbol


class PersistenceError(RuntimeError):
    """Raised when test-symbol mappings cannot be persisted or verified.

    Persistence failures must be loud: a run that fails to write (or writes
    fewer edges than it produced) must surface as ``ERROR`` rather than a
    silently ``COMPLETED`` run with zero evidence.
    """


class Neo4jStore:
    """Stores and retrieves test-symbol mappings in Neo4j using [:EVIDENCE] relationship."""
    
    def __init__(self, neo4j_client=None):
        self.neo4j_client = neo4j_client
    
    def purge_project(self, project_id: int) -> int:
        """
        Remove all Test/Symbol nodes and EVIDENCE edges for a project.

        Args:
            project_id: Project ID to purge

        Returns:
            Number of nodes+edges removed
        """
        if not self.neo4j_client:
            return 0
        query = """
        MATCH (n)
        WHERE n.project_id = $project_id
        DETACH DELETE n
        RETURN count(*) AS removed
        """
        try:
            result = self.neo4j_client.query(query, {"project_id": project_id})
            return result[0]["removed"] if result else 0
        except Exception as e:
            print(f"Warning: Failed to purge project {project_id}: {e}")
            return 0

    def store_mappings(self, mappings: List[Dict[str, Any]], project_id: int, built_at_sha: Optional[str] = None) -> int:
        """
        Store test-symbol mappings in Neo4j atomically and verify the write.

        The mappings are written in a single transaction and the number of
        stored ``[:EVIDENCE]`` edges is re-counted inside that transaction. A
        mismatch (or any write failure) raises :class:`PersistenceError` so the
        surrounding run can be failed instead of silently reporting success.

        Each mapping edge (and its ``TestSymbol`` node) is stamped with
        ``built_at_sha`` — the testbed commit the evidence was derived from — so
        analyze time can detect drift (D2).

        Args:
            mappings: List of dicts with test_name, test_file, symbols
            project_id: Project ID for scoping
            built_at_sha: Commit SHA the mappings were built against (optional;
                existing stamps are preserved when omitted)

        Returns:
            Number of verified EVIDENCE edges stored.

        Raises:
            PersistenceError: if the write fails or the verified edge count does
                not equal the number of distinct mapping edges produced.
        """
        if not self.neo4j_client or not mappings:
            return 0

        edges = self._build_edges(mappings)
        return self._bulk_store_edges(edges, project_id, built_at_sha)

    def replace_mappings(self, mappings: List[Dict[str, Any]], project_id: int,
                         built_at_sha: Optional[str] = None) -> int:
        """Replace project evidence with the provided mappings atomically.

        Deletes all prior coverage-sourced ``[:EVIDENCE]`` edges for
        ``project_id`` and clears old ``built_at_sha`` stamps on surviving
        ``TestSymbol`` nodes, then writes the new coverage mappings in the same
        transaction. Non-coverage edges (e.g. ``source != 'coverage'``) are not
        touched. The write is verified inside the transaction; verification
        failure raises :class:`PersistenceError`.

        Args:
            mappings: List of dicts with test_name, test_file, symbols
            project_id: Project ID for scoping
            built_at_sha: Commit SHA the new mappings were built against

        Returns:
            Number of verified EVIDENCE edges stored.

        Raises:
            PersistenceError: if the write fails or verification mismatches.
        """
        if not self.neo4j_client or not mappings:
            return 0

        edges = self._build_edges(mappings)
        distinct = self._distinct_edges(edges)
        expected = len(distinct)
        if expected == 0:
            return 0

        params = {"edges": distinct, "project_id": project_id, "built_at_sha": built_at_sha}

        # 1. Delete prior coverage-sourced EVIDENCE edges (both endpoints scoped
        #    to the project so we never touch ingestor symbols, which carry no
        #    project_id, or evidence from other projects).
        delete_coverage_edges = """
        MATCH (t:TestSymbol)-[ev:EVIDENCE {source: 'coverage'}]->(s:Symbol)
        WHERE t.project_id = $project_id
          AND s.project_id = $project_id
        DETACH DELETE ev
        RETURN count(ev) AS removed
        """
        # 2. Clear stale built_at_sha stamps on surviving TestSymbol nodes so a
        #    subsequent analyze-pr never sees mixed-commit evidence (D2). Only
        #    the current run's write below re-stamps nodes with a SHA.
        clear_stale_shas = """
        MATCH (t:TestSymbol {project_id: $project_id})
        SET t.built_at_sha = null
        RETURN count(t) AS cleared
        """
        write_query = """
        UNWIND $edges AS e
        MERGE (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })
        SET t.built_at_sha = coalesce($built_at_sha, t.built_at_sha)
        MERGE (s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        SET s.symbol_type = e.symbol_type
        MERGE (t)-[ev:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)
        SET ev.built_at_sha = coalesce($built_at_sha, ev.built_at_sha)
        RETURN count(*) AS created
        """
        verify_query = """
        UNWIND $edges AS e
        MATCH (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })-[ev:EVIDENCE]->(s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        RETURN count(ev) AS stored
        """

        def _verify(results):
            stored = results[-1][0]["stored"] if results else 0
            if stored != expected:
                raise PersistenceError(
                    f"Persistence verification failed: stored {stored} EVIDENCE "
                    f"edges, expected {expected}"
                )

        statements = [
            (delete_coverage_edges, params),
            (clear_stale_shas, params),
            (write_query, params),
            (verify_query, params),
        ]

        try:
            self.neo4j_client.run_in_transaction(statements, verify=_verify)
        except PersistenceError:
            raise
        except Exception as e:
            raise PersistenceError(
                f"Failed to persist test-symbol mappings: {e}"
            ) from e
        return expected

    def get_coverage_summary(self, project_id: int) -> Dict[str, Any]:
        """Read the prior coverage evidence needed to plan an incremental run.

        Returns a stable, path-agnostic shape the planner consumes:

        ``{"anchor_sha": str | None, "tests": [{"name", "file", "source_file"}]}``

        ``anchor_sha`` is only set when *every* ``TestSymbol`` agrees on it — a
        single distinct ``built_at_sha`` for the project (the 11.1 invariant).
        Mixed or absent SHAs yield ``None``, which sends the caller into a full
        run rather than diffing against an unknown anchor. Failures degrade to
        "no evidence" so a read problem can only ever cost us optimality, never
        correctness.

        Args:
            project_id: Project ID for scoping

        Returns:
            dict with ``anchor_sha`` and ``tests``
        """
        if not self.neo4j_client:
            return {"anchor_sha": None, "tests": []}

        anchor_sha: Optional[str] = None
        try:
            rows = self.neo4j_client.query(
                "MATCH (t:TestSymbol {project_id: $project_id}) "
                "WHERE t.built_at_sha IS NOT NULL "
                "RETURN collect(DISTINCT t.built_at_sha) AS shas",
                {"project_id": project_id},
            )
            shas = rows[0]["shas"] if rows else []
            if shas is not None and len(shas) == 1 and shas[0]:
                anchor_sha = shas[0]
        except Exception as e:
            print(f"Warning: Failed to read evidence anchor: {e}")
            return {"anchor_sha": None, "tests": []}

        tests: List[Dict[str, str]] = []
        try:
            rows = self.neo4j_client.query(
                "MATCH (t:TestSymbol)-[ev:EVIDENCE {source: 'coverage'}]->(s:Symbol) "
                "WHERE t.project_id = $project_id "
                "  AND s.project_id = $project_id "
                "RETURN t.name AS test_name, t.file_path AS test_file, "
                "       s.file_path AS source_file",
                {"project_id": project_id},
            )
            tests = [
                {
                    "name": r["test_name"],
                    "file": r["test_file"],
                    "source_file": r["source_file"],
                }
                for r in (rows or [])
                if r.get("test_name") and r.get("source_file")
            ]
        except Exception as e:
            print(f"Warning: Failed to read coverage evidence: {e}")
            return {"anchor_sha": anchor_sha, "tests": []}

        return {"anchor_sha": anchor_sha, "tests": tests}

    def apply_incremental_mappings(
        self,
        mappings: List[Dict[str, Any]],
        project_id: int,
        built_at_sha: Optional[str] = None,
        rerun_test_names: Optional[List[str]] = None,
        drop_test_names: Optional[List[str]] = None,
    ) -> int:
        """Write evidence for re-run tests and re-stamp carried-forward evidence.

        Unlike :meth:`replace_mappings`, this never wipes the whole project: only
        the tests named in ``rerun_test_names`` have their coverage edges
        replaced, and ``drop_test_names`` are deleted outright (e.g. tests whose
        files no longer exist). Every surviving coverage edge — the evidence
        carried forward from the prior run — is then re-stamped with
        ``built_at_sha`` so the project presents a single anchor (the 11.1
        invariant), and analyze time sees a fresh, non-mixed commit (D2).

        Args:
            mappings: Evidence produced *this* run (re-run tests only)
            project_id: Project ID for scoping
            built_at_sha: New commit the whole project's evidence is anchored to
            rerun_test_names: Test node ids whose old edges are replaced
            drop_test_names: Test node ids whose edges are deleted and not rewritten

        Returns:
            Number of verified EVIDENCE edges written (0 when nothing re-ran).

        Raises:
            PersistenceError: if the write fails or verification mismatches.
        """
        if not self.neo4j_client:
            return 0

        distinct = self._distinct_edges(self._build_edges(mappings))
        expected = len(distinct)

        names = sorted({
            n for n in list(rerun_test_names or []) + list(drop_test_names or []) if n
        })
        params = {
            "edges": distinct,
            "project_id": project_id,
            "built_at_sha": built_at_sha,
            "names": names,
        }

        # 1. Replace (or drop) only the affected tests' coverage edges.
        delete_affected = """
        MATCH (t:TestSymbol {project_id: $project_id})-[ev:EVIDENCE {source: 'coverage'}]->(s:Symbol)
        WHERE s.project_id = $project_id
          AND t.name IN $names
        DETACH DELETE ev
        RETURN count(ev) AS removed
        """
        write_query = """
        UNWIND $edges AS e
        MERGE (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })
        SET t.built_at_sha = coalesce($built_at_sha, t.built_at_sha)
        MERGE (s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        SET s.symbol_type = e.symbol_type
        MERGE (t)-[ev:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)
        SET ev.built_at_sha = coalesce($built_at_sha, ev.built_at_sha)
        RETURN count(*) AS created
        """
        verify_query = """
        UNWIND $edges AS e
        MATCH (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })-[ev:EVIDENCE]->(s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        RETURN count(ev) AS stored
        """

        statements = [(delete_affected, params)]
        if expected:
            statements.append((write_query, params))

        # 2. Re-stamp the whole project (carried-forward evidence included).
        #    Skipped when there is no new SHA to stamp, so an omitted
        #    ``built_at_sha`` can never clear existing anchors.
        if built_at_sha:
            statements.append((
                """
                MATCH (t:TestSymbol {project_id: $project_id})
                SET t.built_at_sha = $built_at_sha
                RETURN count(t) AS cleared
                """,
                params,
            ))
            statements.append((
                """
                MATCH (t:TestSymbol {project_id: $project_id})-[ev:EVIDENCE {source: 'coverage'}]->()
                SET ev.built_at_sha = $built_at_sha
                RETURN count(ev) AS stamped
                """,
                params,
            ))

        verify = None
        if expected:
            def _verify(results):
                stored = results[-1][0]["stored"] if results else 0
                if stored != expected:
                    raise PersistenceError(
                        f"Persistence verification failed: stored {stored} EVIDENCE "
                        f"edges, expected {expected}"
                    )
            statements.append((verify_query, params))
            verify = _verify

        try:
            self.neo4j_client.run_in_transaction(statements, verify=verify)
        except PersistenceError:
            raise
        except Exception as e:
            raise PersistenceError(
                f"Failed to persist incremental test-symbol mappings: {e}"
            ) from e
        return expected

    def count_coverage_edges(self, project_id: int) -> int:
        """Total coverage ``[:EVIDENCE]`` edges now stored for the project.

        An incremental run writes only the re-run tests' edges, so the number
        returned by :meth:`apply_incremental_mappings` is *not* the project
        total. Reporting the total keeps the run record honest about how much
        evidence actually exists after carried-forward evidence was re-stamped.
        """
        if not self.neo4j_client:
            return 0
        try:
            rows = self.neo4j_client.query(
                "MATCH (t:TestSymbol {project_id: $project_id})"
                "-[ev:EVIDENCE {source: 'coverage'}]->() "
                "RETURN count(ev) AS edges",
                {"project_id": project_id},
            )
            return int(rows[0]["edges"]) if rows else 0
        except Exception as e:
            print(f"Warning: Failed to count coverage edges: {e}")
            return 0

    def _build_edges(self, mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flatten mappings into one edge dict per (test, symbol) pair."""
        edges = []
        for mapping in mappings:
            test_name = mapping.get("test_name", "")
            test_file = mapping.get("test_file", "")
            for symbol in mapping.get("symbols", []):
                if isinstance(symbol, tuple):
                    sym_name = symbol[0]
                    sym_type = symbol[1]
                    sym_start = symbol[2]
                    sym_end = symbol[3]
                    sym_file = symbol[4]
                else:
                    sym_name = symbol.name
                    sym_type = symbol.symbol_type
                    sym_start = symbol.start_line
                    sym_end = symbol.end_line
                    sym_file = symbol.file_path
                edges.append({
                    "test_name": test_name,
                    "test_file": test_file,
                    "symbol_name": sym_name,
                    "symbol_file": sym_file,
                    "symbol_type": sym_type,
                    "start_line": sym_start,
                    "end_line": sym_end,
                })
        return edges

    @staticmethod
    def _distinct_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate edges keyed by the (test, symbol) node identity."""
        seen = set()
        distinct = []
        for e in edges:
            key = (
                e["test_name"],
                e["test_file"],
                e["symbol_name"],
                e["symbol_file"],
                e["start_line"],
                e["end_line"],
            )
            if key in seen:
                continue
            seen.add(key)
            distinct.append(e)
        return distinct

    def _bulk_store_edges(self, edges: List[Dict], project_id: int, built_at_sha: Optional[str] = None) -> int:
        """Atomically create nodes/EVIDENCE edges and verify the stored count."""
        if not edges:
            return 0

        distinct = self._distinct_edges(edges)
        expected = len(distinct)
        params = {"edges": distinct, "project_id": project_id, "built_at_sha": built_at_sha}

        write_query = """
        UNWIND $edges AS e
        MERGE (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })
        SET t.built_at_sha = coalesce($built_at_sha, t.built_at_sha)
        MERGE (s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        SET s.symbol_type = e.symbol_type
        MERGE (t)-[ev:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)
        SET ev.built_at_sha = coalesce($built_at_sha, ev.built_at_sha)
        RETURN count(*) AS created
        """
        verify_query = """
        UNWIND $edges AS e
        MATCH (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })-[ev:EVIDENCE]->(s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id,
            start_line: e.start_line,
            end_line: e.end_line
        })
        RETURN count(ev) AS stored
        """

        def _verify(results):
            stored = results[1][0]["stored"] if results and results[1] else 0
            if stored != expected:
                raise PersistenceError(
                    f"Persistence verification failed: stored {stored} EVIDENCE "
                    f"edges, expected {expected}"
                )

        try:
            self.neo4j_client.run_in_transaction(
                [(write_query, params), (verify_query, params)],
                verify=_verify,
            )
        except PersistenceError:
            raise
        except Exception as e:
            raise PersistenceError(
                f"Failed to persist test-symbol mappings: {e}"
            ) from e
        return expected
    
    def get_impacted_tests(
        self,
        project_id: int,
        changed_symbols: List[str]
    ) -> List[Dict[str, Any]]:
        """Get tests that cover the given symbols using [:EVIDENCE] relationship."""
        if not self.neo4j_client:
            return []
        
        query = """
        MATCH (t:TestSymbol)-[e:EVIDENCE]->(s:Symbol)
        WHERE s.project_id = $project_id
          AND s.name IN $changed_symbols
        RETURN t.name as test_name, t.file_path as test_file,
               e.confidence as confidence, e.source as source
        ORDER BY test_name
        """
        
        try:
            params = {
                "project_id": project_id,
                "changed_symbols": changed_symbols
            }
            results = self.neo4j_client.query(query, params)
            return [
                {
                    "test_name": r["test_name"],
                    "test_file": r["test_file"],
                    "confidence": r["confidence"]
                }
                for r in results
            ]
        except Exception as e:
            print(f"Warning: Failed to query impacted tests: {e}")
            return []
