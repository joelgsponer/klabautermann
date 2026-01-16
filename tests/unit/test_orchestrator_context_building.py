"""
Unit tests for Orchestrator _build_context() method (T053).

Tests parallel context gathering, partial failure handling,
and config-driven behavior.

Reference: specs/MAINAGENT.md Section 4.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import (
    ChannelType,
    CommunityContext,
    EnrichedContext,
    EntityReference,
    TaskNode,
    TaskStatus,
    ThreadContext,
    ThreadSummary,
)


@pytest.fixture
def mock_graphiti():
    """Mock GraphitiClient."""
    return MagicMock()


@pytest.fixture
def mock_thread_manager():
    """Mock ThreadManager."""
    return MagicMock()


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4jClient."""
    return MagicMock()


@pytest.fixture
def orchestrator(mock_graphiti, mock_thread_manager, mock_neo4j_client):
    """Create Orchestrator with mocked dependencies."""
    orch = Orchestrator(
        graphiti=mock_graphiti,
        thread_manager=mock_thread_manager,
        neo4j_client=mock_neo4j_client,
        config={},
    )
    return orch


@pytest.mark.asyncio
async def test_build_context_parallel_execution(orchestrator, mock_thread_manager):
    """Test that all context queries are executed in parallel."""
    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    # Mock all query functions
    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        # Set up return values
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=ThreadContext(
                thread_uuid=thread_uuid,
                channel_type=ChannelType.CLI,
                messages=[{"role": "user", "content": "test"}],
                max_messages=20,
            )
        )
        mock_summaries.return_value = []
        mock_tasks.return_value = []
        mock_entities.return_value = []
        mock_islands.return_value = []

        # Call _build_context
        context = await orchestrator._build_context(thread_uuid, trace_id)

        # Verify all queries were called
        mock_thread_manager.get_context_window.assert_called_once()
        mock_summaries.assert_called_once()
        mock_tasks.assert_called_once()
        mock_entities.assert_called_once()
        mock_islands.assert_called_once()

        # Verify result structure
        assert isinstance(context, EnrichedContext)
        assert context.thread_uuid == thread_uuid
        assert context.channel_type == ChannelType.CLI
        assert len(context.messages) == 1
        assert context.recent_summaries == []
        assert context.pending_tasks == []
        assert context.recent_entities == []


@pytest.mark.asyncio
async def test_build_context_partial_failure(orchestrator, mock_thread_manager):
    """Test that if one query fails, others still succeed."""
    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    # Mock queries - one will fail, others succeed
    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        # Set up - summaries will fail, others succeed
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=ThreadContext(
                thread_uuid=thread_uuid,
                channel_type=ChannelType.CLI,
                messages=[],
            )
        )
        mock_summaries.side_effect = RuntimeError("Database connection failed")
        mock_tasks.return_value = [
            TaskNode(uuid="task-1", action="Test task", status=TaskStatus.TODO)
        ]
        mock_entities.return_value = [
            EntityReference(
                uuid="entity-1", name="Test", entity_type="Person", created_at=1234567890.0
            )
        ]
        mock_islands.return_value = [
            CommunityContext(name="Test Island", theme="Testing", summary="A test island")
        ]

        # Call _build_context
        context = await orchestrator._build_context(thread_uuid, trace_id)

        # Verify result - summaries should be empty due to exception
        assert isinstance(context, EnrichedContext)
        assert context.recent_summaries == []  # Failed query
        assert len(context.pending_tasks) == 1  # Succeeded
        assert len(context.recent_entities) == 1  # Succeeded
        assert context.relevant_islands is not None  # Succeeded
        assert len(context.relevant_islands) == 1


