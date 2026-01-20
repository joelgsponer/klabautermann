"""
Smoke tests for ingestion payload validation.

These tests verify that the Orchestrator properly validates and fixes
ingest task payloads before dispatching to the Ingestor, ensuring the
'text' field is always present.

Reference: CLAUDE.md testing philosophy
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import PlannedTask, TaskPlan


class TestIngestionPayloadValidation:
    """Verify ingest task payloads are validated and fixed."""

    @pytest.fixture
    def mock_orchestrator(self) -> Orchestrator:
        """Create Orchestrator with mocked dependencies."""
        mock_graphiti = MagicMock()
        mock_thread_manager = MagicMock()
        mock_thread_manager.get_or_create_thread = AsyncMock(return_value="test-thread-uuid")
        mock_thread_manager.add_message = AsyncMock(return_value="test-msg-uuid")

        orchestrator = Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_manager,
            config={"model": {"primary": "claude-sonnet-4-20250514"}},
        )

        # Mock agent registry with ingestor
        mock_ingestor = MagicMock()
        mock_ingestor.process_message = AsyncMock(return_value={"status": "ingested"})
        orchestrator._agent_registry = {
            "ingestor": mock_ingestor,
            "researcher": MagicMock(),
            "executor": MagicMock(),
        }

        return orchestrator

    @pytest.mark.asyncio
    async def test_ingest_task_with_text_passes_through(
        self,
        mock_orchestrator: Orchestrator,
    ) -> None:
        """Ingest tasks with 'text' field are used as-is."""
        original_text = "I met Sarah from Acme Corp"
        task_plan = TaskPlan(
            reasoning="User mentioned a new contact",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store new contact",
                    agent="ingestor",
                    payload={"text": "Sarah works at Acme Corp"},  # Has text
                    blocking=False,
                ),
            ],
            direct_response=None,
        )

        await mock_orchestrator._execute_parallel(
            task_plan, "test-trace", original_text=original_text
        )

        # Payload should still have original text value
        assert task_plan.tasks[0].payload["text"] == "Sarah works at Acme Corp"

    @pytest.mark.asyncio
    async def test_ingest_task_without_text_gets_fallback(
        self,
        mock_orchestrator: Orchestrator,
    ) -> None:
        """Ingest tasks missing 'text' get original message as fallback."""
        original_text = "I met Sarah from Acme Corp today"
        task_plan = TaskPlan(
            reasoning="User mentioned a new contact",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store new contact",
                    agent="ingestor",
                    payload={"content": "Sarah"},  # Wrong key - missing 'text'
                    blocking=False,
                ),
            ],
            direct_response=None,
        )

        await mock_orchestrator._execute_parallel(
            task_plan, "test-trace", original_text=original_text
        )

        # Payload should now have 'text' with original message
        assert task_plan.tasks[0].payload["text"] == original_text
        assert task_plan.tasks[0].payload["content"] == "Sarah"  # Original key preserved

    @pytest.mark.asyncio
    async def test_ingest_task_with_empty_text_gets_fallback(
        self,
        mock_orchestrator: Orchestrator,
    ) -> None:
        """Ingest tasks with empty 'text' get original message as fallback."""
        original_text = "I learned that John is the CEO of TechCorp"
        task_plan = TaskPlan(
            reasoning="User mentioned company leadership",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store leadership info",
                    agent="ingestor",
                    payload={"text": ""},  # Empty text
                    blocking=False,
                ),
            ],
            direct_response=None,
        )

        await mock_orchestrator._execute_parallel(
            task_plan, "test-trace", original_text=original_text
        )

        # Payload should now have 'text' with original message
        assert task_plan.tasks[0].payload["text"] == original_text

    @pytest.mark.asyncio
    async def test_research_task_payload_not_modified(
        self,
        mock_orchestrator: Orchestrator,
    ) -> None:
        """Research task payloads are not modified (no 'text' fallback)."""
        # Add mock researcher
        mock_researcher = MagicMock()
        mock_researcher.process_message = AsyncMock(return_value={"results": []})
        mock_orchestrator._agent_registry["researcher"] = mock_researcher

        original_text = "Who is Sarah?"
        task_plan = TaskPlan(
            reasoning="User asking about a person",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Find Sarah",
                    agent="researcher",
                    payload={"query": "Sarah"},  # Research uses 'query', not 'text'
                    blocking=True,
                ),
            ],
            direct_response=None,
        )

        await mock_orchestrator._execute_parallel(
            task_plan, "test-trace", original_text=original_text
        )

        # Research payload should NOT have 'text' added
        assert "text" not in task_plan.tasks[0].payload
        assert task_plan.tasks[0].payload["query"] == "Sarah"

    @pytest.mark.asyncio
    async def test_multiple_ingest_tasks_all_validated(
        self,
        mock_orchestrator: Orchestrator,
    ) -> None:
        """Multiple ingest tasks all get validated and fixed."""
        original_text = "I met John (CEO) and Sarah (CTO) from Acme Corp"
        task_plan = TaskPlan(
            reasoning="User mentioned multiple contacts",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store John as CEO",
                    agent="ingestor",
                    payload={},  # Empty payload
                    blocking=False,
                ),
                PlannedTask(
                    task_type="ingest",
                    description="Store Sarah as CTO",
                    agent="ingestor",
                    payload={"person": "Sarah"},  # Wrong key
                    blocking=False,
                ),
                PlannedTask(
                    task_type="ingest",
                    description="Store Acme Corp",
                    agent="ingestor",
                    payload={"text": "Acme Corp is a tech company"},  # Correct
                    blocking=False,
                ),
            ],
            direct_response=None,
        )

        await mock_orchestrator._execute_parallel(
            task_plan, "test-trace", original_text=original_text
        )

        # All ingest tasks should have 'text' field
        for task in task_plan.tasks:
            assert "text" in task.payload, f"Task '{task.description}' missing text"

        # First two should have fallback, third should keep original
        assert task_plan.tasks[0].payload["text"] == original_text
        assert task_plan.tasks[1].payload["text"] == original_text
        assert task_plan.tasks[2].payload["text"] == "Acme Corp is a tech company"


class TestTaskPlanningPromptSchema:
    """Verify TASK_PLANNING_PROMPT documents payload schemas."""

    def test_prompt_includes_ingest_payload_schema(self) -> None:
        """TASK_PLANNING_PROMPT documents ingest payload format."""
        assert "ingest tasks:" in Orchestrator.TASK_PLANNING_PROMPT.lower()
        assert '"text"' in Orchestrator.TASK_PLANNING_PROMPT

    def test_prompt_includes_research_payload_schema(self) -> None:
        """TASK_PLANNING_PROMPT documents research payload format."""
        assert "research tasks:" in Orchestrator.TASK_PLANNING_PROMPT.lower()
        assert '"query"' in Orchestrator.TASK_PLANNING_PROMPT

    def test_prompt_includes_execute_payload_schema(self) -> None:
        """TASK_PLANNING_PROMPT documents execute payload format."""
        assert "execute tasks:" in Orchestrator.TASK_PLANNING_PROMPT.lower()
        assert '"action_type"' in Orchestrator.TASK_PLANNING_PROMPT
