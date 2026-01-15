"""
Graphiti client wrapper for Klabautermann.

Provides temporal knowledge graph operations via the Graphiti library.
Handles entity extraction, episode ingestion, and semantic search.

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from klabautermann.core.exceptions import ExternalServiceError, GraphConnectionError
from klabautermann.core.logger import logger
from klabautermann.core.models import SearchResult


if TYPE_CHECKING:
    from graphiti_core import Graphiti


class GraphitiClient:
    """
    Wrapper around Graphiti temporal knowledge graph.

    Graphiti handles:
    - Entity extraction from natural language
    - Temporal relationship management
    - Semantic vector search
    - Graph traversal for context
    """

    def __init__(
        self,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        """
        Initialize Graphiti client.

        Args:
            neo4j_uri: Neo4j bolt URI. Defaults to NEO4J_URI env var.
            neo4j_user: Database username. Defaults to NEO4J_USERNAME env var.
            neo4j_password: Database password. Defaults to NEO4J_PASSWORD env var.
            openai_api_key: OpenAI API key for embeddings. Defaults to OPENAI_API_KEY env var.
        """
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USERNAME", "neo4j")
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD", "")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")

        self._client: Graphiti | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._client is not None

    async def connect(self) -> None:
        """Initialize Graphiti connection."""
        logger.info("[CHART] Connecting to Graphiti...", extra={"agent_name": "graphiti"})

        try:
            # Import here to avoid import errors if graphiti not installed
            from graphiti_core import Graphiti

            # Initialize Graphiti with Neo4j credentials
            self._client = Graphiti(
                self.neo4j_uri,
                self.neo4j_user,
                self.neo4j_password,
            )

            # Build indices and constraints if needed
            # Note: This may already be done by our init_database.py script
            try:
                await self._client.build_indices_and_constraints()
            except Exception as e:
                # Indices may already exist, which is fine
                logger.debug(f"[WHISPER] Index build note: {e}", extra={"agent_name": "graphiti"})

            self._connected = True
            logger.info("[BEACON] Graphiti connected", extra={"agent_name": "graphiti"})

        except ImportError:
            logger.error(
                "[STORM] graphiti-core not installed. Install with: pip install graphiti-core",
                extra={"agent_name": "graphiti"},
            )
            raise ExternalServiceError("graphiti", "graphiti-core package not installed") from None

        except Exception as e:
            logger.error(
                f"[SHIPWRECK] Graphiti connection failed: {e}",
                extra={"agent_name": "graphiti"},
            )
            raise GraphConnectionError(f"Failed to connect to Graphiti: {e}") from e

    async def disconnect(self) -> None:
        """Close Graphiti connection."""
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning(
                    f"[SWELL] Error closing Graphiti: {e}", extra={"agent_name": "graphiti"}
                )
            finally:
                self._client = None
                self._connected = False
                logger.info("[CHART] Graphiti disconnected", extra={"agent_name": "graphiti"})

    def _ensure_connected(self) -> None:
        """Raise error if not connected."""
        if not self.is_connected or self._client is None:
            raise GraphConnectionError("Graphiti client not connected")

    async def add_episode(
        self,
        content: str,
        source: str = "conversation",
        reference_time: datetime | None = None,
        group_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """
        Ingest new information into the knowledge graph.

        Graphiti will:
        1. Extract entities from the content
        2. Create/update nodes in the graph
        3. Create/update relationships
        4. Handle temporal aspects (created_at, expired_at)

        Args:
            content: Text content to ingest
            source: Source type (conversation, email, calendar, etc.)
            reference_time: When the events in content occurred
            group_id: Optional group identifier for related episodes
            trace_id: Trace ID for logging
        """
        self._ensure_connected()
        assert self._client is not None  # Guaranteed by _ensure_connected

        logger.info(
            "[CHART] Ingesting episode...",
            extra={"trace_id": trace_id, "agent_name": "graphiti", "source": source},
        )

        try:
            from graphiti_core.nodes import EpisodeType

            # Determine episode type based on source
            episode_type_map = {
                "conversation": EpisodeType.message,
                "email": EpisodeType.message,
                "calendar": EpisodeType.message,
                "note": EpisodeType.text,
            }
            episode_type = episode_type_map.get(source, EpisodeType.message)

            # Use current time if no reference time provided
            ref_time = reference_time or datetime.now(tz=UTC)

            await self._client.add_episode(
                name=f"episode_{trace_id or 'unknown'}_{ref_time.timestamp():.0f}",
                episode_body=content,
                source=episode_type,
                source_description=f"Klabautermann {source} channel",
                reference_time=ref_time,
                group_id=group_id or "default",
            )

            logger.info(
                "[BEACON] Episode ingested successfully",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )

        except Exception as e:
            logger.error(
                f"[STORM] Episode ingestion failed: {e}",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )
            raise ExternalServiceError("graphiti", f"Episode ingestion failed: {e}") from e

    async def search(
        self,
        query: str,
        limit: int = 10,
        _center_node_uuid: str | None = None,  # Reserved for future use
        trace_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Search the knowledge graph.

        Uses hybrid search combining:
        - Vector similarity (semantic search)
        - Graph traversal (structural context)

        Args:
            query: Natural language search query
            limit: Maximum number of results
            center_node_uuid: Optional node to center search around
            trace_id: Trace ID for logging

        Returns:
            List of SearchResult objects with facts and metadata
        """
        self._ensure_connected()
        assert self._client is not None  # Guaranteed by _ensure_connected

        logger.info(
            f"[CHART] Searching: {query[:50]}...",
            extra={"trace_id": trace_id, "agent_name": "graphiti"},
        )

        try:
            # Execute search
            results = await self._client.search(query, num_results=limit)

            # Convert to our SearchResult format
            search_results: list[SearchResult] = []
            for r in results:
                # Graphiti returns different result types; handle flexibly
                content = getattr(r, "fact", None) or getattr(r, "content", None) or str(r)
                score = getattr(r, "score", 1.0)

                # Extract metadata if available
                metadata: dict[str, Any] = {}
                for attr in ("source", "created_at", "uuid", "episode_uuid"):
                    if hasattr(r, attr):
                        metadata[attr] = getattr(r, attr)

                search_results.append(
                    SearchResult(
                        uuid=getattr(r, "uuid", ""),
                        label=getattr(r, "label", "Fact"),
                        name=getattr(r, "name", None),
                        content=str(content),
                        score=float(score),
                        metadata=metadata,
                    )
                )

            logger.info(
                f"[BEACON] Search returned {len(search_results)} results",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )

            return search_results

        except Exception as e:
            logger.error(
                f"[STORM] Search failed: {e}",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )
            raise ExternalServiceError("graphiti", f"Search failed: {e}") from e

    async def search_entities(
        self,
        query: str,
        limit: int = 5,
        trace_id: str | None = None,
    ) -> list[SearchResult]:
        """
        Search entity nodes via fulltext index.

        Unlike search() which returns edges/facts, this searches entity nodes
        directly using Neo4j's fulltext index on name and summary.

        Args:
            query: Search query
            limit: Maximum number of results
            trace_id: Trace ID for logging

        Returns:
            List of SearchResult objects for matching entities
        """
        self._ensure_connected()
        assert self._client is not None  # Guaranteed by _ensure_connected

        logger.info(
            f"[CHART] Searching entities: {query[:50]}...",
            extra={"trace_id": trace_id, "agent_name": "graphiti"},
        )

        try:
            # Access the Neo4j driver from Graphiti client
            driver = self._client.driver

            # Use fulltext index on entity name and summary
            cypher = """
                CALL db.index.fulltext.queryNodes("node_name_and_summary", $query)
                YIELD node, score
                RETURN node.uuid as uuid, node.name as name, node.summary as summary,
                       labels(node) as labels, score
                LIMIT $limit
            """

            results = await driver.execute_query(
                cypher, parameters_={"query": query, "limit": limit}
            )

            search_results: list[SearchResult] = []
            for record in results.records:
                # Format content from entity data
                name = record.get("name", "Unknown")
                summary = record.get("summary", "")
                labels_list = record.get("labels", [])
                label = labels_list[0] if labels_list else "Entity"

                content = f"{name}: {summary}" if summary else name

                search_results.append(
                    SearchResult(
                        uuid=record.get("uuid", ""),
                        label=label,
                        name=name,
                        content=content,
                        score=float(record.get("score", 1.0)),
                        metadata={"labels": labels_list},
                    )
                )

            logger.info(
                f"[BEACON] Entity search returned {len(search_results)} results",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )

            return search_results

        except Exception as e:
            logger.error(
                f"[STORM] Entity search failed: {e}",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )
            # Return empty list instead of raising - entity search is supplementary
            return []

    async def get_entity(
        self,
        uuid: str,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve a specific entity by UUID.

        Args:
            uuid: Entity UUID
            trace_id: Trace ID for logging

        Returns:
            Entity data dictionary or None if not found
        """
        self._ensure_connected()
        assert self._client is not None  # Guaranteed by _ensure_connected

        try:
            # Use Graphiti's get method if available, otherwise query directly
            if hasattr(self._client, "get_node"):
                result = await self._client.get_node(uuid)
                return dict(result) if result else None
            else:
                # Fallback: query via search
                logger.debug(
                    f"[WHISPER] get_entity falling back to search for {uuid}",
                    extra={"trace_id": trace_id, "agent_name": "graphiti"},
                )
                return None

        except Exception as e:
            logger.error(
                f"[STORM] get_entity failed: {e}",
                extra={"trace_id": trace_id, "agent_name": "graphiti"},
            )
            return None


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["GraphitiClient"]
