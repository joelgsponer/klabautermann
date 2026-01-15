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

from klabautermann.core.exceptions import ThreadNotFoundError
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

        If the thread is in 'archiving' status, it will be reactivated first
        to prevent message loss during archival.

        Args:
            thread_uuid: Thread UUID to add message to
            role: Message role (user or assistant)
            content: Message content
            metadata: Optional metadata dictionary
            trace_id: Trace ID for logging

        Returns:
            MessageNode representing the created message
        """
        # Check thread status and reactivate if archiving
        thread = await self.get_thread(thread_uuid, trace_id=trace_id)
        if thread.status == ThreadStatus.ARCHIVING:
            logger.info(
                f"[BEACON] Reactivating archiving thread {thread_uuid[:8]}... due to new message",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )
            await self.reactivate_thread(thread_uuid, trace_id=trace_id)

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

        count: int = result[0]["count"] if result else 0
        return count

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

    async def mark_archiving(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> bool:
        """
        Atomically mark thread as archiving.

        This method implements the first state transition in the thread lifecycle:
        active -> archiving. The atomic WHERE clause ensures that only active
        threads can transition to archiving, preventing race conditions.

        Args:
            thread_uuid: Thread UUID to mark as archiving
            trace_id: Trace ID for logging

        Returns:
            True if successful, False if thread not in 'active' state
        """
        now = time.time()
        query = """
        MATCH (t:Thread {uuid: $thread_uuid})
        WHERE t.status = 'active'
        SET t.status = 'archiving',
            t.archiving_started_at = $now,
            t.updated_at = $now
        RETURN t.uuid
        """
        result = await self.neo4j.execute_query(
            query,
            {"thread_uuid": thread_uuid, "now": now},
            trace_id=trace_id,
        )

        success = len(result) > 0
        if success:
            logger.info(
                f"[CHART] Thread {thread_uuid[:8]}... status -> archiving",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )
        else:
            logger.debug(
                f"[WHISPER] Cannot mark thread {thread_uuid[:8]}... as archiving (not active)",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )

        return success

    async def mark_archived(
        self,
        thread_uuid: str,
        summary_uuid: str,
        trace_id: str | None = None,
    ) -> bool:
        """
        Mark thread as archived and link summary note.

        This method implements the second state transition in the thread lifecycle:
        archiving -> archived. The atomic WHERE clause ensures that only threads
        currently in 'archiving' state can be archived.

        Args:
            thread_uuid: Thread UUID to mark as archived
            summary_uuid: UUID of the summary Note node
            trace_id: Trace ID for logging

        Returns:
            True if successful, False if thread not in 'archiving' state
        """
        now = time.time()
        query = """
        MATCH (t:Thread {uuid: $thread_uuid})
        WHERE t.status = 'archiving'
        MATCH (n:Note {uuid: $summary_uuid})
        SET t.status = 'archived',
            t.archived_at = $now,
            t.updated_at = $now
        CREATE (n)-[:SUMMARY_OF]->(t)
        RETURN t.uuid
        """
        result = await self.neo4j.execute_query(
            query,
            {"thread_uuid": thread_uuid, "summary_uuid": summary_uuid, "now": now},
            trace_id=trace_id,
        )

        success = len(result) > 0
        if success:
            logger.info(
                f"[CHART] Thread {thread_uuid[:8]}... status -> archived (summary: {summary_uuid[:8]}...)",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )
        else:
            logger.debug(
                f"[WHISPER] Cannot mark thread {thread_uuid[:8]}... as archived (not archiving)",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )

        return success

    async def reactivate_thread(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> bool:
        """
        Reactivate a thread that was being archived.

        This method reverts the archiving -> active transition. It's used when
        archival fails or when a new message arrives while a thread is being archived.

        Args:
            thread_uuid: Thread UUID to reactivate
            trace_id: Trace ID for logging

        Returns:
            True if successful, False if thread not in 'archiving' state
        """
        now = time.time()
        query = """
        MATCH (t:Thread {uuid: $thread_uuid})
        WHERE t.status = 'archiving'
        SET t.status = 'active',
            t.updated_at = $now
        REMOVE t.archiving_started_at
        RETURN t.uuid
        """
        result = await self.neo4j.execute_query(
            query,
            {"thread_uuid": thread_uuid, "now": now},
            trace_id=trace_id,
        )

        success = len(result) > 0
        if success:
            logger.info(
                f"[CHART] Thread {thread_uuid[:8]}... status -> active (reactivated)",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )
        else:
            logger.debug(
                f"[WHISPER] Cannot reactivate thread {thread_uuid[:8]}... (not archiving)",
                extra={"trace_id": trace_id, "agent_name": "thread_manager"},
            )

        return success

    async def get_inactive_threads(
        self,
        cooldown_minutes: int = 60,
        limit: int = 10,
        trace_id: str | None = None,
    ) -> list[str]:
        """
        Find threads inactive for longer than cooldown period.

        This query identifies threads ready for archival by the Archivist agent.
        Threads must be in 'active' status and have not received a message for
        the specified cooldown period.

        Args:
            cooldown_minutes: Minutes of inactivity before considered cold
            limit: Maximum threads to return
            trace_id: Trace ID for logging

        Returns:
            List of thread UUIDs ready for archival, ordered by last_message_at ASC
            (oldest inactive threads first)
        """
        # Calculate cutoff timestamp
        cutoff = time.time() - (cooldown_minutes * 60)

        query = """
        MATCH (t:Thread)
        WHERE t.status = 'active'
          AND t.last_message_at < $cutoff_timestamp
        RETURN t.uuid
        ORDER BY t.last_message_at ASC
        LIMIT $limit
        """

        result = await self.neo4j.execute_query(
            query,
            {"cutoff_timestamp": cutoff, "limit": limit},
            trace_id=trace_id,
        )

        thread_uuids = [r["t.uuid"] for r in result]

        logger.debug(
            f"[WHISPER] Found {len(thread_uuids)} inactive threads (cooldown: {cooldown_minutes}m)",
            extra={"trace_id": trace_id, "agent_name": "thread_manager"},
        )

        return thread_uuids


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["ThreadManager"]
