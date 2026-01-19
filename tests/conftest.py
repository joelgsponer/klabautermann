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
