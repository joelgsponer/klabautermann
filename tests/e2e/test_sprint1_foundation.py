"""
Sprint 1 End-to-End Tests

These tests validate the Golden Scenarios for Sprint 1:
1. "I met Sarah from Acme" creates appropriate graph nodes
2. Context persistence works across messages
3. Response generation meets performance requirements

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.

Reference: specs/quality/TESTING.md
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest


# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
async def neo4j_client():
    """Initialize Neo4j client for tests."""
    from klabautermann.memory.neo4j_client import Neo4jClient

    client = Neo4jClient(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "klabautermann"),
    )
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def graphiti_client():
    """Initialize Graphiti client for tests (optional)."""
    from klabautermann.memory.graphiti_client import GraphitiClient

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY not set - skipping Graphiti tests")

    client = GraphitiClient(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "klabautermann"),
        openai_api_key=openai_key,
    )

    try:
        await client.connect()
        yield client
        await client.disconnect()
    except Exception as e:
        pytest.skip(f"Could not connect to Graphiti: {e}")


@pytest.fixture
def test_thread_id():
    """Generate unique thread ID for test isolation."""
    return f"test-{uuid.uuid4()}"


@pytest.fixture
async def cleanup_test_thread(neo4j_client, test_thread_id):
    """Clean up test thread and messages after each test."""
    yield
    # Cleanup: remove test thread and messages
    await neo4j_client.execute_query(
        """
        MATCH (t:Thread)
        WHERE t.external_id STARTS WITH 'test-'
        OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
        DETACH DELETE t, m
        """,
        {},
    )


# ===========================================================================
# Test Classes
# ===========================================================================


@pytest.mark.e2e
class TestSprint1Foundation:
    """End-to-end tests for Sprint 1 foundation."""

    @pytest.mark.asyncio
    async def test_thread_creation(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that threads can be created and retrieved."""
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)

        # Act - create thread
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Assert - thread created
        assert thread is not None
        assert thread.uuid is not None
        assert thread.external_id == test_thread_id
        assert thread.channel_type.value == "test"

        # Act - get same thread again
        thread2 = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Assert - same thread returned
        assert thread2.uuid == thread.uuid

    @pytest.mark.asyncio
    async def test_message_persistence(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that messages are persisted to the graph."""
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Act - add messages
        await thread_manager.add_message(
            thread_uuid=thread.uuid,
            role="user",
            content="Hello, world!",
        )

        await thread_manager.add_message(
            thread_uuid=thread.uuid,
            role="assistant",
            content="Hello! How can I help?",
        )

        # Assert - messages exist in graph
        result = await neo4j_client.execute_query(
            """
            MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
            RETURN m ORDER BY m.timestamp
            """,
            {"thread_uuid": thread.uuid},
        )

        assert len(result) == 2
        assert result[0]["m"]["role"] == "user"
        assert result[0]["m"]["content"] == "Hello, world!"
        assert result[1]["m"]["role"] == "assistant"
        assert result[1]["m"]["content"] == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_context_window(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that context window returns messages in order."""
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Act - add several messages
        messages = [
            ("user", "First message"),
            ("assistant", "First response"),
            ("user", "Second message"),
            ("assistant", "Second response"),
            ("user", "Third message"),
        ]

        for role, content in messages:
            await thread_manager.add_message(
                thread_uuid=thread.uuid,
                role=role,
                content=content,
            )

        # Get context window
        context = await thread_manager.get_context_window(
            thread_uuid=thread.uuid,
            limit=10,
        )

        # Assert - messages in correct order
        assert len(context.messages) == 5
        assert context.messages[0]["content"] == "First message"
        assert context.messages[1]["content"] == "First response"
        assert context.messages[2]["content"] == "Second message"
        assert context.messages[3]["content"] == "Second response"
        assert context.messages[4]["content"] == "Third message"

    @pytest.mark.asyncio
    async def test_context_window_limit(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that context window respects limit parameter."""
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Add 10 messages
        for i in range(10):
            await thread_manager.add_message(
                thread_uuid=thread.uuid,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )

        # Act - get limited context
        context = await thread_manager.get_context_window(
            thread_uuid=thread.uuid,
            limit=3,
        )

        # Assert - only last 3 messages
        assert len(context.messages) == 3
        # Should be the last 3 messages in chronological order
        assert context.messages[0]["content"] == "Message 7"
        assert context.messages[1]["content"] == "Message 8"
        assert context.messages[2]["content"] == "Message 9"


@pytest.mark.e2e
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
class TestOrchestratorIntegration:
    """Tests that require the Anthropic API."""

    @pytest.mark.asyncio
    async def test_orchestrator_response(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that orchestrator generates responses."""
        from klabautermann.agents.orchestrator import Orchestrator
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        orchestrator = Orchestrator(
            graphiti=None,  # Skip ingestion for this test
            thread_manager=thread_manager,
        )

        # Create thread first
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Act
        response = await orchestrator.handle_user_input(
            thread_id=thread.uuid,
            text="Hello, how are you?",
            trace_id="test-response",
        )

        # Assert
        assert response is not None
        assert len(response) > 0
        assert isinstance(response, str)

    @pytest.mark.asyncio
    async def test_response_time(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_thread,
    ):
        """Test that response time is under 10 seconds."""
        from klabautermann.agents.orchestrator import Orchestrator
        from klabautermann.memory.thread_manager import ThreadManager

        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        orchestrator = Orchestrator(
            graphiti=None,
            thread_manager=thread_manager,
        )

        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        # Act
        start = time.time()
        response = await orchestrator.handle_user_input(
            thread_id=thread.uuid,
            text="What is 2 + 2?",
        )
        elapsed = time.time() - start

        # Assert
        assert elapsed < 10.0, f"Response took {elapsed:.2f}s, expected <10s"
        assert response is not None


@pytest.mark.e2e
class TestGraphOperations:
    """Tests for Neo4j graph operations."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_node(
        self,
        neo4j_client,
        cleanup_test_thread,
    ):
        """Test basic node creation and retrieval."""
        from klabautermann.core.ontology import NodeLabel

        # Arrange
        test_uuid = f"test-person-{uuid.uuid4()}"
        properties = {
            "uuid": test_uuid,
            "name": "Test Person",
            "email": "test@example.com",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        try:
            # Act - create node
            await neo4j_client.create_node(
                label=NodeLabel.PERSON,
                properties=properties,
            )

            # Retrieve node
            result = await neo4j_client.get_node_by_uuid(
                label=NodeLabel.PERSON,
                uuid=test_uuid,
            )

            # Assert
            assert result is not None
            assert result["name"] == "Test Person"
            assert result["email"] == "test@example.com"

        finally:
            # Cleanup
            await neo4j_client.execute_query(
                "MATCH (p:Person {uuid: $uuid}) DELETE p",
                {"uuid": test_uuid},
            )

    @pytest.mark.asyncio
    async def test_parametrized_queries(
        self,
        neo4j_client,
    ):
        """Test that queries are properly parametrized."""
        # This test verifies that the Neo4j client properly uses parameters
        # and doesn't allow injection

        # Act - execute a safe parametrized query
        result = await neo4j_client.execute_query(
            "RETURN $name as name, $value as value",
            {"name": "test'; DROP DATABASE neo4j; --", "value": 123},
        )

        # Assert - the malicious string was safely passed as a parameter
        assert len(result) == 1
        assert result[0]["name"] == "test'; DROP DATABASE neo4j; --"
        assert result[0]["value"] == 123


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])
