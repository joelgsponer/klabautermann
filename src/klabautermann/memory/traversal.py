"""
Optimized relationship traversal utilities for Klabautermann.

Provides efficient graph traversal patterns with:
- Traversal hints for the Neo4j query planner
- Relationship index utilization
- Performance benchmarking and statistics
- Common traversal patterns as reusable functions

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.ontology import NodeLabel, RelationType


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Traversal Configuration
# =============================================================================


class TraversalDirection(str, Enum):
    """Direction for relationship traversal."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass
class TraversalConfig:
    """Configuration for a traversal operation."""

    max_depth: int = 3
    direction: TraversalDirection = TraversalDirection.BOTH
    relationship_types: list[RelationType] | None = None
    include_expired: bool = False
    limit: int = 100
    use_index_hints: bool = True


# =============================================================================
# Performance Statistics
# =============================================================================


@dataclass
class TraversalStats:
    """Statistics from a traversal operation."""

    query_time_ms: float
    nodes_visited: int
    relationships_traversed: int
    paths_found: int
    depth_reached: int
    used_index: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_time_ms": round(self.query_time_ms, 2),
            "nodes_visited": self.nodes_visited,
            "relationships_traversed": self.relationships_traversed,
            "paths_found": self.paths_found,
            "depth_reached": self.depth_reached,
            "used_index": self.used_index,
        }


@dataclass
class TraversalResult:
    """Result of a traversal operation."""

    nodes: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    paths: list[list[dict[str, Any]]]
    stats: TraversalStats

    @property
    def is_empty(self) -> bool:
        """Check if traversal found nothing."""
        return len(self.nodes) == 0


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""

    operation: str
    iterations: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    times_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "iterations": self.iterations,
            "total_time_ms": round(self.total_time_ms, 2),
            "avg_time_ms": round(self.avg_time_ms, 2),
            "min_time_ms": round(self.min_time_ms, 2),
            "max_time_ms": round(self.max_time_ms, 2),
        }


# =============================================================================
# Index Hints
# =============================================================================


# Map of relationship types to their temporal indexes
RELATIONSHIP_INDEXES: dict[RelationType, str] = {
    RelationType.WORKS_AT: "works_at_temporal",
    RelationType.LOCATED_IN: "located_in_temporal",
    RelationType.SPOUSE_OF: "spouse_temporal",
    RelationType.FRIEND_OF: "friend_temporal",
    RelationType.PRACTICES: "practices_temporal",
}

# Map of node labels to their search indexes
NODE_SEARCH_INDEXES: dict[NodeLabel, str] = {
    NodeLabel.PERSON: "person_search",
    NodeLabel.ORGANIZATION: "org_search",
    NodeLabel.NOTE: "note_search",
    NodeLabel.PROJECT: "project_search",
    NodeLabel.EMAIL: "email_search",
    NodeLabel.CALENDAR_EVENT: "calendarevent_search",
    NodeLabel.COMMUNITY: "community_search",
}


def get_index_hint(rel_type: RelationType) -> str | None:
    """Get the index hint for a relationship type."""
    return RELATIONSHIP_INDEXES.get(rel_type)


def get_search_index(label: NodeLabel) -> str | None:
    """Get the fulltext search index for a node label."""
    return NODE_SEARCH_INDEXES.get(label)


# =============================================================================
# Traversal Functions
# =============================================================================


