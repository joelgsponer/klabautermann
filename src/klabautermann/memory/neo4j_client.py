"""
Neo4j direct client for Klabautermann.

Provides safe, parametrized query execution for operations not covered by Graphiti.
All queries MUST use parameters - never use f-strings with user input.

Reference: specs/architecture/ONTOLOGY.md Section 5
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from neo4j import AsyncGraphDatabase

from klabautermann.core.exceptions import GraphConnectionError
from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from neo4j import AsyncDriver, AsyncSession

    from klabautermann.core.ontology import NodeLabel, RelationType


class Neo4jClient:
    """
    Direct Neo4j access for custom queries.

    CRITICAL: All queries must use parameters. Never use f-strings with user input.
    The only safe interpolation is NodeLabel/RelationType enum values.
    """

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str = "neo4j",
    ) -> None:
        """
        Initialize Neo4j client.

        Args:
            uri: Neo4j bolt URI. Defaults to NEO4J_URI env var.
            username: Database username. Defaults to NEO4J_USERNAME env var.
            password: Database password. Defaults to NEO4J_PASSWORD env var.
            database: Database name. Defaults to "neo4j".
        """
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.username = username or os.getenv("NEO4J_USERNAME", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        self.database = database
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Initialize Neo4j driver and verify connection."""
        logger.info("[CHART] Connecting to Neo4j...", extra={"agent_name": "neo4j_client"})

        # Ensure credentials are available
        if not self.uri or not self.username:
            raise GraphConnectionError("Neo4j URI and username are required")

        try:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password or ""),
            )
            # Verify connection
            if not await self.health_check():
                raise GraphConnectionError("Neo4j health check failed")

            logger.info("[BEACON] Neo4j connected", extra={"agent_name": "neo4j_client"})

        except Exception as e:
            logger.error(
                f"[SHIPWRECK] Neo4j connection failed: {e}",
                extra={"agent_name": "neo4j_client"},
            )
            raise GraphConnectionError(f"Failed to connect to Neo4j: {e}") from e

    async def disconnect(self) -> None:
        """Close Neo4j driver."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("[CHART] Neo4j disconnected", extra={"agent_name": "neo4j_client"})

    async def health_check(self) -> bool:
        """Verify database connection is working."""
        if not self._driver:
            return False

        try:
            async with self._driver.session(database=self.database) as session:
                result = await session.run("RETURN 1 as ping")
                await result.single()
            return True
        except Exception as e:
            logger.error(
                f"[STORM] Neo4j health check failed: {e}",
                extra={"agent_name": "neo4j_client"},
            )
            return False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Get a database session as context manager."""
        if not self._driver:
            raise GraphConnectionError("Neo4j client not connected")

        async with self._driver.session(database=self.database) as session:
            yield session

    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a parametrized Cypher query.

        CRITICAL: Never use f-strings with user input in queries.
        Always pass user data through the parameters dict.

        Args:
            query: Cypher query string with $param placeholders
            parameters: Dictionary of parameter values
            trace_id: Optional trace ID for logging

        Returns:
            List of record dictionaries

        Raises:
            GraphConnectionError: If not connected
        """
        if not self._driver:
            raise GraphConnectionError("Neo4j client not connected")

        parameters = parameters or {}

        logger.debug(
            f"[WHISPER] Executing query: {query[:100]}...",
            extra={
                "trace_id": trace_id,
                "agent_name": "neo4j_client",
                "params": list(parameters.keys()),
            },
        )

        async with self.session() as session:
            result = await session.run(query, parameters)
            records: list[dict[str, Any]] = await result.data()
            return records

    async def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        trace_id: str | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Execute a read-only transaction."""
        if not self._driver:
            raise GraphConnectionError("Neo4j client not connected")

        parameters = parameters or {}

        async with self._driver.session(database=self.database) as session:
            tx = await session.begin_transaction()
            try:
                result = await tx.run(query, parameters)
                records: list[dict[str, Any]] = await result.data()
                return records
            finally:
                await tx.close()

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        trace_id: str | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Execute a write transaction with automatic commit/rollback."""
        if not self._driver:
            raise GraphConnectionError("Neo4j client not connected")

        parameters = parameters or {}

        async with self._driver.session(database=self.database) as session:
            tx = await session.begin_transaction()
            try:
                result = await tx.run(query, parameters)
                records: list[dict[str, Any]] = await result.data()
                await tx.commit()
                return records
            except Exception:
                await tx.rollback()
                raise

    # =========================================================================
    # Common Operations
    # =========================================================================

    async def create_node(
        self,
        label: NodeLabel,
        properties: dict[str, Any],
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a node with the given label and properties.

        Note: label is from enum (safe), properties are parametrized (safe).
        """
        query = f"CREATE (n:{label.value} $props) RETURN n"

        result = await self.execute_query(
            query,
            {"props": properties},
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Created {label.value} node",
            extra={"trace_id": trace_id, "agent_name": "neo4j_client"},
        )

        node: dict[str, Any] = result[0]["n"] if result else {}
        return node

    async def get_node_by_uuid(
        self,
        label: NodeLabel,
        uuid: str,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a node by UUID."""
        query = f"MATCH (n:{label.value} {{uuid: $uuid}}) RETURN n"

        result = await self.execute_query(
            query,
            {"uuid": uuid},
            trace_id=trace_id,
        )

        return result[0]["n"] if result else None

    async def update_node(
        self,
        label: NodeLabel,
        uuid: str,
        properties: dict[str, Any],
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a node's properties by UUID."""
        query = f"""
        MATCH (n:{label.value} {{uuid: $uuid}})
        SET n += $props
        RETURN n
        """

        result = await self.execute_query(
            query,
            {"uuid": uuid, "props": properties},
            trace_id=trace_id,
        )

        return result[0]["n"] if result else None

    async def create_relationship(
        self,
        from_label: NodeLabel,
        from_uuid: str,
        rel_type: RelationType,
        to_label: NodeLabel,
        to_uuid: str,
        properties: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """
        Create a relationship between two nodes.

        Note: Labels and rel_type are from enums (safe).
        UUIDs and properties are parametrized (safe).
        """
        properties = properties or {}

        query = f"""
        MATCH (a:{from_label.value} {{uuid: $from_uuid}})
        MATCH (b:{to_label.value} {{uuid: $to_uuid}})
        CREATE (a)-[r:{rel_type.value} $props]->(b)
        RETURN r
        """

        result = await self.execute_query(
            query,
            {"from_uuid": from_uuid, "to_uuid": to_uuid, "props": properties},
            trace_id=trace_id,
        )

        return len(result) > 0

    async def find_nodes(
        self,
        label: NodeLabel,
        properties: dict[str, Any],
        limit: int = 100,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find nodes matching the given properties."""
        # Build WHERE clause from properties
        where_clauses = [f"n.{key} = ${key}" for key in properties]
        where_str = " AND ".join(where_clauses) if where_clauses else "TRUE"

        query = f"""
        MATCH (n:{label.value})
        WHERE {where_str}
        RETURN n
        LIMIT $limit
        """

        params = {**properties, "limit": limit}

        result = await self.execute_query(query, params, trace_id=trace_id)

        return [r["n"] for r in result]


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Neo4jClient"]
