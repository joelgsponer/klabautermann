"""
Pytest configuration and shared fixtures for Klabautermann tests.

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import TYPE_CHECKING, Any

import pytest


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient
    from klabautermann.memory.thread_manager import ThreadManager


# ===========================================================================
# Event Loop Configuration
# ===========================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ===========================================================================
# Service Availability Checks
# ===========================================================================


def neo4j_available() -> bool:
    """Check if Neo4j test instance is available on port 7688."""
    try:
        host = os.getenv("NEO4J_HOST", "localhost")
        port = int(os.getenv("NEO4J_TEST_PORT", "7688"))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def openai_available() -> bool:
    """Check if OpenAI API key is configured."""
    return bool(os.getenv("OPENAI_API_KEY"))


def anthropic_available() -> bool:
    """Check if Anthropic API key is configured."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ===========================================================================
# Skip Markers for Service Dependencies
# ===========================================================================

requires_neo4j = pytest.mark.skipif(
    not neo4j_available(),
    reason="Neo4j not available. Start with: docker-compose -f docker-compose.test.yml up -d",
)

requires_openai = pytest.mark.skipif(
    not openai_available(),
    reason="OPENAI_API_KEY not set",
)

requires_anthropic = pytest.mark.skipif(
    not anthropic_available(),
    reason="ANTHROPIC_API_KEY not set",
)


# ===========================================================================
# Neo4j Fixtures (Real Service)
# ===========================================================================


