"""
Memory module - The Locker (knowledge graph interface).

Contains:
- graphiti_client: Wrapper around Graphiti library
- neo4j_client: Direct Neo4j driver access
- thread_manager: Conversation thread persistence
- queries: Parametrized Cypher query library
- graph_statistics: Graph node/relationship counts
- context_statistics: Context window token/overflow tracking
"""

from klabautermann.memory.context_statistics import (
    ContextWindowMetrics,
    GlobalContextMetrics,
    get_global_context_metrics,
    get_thread_context_metrics,
)
from klabautermann.memory.graph_statistics import (
    GraphStatistics,
    get_graph_statistics,
    get_node_counts_by_type,
    get_relationship_counts_by_type,
)
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.queries import CypherQueries, QueryBuilder, QueryResult
from klabautermann.memory.thread_manager import ThreadManager


__all__ = [
    # Clients
    "CypherQueries",
    "GraphitiClient",
    "Neo4jClient",
    "QueryBuilder",
    "QueryResult",
    "ThreadManager",
    # Graph Statistics
    "GraphStatistics",
    "get_graph_statistics",
    "get_node_counts_by_type",
    "get_relationship_counts_by_type",
    # Context Statistics
    "ContextWindowMetrics",
    "GlobalContextMetrics",
    "get_global_context_metrics",
    "get_thread_context_metrics",
]
