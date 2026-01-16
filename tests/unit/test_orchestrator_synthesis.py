"""
Unit tests for Orchestrator _synthesize_response() method (T056).

Tests response synthesis with Claude Opus, context and result formatting,
proactive behavior, error handling, and fallback responses.

Reference: specs/MAINAGENT.md Section 4.5
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


@pytest.fixture
def sample_enriched_context():
    """Create a sample EnrichedContext for testing."""
    return EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[
            {"role": "user", "content": "What do you know about Sarah?"},
            {"role": "assistant", "content": "Let me search for that."},
        ],
        recent_summaries=[
            ThreadSummary(
                summary="Discussed Sarah's new job at Acme Corp",
                topics=["career", "Sarah"],
                participants=["Sarah"],
            )
        ],
        pending_tasks=[
            TaskNode(uuid="task-1", action="Email Sarah about project", status=TaskStatus.TODO)
        ],
        recent_entities=[
            EntityReference(
                uuid="ent-1",
                name="Sarah Johnson",
                entity_type="Person",
                created_at=1234567890.0,
            )
        ],
        relevant_islands=[
            CommunityContext(
                name="Work Island",
                theme="Professional",
                summary="Work-related activities",
                pending_tasks=2,
            )
        ],
    )


@pytest.mark.asyncio
async def test_synthesize_response_with_results(orchestrator, sample_enriched_context):
    """Test that synthesis generates coherent response from multiple results."""
    trace_id = "test-trace-123"
    original_text = "What do you know about Sarah?"
    results = {
        "Search for Sarah in knowledge graph": {
            "agent": "researcher",
            "response": "Sarah Johnson works at Acme Corp as a PM. Met her last week.",
            "task_type": "research",
        },
        "Check calendar for Sarah meetings": {
            "agent": "executor",
            "response": "No upcoming meetings with Sarah found.",
            "task_type": "execute",
        },
    }

    mock_response = "Sarah Johnson works at Acme Corp as a PM. You met her last week. There are no upcoming meetings scheduled with her."

    with patch.object(
        orchestrator, "_call_opus_for_synthesis", new=AsyncMock(return_value=mock_response)
    ):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify response is returned
        assert isinstance(response, str)
        assert "Sarah Johnson" in response
        assert "Acme Corp" in response


@pytest.mark.asyncio
async def test_synthesize_response_empty_results(orchestrator, sample_enriched_context):
    """Test that synthesis handles empty results gracefully."""
    trace_id = "test-trace-123"
    original_text = "What do you know about Sarah?"
    results = {}

    mock_response = "I don't have any information about Sarah in The Locker."

    with patch.object(
        orchestrator, "_call_opus_for_synthesis", new=AsyncMock(return_value=mock_response)
    ):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify response handles empty results
        assert isinstance(response, str)
        assert len(response) > 0


@pytest.mark.asyncio
async def test_synthesize_response_all_failed_results(orchestrator, sample_enriched_context):
    """Test that synthesis handles all-failed results gracefully."""
    trace_id = "test-trace-123"
    original_text = "What do you know about Sarah?"
    results = {
        "Search for Sarah": {"error": "Connection timeout"},
        "Check calendar": {"error": "Calendar API unavailable"},
    }

    mock_response = "I had trouble retrieving information. The search timed out and calendar is currently unavailable. Please try again later."

    with patch.object(
        orchestrator, "_call_opus_for_synthesis", new=AsyncMock(return_value=mock_response)
    ):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify response acknowledges failures
        assert isinstance(response, str)
        assert "trouble" in response.lower() or "unavailable" in response.lower()


@pytest.mark.asyncio
async def test_synthesize_response_with_proactive_suggestions(
    orchestrator, sample_enriched_context
):
    """Test that proactive suggestions are included based on config."""
    trace_id = "test-trace-123"
    original_text = "I need to meet with Sarah next week"
    results = {
        "Search for Sarah": {
            "agent": "researcher",
            "response": "Sarah Johnson, PM at Acme Corp, email: sarah@acme.com",
            "task_type": "research",
        },
    }

    mock_response = "Sarah Johnson is a PM at Acme Corp. Her email is sarah@acme.com. Should I add this to your calendar?"

    # Mock config with proactive behavior enabled
    with (
        patch.object(
            orchestrator,
            "_load_v2_config",
            return_value={
                "proactive_behavior": {
                    "suggest_calendar_events": True,
                    "suggest_follow_ups": True,
                }
            },
        ),
        patch.object(
            orchestrator, "_call_opus_for_synthesis", new=AsyncMock(return_value=mock_response)
        ),
    ):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify proactive suggestion is present
        assert isinstance(response, str)
        assert "calendar" in response.lower() or "add" in response.lower()


@pytest.mark.asyncio
async def test_synthesize_response_fallback_on_error(orchestrator, sample_enriched_context):
    """Test fallback response when synthesis fails."""
    trace_id = "test-trace-123"
    original_text = "What do you know about Sarah?"
    results = {
        "Search for Sarah": {
            "agent": "researcher",
            "response": "Sarah Johnson works at Acme Corp",
            "task_type": "research",
        },
    }

    # Simulate synthesis failure
    with patch.object(orchestrator, "_call_opus_for_synthesis", side_effect=Exception("API error")):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify fallback response is used
        assert isinstance(response, str)
        assert "trouble" in response.lower() or "information" in response.lower()


@pytest.mark.asyncio
async def test_format_context_for_synthesis(orchestrator, sample_enriched_context):
    """Test context formatting for synthesis prompt."""
    formatted = orchestrator._format_context_for_synthesis(sample_enriched_context)

    # Verify recent messages are included
    assert "RECENT CONVERSATION:" in formatted
    assert "What do you know about Sarah?" in formatted

    # Verify pending tasks are included
    assert "RELEVANT PENDING TASKS:" in formatted
    assert "Email Sarah about project" in formatted


@pytest.mark.asyncio
async def test_format_context_for_synthesis_limits_messages(orchestrator):
    """Test that only last 3 messages are included in context."""
    # Create context with 5 messages
    context = EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
        ],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )

    formatted = orchestrator._format_context_for_synthesis(context)

    # Verify only last 3 messages are included
    assert "Message 3" in formatted
    assert "Response 2" in formatted
    assert "Message 2" in formatted
    assert "Message 1" not in formatted  # Too old
    assert "Response 1" not in formatted  # Too old


@pytest.mark.asyncio
async def test_format_context_for_synthesis_limits_tasks(orchestrator):
    """Test that only first 3 pending tasks are included."""
    # Create context with 5 tasks
    context = EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[],
        recent_summaries=[],
        pending_tasks=[
            TaskNode(uuid="task-1", action="Task 1", status=TaskStatus.TODO),
            TaskNode(uuid="task-2", action="Task 2", status=TaskStatus.TODO),
            TaskNode(uuid="task-3", action="Task 3", status=TaskStatus.TODO),
            TaskNode(uuid="task-4", action="Task 4", status=TaskStatus.TODO),
            TaskNode(uuid="task-5", action="Task 5", status=TaskStatus.TODO),
        ],
        recent_entities=[],
        relevant_islands=None,
    )

    formatted = orchestrator._format_context_for_synthesis(context)

    # Verify only first 3 tasks are included
    assert "Task 1" in formatted
    assert "Task 2" in formatted
    assert "Task 3" in formatted
    assert "Task 4" not in formatted
    assert "Task 5" not in formatted


@pytest.mark.asyncio
async def test_format_context_for_synthesis_empty(orchestrator):
    """Test context formatting with empty context."""
    empty_context = EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )

    formatted = orchestrator._format_context_for_synthesis(empty_context)

    # Should return fallback message
    assert formatted == "No additional context."


@pytest.mark.asyncio
async def test_format_results_for_synthesis(orchestrator):
    """Test result formatting for synthesis prompt."""
    results = {
        "Search for Sarah": {
            "agent": "researcher",
            "response": "Sarah Johnson works at Acme Corp",
            "task_type": "research",
        },
        "Check calendar": {
            "agent": "executor",
            "response": "No meetings found",
            "task_type": "execute",
        },
    }

    formatted = orchestrator._format_results_for_synthesis(results)

    # Verify all results are formatted
    assert "TASK: Search for Sarah" in formatted
    assert "RESULT: Sarah Johnson works at Acme Corp" in formatted
    assert "TASK: Check calendar" in formatted
    assert "RESULT: No meetings found" in formatted


@pytest.mark.asyncio
async def test_format_results_for_synthesis_with_errors(orchestrator):
    """Test result formatting includes errors properly."""
    results = {
        "Search for Sarah": {
            "agent": "researcher",
            "response": "Sarah Johnson works at Acme Corp",
            "task_type": "research",
        },
        "Check calendar": {
            "error": "Calendar API timeout",
        },
    }

    formatted = orchestrator._format_results_for_synthesis(results)

    # Verify error is formatted correctly
    assert "TASK: Check calendar" in formatted
    assert "STATUS: Failed - Calendar API timeout" in formatted


@pytest.mark.asyncio
async def test_format_results_for_synthesis_truncates_long_responses(orchestrator):
    """Test that long responses are truncated."""
    long_response = "A" * 600  # Longer than 500 char limit
    results = {
        "Search task": {
            "agent": "researcher",
            "response": long_response,
            "task_type": "research",
        },
    }

    formatted = orchestrator._format_results_for_synthesis(results)

    # Verify truncation (500 chars max)
    assert "A" * 500 in formatted
    assert "A" * 600 not in formatted


@pytest.mark.asyncio
async def test_format_results_for_synthesis_empty(orchestrator):
    """Test result formatting with empty results."""
    results = {}

    formatted = orchestrator._format_results_for_synthesis(results)

    # Should return fallback message
    assert formatted == "No results from subagents."


@pytest.mark.asyncio
async def test_call_opus_for_synthesis(orchestrator):
    """Test that Opus is called with correct parameters for synthesis."""
    trace_id = "test-trace-123"
    prompt = "Test synthesis prompt"

    # Mock the Anthropic client
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Synthesized response text")]

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.return_value = mock_message

    # Patch the _anthropic property directly
    orchestrator._anthropic = mock_anthropic

    result = await orchestrator._call_opus_for_synthesis(prompt, trace_id)

    # Verify result
    assert result == "Synthesized response text"

    # Verify Anthropic was called correctly
    mock_anthropic.messages.create.assert_called_once()
    call_args = mock_anthropic.messages.create.call_args[1]

    assert call_args["model"] == "claude-opus-4-5-20251101"
    assert call_args["max_tokens"] == 1000
    assert call_args["messages"][0]["role"] == "user"
    assert call_args["messages"][0]["content"] == prompt


@pytest.mark.asyncio
async def test_build_fallback_response_no_results(orchestrator):
    """Test fallback response with no results."""
    results = {}

    fallback = orchestrator._build_fallback_response(results)

    # Verify fallback message for no results
    assert isinstance(fallback, str)
    assert "processed" in fallback.lower() or "couldn't find" in fallback.lower()


@pytest.mark.asyncio
async def test_build_fallback_response_successful_results(orchestrator):
    """Test fallback response with successful results."""
    results = {
        "Search task": {
            "agent": "researcher",
            "response": "Found Sarah Johnson at Acme Corp",
            "task_type": "research",
        },
    }

    fallback = orchestrator._build_fallback_response(results)

    # Verify fallback includes information from results
    assert isinstance(fallback, str)
    assert len(fallback) > 0
    assert "information" in fallback.lower() or "learned" in fallback.lower()


@pytest.mark.asyncio
async def test_build_fallback_response_all_errors(orchestrator):
    """Test fallback response when all results are errors."""
    results = {
        "Search task": {"error": "Timeout"},
        "Execute task": {"error": "API unavailable"},
    }

    fallback = orchestrator._build_fallback_response(results)

    # Verify fallback acknowledges failure
    assert isinstance(fallback, str)
    assert "trouble" in fallback.lower() or "rephrasing" in fallback.lower()


@pytest.mark.asyncio
async def test_synthesize_response_includes_acknowledgment(orchestrator, sample_enriched_context):
    """Test that synthesis acknowledges new information ingestion."""
    trace_id = "test-trace-123"
    original_text = "I learned that Sarah studied at Harvard"
    results = {
        "Store fact about Sarah": {
            "agent": "ingestor",
            "response": "Fact stored successfully",
            "task_type": "ingest",
        },
    }

    mock_response = (
        "Got it! I've noted that Sarah studied at Harvard. Anything else I should know about her?"
    )

    with patch.object(
        orchestrator, "_call_opus_for_synthesis", new=AsyncMock(return_value=mock_response)
    ):
        response = await orchestrator._synthesize_response(
            original_text, sample_enriched_context, results, trace_id
        )

        # Verify acknowledgment is present
        assert isinstance(response, str)
        assert "noted" in response.lower() or "got it" in response.lower()


@pytest.mark.asyncio
async def test_synthesize_response_proactive_config_disabled(orchestrator, sample_enriched_context):
    """Test that additional proactive guidance is NOT appended when config disabled."""
    trace_id = "test-trace-123"
    original_text = "I need to meet with Sarah"
    results = {
        "Search for Sarah": {
            "agent": "researcher",
            "response": "Sarah Johnson, PM at Acme Corp",
            "task_type": "research",
        },
    }

    # Mock config with proactive behavior disabled
    with patch.object(
        orchestrator,
        "_load_v2_config",
        return_value={
            "proactive_behavior": {
                "suggest_calendar_events": False,
                "suggest_follow_ups": False,
            }
        },
    ):
        # Capture the prompt that would be sent to Opus
        captured_prompt = None

        async def capture_prompt(prompt, trace_id):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "Response without suggestions"

        with patch.object(orchestrator, "_call_opus_for_synthesis", side_effect=capture_prompt):
            await orchestrator._synthesize_response(
                original_text, sample_enriched_context, results, trace_id
            )

            # Verify additional proactive guidance lines are NOT appended
            # (The base prompt already has proactive suggestions, but when disabled,
            # no EXTRA lines should be added beyond the base prompt)
            assert captured_prompt is not None
            # These are the specific lines added when config is enabled
            assert "\n- If relevant, suggest adding calendar events." not in captured_prompt
            assert "\n- If relevant, suggest follow-up actions." not in captured_prompt


@pytest.mark.asyncio
async def test_synthesize_response_truncates_message_content(orchestrator):
    """Test that long message content is truncated in context."""
    long_message = "A" * 200  # Will be truncated to 150
    context = EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[
            {"role": "user", "content": long_message},
        ],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )

    formatted = orchestrator._format_context_for_synthesis(context)

    # Verify truncation (150 chars max per message)
    assert "A" * 150 in formatted
    assert "A" * 200 not in formatted
