"""
Unit tests for Orchestrator v2 Task Planning.

Reference: specs/MAINAGENT.md Section 4.3
Task: T080 - Unit Tests for Task Planning

Tests the Think phase of Think-Dispatch-Synthesize pattern with mocked LLM responses.
Validates task decomposition, blocking/non-blocking task assignment, and error handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import (
    ChannelType,
    EnrichedContext,
    PlannedTask,
    TaskPlan,
)


def mock_task_plan_response(
    reasoning: str,
    tasks: list[dict] | None = None,
    direct_response: str | None = None,
) -> str:
    """Helper to create mock LLM task planning response JSON.

    Args:
        reasoning: LLM's reasoning about what tasks are needed
        tasks: List of task dictionaries with task_type, description, agent, payload, blocking
        direct_response: Optional direct response if no tasks needed

    Returns:
        JSON string matching TaskPlan schema
    """
    return json.dumps(
        {
            "reasoning": reasoning,
            "tasks": tasks or [],
            "direct_response": direct_response,
        }
    )


@pytest.fixture
def mock_orchestrator():
    """Create an Orchestrator instance with mocked dependencies."""
    with patch.object(Orchestrator, "__init__", lambda _: None):
        orch = Orchestrator()
        orch.config = MagicMock()
        orch.config_v2 = MagicMock()
        orch._anthropic = MagicMock()  # Mock the private attribute, not the property
        orch.name = "orchestrator"
        orch.TASK_PLANNING_PROMPT = Orchestrator.TASK_PLANNING_PROMPT
        # Mock the LLM call method
        orch._call_opus_for_planning = AsyncMock()
        # Mock skill planner (returns None for no skill match)
        orch._skill_planner = MagicMock()
        orch._skill_planner.match_and_plan = MagicMock(return_value=None)
        # Use real parsing and formatting methods
        orch._parse_task_plan = Orchestrator._parse_task_plan.__get__(orch)
        orch._format_context_for_planning = Orchestrator._format_context_for_planning.__get__(orch)
        return orch


@pytest.fixture
def empty_context():
    """Create minimal EnrichedContext for testing."""
    return EnrichedContext(
        thread_uuid="test-thread-001",
        channel_type=ChannelType.CLI,
        messages=[],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )


@pytest.fixture
def context_with_messages():
    """Create EnrichedContext with conversation history."""
    return EnrichedContext(
        thread_uuid="test-thread-002",
        channel_type=ChannelType.CLI,
        messages=[
            {"role": "user", "content": "I met Sarah from Acme yesterday"},
            {"role": "assistant", "content": "Got it, I've noted that Sarah works at Acme."},
        ],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
        relevant_islands=None,
    )


class TestTaskPlanning:
    """Test suite for _plan_tasks() method."""

    # =========================================================================
    # Multi-Intent Message Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_multi_intent_message(self, mock_orchestrator, empty_context):
        """Multi-intent message should produce multiple tasks with correct types.

        When user provides information AND asks questions AND requests actions,
        the planner should decompose into separate ingest/research/execute tasks.
        """
        mock_response = mock_task_plan_response(
            reasoning="User is telling me about Sarah (ingest), asking about meetings (execute), "
            "and asking about food preferences (research)",
            tasks=[
                {
                    "task_type": "ingest",
                    "description": "Store fact that Sarah studied at Harvard",
                    "agent": "ingestor",
                    "payload": {"text": "Sarah studied at Harvard"},
                    "blocking": False,
                },
                {
                    "task_type": "execute",
                    "description": "Check calendar for next week's meetings",
                    "agent": "executor",
                    "payload": {"action": "calendar_search", "timeframe": "next week"},
                    "blocking": True,
                },
                {
                    "task_type": "research",
                    "description": "Search for Sarah's food preferences",
                    "agent": "researcher",
                    "payload": {"query": "Sarah food preferences"},
                    "blocking": True,
                },
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Learned Sarah studied at Harvard. Any meetings next week? Does she like Italian food?",
            empty_context,
            "trace-001",
        )

        assert len(plan.tasks) == 3
        assert plan.tasks[0].task_type == "ingest"
        assert plan.tasks[0].agent == "ingestor"
        assert plan.tasks[0].blocking is False  # Ingest is fire-and-forget
        assert plan.tasks[1].task_type == "execute"
        assert plan.tasks[1].blocking is True  # Execute needs result
        assert plan.tasks[2].task_type == "research"
        assert plan.tasks[2].blocking is True  # Research needs result
        assert plan.direct_response is None

    @pytest.mark.asyncio
    async def test_single_intent_message(self, mock_orchestrator, empty_context):
        """Simple single-intent message should produce one task."""
        mock_response = mock_task_plan_response(
            reasoning="User asking a factual question about known entity Sarah",
            tasks=[
                {
                    "task_type": "research",
                    "description": "Search for information about Sarah",
                    "agent": "researcher",
                    "payload": {"query": "Who is Sarah?"},
                    "blocking": True,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Who is Sarah?",
            empty_context,
            "trace-002",
        )

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_type == "research"
        assert plan.tasks[0].agent == "researcher"
        assert plan.direct_response is None

    # =======================================================================
    # Direct Response Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_greeting_direct_response(self, mock_orchestrator, empty_context):
        """Simple greeting should return direct response without tasks."""
        mock_response = mock_task_plan_response(
            reasoning="Simple greeting, no tasks or information needed",
            tasks=[],
            direct_response="Ahoy! How can I help you today?",
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Hello!",
            empty_context,
            "trace-003",
        )

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None
        assert "Ahoy" in plan.direct_response or "help" in plan.direct_response.lower()

    @pytest.mark.asyncio
    async def test_acknowledgment_direct_response(self, mock_orchestrator, empty_context):
        """Acknowledgment should get direct response."""
        mock_response = mock_task_plan_response(
            reasoning="User expressing gratitude, no action needed",
            tasks=[],
            direct_response="You're welcome! Let me know if you need anything else.",
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Thanks for the help!",
            empty_context,
            "trace-004",
        )

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    # =========================================================================
    # Task Type Classification Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_task_type_classification_ingest(self, mock_orchestrator, empty_context):
        """Ingestion tasks should be correctly classified."""
        mock_response = mock_task_plan_response(
            reasoning="User sharing new information about a person and organization",
            tasks=[
                {
                    "task_type": "ingest",
                    "description": "Store information about John and Acme Corp",
                    "agent": "ingestor",
                    "payload": {"text": "I met John from Acme Corp, he's a PM"},
                    "blocking": False,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "I met John from Acme Corp, he's a PM",
            empty_context,
            "trace-005",
        )

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_type == "ingest"
        assert plan.tasks[0].agent == "ingestor"

    @pytest.mark.asyncio
    async def test_task_type_classification_research(self, mock_orchestrator, empty_context):
        """Research tasks should be correctly classified."""
        mock_response = mock_task_plan_response(
            reasoning="User asking for information retrieval from knowledge graph",
            tasks=[
                {
                    "task_type": "research",
                    "description": "Find all information about Project Alpha",
                    "agent": "researcher",
                    "payload": {"query": "Project Alpha status"},
                    "blocking": True,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "What is the status of Project Alpha?",
            empty_context,
            "trace-006",
        )

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_type == "research"
        assert plan.tasks[0].agent == "researcher"

    @pytest.mark.asyncio
    async def test_task_type_classification_execute(self, mock_orchestrator, empty_context):
        """Execute tasks should be correctly classified."""
        mock_response = mock_task_plan_response(
            reasoning="User wants to send email, requires Executor agent with MCP",
            tasks=[
                {
                    "task_type": "execute",
                    "description": "Send email to John about the meeting",
                    "agent": "executor",
                    "payload": {
                        "action": "email_send",
                        "recipient": "John",
                        "subject": "Meeting follow-up",
                    },
                    "blocking": True,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Send an email to John about the meeting",
            empty_context,
            "trace-007",
        )

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_type == "execute"
        assert plan.tasks[0].agent == "executor"

    # =========================================================================
    # Blocking Flag Assignment Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_blocking_flag_assignment(self, mock_orchestrator, empty_context):
        """Ingest tasks should be non-blocking, research/execute should be blocking."""
        mock_response = mock_task_plan_response(
            reasoning="Mix of ingest (background), research (needs result), execute (needs result)",
            tasks=[
                {
                    "task_type": "ingest",
                    "description": "Store meeting notes",
                    "agent": "ingestor",
                    "payload": {"text": "Met with Sarah about Q4 budget"},
                    "blocking": False,
                },
                {
                    "task_type": "research",
                    "description": "Find Sarah's email",
                    "agent": "researcher",
                    "payload": {"query": "Sarah email"},
                    "blocking": True,
                },
                {
                    "task_type": "execute",
                    "description": "Check calendar availability",
                    "agent": "executor",
                    "payload": {"action": "calendar_list"},
                    "blocking": True,
                },
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Met with Sarah about Q4 budget. What's her email? Check my calendar.",
            empty_context,
            "trace-008",
        )

        # Verify blocking flags
        ingest_task = next(t for t in plan.tasks if t.task_type == "ingest")
        research_task = next(t for t in plan.tasks if t.task_type == "research")
        execute_task = next(t for t in plan.tasks if t.task_type == "execute")

        assert ingest_task.blocking is False
        assert research_task.blocking is True
        assert execute_task.blocking is True

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_malformed_json_fallback(self, mock_orchestrator, empty_context):
        """Malformed LLM response should trigger fallback plan."""
        mock_orchestrator._call_opus_for_planning.return_value = "This is not JSON at all"

        plan = await mock_orchestrator._plan_tasks(
            "Test message",
            empty_context,
            "trace-009",
        )

        # Should fall back to direct response
        assert len(plan.tasks) == 0
        assert plan.direct_response is not None
        assert "trouble" in plan.direct_response.lower() or "again" in plan.direct_response.lower()

    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self, mock_orchestrator, empty_context):
        """LLM timeout should trigger fallback plan."""

        mock_orchestrator._call_opus_for_planning.side_effect = TimeoutError("LLM took too long")

        plan = await mock_orchestrator._plan_tasks(
            "Test message",
            empty_context,
            "trace-010",
        )

        # Should fall back to direct response
        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self, mock_orchestrator, empty_context):
        """Generic LLM exception should trigger fallback."""
        mock_orchestrator._call_opus_for_planning.side_effect = Exception("API Error")

        plan = await mock_orchestrator._plan_tasks(
            "Test message",
            empty_context,
            "trace-011",
        )

        # Should fall back to direct response
        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    @pytest.mark.asyncio
    async def test_empty_message_handling(self, mock_orchestrator, empty_context):
        """Empty or whitespace-only message should be handled gracefully."""
        mock_response = mock_task_plan_response(
            reasoning="Empty message, nothing to do",
            tasks=[],
            direct_response="I didn't catch that. What would you like me to do?",
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "",
            empty_context,
            "trace-012",
        )

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    # =========================================================================
    # Context Integration Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_prompt_includes_context(self, mock_orchestrator, context_with_messages):
        """Planning prompt should include enriched context."""
        mock_response = mock_task_plan_response(
            reasoning="Using context about Sarah to answer follow-up question",
            tasks=[
                {
                    "task_type": "research",
                    "description": "Find Sarah's role at Acme",
                    "agent": "researcher",
                    "payload": {"query": "Sarah Acme role"},
                    "blocking": True,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        await mock_orchestrator._plan_tasks(
            "What's Sarah's role at Acme?",
            context_with_messages,
            "trace-013",
        )

        # Verify the LLM was called with context
        mock_orchestrator._call_opus_for_planning.assert_called_once()
        call_args = mock_orchestrator._call_opus_for_planning.call_args[0][0]

        # Prompt should include context section
        assert "CURRENT CONTEXT:" in call_args or "RECENT CONVERSATION:" in call_args

    # =========================================================================
    # JSON Parsing Edge Cases
    # =========================================================================

    @pytest.mark.asyncio
    async def test_handles_markdown_code_block(self, mock_orchestrator, empty_context):
        """Should handle LLM response wrapped in markdown code block."""
        mock_response = f"""```json
{mock_task_plan_response(
    reasoning="Test reasoning",
    tasks=[
        {
            "task_type": "research",
            "description": "Test task",
            "agent": "researcher",
            "payload": {"query": "test"},
            "blocking": True,
        }
    ],
)}
```"""

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Who is Sarah?",
            empty_context,
            "trace-014",
        )

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_type == "research"

    @pytest.mark.asyncio
    async def test_handles_json_with_extra_text(self, mock_orchestrator, empty_context):
        """Should extract JSON from response with surrounding text."""
        mock_response = f"""
