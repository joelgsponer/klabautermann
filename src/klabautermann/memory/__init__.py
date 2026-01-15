"""
Memory module - The Locker (knowledge graph interface).

Contains:
- graphiti_client: Wrapper around Graphiti library
- neo4j_client: Direct Neo4j driver access
- thread_manager: Conversation thread persistence
- queries: Parametrized Cypher query library
"""

from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.queries import CypherQueries, QueryBuilder, QueryResult
from klabautermann.memory.thread_manager import ThreadManager


__all__ = [
    "CypherQueries",
    "GraphitiClient",
    "Neo4jClient",
    "QueryBuilder",
    "QueryResult",
    "ThreadManager",
]
