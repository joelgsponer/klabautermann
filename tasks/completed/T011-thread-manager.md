# Create Thread Manager

## Metadata
- **ID**: T011
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) Section 2.12

## Dependencies
- [ ] T009 - Graphiti client (for episode addition)
- [ ] T010 - Neo4j client (for thread queries)

## Context
Threads are conversation containers that maintain context across messages. The Thread Manager handles creating threads, adding messages, and retrieving the rolling context window that the Orchestrator uses to maintain conversational coherence.

## Requirements
- [ ] Create `src/klabautermann/memory/thread_manager.py` with:

### ThreadManager Class
- [ ] `get_or_create_thread()` - Find or create thread by external_id
- [ ] `add_message()` - Add message to thread with [:PRECEDES] link
- [ ] `get_context_window()` - Retrieve last N messages for context
- [ ] `update_thread_status()` - Change thread status

### Thread Operations
- [ ] Create Thread node with:
  - uuid (generated)
  - external_id (from channel - chat_id, session_id)
  - channel_type (cli, telegram, etc.)
  - status (active, archiving, archived)
  - created_at, last_message_at

### Message Operations
- [ ] Create Message node with:
  - uuid (generated)
  - role (user or assistant)
  - content (message text)
  - timestamp
- [ ] Link message to thread via [:CONTAINS]
- [ ] Link to previous message via [:PRECEDES]
- [ ] Update thread's last_message_at

### Context Window Retrieval
- [ ] Follow [:PRECEDES] chain backwards from latest
- [ ] Return in chronological order
- [ ] Include role and content for each message

## Acceptance Criteria
- [ ] `get_or_create_thread("cli-session-1", "cli")` creates thread if not exists
- [ ] `add_message(thread_uuid, "user", "Hello")` creates linked message
- [ ] `get_context_window(thread_uuid, limit=15)` returns last 15 messages in order
- [ ] Thread's `last_message_at` updates on new message
- [ ] Messages linked via [:PRECEDES] chain

## Implementation Notes

```python
import uuid as uuid_lib
import time
from typing import Optional, List

from klabautermann.core.logger import logger
from klabautermann.core.models import ThreadNode, MessageNode, ThreadContext
from klabautermann.core.ontology import NodeLabel, RelationType
from klabautermann.memory.neo4j_client import Neo4jClient


class ThreadManager:
    """Manages conversation threads and message persistence."""

    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    async def get_or_create_thread(
        self,
        external_id: str,
        channel_type: str,
        trace_id: Optional[str] = None,
    ) -> ThreadNode:
        """Get existing thread or create new one."""
        # Try to find existing
        query = """
        MATCH (t:Thread {external_id: $external_id, channel_type: $channel_type})
        RETURN t
        """
        result = await self.neo4j.execute_query(
            query,
            {"external_id": external_id, "channel_type": channel_type},
            trace_id=trace_id,
        )

        if result:
            return ThreadNode(**result[0]["t"])

        # Create new thread
        now = time.time()
        thread_data = {
            "uuid": str(uuid_lib.uuid4()),
            "external_id": external_id,
            "channel_type": channel_type,
            "status": "active",
            "created_at": now,
            "last_message_at": now,
        }

        create_query = """
        CREATE (t:Thread $props)
        RETURN t
        """
        result = await self.neo4j.execute_query(
            create_query,
            {"props": thread_data},
            trace_id=trace_id,
        )

        logger.info(
            f"[BEACON] Created thread {thread_data['uuid'][:8]}...",
            extra={"trace_id": trace_id}
        )

        return ThreadNode(**result[0]["t"])

    async def add_message(
        self,
        thread_uuid: str,
        role: str,
        content: str,
        trace_id: Optional[str] = None,
    ) -> MessageNode:
        """Add a message to a thread."""
        now = time.time()
        message_data = {
            "uuid": str(uuid_lib.uuid4()),
            "role": role,
            "content": content,
            "timestamp": now,
        }

        # Create message and link to thread, with PRECEDES to previous
        query = """
        MATCH (t:Thread {uuid: $thread_uuid})
        OPTIONAL MATCH (t)-[:CONTAINS]->(prev:Message)
        WHERE NOT (prev)-[:PRECEDES]->()
        CREATE (m:Message $msg_props)
        CREATE (t)-[:CONTAINS]->(m)
        WITH t, m, prev
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (prev)-[:PRECEDES]->(m)
        )
        SET t.last_message_at = $now
        RETURN m
        """

        result = await self.neo4j.execute_query(
            query,
            {
                "thread_uuid": thread_uuid,
                "msg_props": message_data,
                "now": now,
            },
            trace_id=trace_id,
        )

        return MessageNode(**result[0]["m"])

    async def get_context_window(
        self,
        thread_uuid: str,
        limit: int = 15,
        trace_id: Optional[str] = None,
    ) -> ThreadContext:
        """Get the rolling context window for a thread."""
        # Get messages in reverse chronological order, then reverse
        query = """
        MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
        WITH m ORDER BY m.timestamp DESC LIMIT $limit
        WITH collect(m) as messages
        UNWIND reverse(messages) as msg
        RETURN msg.role as role, msg.content as content, msg.timestamp as timestamp
        ORDER BY msg.timestamp ASC
        """

        result = await self.neo4j.execute_query(
            query,
            {"thread_uuid": thread_uuid, "limit": limit},
            trace_id=trace_id,
        )

        messages = [
            {"role": r["role"], "content": r["content"]}
            for r in result
        ]

        return ThreadContext(
            thread_uuid=thread_uuid,
            messages=messages,
            message_count=len(messages),
        )
```

Reference ONTOLOGY.md Section 5.2 for the context window query pattern.