@pytest.fixture(scope="session")
async def neo4j_client() -> AsyncGenerator[Neo4jClient, None]:
    """
    Neo4j client connected to test database.

    Uses test port (7688) to avoid conflicts with development.
    """
    from klabautermann.memory.neo4j_client import Neo4jClient

    client = Neo4jClient(
        uri=os.getenv("NEO4J_TEST_URI", "bolt://localhost:7688"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_TEST_PASSWORD", "testpassword"),
    )

    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture(scope="session")
async def graphiti_client() -> AsyncGenerator[GraphitiClient, None]:
    """
    Graphiti client connected to test Neo4j instance.

    Requires OPENAI_API_KEY for embeddings.
    """
    if not openai_available():
        pytest.skip("OPENAI_API_KEY not set - skipping Graphiti tests")

    from klabautermann.memory.graphiti_client import GraphitiClient

    client = GraphitiClient(
        neo4j_uri=os.getenv("NEO4J_TEST_URI", "bolt://localhost:7688"),
        neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("NEO4J_TEST_PASSWORD", "testpassword"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )

    try:
        await client.connect()
        yield client
        await client.disconnect()
    except Exception as e:
        pytest.skip(f"Could not connect to Graphiti: {e}")


@pytest.fixture(scope="session")
async def thread_manager(neo4j_client: Neo4jClient) -> ThreadManager:
    """ThreadManager for test database (session-scoped to match neo4j_client)."""
    from klabautermann.memory.thread_manager import ThreadManager

    return ThreadManager(neo4j_client)


# ===========================================================================
# Test Data Fixtures
# ===========================================================================


@pytest.fixture
def test_thread_id() -> str:
    """Generate unique thread ID for test isolation."""
    return f"test-thread-{uuid.uuid4()}"


@pytest.fixture
async def cleanup_test_data(neo4j_client: Neo4jClient) -> AsyncGenerator[None, None]:
    """Clean up test data after each test."""
    yield
    # Cleanup: remove all test-prefixed nodes
    await neo4j_client.execute_query(
        """
        MATCH (n)
        WHERE n.uuid STARTS WITH 'test-' OR n.uuid STARTS WITH 'golden-'
        DETACH DELETE n
        """,
        {},
    )


@pytest.fixture
async def cleanup_golden_data(neo4j_client: Neo4jClient) -> AsyncGenerator[None, None]:
    """Clean up golden scenario data after each test."""
    yield
    await neo4j_client.execute_query(
        """
        MATCH (t:Thread)
        WHERE t.external_id STARTS WITH 'golden-'
        OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
        DETACH DELETE t, m
        """,
        {},
    )
    await neo4j_client.execute_query(
        """
        MATCH (n)
        WHERE n.name CONTAINS 'John' OR n.name CONTAINS 'Sarah'
           OR n.name CONTAINS 'Bob' OR n.name CONTAINS 'Dave'
           OR n.name CONTAINS 'Alice' OR n.name CONTAINS 'Mark'
           OR n.name CONTAINS 'Test'
        DETACH DELETE n
        """,
        {},
    )


# ===========================================================================
# Mock Fixtures (for Unit Tests)
# ===========================================================================


@pytest.fixture
def mock_neo4j_driver() -> Any:
    """Mock Neo4j driver for unit tests."""
    from unittest.mock import MagicMock

    driver = MagicMock()
    driver.session = MagicMock()
    return driver


@pytest.fixture
def mock_anthropic_client() -> Any:
    """Mock Anthropic client for unit tests."""
    from unittest.mock import AsyncMock, MagicMock

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


# ===========================================================================
# Sample Data Fixtures
# ===========================================================================


@pytest.fixture
def sample_thread_context() -> dict[str, Any]:
    """Sample thread context for testing."""
    return {
        "thread_uuid": "test-thread-uuid",
        "channel_type": "cli",
        "messages": [
            {"role": "user", "content": "Hello, I met Sarah from Acme Corp today."},
            {"role": "assistant", "content": "Nice to meet Sarah! What does she do at Acme?"},
        ],
    }


# ===========================================================================
# Thread Manager Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_thread_manager() -> Any:
    """
    Mock ThreadManager for unit tests.

    Provides a fully mocked ThreadManager with async methods.
    """
    from unittest.mock import AsyncMock, MagicMock

    from klabautermann.core.models import (
        ChannelType,
        MessageNode,
        ThreadContext,
        ThreadNode,
        ThreadStatus,
    )

    manager = MagicMock()

    # Default thread for get_or_create_thread
    default_thread = ThreadNode(
        uuid="test-thread-uuid",
        external_id="test-external-id",
        channel_type=ChannelType.CLI,
        status=ThreadStatus.ACTIVE,
        created_at=1234567890.0,
        updated_at=1234567890.0,
        last_message_at=1234567890.0,
    )

    manager.get_or_create_thread = AsyncMock(return_value=default_thread)
    manager.get_thread = AsyncMock(return_value=default_thread)
    manager.add_message = AsyncMock(
        return_value=MessageNode(
            uuid="test-msg-uuid",
            role="user",
            content="Test message",
            timestamp=1234567890.0,
        )
    )
    manager.get_context_window = AsyncMock(
        return_value=ThreadContext(
            thread_uuid="test-thread-uuid",
            channel_type=ChannelType.CLI,
            messages=[],
            max_messages=20,
        )
    )
    manager.update_thread_status = AsyncMock(return_value=default_thread)
    manager.get_message_count = AsyncMock(return_value=0)
    manager.get_recent_threads = AsyncMock(return_value=[])
    manager.mark_archiving = AsyncMock(return_value=True)
    manager.mark_archived = AsyncMock(return_value=True)
    manager.reactivate_thread = AsyncMock(return_value=True)
    manager.get_inactive_threads = AsyncMock(return_value=[])

    return manager


@pytest.fixture
def thread_factory() -> Any:
    """
    Factory fixture to create ThreadNode objects for testing.

    Usage:
        thread = thread_factory()
        thread = thread_factory(channel_type="telegram", external_id="tg-123")
    """
    import time

    from klabautermann.core.models import ChannelType, ThreadNode, ThreadStatus

    def _create_thread(
        uuid: str | None = None,
        external_id: str | None = None,
        channel_type: str | ChannelType = ChannelType.CLI,
        user_id: str | None = None,
        status: ThreadStatus = ThreadStatus.ACTIVE,
        created_at: float | None = None,
        **kwargs: Any,
    ) -> ThreadNode:
        """Create a ThreadNode with test defaults."""
        now = time.time()
        thread_uuid = uuid or f"test-thread-{uuid_lib.uuid4()}"
        ext_id = external_id or f"test-ext-{uuid_lib.uuid4()}"

        if isinstance(channel_type, str):
            channel_type = ChannelType(channel_type)

        return ThreadNode(
            uuid=thread_uuid,
            external_id=ext_id,
            channel_type=channel_type,
            user_id=user_id,
            status=status,
            created_at=created_at or now,
            updated_at=created_at or now,
            last_message_at=created_at or now,
            **kwargs,
        )

    return _create_thread


@pytest.fixture
def message_factory() -> Any:
    """
    Factory fixture to create MessageNode objects for testing.

    Usage:
        msg = message_factory(content="Hello")
        msg = message_factory(role="assistant", content="Hi there!")
    """
    import time

    from klabautermann.core.models import MessageNode

    def _create_message(
        uuid: str | None = None,
        role: str = "user",
        content: str = "Test message",
        timestamp: float | None = None,
        metadata: dict | None = None,
    ) -> MessageNode:
        """Create a MessageNode with test defaults."""
        msg_uuid = uuid or f"test-msg-{uuid_lib.uuid4()}"
        return MessageNode(
            uuid=msg_uuid,
            role=role,
            content=content,
            timestamp=timestamp or time.time(),
            metadata=metadata,
        )

    return _create_message


@pytest.fixture
def conversation_factory(message_factory: Any) -> Any:
    """
    Factory fixture to create conversation sequences.

    Usage:
        messages = conversation_factory([
            ("user", "Hello"),
            ("assistant", "Hi there!"),
            ("user", "How are you?"),
        ])
    """
    from klabautermann.core.models import MessageNode

    def _create_conversation(
        exchanges: list[tuple[str, str]],
    ) -> list[MessageNode]:
        """Create a sequence of messages from (role, content) tuples."""
        import time

        base_time = time.time() - len(exchanges)  # Spread messages over time
        messages = []

        for i, (role, content) in enumerate(exchanges):
            msg = message_factory(
                role=role,
                content=content,
                timestamp=base_time + i,
            )
            messages.append(msg)

        return messages

    return _create_conversation


@pytest.fixture
def sample_conversation() -> list[tuple[str, str]]:
    """Sample conversation data for testing."""
    return [
        ("user", "Hello, I met Sarah from Acme Corp today."),
        ("assistant", "Nice to meet Sarah! What does she do at Acme?"),
        ("user", "She's a product manager working on their new AI platform."),
        ("assistant", "That's interesting! I'll remember that Sarah is a PM at Acme."),
    ]
