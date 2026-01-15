"""
Thread Manager for Klabautermann.

Manages conversation threads and message persistence.
Threads maintain context across messages for coherent conversations.

Reference: specs/architecture/MEMORY.md, ONTOLOGY.md Section 2.12
"""

from __future__ import annotations

import time
import uuid as uuid_lib
from typing import TYPE_CHECKING

from klabautermann.core.exceptions import GraphConnectionError, ThreadNotFoundError
from klabautermann.core.logger import logger
from klabautermann.core.models import (
    ChannelType,
    MessageNode,
    MessageRole,
    ThreadContext,
    ThreadNode,
    ThreadStatus,
)


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


class ThreadManager:
    """
    Manages conversation threads and message persistence.

    Responsibilities:
    - Create/retrieve threads by external_id
    - Add messages with [:PRECEDES] linking
    - Retrieve rolling context window
    - Update thread status for archival
    """

    def __init__(self, neo4j: Neo4jClient) -> None:
        """
        Initialize ThreadManager.

        Args:
            neo4j: Neo4jClient instance for database operations
        """
        self.neo4j = neo4j

    async def get_or_create_thread(
        self,
        external_id: str,
        channel_type: str | ChannelType,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> ThreadNode:
        """
        Get existing thread or create new one.

        Args:
            external_id: Channel-specific identifier (chat_id, session_id)
            channel_type: Type of channel (cli, telegram, discord)
            user_id: Optional platform user identifier
            trace_id: Trace ID for logging

        Returns:
            ThreadNode representing the thread
        """
        # Normalize channel_type to string
        if isinstance(channel_type, ChannelType):
            channel_type = channel_type.value

        # Try to find existing thread
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
            logger.debug(
                f"[WHISPER] Found existing thread for {external_id}",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )
            return ThreadNode(**result[0]["t"])

        # Create new thread
        now = time.time()
        thread_uuid = str(uuid_lib.uuid4())
        thread_data = {
            "uuid": thread_uuid,
            "external_id": external_id,
            "channel_type": channel_type,
            "user_id": user_id,
            "status": ThreadStatus.ACTIVE.value,
            "created_at": now,
            "updated_at": now,
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
            f"[BEACON] Created thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "thread_manager"},
        )

        return ThreadNode(**result[0]["t"])

    async def get_thread(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> ThreadNode:
        """
        Get thread by UUID.

        Args:
            thread_uuid: Thread UUID
            trace_id: Trace ID for logging

        Returns:
            ThreadNode

        Raises:
            ThreadNotFoundError: If thread doesn't exist
        """
        query = """
        MATCH (t:Thread {uuid: $uuid})
        RETURN t
        """
        result = await self.neo4j.execute_query(
            query,
            {"uuid": thread_uuid},
            trace_id=trace_id,
        )

        if not result:
            raise ThreadNotFoundError(thread_uuid)

        return ThreadNode(**result[0]["t"])

    async def add_message(
        self,
        thread_uuid: str,
        role: str | MessageRole,
        content: str,
        metadata: dict | None = None,
        trace_id: str | None = None,
    ) -> MessageNode:
        """
        Add a message to a thread.

        Creates the message node, links it to the thread via [:CONTAINS],
        and links to the previous message via [:PRECEDES].

        Args:
            thread_uuid: Thread UUID to add message to
            role: Message role (user or assistant)
            content: Message content
            metadata: Optional metadata dictionary
            trace_id: Trace ID for logging

        Returns:
            MessageNode representing the created message
        """
        # Normalize role to string
        if isinstance(role, MessageRole):
            role = role.value

        now = time.time()
        message_uuid = str(uuid_lib.uuid4())
        message_data = {
            "uuid": message_uuid,
            "role": role,
            "content": content,
            "timestamp": now,
        }

        # Add metadata if provided (as JSON string for Neo4j compatibility)
        if metadata:
            import json

            message_data["metadata"] = json.dumps(metadata)

        # Create message and link to thread
        # Find the latest message (one without outgoing PRECEDES) and link to it
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
        SET t.last_message_at = $now, t.updated_at = $now
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

        if not result:
            raise ThreadNotFoundError(thread_uuid)

        logger.debug(
            f"[WHISPER] Added {role} message to thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "thread_manager"},
        )

        return MessageNode(**result[0]["m"])

    async def get_context_window(
        self,
        thread_uuid: str,
        limit: int = 20,
        trace_id: str | None = None,
    ) -> ThreadContext:
        """
        Get the rolling context window for a thread.

        Retrieves the last N messages in chronological order,
        suitable for passing to the LLM as conversation context.

        Args:
            thread_uuid: Thread UUID
            limit: Maximum number of messages to retrieve
            trace_id: Trace ID for logging

        Returns:
            ThreadContext with messages in chronological order
        """
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

        # Get thread info
        thread_result = await self.neo4j.execute_query(
            "MATCH (t:Thread {uuid: $uuid}) RETURN t.channel_type as channel_type",
            {"uuid": thread_uuid},
            trace_id=trace_id,
        )

        channel_type = ChannelType.CLI  # default
        if thread_result:
            channel_str = thread_result[0].get("channel_type", "cli")
            try:
                channel_type = ChannelType(channel_str)
            except ValueError:
                channel_type = ChannelType.CLI

        messages = [{"role": r["role"], "content": r["content"]} for r in result]

        logger.debug(
            f"[WHISPER] Retrieved {len(messages)} messages for context",
            extra={"trace_id": trace_id, "agent_name": "thread_manager"},
        )

        return ThreadContext(
            thread_uuid=thread_uuid,
            channel_type=channel_type,
            messages=messages,
            max_messages=limit,
        )

    async def update_thread_status(
        self,
        thread_uuid: str,
        status: str | ThreadStatus,
        trace_id: str | None = None,
    ) -> ThreadNode:
        """
        Update thread status.

        Args:
            thread_uuid: Thread UUID
            status: New status value
            trace_id: Trace ID for logging

        Returns:
            Updated ThreadNode
        """
        # Normalize status to string
        if isinstance(status, ThreadStatus):
            status = status.value

        query = """
        MATCH (t:Thread {uuid: $uuid})
        SET t.status = $status, t.updated_at = $now
        RETURN t
        """

        result = await self.neo4j.execute_query(
            query,
            {"uuid": thread_uuid, "status": status, "now": time.time()},
            trace_id=trace_id,
        )

        if not result:
            raise ThreadNotFoundError(thread_uuid)

        logger.info(
            f"[CHART] Thread {thread_uuid[:8]}... status -> {status}",
            extra={"trace_id": trace_id, "agent_name": "thread_manager"},
        )

        return ThreadNode(**result[0]["t"])

    async def get_message_count(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> int:
        """Get the number of messages in a thread."""
        query = """
        MATCH (t:Thread {uuid: $uuid})-[:CONTAINS]->(m:Message)
        RETURN count(m) as count
        """

        result = await self.neo4j.execute_query(
            query,
            {"uuid": thread_uuid},
            trace_id=trace_id,
        )

        return result[0]["count"] if result else 0

    async def get_recent_threads(
        self,
        channel_type: str | ChannelType | None = None,
        limit: int = 10,
        trace_id: str | None = None,
    ) -> list[ThreadNode]:
        """
        Get recent threads, optionally filtered by channel type.

        Args:
            channel_type: Optional channel type filter
            limit: Maximum number of threads to retrieve
            trace_id: Trace ID for logging

        Returns:
            List of ThreadNode objects
        """
        if channel_type:
            if isinstance(channel_type, ChannelType):
                channel_type = channel_type.value
            query = """
            MATCH (t:Thread {channel_type: $channel_type})
            RETURN t
            ORDER BY t.last_message_at DESC
            LIMIT $limit
            """
            params = {"channel_type": channel_type, "limit": limit}
        else:
            query = """
            MATCH (t:Thread)
            RETURN t
            ORDER BY t.last_message_at DESC
            LIMIT $limit
            """
            params = {"limit": limit}

        result = await self.neo4j.execute_query(query, params, trace_id=trace_id)

        return [ThreadNode(**r["t"]) for r in result]


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["ThreadManager"]