@pytest.mark.asyncio
async def test_build_context_config_driven(orchestrator, mock_thread_manager):
    """Test that config flags disable specific queries."""
    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    # Override config to disable some queries
    with patch.object(orchestrator, "_load_v2_config") as mock_config:
        mock_config.return_value = {
            "context": {
                "message_window": 10,
                "summary_hours": 6,
                "include_pending_tasks": False,  # Disabled
                "include_recent_entities": False,  # Disabled
                "recent_entity_hours": 12,
                "include_islands": True,
            }
        }

        with (
            patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
            patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
            patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
            patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
        ):
            mock_thread_manager.get_context_window = AsyncMock(
                return_value=ThreadContext(
                    thread_uuid=thread_uuid,
                    channel_type=ChannelType.CLI,
                    messages=[],
                )
            )
            mock_summaries.return_value = []
            mock_islands.return_value = []

            # Call _build_context
            context = await orchestrator._build_context(thread_uuid, trace_id)

            # Verify only enabled queries were called
            mock_thread_manager.get_context_window.assert_called_once_with(thread_uuid, limit=10)
            mock_summaries.assert_called_once()
            mock_tasks.assert_not_called()  # Disabled
            mock_entities.assert_not_called()  # Disabled
            mock_islands.assert_called_once()

            # Verify disabled queries return empty lists
            assert context.pending_tasks == []
            assert context.recent_entities == []


@pytest.mark.asyncio
async def test_build_context_trace_id_propagation(orchestrator, mock_thread_manager):
    """Test that trace_id is passed to all query functions."""
    trace_id = "test-trace-xyz"
    thread_uuid = "thread-abc"

    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=ThreadContext(
                thread_uuid=thread_uuid,
                channel_type=ChannelType.CLI,
                messages=[],
            )
        )
        mock_summaries.return_value = []
        mock_tasks.return_value = []
        mock_entities.return_value = []
        mock_islands.return_value = []

        # Call _build_context
        await orchestrator._build_context(thread_uuid, trace_id)

        # Verify trace_id was passed to all queries
        _, summaries_kwargs = mock_summaries.call_args
        assert summaries_kwargs["trace_id"] == trace_id

        _, tasks_kwargs = mock_tasks.call_args
        assert tasks_kwargs["trace_id"] == trace_id

        _, entities_kwargs = mock_entities.call_args
        assert entities_kwargs["trace_id"] == trace_id

        _, islands_kwargs = mock_islands.call_args
        assert islands_kwargs["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_build_context_without_neo4j_client(mock_thread_manager):
    """Test context building when Neo4jClient is not available."""
    # Create orchestrator WITHOUT neo4j_client
    orch = Orchestrator(
        graphiti=MagicMock(),
        thread_manager=mock_thread_manager,
        neo4j_client=None,  # No neo4j_client
        config={},
    )

    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=ThreadContext(
                thread_uuid=thread_uuid,
                channel_type=ChannelType.CLI,
                messages=[],
            )
        )

        # Call _build_context
        context = await orch._build_context(thread_uuid, trace_id)

        # Verify Neo4j queries were NOT called (no neo4j_client)
        mock_summaries.assert_not_called()
        mock_tasks.assert_not_called()
        mock_entities.assert_not_called()
        mock_islands.assert_not_called()

        # Verify we got minimal context from ThreadManager only
        assert isinstance(context, EnrichedContext)
        assert context.recent_summaries == []
        assert context.pending_tasks == []
        assert context.recent_entities == []
        assert context.relevant_islands is None


@pytest.mark.asyncio
async def test_build_context_without_thread_manager(mock_neo4j_client):
    """Test context building when ThreadManager is not available."""
    # Create orchestrator WITHOUT thread_manager
    orch = Orchestrator(
        graphiti=MagicMock(),
        thread_manager=None,  # No thread_manager
        neo4j_client=mock_neo4j_client,
        config={},
    )

    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        mock_summaries.return_value = []
        mock_tasks.return_value = []
        mock_entities.return_value = []
        mock_islands.return_value = []

        # Call _build_context
        context = await orch._build_context(thread_uuid, trace_id)

        # Verify we got empty messages from fallback
        assert isinstance(context, EnrichedContext)
        assert context.messages == []
        assert context.channel_type == ChannelType.CLI

        # But Neo4j queries still ran
        mock_summaries.assert_called_once()
        mock_tasks.assert_called_once()
        mock_entities.assert_called_once()
        mock_islands.assert_called_once()