Here's my analysis:

{mock_task_plan_response(
    reasoning="Test reasoning",
    tasks=[],
    direct_response="Simple greeting response",
)}

That's my recommendation.
"""

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Hello",
            empty_context,
            "trace-015",
        )

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    # =========================================================================
    # Task Plan Model Validation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_task_plan_model_validation(self, mock_orchestrator, empty_context):
        """TaskPlan should validate all required fields."""
        mock_response = mock_task_plan_response(
            reasoning="Test validation",
            tasks=[
                {
                    "task_type": "ingest",
                    "description": "Test description",
                    "agent": "ingestor",
                    "payload": {"text": "test"},
                    "blocking": False,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Test",
            empty_context,
            "trace-016",
        )

        assert isinstance(plan, TaskPlan)
        assert hasattr(plan, "reasoning")
        assert hasattr(plan, "tasks")
        assert hasattr(plan, "direct_response")
        assert isinstance(plan.tasks, list)
        assert all(isinstance(t, PlannedTask) for t in plan.tasks)

    @pytest.mark.asyncio
    async def test_planned_task_model_fields(self, mock_orchestrator, empty_context):
        """PlannedTask should have all required fields."""
        mock_response = mock_task_plan_response(
            reasoning="Test task fields",
            tasks=[
                {
                    "task_type": "research",
                    "description": "Find information about Sarah",
                    "agent": "researcher",
                    "payload": {"query": "Sarah"},
                    "blocking": True,
                }
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Who is Sarah?",
            empty_context,
            "trace-017",
        )

        task = plan.tasks[0]
        assert task.task_type in ["ingest", "research", "execute"]
        assert task.agent in ["ingestor", "researcher", "executor"]
        assert isinstance(task.description, str)
        assert isinstance(task.payload, dict)
        assert isinstance(task.blocking, bool)

    # =========================================================================
    # Complex Scenario Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_complex_multi_step_workflow(self, mock_orchestrator, empty_context):
        """Complex message should decompose into logical workflow."""
        mock_response = mock_task_plan_response(
            reasoning="User wants to: 1) Store meeting notes, 2) Find John's email, "
            "3) Send him a follow-up",
            tasks=[
                {
                    "task_type": "ingest",
                    "description": "Store meeting notes about Q4 planning",
                    "agent": "ingestor",
                    "payload": {"text": "Met with John to discuss Q4 planning and budget"},
                    "blocking": False,
                },
                {
                    "task_type": "research",
                    "description": "Find John's email address",
                    "agent": "researcher",
                    "payload": {"query": "John email"},
                    "blocking": True,
                },
                {
                    "task_type": "execute",
                    "description": "Send follow-up email to John",
                    "agent": "executor",
                    "payload": {
                        "action": "email_send",
                        "recipient": "John",
                        "subject": "Q4 Planning Follow-up",
                    },
                    "blocking": True,
                },
            ],
        )

        mock_orchestrator._call_opus_for_planning.return_value = mock_response

        plan = await mock_orchestrator._plan_tasks(
            "Met with John to discuss Q4 planning. Send him a follow-up email about the budget.",
            empty_context,
            "trace-018",
        )

        assert len(plan.tasks) == 3
        # Ingest happens in background
        assert plan.tasks[0].task_type == "ingest"
        assert plan.tasks[0].blocking is False
        # Research and execute are blocking
        assert all(t.blocking for t in plan.tasks[1:])
