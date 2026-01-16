"""
Unit tests for Orchestrator _plan_tasks() method (T054).

Tests task planning with Claude Opus, response parsing,
error handling, and context formatting.

Reference: specs/MAINAGENT.md Section 4.3
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
    TaskPlan,
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
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        recent_summaries=[
            ThreadSummary(
                summary="Discussed Sarah's new job",
                topics=["career", "Sarah"],
                participants=["Sarah"],
            )
        ],
        pending_tasks=[TaskNode(uuid="task-1", action="Email Sarah", status=TaskStatus.TODO)],
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
async def test_plan_tasks_multi_intent_message(orchestrator, sample_enriched_context):
    """Test that multi-intent message returns TaskPlan with multiple tasks."""
    trace_id = "test-trace-123"
    user_message = "I learned Sarah studied at Harvard. Do I have a meeting with her next week?"

    # Mock Opus response with multiple tasks
    mock_response = """```json
{
  "reasoning": "User is providing new information and asking a question. Need to ingest the fact and check calendar.",
  "tasks": [
    {
      "task_type": "ingest",
      "description": "Store fact that Sarah studied at Harvard",
      "agent": "ingestor",
      "payload": {"text": "Sarah studied at Harvard"},
      "blocking": false
    },
    {
      "task_type": "execute",
      "description": "Check calendar for meetings with Sarah next week",
      "agent": "executor",
      "payload": {"action": "calendar_search", "params": {"query": "Sarah", "time_range": "next_week"}},
      "blocking": true
    }
  ],
  "direct_response": null
}
```"""

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify task plan structure
        assert isinstance(task_plan, TaskPlan)
        assert len(task_plan.tasks) == 2
        assert task_plan.direct_response is None
        assert "ingest" in task_plan.reasoning.lower()

        # Verify first task (ingest)
        assert task_plan.tasks[0].task_type == "ingest"
        assert task_plan.tasks[0].agent == "ingestor"
        assert task_plan.tasks[0].blocking is False

        # Verify second task (execute)
        assert task_plan.tasks[1].task_type == "execute"
        assert task_plan.tasks[1].agent == "executor"
        assert task_plan.tasks[1].blocking is True


@pytest.mark.asyncio
async def test_plan_tasks_simple_greeting(orchestrator, sample_enriched_context):
    """Test that simple greeting returns direct_response without tasks."""
    trace_id = "test-trace-123"
    user_message = "Hello!"

    # Mock Opus response with direct response, no tasks
    mock_response = """```json
{
  "reasoning": "Simple greeting, no tasks needed",
  "tasks": [],
  "direct_response": "Hello! How can I help you today?"
}
```"""

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify task plan structure
        assert isinstance(task_plan, TaskPlan)
        assert len(task_plan.tasks) == 0
        assert task_plan.direct_response is not None
        assert "hello" in task_plan.direct_response.lower()


@pytest.mark.asyncio
async def test_plan_tasks_blocking_flag_correctness(orchestrator, sample_enriched_context):
    """Test that blocking flag is correctly set for different task types."""
    trace_id = "test-trace-123"
    user_message = "I met John today. What do you know about him? Can you email him?"

    # Mock Opus response with all task types
    mock_response = """{
  "reasoning": "User provides info about John, asks for knowledge, and wants to send email",
  "tasks": [
    {
      "task_type": "ingest",
      "description": "Store that user met John today",
      "agent": "ingestor",
      "payload": {"text": "I met John today"},
      "blocking": false
    },
    {
      "task_type": "research",
      "description": "Search knowledge graph for John",
      "agent": "researcher",
      "payload": {"query": "What do you know about John?"},
      "blocking": true
    },
    {
      "task_type": "execute",
      "description": "Draft email to John",
      "agent": "executor",
      "payload": {"action": "email_draft", "target": "John"},
      "blocking": true
    }
  ],
  "direct_response": null
}"""

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify blocking flags
        assert task_plan.tasks[0].task_type == "ingest"
        assert task_plan.tasks[0].blocking is False  # Ingest is fire-and-forget

        assert task_plan.tasks[1].task_type == "research"
        assert task_plan.tasks[1].blocking is True  # Research needs results

        assert task_plan.tasks[2].task_type == "execute"
        assert task_plan.tasks[2].blocking is True  # Execute needs results


@pytest.mark.asyncio
async def test_plan_tasks_malformed_json_fallback(orchestrator, sample_enriched_context):
    """Test that malformed LLM output doesn't crash and falls back gracefully."""
    trace_id = "test-trace-123"
    user_message = "Test message"

    # Mock Opus response with malformed JSON
    mock_response = "This is not JSON at all!"

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify fallback behavior
        assert isinstance(task_plan, TaskPlan)
        assert len(task_plan.tasks) == 0
        assert task_plan.direct_response is not None
        assert "trouble processing" in task_plan.direct_response.lower()
        assert task_plan.reasoning == "Task planning failed, responding directly"


@pytest.mark.asyncio
async def test_plan_tasks_incomplete_json_fallback(orchestrator, sample_enriched_context):
    """Test handling of incomplete JSON (missing required field 'reasoning')."""
    trace_id = "test-trace-123"
    user_message = "Test message"

    # Mock Opus response with incomplete JSON (missing required 'reasoning' field)
    mock_response = """{"tasks": []}"""  # Missing reasoning (required field)

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify fallback behavior - should fall back due to validation error
        assert isinstance(task_plan, TaskPlan)
        assert task_plan.reasoning == "Task planning failed, responding directly"
        assert task_plan.direct_response is not None