async def traverse_from_node(
    client: Neo4jClient,
    start_uuid: str,
    start_label: NodeLabel,
    config: TraversalConfig | None = None,
    trace_id: str | None = None,
) -> TraversalResult:
    """
    Traverse relationships from a starting node.

    Uses optimized queries with index hints and temporal filtering.

    Args:
        client: Connected Neo4j client.
        start_uuid: UUID of the starting node.
        start_label: Label of the starting node.
        config: Traversal configuration.
        trace_id: Optional trace ID for logging.

    Returns:
        TraversalResult with nodes, relationships, paths, and stats.
    """
    config = config or TraversalConfig()
    start_time = time.time()

    # Build relationship pattern
    rel_pattern = _build_relationship_pattern(config)

    # Build temporal filter
    temporal_filter = "" if config.include_expired else "AND (r.expired_at IS NULL)"

    # Build direction pattern
    if config.direction == TraversalDirection.OUTGOING:
        direction_pattern = f"(start)-[{rel_pattern}]->(related)"
    elif config.direction == TraversalDirection.INCOMING:
        direction_pattern = f"(start)<-[{rel_pattern}]-(related)"
    else:
        direction_pattern = f"(start)-[{rel_pattern}]-(related)"

    query = f"""
    MATCH (start:{start_label.value} {{uuid: $start_uuid}})
    MATCH path = {direction_pattern}
    WHERE length(path) <= $max_depth
    {temporal_filter}
    WITH DISTINCT related, path,
         [rel in relationships(path) | type(rel)] as rel_types
    RETURN related as node,
           properties(related) as props,
           labels(related) as labels,
           rel_types,
           length(path) as depth
    ORDER BY depth
    LIMIT $limit
    """

    params = {
        "start_uuid": start_uuid,
        "max_depth": config.max_depth,
        "limit": config.limit,
    }

    logger.debug(
        f"[WHISPER] Traversing from {start_label.value} {start_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "traversal"},
    )

    results = await client.execute_query(query, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    # Process results
    nodes = []
    relationships = []
    max_depth = 0

    for record in results:
        nodes.append(
            {
                "uuid": record["props"].get("uuid"),
                "labels": record["labels"],
                "properties": record["props"],
                "depth": record["depth"],
            }
        )
        relationships.extend(record["rel_types"])
        max_depth = max(max_depth, record["depth"])

    stats = TraversalStats(
        query_time_ms=query_time,
        nodes_visited=len(nodes),
        relationships_traversed=len(relationships),
        paths_found=len(results),
        depth_reached=max_depth,
    )

    logger.debug(
        f"[WHISPER] Traversal complete: {stats.nodes_visited} nodes, {stats.query_time_ms:.1f}ms",
        extra={"trace_id": trace_id, "agent_name": "traversal"},
    )

    return TraversalResult(
        nodes=nodes,
        relationships=[{"type": rt} for rt in set(relationships)],
        paths=[],  # Full paths not returned for efficiency
        stats=stats,
    )


async def find_shortest_path(
    client: Neo4jClient,
    from_uuid: str,
    to_uuid: str,
    max_depth: int = 6,
    include_expired: bool = False,
    trace_id: str | None = None,
) -> TraversalResult:
    """
    Find the shortest path between two nodes.

    Args:
        client: Connected Neo4j client.
        from_uuid: UUID of the source node.
        to_uuid: UUID of the target node.
        max_depth: Maximum path length.
        include_expired: Whether to include expired relationships.
        trace_id: Optional trace ID for logging.

    Returns:
        TraversalResult with the path if found.
    """
    start_time = time.time()

    temporal_filter = (
        ""
        if include_expired
        else """
        WHERE ALL(r IN relationships(path) WHERE r.expired_at IS NULL)
    """
    )

    query = f"""
    MATCH (source {{uuid: $from_uuid}}), (target {{uuid: $to_uuid}})
    MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
    {temporal_filter}
    WITH path,
         [node in nodes(path) | {{
             uuid: node.uuid,
             labels: labels(node),
             name: node.name
         }}] as path_nodes,
         [rel in relationships(path) | {{
             type: type(rel),
             properties: properties(rel)
         }}] as path_rels
    RETURN path_nodes, path_rels, length(path) as path_length
    LIMIT 1
    """

    params = {"from_uuid": from_uuid, "to_uuid": to_uuid}

    logger.debug(
        f"[WHISPER] Finding path from {from_uuid[:8]}... to {to_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "traversal"},
    )

    results = await client.execute_query(query, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    if not results:
        return TraversalResult(
            nodes=[],
            relationships=[],
            paths=[],
            stats=TraversalStats(
                query_time_ms=query_time,
                nodes_visited=0,
                relationships_traversed=0,
                paths_found=0,
                depth_reached=0,
            ),
        )

    record = results[0]
    path_nodes = record["path_nodes"]
    path_rels = record["path_rels"]
    path_length = record["path_length"]

    stats = TraversalStats(
        query_time_ms=query_time,
        nodes_visited=len(path_nodes),
        relationships_traversed=len(path_rels),
        paths_found=1,
        depth_reached=path_length,
    )

    return TraversalResult(
        nodes=path_nodes,
        relationships=path_rels,
        paths=[path_nodes],
        stats=stats,
    )


async def traverse_dependency_chain(
    client: Neo4jClient,
    task_uuid: str,
    direction: TraversalDirection = TraversalDirection.INCOMING,
    max_depth: int = 5,
    trace_id: str | None = None,
) -> TraversalResult:
    """
    Traverse task dependency chain (BLOCKS relationships).

    Args:
        client: Connected Neo4j client.
        task_uuid: UUID of the target task.
        direction: INCOMING for blockers, OUTGOING for dependents.
        max_depth: Maximum chain depth.
        trace_id: Optional trace ID for logging.

    Returns:
        TraversalResult with the dependency chain.
    """
    start_time = time.time()

    if direction == TraversalDirection.INCOMING:
        pattern = "(t:Task)-[:BLOCKS*1..{max_depth}]->(target:Task {{uuid: $task_uuid}})"
    else:
        pattern = "(target:Task {{uuid: $task_uuid}})-[:BLOCKS*1..{max_depth}]->(t:Task)"

    query = f"""
    MATCH path = {pattern.format(max_depth=max_depth)}
    WITH t, path, length(path) as depth
    RETURN t.uuid as uuid,
           t.name as name,
           t.status as status,
           t.priority as priority,
           depth
    ORDER BY depth
    """

    params = {"task_uuid": task_uuid}

    results = await client.execute_query(query, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    nodes = []
    max_depth_found = 0

    for record in results:
        nodes.append(
            {
                "uuid": record["uuid"],
                "name": record["name"],
                "status": record["status"],
                "priority": record["priority"],
                "depth": record["depth"],
            }
        )
        max_depth_found = max(max_depth_found, record["depth"])

    stats = TraversalStats(
        query_time_ms=query_time,
        nodes_visited=len(nodes),
        relationships_traversed=len(nodes),  # One BLOCKS per node
        paths_found=len(nodes),
        depth_reached=max_depth_found,
    )

    return TraversalResult(
        nodes=nodes,
        relationships=[{"type": "BLOCKS"} for _ in nodes],
        paths=[],
        stats=stats,
    )


async def traverse_reporting_chain(
    client: Neo4jClient,
    person_uuid: str | None = None,
    person_name: str | None = None,
    direction: TraversalDirection = TraversalDirection.OUTGOING,
    max_depth: int = 5,
    include_expired: bool = False,
    trace_id: str | None = None,
) -> TraversalResult:
    """
    Traverse REPORTS_TO management chain for a person.

    Args:
        client: Connected Neo4j client.
        person_uuid: UUID of the starting person (optional).
        person_name: Name of the starting person (optional, used if uuid not provided).
        direction: OUTGOING for managers above, INCOMING for reports below.
        max_depth: Maximum chain depth to traverse.
        include_expired: Whether to include expired relationships.
        trace_id: Optional trace ID for logging.

    Returns:
        TraversalResult with the reporting hierarchy.

    Issue: #19 - [AGT-P-013] Add structural traversal queries (REPORTS_TO chains)
    """
    start_time = time.time()

    if not person_uuid and not person_name:
        logger.warning(
            "[SWELL] traverse_reporting_chain requires person_uuid or person_name",
            extra={"trace_id": trace_id},
        )
        return TraversalResult(
            nodes=[],
            relationships=[],
            paths=[],
            stats=TraversalStats(
                query_time_ms=0,
                nodes_visited=0,
                relationships_traversed=0,
                paths_found=0,
                depth_reached=0,
            ),
        )

    # Build the match condition
    if person_uuid:
        start_match = "MATCH (start:Person {uuid: $person_uuid})"
        params: dict[str, Any] = {"person_uuid": person_uuid}
    else:
        start_match = (
            "MATCH (start:Person) WHERE toLower(start.name) CONTAINS toLower($person_name)"
        )
        params = {"person_name": person_name}

    # Build temporal filter
    temporal_filter = "" if include_expired else "AND ALL(r IN rels WHERE r.expired_at IS NULL)"

    # Build direction-specific pattern
    if direction == TraversalDirection.OUTGOING:
        # Person's managers (upward chain)
        pattern = f"(start)-[rels:REPORTS_TO*1..{max_depth}]->(manager:Person)"
        return_fields = """
            manager.uuid as uuid,
            manager.name as name,
            length(rels) as depth,
            [r IN rels | r.title] as titles
        """
        order_by = "depth"
    else:
        # Person's direct reports (downward chain)
        pattern = f"(report:Person)-[rels:REPORTS_TO*1..{max_depth}]->(start)"
        return_fields = """
            report.uuid as uuid,
            report.name as name,
            length(rels) as depth,
            [r IN rels | r.title] as titles
        """
        order_by = "depth"

    query = f"""
    {start_match}
    MATCH path = {pattern}
    WHERE start <> {'manager' if direction == TraversalDirection.OUTGOING else 'report'}
    {temporal_filter}
    RETURN DISTINCT
        {return_fields}
    ORDER BY {order_by}
    """

    results = await client.execute_query(query, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    nodes = []
    max_depth_found = 0

    for record in results:
        depth = record["depth"]
        nodes.append(
            {
                "uuid": record["uuid"],
                "name": record["name"],
                "depth": depth,
                "titles": record.get("titles", []),
                "role": "manager" if direction == TraversalDirection.OUTGOING else "report",
            }
        )
        max_depth_found = max(max_depth_found, depth)

    stats = TraversalStats(
        query_time_ms=query_time,
        nodes_visited=len(nodes) + 1,  # +1 for start node
        relationships_traversed=sum(n["depth"] for n in nodes),
        paths_found=len(nodes),
        depth_reached=max_depth_found,
    )

    logger.debug(
        f"[WHISPER] Reporting chain traversal: found {len(nodes)} "
        f"{'managers' if direction == TraversalDirection.OUTGOING else 'reports'}",
        extra={"trace_id": trace_id},
    )

    return TraversalResult(
        nodes=nodes,
        relationships=[{"type": "REPORTS_TO"} for _ in nodes],
        paths=[],
        stats=stats,
    )


async def find_connected_entities(
    client: Neo4jClient,
    entity_uuid: str,
    hops: int = 2,
    include_expired: bool = False,
    trace_id: str | None = None,
) -> TraversalResult:
    """
    Find all entities connected within N hops.

    Args:
        client: Connected Neo4j client.
        entity_uuid: UUID of the starting entity.
        hops: Number of hops to traverse (1-3 recommended).
        include_expired: Whether to include expired relationships.
        trace_id: Optional trace ID for logging.

    Returns:
        TraversalResult with connected entities grouped by type.
    """
    start_time = time.time()
    hops = min(hops, 3)  # Cap at 3 for performance

    temporal_clause = (
        ""
        if include_expired
        else "WHERE ALL(r IN rels WHERE r.expired_at IS NULL OR r.expired_at > timestamp())"
    )

    query = f"""
    MATCH (start {{uuid: $entity_uuid}})-[rels*1..{hops}]-(related)
    {temporal_clause}
    WITH DISTINCT related, labels(related)[0] as label, length(rels) as distance
    RETURN label as type,
           related.uuid as uuid,
           related.name as name,
           distance
    ORDER BY distance, type, name
    LIMIT 100
    """

    params = {"entity_uuid": entity_uuid}

    results = await client.execute_query(query, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    nodes = []
    max_distance = 0

    for record in results:
        nodes.append(
            {
                "type": record["type"],
                "uuid": record["uuid"],
                "name": record["name"],
                "distance": record["distance"],
            }
        )
        max_distance = max(max_distance, record["distance"])

    stats = TraversalStats(
        query_time_ms=query_time,
        nodes_visited=len(nodes),
        relationships_traversed=sum(n["distance"] for n in nodes),
        paths_found=len(nodes),
        depth_reached=max_distance,
    )

    return TraversalResult(
        nodes=nodes,
        relationships=[],
        paths=[],
        stats=stats,
    )


# =============================================================================
# Benchmarking
# =============================================================================


async def benchmark_traversal(
    client: Neo4jClient,
    operation_name: str,
    query: str,
    params: dict[str, Any],
    iterations: int = 10,
    trace_id: str | None = None,
) -> BenchmarkResult:
    """
    Benchmark a traversal query.

    Args:
        client: Connected Neo4j client.
        operation_name: Name for this benchmark.
        query: Cypher query to benchmark.
        params: Query parameters.
        iterations: Number of iterations to run.
        trace_id: Optional trace ID for logging.

    Returns:
        BenchmarkResult with timing statistics.
    """
    times: list[float] = []

    logger.info(
        f"[CHART] Benchmarking {operation_name} ({iterations} iterations)...",
        extra={"trace_id": trace_id, "agent_name": "traversal"},
    )

    for i in range(iterations):
        start = time.time()
        await client.execute_query(query, params, trace_id=trace_id)
        elapsed = (time.time() - start) * 1000
        times.append(elapsed)

        # Brief pause between iterations
        if i < iterations - 1:
            await _async_sleep(0.01)

    result = BenchmarkResult(
        operation=operation_name,
        iterations=iterations,
        total_time_ms=sum(times),
        avg_time_ms=sum(times) / len(times),
        min_time_ms=min(times),
        max_time_ms=max(times),
        times_ms=times,
    )

    logger.info(
        f"[BEACON] Benchmark complete: avg={result.avg_time_ms:.2f}ms, "
        f"min={result.min_time_ms:.2f}ms, max={result.max_time_ms:.2f}ms",
        extra={"trace_id": trace_id, "agent_name": "traversal"},
    )

    return result


# =============================================================================
# Helper Functions
# =============================================================================


def _build_relationship_pattern(config: TraversalConfig) -> str:
    """Build the relationship pattern for a traversal query."""
    if config.relationship_types:
        types = "|".join(rt.value for rt in config.relationship_types)
        return f"r:{types}*1..{config.max_depth}"
    return f"r*1..{config.max_depth}"


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper."""
    import asyncio

    await asyncio.sleep(seconds)


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "NODE_SEARCH_INDEXES",
    "RELATIONSHIP_INDEXES",
    "BenchmarkResult",
    "TraversalConfig",
    "TraversalDirection",
    "TraversalResult",
    "TraversalStats",
    "benchmark_traversal",
    "find_connected_entities",
    "find_shortest_path",
    "get_index_hint",
    "get_search_index",
    "traverse_dependency_chain",
    "traverse_from_node",
]
