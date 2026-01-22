"""
Cartographer agent for Klabautermann.

Community detection and Knowledge Island management agent. The Cartographer
identifies clusters of highly related nodes (Knowledge Islands) representing
major life themes (Work, Family, Hobbies). This enables multi-level retrieval
where the Researcher can query at Macro (Island), Meso (Project), or Micro
(Entity) level.

Uses Neo4j Graph Data Science (GDS) for Louvain community detection.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 4
Issues: #69, #70, #71, #72, #73
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Configuration
# =============================================================================


class CommunityTheme(str, Enum):
    """Themes for Knowledge Islands (Communities)."""

    PROFESSIONAL = "professional"
    FAMILY = "family"
    SOCIAL = "social"
    HOBBIES = "hobbies"
    HEALTH = "health"
    FINANCE = "finance"
    UNKNOWN = "unknown"


@dataclass
class CartographerConfig:
    """Configuration for Cartographer agent."""

    # Graph projection name
    projection_name: str = "klabautermann-community"

    # Minimum community size to keep
    min_community_size: int = 3

    # Node labels to include in projection
    node_labels: list[str] = field(
        default_factory=lambda: ["Person", "Organization", "Project", "Hobby", "Note"]
    )

    # Relationship types to include (with UNDIRECTED orientation)
    relationship_types: list[str] = field(
        default_factory=lambda: [
            "WORKS_AT",
            "KNOWS",
            "FRIEND_OF",
            "FAMILY_OF",
            "CONTRIBUTES_TO",
            "MENTIONED_IN",
            "PRACTICES",
        ]
    )

    # Schedule (for future use)
    schedule_cron: str = "0 0 * * 0"  # Sunday midnight

    # Query limits
    default_query_limit: int = 100


@dataclass
class Community:
    """
    A Knowledge Island - a cluster of highly related nodes.

    Communities are detected via Louvain algorithm and represent
    major life themes like Work, Family, Hobbies, etc.
    """

    uuid: str
    name: str
    theme: CommunityTheme
    summary: str | None = None
    node_count: int = 0
    detected_at: int = 0  # Unix timestamp (milliseconds)
    created_at: int = 0  # Unix timestamp (milliseconds)
    last_updated: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "theme": self.theme.value,
            "summary": self.summary,
            "node_count": self.node_count,
            "detected_at": self.detected_at,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }


@dataclass
class CommunityMember:
    """A member node of a Community."""

    uuid: str
    labels: list[str]
    name: str | None = None
    weight: float = 1.0
    detected_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "uuid": self.uuid,
            "labels": self.labels,
            "name": self.name,
            "weight": self.weight,
            "detected_at": self.detected_at,
        }


@dataclass
class DetectionResult:
    """Result of community detection run."""

    communities_created: int = 0
    communities_updated: int = 0
    total_members_assigned: int = 0
    execution_time_ms: int = 0
    gds_available: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "communities_created": self.communities_created,
            "communities_updated": self.communities_updated,
            "total_members_assigned": self.total_members_assigned,
            "execution_time_ms": self.execution_time_ms,
            "gds_available": self.gds_available,
            "errors": self.errors,
        }


# =============================================================================
# Theme Classification
# =============================================================================

# Maps node labels to likely themes
THEME_LABEL_WEIGHTS: dict[str, dict[CommunityTheme, float]] = {
    "Organization": {CommunityTheme.PROFESSIONAL: 1.0},
    "Project": {CommunityTheme.PROFESSIONAL: 0.8},
    "Task": {CommunityTheme.PROFESSIONAL: 0.7},
    "Event": {CommunityTheme.PROFESSIONAL: 0.3, CommunityTheme.SOCIAL: 0.3},
    "Person": {
        CommunityTheme.FAMILY: 0.3,
        CommunityTheme.SOCIAL: 0.3,
        CommunityTheme.PROFESSIONAL: 0.3,
    },
    "Hobby": {CommunityTheme.HOBBIES: 1.0},
    "HealthMetric": {CommunityTheme.HEALTH: 1.0},
    "Routine": {CommunityTheme.HEALTH: 0.5},
    "Resource": {CommunityTheme.FINANCE: 0.5},
    "Note": {CommunityTheme.UNKNOWN: 0.5},
}


def classify_theme(labels: list[str]) -> CommunityTheme:
    """
    Classify community theme based on member node labels.

    Scores each theme based on how many node labels map to it,
    weighted by the strength of association.

    Args:
        labels: List of node labels in the community.

    Returns:
        The most likely theme for this community.
    """
    theme_scores: dict[CommunityTheme, float] = dict.fromkeys(CommunityTheme, 0.0)

    for label in labels:
        if label in THEME_LABEL_WEIGHTS:
            for theme, weight in THEME_LABEL_WEIGHTS[label].items():
                theme_scores[theme] += weight

    # Find the theme with the highest score
    best_theme = CommunityTheme.UNKNOWN
    best_score = 0.0

    for theme, score in theme_scores.items():
        if theme != CommunityTheme.UNKNOWN and score > best_score:
            best_theme = theme
            best_score = score

    return best_theme


# =============================================================================
# Cartographer Agent
# =============================================================================


class Cartographer(BaseAgent):
    """
    Community detection and Knowledge Island management agent.

    The Cartographer uses Neo4j GDS (Graph Data Science) to run the Louvain
    algorithm for community detection. Detected communities become Knowledge
    Islands - clusters of related nodes that enable macro-level search.

    Process:
        1. Project in-memory graph for GDS algorithms
        2. Run Louvain community detection
        3. Classify each community's theme
        4. Create/update Community nodes
        5. Link members via PART_OF_ISLAND relationships
        6. Clean up graph projection
    """

    # Theme mapping for the Cartographer
    THEME_LABEL_WEIGHTS: ClassVar[dict[str, dict[CommunityTheme, float]]] = THEME_LABEL_WEIGHTS

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        config: CartographerConfig | None = None,
    ) -> None:
        """
        Initialize Cartographer.

        Args:
            neo4j_client: Connected Neo4j client for graph operations.
            config: Optional configuration for community detection.
        """
        super().__init__(name="cartographer")
        self.neo4j = neo4j_client
        self.cartographer_config = config or CartographerConfig()

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process an incoming message.

        Cartographer responds to community detection and query commands.

        Args:
            msg: The incoming agent message.

        Returns:
            Response message with detection results or query data.
        """
        trace_id = msg.trace_id
        payload = msg.payload or {}

        operation = payload.get("operation", "detect_communities")

        logger.info(
            f"[CHART] Cartographer processing {operation}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if operation == "detect_communities":
            result = await self.detect_communities(trace_id=trace_id)
            result_payload = result.to_dict()
        elif operation == "get_communities":
            communities = await self.get_communities(trace_id=trace_id)
            result_payload = {
                "communities": [c.to_dict() for c in communities],
                "count": len(communities),
            }
        elif operation == "get_community_members":
            community_uuid = payload.get("community_uuid", "")
            members = await self.get_community_members(community_uuid, trace_id=trace_id)
            result_payload = {
                "members": [m.to_dict() for m in members],
                "count": len(members),
            }
        elif operation == "check_gds":
            available = await self._check_gds_available(trace_id=trace_id)
            result_payload = {"gds_available": available}
        else:
            result_payload = {"error": f"Unknown operation: {operation}"}

        return AgentMessage(
            source_agent=self.name,
            target_agent=msg.source_agent,
            intent="cartographer_result",
            payload=result_payload,
            trace_id=trace_id,
        )

    # =========================================================================
    # Main Operations
    # =========================================================================

    async def detect_communities(
        self,
        trace_id: str | None = None,
    ) -> DetectionResult:
        """
        Run full community detection workflow.

        This is the main entry point that:
            1. Projects the graph for GDS
            2. Runs Louvain algorithm
            3. Creates/updates Community nodes
            4. Links members via PART_OF_ISLAND
            5. Cleans up projection

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            DetectionResult with statistics and any errors.
        """
        start_time = time.time()
        result = DetectionResult()

        # Check GDS availability
        gds_available = await self._check_gds_available(trace_id=trace_id)
        result.gds_available = gds_available

        if not gds_available:
            result.errors.append("Neo4j GDS not available")
            logger.warning(
                "[STORM] Neo4j GDS not available, skipping community detection",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            result.execution_time_ms = int((time.time() - start_time) * 1000)
            return result

        try:
            # Step 1: Project graph
            await self._project_graph(trace_id=trace_id)

            # Step 2: Run Louvain
            communities = await self._run_louvain(trace_id=trace_id)

            # Step 3: Process each community
            for _community_id, member_uuids in communities.items():
                # Get member labels for theme classification
                labels = await self._get_member_labels(member_uuids, trace_id=trace_id)
                theme = classify_theme(labels)

                # Check for existing community with same theme and significant overlap
                existing = await self._find_existing_community(
                    theme, member_uuids, trace_id=trace_id
                )

                if existing:
                    await self._update_community(existing, member_uuids, trace_id=trace_id)
                    result.communities_updated += 1
                else:
                    await self._create_community(theme, member_uuids, trace_id=trace_id)
                    result.communities_created += 1

                result.total_members_assigned += len(member_uuids)

            logger.info(
                f"[BEACON] Community detection complete: "
                f"{result.communities_created} created, "
                f"{result.communities_updated} updated",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        except Exception as e:
            error_msg = f"Community detection failed: {e}"
            result.errors.append(error_msg)
            logger.error(
                f"[STORM] {error_msg}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
        finally:
            # Always clean up projection
            await self._drop_projection(trace_id=trace_id)

        result.execution_time_ms = int((time.time() - start_time) * 1000)
        return result

    # =========================================================================
    # GDS Operations
    # =========================================================================

    async def _check_gds_available(
        self,
        trace_id: str | None = None,
    ) -> bool:
        """
        Check if Neo4j GDS is available.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            True if GDS is available, False otherwise.
        """
        query = """
        RETURN gds.version() AS version
        """
        try:
            result = await self.neo4j.execute_query(query, {}, trace_id=trace_id)
            version: str = result[0].get("version", "") if result else ""
            if version:
                logger.debug(
                    f"[CHART] GDS version {version} available",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                return True
            return False
        except Exception:
            return False

    async def _project_graph(
        self,
        trace_id: str | None = None,
    ) -> None:
        """
        Create in-memory graph projection for GDS algorithms.

        Projects specified node labels and relationship types as an
        undirected graph for community detection.

        Args:
            trace_id: Optional trace ID for logging.
        """
        config = self.cartographer_config

        # Build relationship config for undirected projection
        rel_config = {
            rel_type: {"orientation": "UNDIRECTED"} for rel_type in config.relationship_types
        }

        query = """
        CALL gds.graph.project(
            $projection_name,
            $node_labels,
            $relationship_config
        )
        """

        await self.neo4j.execute_query(
            query,
            {
                "projection_name": config.projection_name,
                "node_labels": config.node_labels,
                "relationship_config": rel_config,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[CHART] Created graph projection '{config.projection_name}'",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    async def _drop_projection(
        self,
        trace_id: str | None = None,
    ) -> None:
        """
        Drop the in-memory graph projection.

        Args:
            trace_id: Optional trace ID for logging.
        """
        config = self.cartographer_config

        query = """
        CALL gds.graph.drop($projection_name, false)
        """

        try:
            await self.neo4j.execute_query(
                query,
                {"projection_name": config.projection_name},
                trace_id=trace_id,
            )
            logger.debug(
                f"[CHART] Dropped graph projection '{config.projection_name}'",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
        except Exception:
            # Projection may not exist, that's OK
            pass

    async def _run_louvain(
        self,
        trace_id: str | None = None,
    ) -> dict[int, list[str]]:
        """
        Run Louvain community detection algorithm.

        Returns communities as a mapping of community ID to member UUIDs.
        Only returns communities meeting the minimum size threshold.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Dictionary mapping community IDs to lists of member UUIDs.
        """
        config = self.cartographer_config

        query = """
        CALL gds.louvain.stream($projection_name)
        YIELD nodeId, communityId
        WITH gds.util.asNode(nodeId) as node, communityId
        RETURN communityId, collect(node.uuid) as members
        """

        results = await self.neo4j.execute_query(
            query,
            {"projection_name": config.projection_name},
            trace_id=trace_id,
        )

        # Filter by minimum size
        communities: dict[int, list[str]] = {}
        for row in results:
            community_id: int = row["communityId"]
            members: list[str] = row["members"]
            if len(members) >= config.min_community_size:
                communities[community_id] = members

        logger.debug(
            f"[CHART] Louvain found {len(communities)} communities "
            f"(min size {config.min_community_size})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return communities

    # =========================================================================
    # Community Operations
    # =========================================================================

    async def _get_member_labels(
        self,
        member_uuids: list[str],
        trace_id: str | None = None,
    ) -> list[str]:
        """
        Get the node labels for a list of member UUIDs.

        Args:
            member_uuids: List of member node UUIDs.
            trace_id: Optional trace ID for logging.

        Returns:
            List of all labels found on member nodes.
        """
        query = """
        UNWIND $uuids as uuid
        MATCH (n {uuid: uuid})
        RETURN labels(n) as labels
        """

        results = await self.neo4j.execute_query(
            query,
            {"uuids": member_uuids},
            trace_id=trace_id,
        )

        # Flatten all labels
        all_labels: list[str] = []
        for row in results:
            labels: list[str] = row.get("labels", [])
            all_labels.extend(labels)

        return all_labels

    async def _find_existing_community(
        self,
        theme: CommunityTheme,
        member_uuids: list[str],
        trace_id: str | None = None,
    ) -> str | None:
        """
        Find an existing community with the same theme and significant overlap.

        Args:
            theme: The community theme.
            member_uuids: List of member UUIDs to check overlap.
            trace_id: Optional trace ID for logging.

        Returns:
            UUID of matching community, or None if not found.
        """
        query = """
        MATCH (c:Community {theme: $theme})
        OPTIONAL MATCH (n)-[:PART_OF_ISLAND]->(c)
        WHERE n.uuid IN $member_uuids
        WITH c, count(n) as overlap_count
        WHERE overlap_count >= $min_overlap
        RETURN c.uuid as uuid
        ORDER BY overlap_count DESC
        LIMIT 1
        """

        # Require at least 50% overlap for matching
        min_overlap = max(1, len(member_uuids) // 2)

        results = await self.neo4j.execute_query(
            query,
            {
                "theme": theme.value,
                "member_uuids": member_uuids,
                "min_overlap": min_overlap,
            },
            trace_id=trace_id,
        )

        if results:
            existing_uuid: str | None = results[0].get("uuid")
            return existing_uuid
        return None

    async def _create_community(
        self,
        theme: CommunityTheme,
        member_uuids: list[str],
        trace_id: str | None = None,
    ) -> str:
        """
        Create a new Community node and link members.

        Args:
            theme: The community theme.
            member_uuids: List of member node UUIDs.
            trace_id: Optional trace ID for logging.

        Returns:
            UUID of the created Community.
        """
        community_uuid = str(uuid.uuid4())
        community_name = f"{theme.value.title()} Island"
        now_ms = int(time.time() * 1000)

        query = """
        CREATE (c:Community {
            uuid: $uuid,
            name: $name,
            theme: $theme,
            node_count: $count,
            detected_at: $now_ms,
            created_at: $now_ms
        })
        WITH c
        UNWIND $members as member_uuid
        MATCH (n {uuid: member_uuid})
        CREATE (n)-[:PART_OF_ISLAND {weight: 1.0, detected_at: $now_ms}]->(c)
        RETURN c.uuid as uuid
        """

        await self.neo4j.execute_query(
            query,
            {
                "uuid": community_uuid,
                "name": community_name,
                "theme": theme.value,
                "count": len(member_uuids),
                "now_ms": now_ms,
                "members": member_uuids,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[CHART] Created community '{community_name}' " f"with {len(member_uuids)} members",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return community_uuid

    async def _update_community(
        self,
        community_uuid: str,
        member_uuids: list[str],
        trace_id: str | None = None,
    ) -> None:
        """
        Update an existing Community with new members.

        Removes old PART_OF_ISLAND relationships and creates new ones.

        Args:
            community_uuid: UUID of the community to update.
            member_uuids: List of new member UUIDs.
            trace_id: Optional trace ID for logging.
        """
        now_ms = int(time.time() * 1000)

        # Remove existing relationships
        remove_query = """
        MATCH (n)-[r:PART_OF_ISLAND]->(c:Community {uuid: $community_uuid})
        DELETE r
        """

        await self.neo4j.execute_query(
            remove_query,
            {"community_uuid": community_uuid},
            trace_id=trace_id,
        )

        # Create new relationships and update count
        update_query = """
        MATCH (c:Community {uuid: $community_uuid})
        SET c.node_count = $count, c.detected_at = $now_ms
        WITH c
        UNWIND $members as member_uuid
        MATCH (n {uuid: member_uuid})
        CREATE (n)-[:PART_OF_ISLAND {weight: 1.0, detected_at: $now_ms}]->(c)
        """

        await self.neo4j.execute_query(
            update_query,
            {
                "community_uuid": community_uuid,
                "count": len(member_uuids),
                "now_ms": now_ms,
                "members": member_uuids,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[CHART] Updated community {community_uuid} " f"with {len(member_uuids)} members",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def get_communities(
        self,
        theme: CommunityTheme | None = None,
        trace_id: str | None = None,
    ) -> list[Community]:
        """
        Get all communities, optionally filtered by theme.

        Args:
            theme: Optional theme to filter by.
            trace_id: Optional trace ID for logging.

        Returns:
            List of Community objects.
        """
        config = self.cartographer_config

        if theme:
            query = """
            MATCH (c:Community {theme: $theme})
            RETURN c.uuid as uuid, c.name as name, c.theme as theme,
                   c.summary as summary, c.node_count as node_count,
                   c.detected_at as detected_at, c.created_at as created_at,
                   c.last_updated as last_updated
            ORDER BY c.node_count DESC
            LIMIT $limit
            """
            params = {"theme": theme.value, "limit": config.default_query_limit}
        else:
            query = """
            MATCH (c:Community)
            RETURN c.uuid as uuid, c.name as name, c.theme as theme,
                   c.summary as summary, c.node_count as node_count,
                   c.detected_at as detected_at, c.created_at as created_at,
                   c.last_updated as last_updated
            ORDER BY c.node_count DESC
            LIMIT $limit
            """
            params = {"limit": config.default_query_limit}

        results = await self.neo4j.execute_query(query, params, trace_id=trace_id)

        return [
            Community(
                uuid=row["uuid"],
                name=row["name"],
                theme=CommunityTheme(row["theme"]),
                summary=row.get("summary"),
                node_count=row.get("node_count", 0),
                detected_at=row.get("detected_at", 0),
                created_at=row.get("created_at", 0),
                last_updated=row.get("last_updated"),
            )
            for row in results
        ]

    async def get_community_members(
        self,
        community_uuid: str,
        trace_id: str | None = None,
    ) -> list[CommunityMember]:
        """
        Get members of a specific community.

        Args:
            community_uuid: UUID of the community.
            trace_id: Optional trace ID for logging.

        Returns:
            List of CommunityMember objects.
        """
        config = self.cartographer_config

        query = """
        MATCH (n)-[r:PART_OF_ISLAND]->(c:Community {uuid: $community_uuid})
        RETURN n.uuid as uuid, labels(n) as labels, n.name as name,
               r.weight as weight, r.detected_at as detected_at
        LIMIT $limit
        """

        results = await self.neo4j.execute_query(
            query,
            {
                "community_uuid": community_uuid,
                "limit": config.default_query_limit,
            },
            trace_id=trace_id,
        )

        return [
            CommunityMember(
                uuid=row["uuid"],
                labels=row.get("labels", []),
                name=row.get("name"),
                weight=row.get("weight", 1.0),
                detected_at=row.get("detected_at", 0),
            )
            for row in results
        ]

    async def get_community_by_uuid(
        self,
        community_uuid: str,
        trace_id: str | None = None,
    ) -> Community | None:
        """
        Get a community by UUID.

        Args:
            community_uuid: UUID of the community.
            trace_id: Optional trace ID for logging.

        Returns:
            Community object if found, None otherwise.
        """
        query = """
        MATCH (c:Community {uuid: $uuid})
        RETURN c.uuid as uuid, c.name as name, c.theme as theme,
               c.summary as summary, c.node_count as node_count,
               c.detected_at as detected_at, c.created_at as created_at,
               c.last_updated as last_updated
        """

        results = await self.neo4j.execute_query(
            query,
            {"uuid": community_uuid},
            trace_id=trace_id,
        )

        if not results:
            return None

        row = results[0]
        return Community(
            uuid=row["uuid"],
            name=row["name"],
            theme=CommunityTheme(row["theme"]),
            summary=row.get("summary"),
            node_count=row.get("node_count", 0),
            detected_at=row.get("detected_at", 0),
            created_at=row.get("created_at", 0),
            last_updated=row.get("last_updated"),
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_community_statistics(
        self,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Get statistics about all communities.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Dictionary with community statistics.
        """
        query = """
        MATCH (c:Community)
        WITH count(c) as total_communities,
             avg(c.node_count) as avg_members,
             max(c.node_count) as max_members,
             min(c.node_count) as min_members
        RETURN total_communities, avg_members, max_members, min_members
        """

        results = await self.neo4j.execute_query(query, {}, trace_id=trace_id)

        if not results:
            return {
                "total_communities": 0,
                "avg_members": 0,
                "max_members": 0,
                "min_members": 0,
                "by_theme": {},
            }

        stats = results[0]

        # Get breakdown by theme
        theme_query = """
        MATCH (c:Community)
        RETURN c.theme as theme, count(c) as count
        ORDER BY count DESC
        """

        theme_results = await self.neo4j.execute_query(theme_query, {}, trace_id=trace_id)

        by_theme = {row["theme"]: row["count"] for row in theme_results}

        return {
            "total_communities": stats.get("total_communities", 0),
            "avg_members": round(stats.get("avg_members", 0) or 0, 1),
            "max_members": stats.get("max_members", 0),
            "min_members": stats.get("min_members", 0),
            "by_theme": by_theme,
        }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "Cartographer",
    "CartographerConfig",
    "Community",
    "CommunityMember",
    "CommunityTheme",
    "DetectionResult",
    "classify_theme",
]