@pytest.mark.asyncio
async def test_format_context_for_planning(orchestrator, sample_enriched_context):
    """Test that context is formatted into a readable string."""
    formatted = orchestrator._format_context_for_planning(sample_enriched_context)

    # Verify all sections are present
    assert "RECENT CONVERSATION:" in formatted
    assert "RECENT THREADS:" in formatted
    assert "PENDING TASKS:" in formatted
    assert "RECENTLY MENTIONED:" in formatted
    assert "KNOWLEDGE AREAS:" in formatted

    # Verify content
    assert "Hello" in formatted  # From messages
    assert "Discussed Sarah's new job" in formatted  # From summaries
    assert "Email Sarah" in formatted  # From pending tasks
    assert "Sarah Johnson" in formatted  # From entities
    assert "Work Island" in formatted  # From islands


@pytest.mark.asyncio
async def test_format_context_for_planning_empty(orchestrator):
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

    formatted = orchestrator._format_context_for_planning(empty_context)

    # Should return fallback message
    assert formatted == "No additional context available."


@pytest.mark.asyncio
async def test_format_context_truncates_long_content(orchestrator):
    """Test that long messages and summaries are truncated."""
    long_message = "A" * 300  # Longer than 200 char limit
    long_summary = ThreadSummary(
        summary="B" * 150,  # Will be truncated to 100
        topics=["test"],
        participants=["Test"],
    )

    context = EnrichedContext(
        thread_uuid="thread-123",
        channel_type=ChannelType.CLI,
        messages=[{"role": "user", "content": long_message}],
        recent_summaries=[long_summary],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )

    formatted = orchestrator._format_context_for_planning(context)

    # Verify truncation
    assert (
        len([line for line in formatted.split("\n") if "A" * 200 in line]) > 0
    )  # Message truncated
    assert "B" * 150 not in formatted  # Summary truncated to 100 chars


@pytest.mark.asyncio
async def test_parse_task_plan_raw_json(orchestrator):
    """Test parsing raw JSON without markdown code blocks."""
    trace_id = "test-trace-123"
    raw_json = """{
  "reasoning": "Test reasoning",
  "tasks": [],
  "direct_response": "Test response"
}"""

    task_plan = orchestrator._parse_task_plan(raw_json, trace_id)

    assert isinstance(task_plan, TaskPlan)
    assert task_plan.reasoning == "Test reasoning"
    assert len(task_plan.tasks) == 0
    assert task_plan.direct_response == "Test response"


@pytest.mark.asyncio
async def test_parse_task_plan_markdown_json(orchestrator):
    """Test parsing JSON within markdown code blocks."""
    trace_id = "test-trace-123"
    markdown_json = """Here's the plan:
```json
{
  "reasoning": "Test reasoning",
  "tasks": [],
  "direct_response": null
}
```
"""

    task_plan = orchestrator._parse_task_plan(markdown_json, trace_id)

    assert isinstance(task_plan, TaskPlan)
    assert task_plan.reasoning == "Test reasoning"
    assert task_plan.direct_response is None


@pytest.mark.asyncio
async def test_call_opus_for_planning(orchestrator):
    """Test that Opus is called with correct parameters."""
    trace_id = "test-trace-123"
    prompt = "Test prompt"

    # Mock the Anthropic client
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text='{"reasoning": "test", "tasks": []}')]

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.return_value = mock_message

    # Patch the _anthropic property directly
    orchestrator._anthropic = mock_anthropic

    await orchestrator._call_opus_for_planning(prompt, trace_id)

    # Verify Anthropic was called correctly
    mock_anthropic.messages.create.assert_called_once()
    call_args = mock_anthropic.messages.create.call_args[1]

    assert call_args["model"] == "claude-opus-4-5-20251101"
    assert call_args["max_tokens"] == 2000
    assert call_args["messages"][0]["role"] == "user"
    assert call_args["messages"][0]["content"] == prompt


@pytest.mark.asyncio
async def test_plan_tasks_reasoning_logged(orchestrator, sample_enriched_context):
    """Test that LLM reasoning is logged in the task plan."""
    trace_id = "test-trace-123"
    user_message = "Test message"

    mock_response = """{
  "reasoning": "This is detailed reasoning about the task plan",
  "tasks": [],
  "direct_response": "Test"
}"""

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify reasoning is captured
        assert task_plan.reasoning == "This is detailed reasoning about the task plan"


@pytest.mark.asyncio
async def test_plan_tasks_with_complex_payload(orchestrator, sample_enriched_context):
    """Test that complex payload structures are preserved."""
    trace_id = "test-trace-123"
    user_message = "Test message"

    mock_response = """{
  "reasoning": "Complex task with nested payload",
  "tasks": [
    {
      "task_type": "execute",
      "description": "Create calendar event",
      "agent": "executor",
      "payload": {
        "action": "calendar_create",
        "params": {
          "title": "Meeting with Sarah",
          "start_time": "2026-01-20T10:00:00",
          "attendees": ["sarah@example.com", "john@example.com"]
        }
      },
      "blocking": true
    }
  ],
  "direct_response": null
}"""

    with patch.object(
        orchestrator, "_call_opus_for_planning", new=AsyncMock(return_value=mock_response)
    ):
        task_plan = await orchestrator._plan_tasks(user_message, sample_enriched_context, trace_id)

        # Verify complex payload is preserved
        assert len(task_plan.tasks) == 1
        task = task_plan.tasks[0]
        assert task.payload["action"] == "calendar_create"
        assert "params" in task.payload
        assert task.payload["params"]["title"] == "Meeting with Sarah"
        assert isinstance(task.payload["params"]["attendees"], list)
        assert len(task.payload["params"]["attendees"]) == 2
