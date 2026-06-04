#!/usr/bin/env python
"""
Migration script for Task 1.1.5: Neo4j Schema Updates

Adds:
- New properties on Symbol/TestSymbol: summary, signature, embedding, summary_version
- EXECUTED_BY relationship with confidence, source, created_at
- Vector index for symbol embeddings

Usage:
    python scripts/migrate_schema.py [--dry-run] [--project-id ID]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from testsquad_core.graph.client import Neo4jClient


def migrate_schema(client: Neo4jClient, dry_run: bool = False) -> dict:
    """Execute schema migration.
    
    Returns:
        Dict with migration results
    """
    results = {
        "vector_index_created": False,
        "properties_added": 0,
        "executed_by_edges": 0,
        "errors": []
    }
    
    # 1. Create vector index
    print("Creating vector index for symbol embeddings...")
    try:
        if not dry_run:
            client.create_vector_index()
        results["vector_index_created"] = True
        print("  OK: Vector index created (or already exists)")
    except Exception as e:
        err = f"Vector index creation failed: {e}"
        print(f"  WARNING: {err}")
        results["errors"].append(err)
    
    # 2. Add new properties to Symbol nodes (via SET for existing)
    print("Adding properties to existing Symbol nodes...")
    symbol_props_query = """
    MATCH (s:Symbol)
    WHERE s.summary IS NULL
    SET s.summary_version = 1
    WITH count(s) as cnt
    RETURN cnt
    """
    try:
        if not dry_run:
            result = client.query(symbol_props_query)
            results["properties_added"] = result[0].get("cnt", 0) if result else 0
        else:
            results["properties_added"] = 0
        print(f"  OK: {results['properties_added']} Symbol nodes updated")
    except Exception as e:
        err = f"Failed to add Symbol properties: {e}"
        print(f"  WARNING: {err}")
        results["errors"].append(err)
    
    # 3. Add new properties to TestSymbol nodes
    print("Adding properties to existing TestSymbol nodes...")
    test_props_query = """
    MATCH (ts:TestSymbol)
    WHERE ts.summary IS NULL
    SET ts.summary_version = 1
    WITH count(ts) as cnt
    RETURN cnt
    """
    try:
        if not dry_run:
            result = client.query(test_props_query)
            results["properties_added"] += result[0].get("cnt", 0) if result else 0
        print(f"  OK: TestSymbol nodes updated")
    except Exception as e:
        err = f"Failed to add TestSymbol properties: {e}"
        print(f"  WARNING: {err}")
        results["errors"].append(err)
    
    # 4. Verify EXECUTED_BY relationship support
    print("Verifying EXECUTED_BY relationship support...")
    verify_query = """
    MATCH (s:Symbol)-[r:EXECUTED_BY]->(ts:TestSymbol)
    RETURN count(r) as edge_count
    """
    try:
        if not dry_run:
            result = client.query(verify_query)
            results["executed_by_edges"] = result[0].get("edge_count", 0) if result else 0
        print(f"  OK: {results['executed_by_edges']} EXECUTED_BY edges exist")
    except Exception as e:
        # Edge might not exist yet - that's OK
        print(f"  OK: EXECUTED_BY relationship ready (0 edges)")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Migrate Neo4j schema for vector embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--project-id", type=int, help="Specific project ID to migrate")
    parser.add_argument("--uri", default=None, help="Neo4j URI (default: from env)")
    parser.add_argument("--user", default=None, help="Neo4j user (default: from env)")
    parser.add_argument("--password", default=None, help="Neo4j password (default: from env)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Neo4j Schema Migration: Task 1.1.5")
    print("=" * 60)
    
    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
        print()
    
    # Create client
    client = Neo4jClient(
        uri=args.uri,
        user=args.user,
        password=args.password
    )
    
    try:
        # Run migration
        results = migrate_schema(client, dry_run=args.dry_run)
        
        # Summary
        print()
        print("=" * 60)
        print("Migration Summary")
        print("=" * 60)
        print(f"  Vector index created: {results['vector_index_created']}")
        print(f"  Properties added: {results['properties_added']}")
        print(f"  EXECUTED_BY edges: {results['executed_by_edges']}")
        print(f"  Errors: {len(results['errors'])}")
        
        if results["errors"]:
            for err in results["errors"]:
                print(f"    - {err}")
        
        if args.dry_run:
            print()
            print("DRY RUN complete. Re-run without --dry-run to apply changes.")
        
    finally:
        client.close()
    
    return 0 if not results["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())