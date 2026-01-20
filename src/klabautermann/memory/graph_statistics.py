"""
Graph statistics collection for Klabautermann.

Provides comprehensive statistics about the knowledge graph including
node counts by type, relationship counts, and total graph size.

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NodeCountByType:
    """Node count for a specific node type."""

    label: str
    count: int


@dataclass
class RelationshipCountByType:
    """Relationship count for a specific relationship type."""

    relationship_type: str
    count: int


@dataclass
class GraphStatistics:
    """Complete graph statistics."""

    # Node statistics
    total_nodes: int
    nodes_by_type: list[NodeCountByType]

    # Relationship statistics
    total_relationships: int
    relationships_by_type: list[RelationshipCountByType]

    # Metadata
    timestamp: datetime
    database_name: str | None = None


# =============================================================================
# Statistics Functions
# =============================================================================


async def get_node_counts_by_type(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> list[NodeCountByType]:
    """
    Get count of nodes grouped by label.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        List of NodeCountByType for each label
    """
    logger.debug(
        "[WHISPER] Counting nodes by type",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    query = """
    CALL db.labels() YIELD label
    CALL {
        WITH label
        MATCH (n)
        WHERE label IN labels(n)
        RETURN count(n) AS count
    }
    RETURN label, count
    ORDER BY count DESC
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    counts = [NodeCountByType(label=row["label"], count=int(row["count"])) for row in result]

    logger.debug(
        f"[WHISPER] Found {len(counts)} node types",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    return counts


async def get_relationship_counts_by_type(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> list[RelationshipCountByType]:
    """
    Get count of relationships grouped by type.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        List of RelationshipCountByType for each relationship type
    """
    logger.debug(
        "[WHISPER] Counting relationships by type",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    query = """
    CALL db.relationshipTypes() YIELD relationshipType
    CALL {
        WITH relationshipType
        MATCH ()-[r]->()
        WHERE type(r) = relationshipType
        RETURN count(r) AS count
    }
    RETURN relationshipType, count
    ORDER BY count DESC
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    counts = [
        RelationshipCountByType(relationship_type=row["relationshipType"], count=int(row["count"]))
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Found {len(counts)} relationship types",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    return counts


async def get_total_node_count(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> int:
    """
    Get total number of nodes in the graph.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        Total node count
    """
    query = "MATCH (n) RETURN count(n) AS total"
    result = await neo4j.execute_query(query, {}, trace_id=trace_id)
    return int(result[0]["total"]) if result else 0


async def get_total_relationship_count(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> int:
    """
    Get total number of relationships in the graph.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        Total relationship count
    """
    query = "MATCH ()-[r]->() RETURN count(r) AS total"
    result = await neo4j.execute_query(query, {}, trace_id=trace_id)
    return int(result[0]["total"]) if result else 0


async def get_graph_statistics(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> GraphStatistics:
    """
    Get complete graph statistics.

    Aggregates node counts, relationship counts, and totals into
    a comprehensive statistics report.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        GraphStatistics with all metrics
    """
    logger.info(
        "[CHART] Computing graph statistics",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    # Gather all statistics
    nodes_by_type = await get_node_counts_by_type(neo4j, trace_id)
    relationships_by_type = await get_relationship_counts_by_type(neo4j, trace_id)
    total_nodes = await get_total_node_count(neo4j, trace_id)
    total_relationships = await get_total_relationship_count(neo4j, trace_id)

    stats = GraphStatistics(
        total_nodes=total_nodes,
        nodes_by_type=nodes_by_type,
        total_relationships=total_relationships,
        relationships_by_type=relationships_by_type,
        timestamp=datetime.now(),
    )

    logger.info(
        f"[CHART] Graph statistics: {total_nodes} nodes, {total_relationships} relationships",
        extra={"trace_id": trace_id, "agent_name": "graph_stats"},
    )

    return stats


def statistics_to_dict(stats: GraphStatistics) -> dict:
    """
    Convert GraphStatistics to a serializable dictionary.

    Args:
        stats: GraphStatistics instance

    Returns:
        Dictionary representation of statistics
    """
    return {
        "total_nodes": stats.total_nodes,
        "total_relationships": stats.total_relationships,
        "nodes_by_type": {node.label: node.count for node in stats.nodes_by_type},
        "relationships_by_type": {
            rel.relationship_type: rel.count for rel in stats.relationships_by_type
        },
        "timestamp": stats.timestamp.isoformat(),
        "database_name": stats.database_name,
    }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "GraphStatistics",
    "NodeCountByType",
    "RelationshipCountByType",
    "get_graph_statistics",
    "get_node_counts_by_type",
    "get_relationship_counts_by_type",
    "get_total_node_count",
    "get_total_relationship_count",
    "statistics_to_dict",
]