@pytest.mark.asyncio
async def test_build_context_full_payload(orchestrator, mock_thread_manager):
    """Test context building with all layers returning data."""
    trace_id = "test-trace-123"
    thread_uuid = "thread-abc"

    with (
        patch("klabautermann.agents.orchestrator.get_recent_summaries") as mock_summaries,
        patch("klabautermann.agents.orchestrator.get_pending_tasks") as mock_tasks,
        patch("klabautermann.agents.orchestrator.get_recent_entities") as mock_entities,
        patch("klabautermann.agents.orchestrator.get_relevant_islands") as mock_islands,
    ):
        # Set up rich data from all layers
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=ThreadContext(
                thread_uuid=thread_uuid,
                channel_type=ChannelType.TELEGRAM,
                messages=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ],
            )
        )

        mock_summaries.return_value = [
            ThreadSummary(
                summary="Discussed project timeline",
                topics=["project", "deadline"],
                participants=["Alice", "Bob"],
            ),
            ThreadSummary(
                summary="Email follow-up needed",
                topics=["email", "action"],
                participants=["Charlie"],
            ),
        ]

        mock_tasks.return_value = [
            TaskNode(uuid="task-1", action="Send report to Alice", status=TaskStatus.TODO),
            TaskNode(uuid="task-2", action="Review PR", status=TaskStatus.IN_PROGRESS),
        ]

        mock_entities.return_value = [
            EntityReference(
                uuid="ent-1",
                name="Alice Johnson",
                entity_type="Person",
                created_at=1234567890.0,
            ),
            EntityReference(
                uuid="ent-2", name="Acme Corp", entity_type="Organization", created_at=1234567891.0
            ),
        ]

        mock_islands.return_value = [
            CommunityContext(
                name="Work Projects",
                theme="Professional work",
                summary="Active work projects and collaborations",
                pending_tasks=3,
            )
        ]

        # Call _build_context
        context = await orchestrator._build_context(thread_uuid, trace_id)

        # Verify all data is present
        assert len(context.messages) == 2
        assert context.channel_type == ChannelType.TELEGRAM
        assert len(context.recent_summaries) == 2
        assert len(context.pending_tasks) == 2
        assert len(context.recent_entities) == 2
        assert context.relevant_islands is not None
        assert len(context.relevant_islands) == 1
        assert context.relevant_islands[0].pending_tasks == 3


@pytest.mark.asyncio
async def test_load_v2_config_defaults(orchestrator):
    """Test that _load_v2_config returns sensible defaults when config is unavailable."""
    with patch("klabautermann.config.manager.ConfigManager") as mock_cm:
        # Simulate config loading failure
        mock_cm.side_effect = ImportError("Config module not available")

        config = orchestrator._load_v2_config()

        # Verify defaults are returned
        assert "context" in config
        assert config["context"]["message_window"] == 20
        assert config["context"]["summary_hours"] == 12
        assert config["context"]["include_pending_tasks"] is True
        assert config["context"]["include_recent_entities"] is True
        assert config["context"]["recent_entity_hours"] == 24
        assert config["context"]["include_islands"] is True


@pytest.mark.asyncio
async def test_build_empty_context_window(orchestrator):
    """Test _build_empty_context_window helper."""
    thread_uuid = "thread-xyz"
    context = await orchestrator._build_empty_context_window(thread_uuid)

    assert isinstance(context, ThreadContext)
    assert context.thread_uuid == thread_uuid
    assert context.channel_type == ChannelType.CLI
    assert context.messages == []
    assert context.max_messages == 20


@pytest.mark.asyncio
async def test_return_empty_list(orchestrator):
    """Test _return_empty_list helper."""
    result = await orchestrator._return_empty_list()
    assert result == []
    assert isinstance(result, list)
