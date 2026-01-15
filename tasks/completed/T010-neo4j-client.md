# Implement Neo4j Direct Client

## Metadata
- **ID**: T010
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @graph-engineer

## Specs
- Primary: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) Section 5
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md) Section 4

## Dependencies
- [ ] T006 - Ontology constants
- [ ] T008 - Logging system

## Context
While Graphiti handles entity extraction and semantic search, we need direct Neo4j access for custom queries, thread management, and operations not covered by Graphiti. This client provides safe, parametrized query execution.

## Requirements
- [ ] Create `src/klabautermann/memory/neo4j_client.py` with:

### Neo4jClient Class
- [ ] Initialize with credentials from environment
- [ ] Connection pooling via async driver
- [ ] `execute_query()` for parametrized queries (CRITICAL: no f-strings)
- [ ] `execute_read()` for read-only transactions
- [ ] `execute_write()` for write transactions
- [ ] Context manager support for sessions
- [ ] Health check method

### Query Safety
- [ ] All queries MUST use parameters, never string interpolation
- [ ] Validate query contains no f-string patterns
- [ ] Log all queries with trace IDs

### Common Operations
- [ ] `create_node()` - Create node with label and properties
- [ ] `create_relationship()` - Create relationship between nodes
- [ ] `get_node_by_uuid()` - Retrieve single node
- [ ] `run_cypher()` - Execute arbitrary parametrized Cypher

## Acceptance Criteria
- [ ] Client connects using async driver
- [ ] Queries are properly parametrized (no injection risk)
- [ ] Connection pool is managed correctly
- [ ] Health check verifies database accessibility
- [ ] All operations logged with trace ID

## Implementation Notes

```python
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from neo4j import AsyncGraphDatabase, AsyncDriver

from klabautermann.core.logger import logger
from klabautermann.core.ontology import NodeLabel, RelationType


class Neo4jClient:
    """Direct Neo4j access for custom queries."""

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ):
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self._driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        """Initialize Neo4j driver."""
        logger.info("[CHART] Connecting to Neo4j...")
        self._driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.username, self.password),
        )
        # Verify connection
        await self.health_check()
        logger.info("[BEACON] Neo4j connected")

    async def disconnect(self) -> None:
        """Close Neo4j driver."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("[CHART] Neo4j disconnected")

    async def health_check(self) -> bool:
        """Verify database connection."""
        try:
            async with self._driver.session(database=self.database) as session:
                result = await session.run("RETURN 1 as ping")
                await result.single()
            return True
        except Exception as e:
            logger.error(f"[STORM] Neo4j health check failed: {e}")
            return False

    @asynccontextmanager
    async def session(self):
        """Get a database session."""
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")
        async with self._driver.session(database=self.database) as session:
            yield session

    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a parametrized Cypher query.

        CRITICAL: Never use f-strings in queries. Always use parameters.
        """
        parameters = parameters or {}

        logger.debug(
            f"[WHISPER] Executing query: {query[:100]}...",
            extra={"trace_id": trace_id, "params": list(parameters.keys())}
        )

        async with self.session() as session:
            result = await session.run(query, parameters)
            records = await result.data()
            return records

    async def create_node(
        self,
        label: NodeLabel,
        properties: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a node with the given label and properties."""
        # GOOD: Parametrized query
        query = f"CREATE (n:{label.value} $props) RETURN n"
        # Note: label is from enum (safe), properties are parametrized

        result = await self.execute_query(
            query,
            {"props": properties},
            trace_id=trace_id,
        )
        return result[0]["n"] if result else {}

    async def get_node_by_uuid(
        self,
        label: NodeLabel,
        uuid: str,
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a node by UUID."""
        query = f"MATCH (n:{label.value} {{uuid: $uuid}}) RETURN n"

        result = await self.execute_query(
            query,
            {"uuid": uuid},
            trace_id=trace_id,
        )
        return result[0]["n"] if result else None
```

**Security Note**: The `label.value` in queries is safe because it comes from our enum, not user input. All user-provided values MUST go through parameters.
