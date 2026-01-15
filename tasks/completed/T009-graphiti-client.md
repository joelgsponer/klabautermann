# Implement Graphiti Client Wrapper

## Metadata
- **ID**: T009
- **Priority**: P0
- **Category**: core
- **Effort**: L
- **Status**: pending
- **Assignee**: @graph-engineer

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)

## Dependencies
- [ ] T006 - Ontology constants
- [ ] T008 - Logging system

## Context
Graphiti is the temporal knowledge graph library that provides the core memory functionality. This wrapper abstracts Graphiti's API and handles connection management, error handling, and integration with our logging system.

## Requirements
- [ ] Create `src/klabautermann/memory/graphiti_client.py` with:

### GraphitiClient Class
- [ ] Initialize with Neo4j credentials from environment
- [ ] Configure OpenAI embeddings integration
- [ ] Implement `add_episode()` for ingesting new information
- [ ] Implement `search()` for semantic search
- [ ] Implement `get_entity()` for direct entity retrieval
- [ ] Connection management (connect/disconnect)
- [ ] Error handling with retry logic

### Episode Ingestion
- [ ] Accept raw text content
- [ ] Accept optional source metadata (thread_id, channel, timestamp)
- [ ] Pass to Graphiti for entity extraction and graph update
- [ ] Log ingestion with trace ID

### Search
- [ ] Accept query string
- [ ] Accept optional filters (entity type, date range)
- [ ] Return structured SearchResult objects
- [ ] Include source attribution in results

## Acceptance Criteria
- [ ] Client connects to Neo4j on initialization
- [ ] `add_episode("I met Sarah from Acme")` creates graph nodes
- [ ] `search("Who is Sarah?")` returns relevant results
- [ ] Errors are logged and re-raised appropriately
- [ ] Client works with async/await pattern

## Implementation Notes

```python
from typing import Optional, List, Dict, Any
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

from klabautermann.core.logger import logger
from klabautermann.core.models import SearchResult


class GraphitiClient:
    """Wrapper around Graphiti temporal knowledge graph."""

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        openai_api_key: str,
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.openai_api_key = openai_api_key
        self._client: Optional[Graphiti] = None

    async def connect(self) -> None:
        """Initialize Graphiti connection."""
        logger.info("[CHART] Connecting to Graphiti...")
        self._client = Graphiti(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password,
        )
        # Configure embeddings
        # Note: Check Graphiti docs for exact configuration
        await self._client.build_indices_and_constraints()
        logger.info("[BEACON] Graphiti connected")

    async def disconnect(self) -> None:
        """Close Graphiti connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("[CHART] Graphiti disconnected")

    async def add_episode(
        self,
        content: str,
        source: str = "conversation",
        reference_time: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Ingest new information into the knowledge graph."""
        if not self._client:
            raise RuntimeError("Graphiti client not connected")

        logger.info(
            f"[CHART] Ingesting episode",
            extra={"trace_id": trace_id, "source": source}
        )

        try:
            await self._client.add_episode(
                name=f"episode_{trace_id or 'unknown'}",
                episode_body=content,
                source=EpisodeType.message,
                reference_time=reference_time,
            )
            logger.info(
                "[BEACON] Episode ingested",
                extra={"trace_id": trace_id}
            )
        except Exception as e:
            logger.error(
                f"[STORM] Episode ingestion failed: {e}",
                extra={"trace_id": trace_id}
            )
            raise

    async def search(
        self,
        query: str,
        limit: int = 10,
        trace_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search the knowledge graph."""
        if not self._client:
            raise RuntimeError("Graphiti client not connected")

        logger.info(
            f"[CHART] Searching: {query[:50]}...",
            extra={"trace_id": trace_id}
        )

        try:
            results = await self._client.search(query, num_results=limit)
            # Convert to our SearchResult format
            return [
                SearchResult(
                    content=r.fact if hasattr(r, 'fact') else str(r),
                    score=getattr(r, 'score', 1.0),
                    source=getattr(r, 'source', 'unknown'),
                )
                for r in results
            ]
        except Exception as e:
            logger.error(
                f"[STORM] Search failed: {e}",
                extra={"trace_id": trace_id}
            )
            raise
```

**Graphiti Fallback**: If Graphiti integration proves too complex, this task may need to be simplified to direct Neo4j operations with manual temporal handling. Document any fallback decisions in `devnotes/graph/graphiti-decision.md`.
