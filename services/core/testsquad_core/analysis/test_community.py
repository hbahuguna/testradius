import logging
import networkx as nx
from typing import Dict, List
from ..graph.client import Neo4jClient

logger = logging.getLogger(__name__)


class TestCommunityDetector:
    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    def fetch_test_graph(self) -> nx.DiGraph:
        """Fetches the test call graph from Neo4j."""
        query = """
        MATCH (ts1:TestSymbol)-[:CALLS_PRODUCT]->(s:Symbol)
        RETURN ts1.name AS source_name, ts1.file_path AS source_file,
               s.name AS target_name, s.file_path AS target_file
        """
        results = self.neo4j.query(query)

        G = nx.DiGraph()
        for row in results:
            source = f"{row['source_file']}::{row['source_name']}"
            target = f"{row['target_file']}::{row['target_name']}"

            if source not in G:
                G.add_node(source, name=row['source_name'], file_path=row['source_file'])
            if target not in G:
                G.add_node(target, name=row['target_name'], file_path=row['target_file'])

            G.add_edge(source, target)

        logger.info(f"Fetched test graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
        return G

    def fetch_test_import_graph(self) -> nx.DiGraph:
        """Fetches the test import graph from Neo4j (for community detection within test files)."""
        query = """
        MATCH (tf1:TestFile)-[:IMPORTS]->(tf2:TestFile)
        RETURN tf1.path AS source_file, tf2.path AS target_file
        """
        results = self.neo4j.query(query)

        G = nx.DiGraph()
        for row in results:
            source = row['source_file']
            target = row['target_file']

            if source not in G:
                G.add_node(source, file_path=source)
            if target not in G:
                G.add_node(target, file_path=target)

            G.add_edge(source, target)

        logger.info(f"Fetched test import graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
        return G

    def fetch_test_internal_call_graph(self) -> nx.DiGraph:
        """Fetches internal test-to-test call graph."""
        query = """
        MATCH (ts1:TestSymbol)-[:CALLS]->(ts2:TestSymbol)
        RETURN ts1.name AS source_name, ts1.file_path AS source_file,
               ts2.name AS target_name, ts2.file_path AS target_file
        """
        results = self.neo4j.query(query)

        G = nx.DiGraph()
        for row in results:
            source = f"{row['source_file']}::{row['source_name']}"
            target = f"{row['target_file']}::{row['target_name']}"

            if source not in G:
                G.add_node(source, name=row['source_name'], file_path=row['source_file'])
            if target not in G:
                G.add_node(target, name=row['target_name'], file_path=row['target_file'])

            G.add_edge(source, target)

        logger.info(f"Fetched internal test call graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
        return G

    def detect_test_communities(self) -> List[Dict]:
        """Runs the Leiden community detection algorithm on test graphs."""
        import igraph as ig
        import leidenalg

        G = self.fetch_test_graph()
        if G.number_of_nodes() == 0:
            logger.warning("No nodes found for test community detection.")
            return []

        node_list = list(G.nodes())
        node_index = {node: i for i, node in enumerate(node_list)}

        edges = [(node_index[u], node_index[v]) for u, v in G.edges()]

        g_ig = ig.Graph(len(node_list), edges, directed=True)

        logger.info("Executing Leiden algorithm for test community discovery...")
        partition = leidenalg.find_partition(g_ig, leidenalg.ModularityVertexPartition)

        update_data = []
        for i, community_nodes in enumerate(partition):
            for node_idx in community_nodes:
                node_id = node_list[node_idx]
                node_data = G.nodes[node_id]
                update_data.append({
                    "name": node_data["name"],
                    "file_path": node_data["file_path"],
                    "test_community_id": i
                })

        logger.info(f"Leiden algorithm identified {len(partition)} test communities.")
        return update_data

    def run_and_save(self):
        """Fetches graph, detects communities, and saves back to Neo4j."""
        community_data = self.detect_test_communities()
        if not community_data:
            return

        BATCH_SIZE = 1000
        total_updated = 0
        for i in range(0, len(community_data), BATCH_SIZE):
            batch = community_data[i:i+BATCH_SIZE]
            result = self.neo4j.bulk_update_test_communities(batch)
            if result and result[0].get("updated_count"):
                total_updated += result[0]["updated_count"]

        logger.info(f"Successfully updated test community IDs for {total_updated} test symbols in Neo4j.")