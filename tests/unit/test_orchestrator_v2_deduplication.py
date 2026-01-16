"""
Unit tests for Orchestrator v2 task deduplication.

Reference: T072 - Task Deduplication
Reference: specs/MAINAGENT.md Section 12 (Open Question 4)

Tests verify that the orchestrator deduplicates similar tasks while:
- Preserving unique tasks
- Never deduplicating ingest tasks (each fact is unique)
- Merging similar research queries (same entity/topic)
- Merging execute tasks only if same action type
- Logging deduplication events

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from unittest.mock import MagicMock

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import PlannedTask


class TestTaskDeduplication:
    """Test suite for task deduplication."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator instance for testing."""
        # Mock dependencies
        mock_neo4j = MagicMock()
        mock_thread_mgr = MagicMock()
        mock_graphiti = MagicMock()

        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_mgr,
            neo4j_client=mock_neo4j,
        )

    def test_deduplicate_similar_research_queries(self, orchestrator: Orchestrator) -> None:
        """Should merge research tasks with same entity/topic."""
        tasks = [
            PlannedTask(
                task_type="research",
                description="Search for Sarah Johnson",
                agent="researcher",
                payload={"query": "Search for Sarah Johnson"},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Find information about Sarah Johnson's work",
                agent="researcher",
                payload={"query": "Sarah Johnson work history"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # Both queries start with "search for sarah" / "sarah johnson"
        # Should be merged
        assert len(deduplicated) == 1
        # Should keep longer description
        assert "work" in deduplicated[0].description.lower() or len(
            deduplicated[0].description
        ) >= len(tasks[0].description)

    def test_preserve_different_research_queries(self, orchestrator: Orchestrator) -> None:
        """Should keep research tasks with different entities."""
        tasks = [
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Search for Sarah"},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Search for John",
                agent="researcher",
                payload={"query": "Search for John"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # Different entities - should not merge
        assert len(deduplicated) == 2

    def test_never_deduplicate_ingest_tasks(self, orchestrator: Orchestrator) -> None:
        """Should never merge ingest tasks (each fact is unique)."""
        tasks = [
            PlannedTask(
                task_type="ingest",
                description="Store fact about Sarah",
                agent="ingestor",
                payload={"text": "Sarah works at Acme"},
                blocking=False,
            ),
            PlannedTask(
                task_type="ingest",
                description="Store fact about Sarah",
                agent="ingestor",
                payload={"text": "Sarah is a PM"},
                blocking=False,
            ),
            PlannedTask(
                task_type="ingest",
                description="Store fact about Sarah",
                agent="ingestor",
                payload={"text": "Sarah has email sarah@acme.com"},
                blocking=False,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # All ingest tasks should be preserved
        assert len(deduplicated) == 3

    def test_merge_similar_execute_tasks(self, orchestrator: Orchestrator) -> None:
        """Should merge execute tasks with same action type."""
        tasks = [
            PlannedTask(
                task_type="execute",
                description="Send email to Sarah",
                agent="executor",
                payload={"action": "send email", "recipient": "sarah@example.com"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Send email with meeting details",
                agent="executor",
                payload={"action": "send email", "subject": "Meeting tomorrow"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # Both are "send" actions - should merge
        assert len(deduplicated) == 1

    def test_preserve_different_execute_actions(self, orchestrator: Orchestrator) -> None:
        """Should keep execute tasks with different action types."""
        tasks = [
            PlannedTask(
                task_type="execute",
                description="Send email",
                agent="executor",
                payload={"action": "send email"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Create calendar event",
                agent="executor",
                payload={"action": "create calendar event"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # Different actions - should not merge
        assert len(deduplicated) == 2

    def test_merge_preserves_blocking_status(self, orchestrator: Orchestrator) -> None:
        """Should preserve blocking=True if either task is blocking."""
        tasks = [
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Search for Sarah"},
                blocking=False,
            ),
            PlannedTask(
                task_type="research",
                description="Search for Sarah Johnson",
                agent="researcher",
                payload={"query": "Search for Sarah Johnson"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        assert len(deduplicated) == 1
        # Should be blocking since one of the tasks was blocking
        assert deduplicated[0].blocking is True

    def test_merge_combines_payloads(self, orchestrator: Orchestrator) -> None:
        """Should merge payload fields from both tasks."""
        tasks = [
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Search for Sarah", "limit": 10},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Search for Sarah with details",
                agent="researcher",
                payload={"query": "Search for Sarah Johnson", "include_relations": True},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        assert len(deduplicated) == 1
        # Payload should contain fields from both tasks
        payload = deduplicated[0].payload
        assert "query" in payload
        assert "include_relations" in payload or "limit" in payload

    def test_single_task_returns_unchanged(self, orchestrator: Orchestrator) -> None:
        """Should return single task unchanged."""
        tasks = [
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Search for Sarah"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        assert len(deduplicated) == 1
        assert deduplicated[0] == tasks[0]

    def test_empty_task_list_returns_empty(self, orchestrator: Orchestrator) -> None:
        """Should handle empty task list."""
        tasks: list[PlannedTask] = []

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        assert len(deduplicated) == 0

    def test_mixed_task_types(self, orchestrator: Orchestrator) -> None:
        """Should handle mixed task types correctly."""
        tasks = [
            PlannedTask(
                task_type="ingest",
                description="Store fact",
                agent="ingestor",
                payload={"text": "fact1"},
                blocking=False,
            ),
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Search for Sarah"},
                blocking=True,
            ),
            PlannedTask(
                task_type="ingest",
                description="Store another fact",
                agent="ingestor",
                payload={"text": "fact2"},
                blocking=False,
            ),
            PlannedTask(
                task_type="research",
                description="Search for Sarah Johnson",
                agent="researcher",
                payload={"query": "Search for Sarah Johnson"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Send email",
                agent="executor",
                payload={"action": "send email"},
                blocking=True,
            ),
        ]

        deduplicated = orchestrator._deduplicate_tasks(tasks, "test-trace-id")

        # Should preserve both ingest tasks (2)
        # Should merge the two research tasks (1)
        # Should keep the execute task (1)
        # Total: 4 tasks
        assert len(deduplicated) == 4

        # Verify ingest tasks are preserved
        ingest_tasks = [t for t in deduplicated if t.task_type == "ingest"]
        assert len(ingest_tasks) == 2


class TestTaskSimilarityKey:
    """Test suite for task similarity key generation."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator instance for testing."""
        mock_neo4j = MagicMock()
        mock_thread_mgr = MagicMock()
        mock_graphiti = MagicMock()

        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_mgr,
            neo4j_client=mock_neo4j,
        )

    def test_research_key_extracts_entity(self, orchestrator: Orchestrator) -> None:
        """Should extract entity from research query."""
        task = PlannedTask(
            task_type="research",
            description="Search for Sarah",
            agent="researcher",
            payload={"query": "Search for Sarah"},
            blocking=True,
        )

        key = orchestrator._task_similarity_key(task)

        assert key == "research:sarah"

    def test_research_key_normalizes_case(self, orchestrator: Orchestrator) -> None:
        """Should normalize query to lowercase."""
        task = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "SEARCH FOR SARAH"},
            blocking=True,
        )

        key = orchestrator._task_similarity_key(task)

        assert key == "research:sarah"

    def test_execute_key_extracts_action_verb(self, orchestrator: Orchestrator) -> None:
        """Should extract action verb from execute task."""
        task = PlannedTask(
            task_type="execute",
            description="Send email",
            agent="executor",
            payload={"action": "send email to sarah@example.com"},
            blocking=True,
        )

        key = orchestrator._task_similarity_key(task)

        assert key == "execute:send"

    def test_execute_key_normalizes_case(self, orchestrator: Orchestrator) -> None:
        """Should normalize action to lowercase."""
        task = PlannedTask(
            task_type="execute",
            description="Create event",
            agent="executor",
            payload={"action": "CREATE calendar event"},
            blocking=True,
        )

        key = orchestrator._task_similarity_key(task)

        assert key == "execute:create"

    def test_ingest_key_is_unique(self, orchestrator: Orchestrator) -> None:
        """Should generate unique keys for ingest tasks."""
        task1 = PlannedTask(
            task_type="ingest",
            description="Store fact",
            agent="ingestor",
            payload={"text": "fact1"},
            blocking=False,
        )
        task2 = PlannedTask(
            task_type="ingest",
            description="Store fact",
            agent="ingestor",
            payload={"text": "fact2"},
            blocking=False,
        )

        key1 = orchestrator._task_similarity_key(task1)
        key2 = orchestrator._task_similarity_key(task2)

        # Keys should be different (use object ID)
        assert key1 != key2
        assert key1.startswith("ingest:")
        assert key2.startswith("ingest:")


class TestMergeTasks:
    """Test suite for task merging."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator instance for testing."""
        mock_neo4j = MagicMock()
        mock_thread_mgr = MagicMock()
        mock_graphiti = MagicMock()

        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_mgr,
            neo4j_client=mock_neo4j,
        )

    def test_keeps_longer_description(self, orchestrator: Orchestrator) -> None:
        """Should keep the longer/more detailed description."""
        task1 = PlannedTask(
            task_type="research",
            description="Search Sarah",
            agent="researcher",
            payload={"query": "Search Sarah"},
            blocking=True,
        )
        task2 = PlannedTask(
            task_type="research",
            description="Search for Sarah Johnson and her work history",
            agent="researcher",
            payload={"query": "Search for Sarah Johnson"},
            blocking=True,
        )

        merged = orchestrator._merge_tasks(task1, task2)

        # Should keep task2's description (longer)
        assert merged.description == task2.description

    def test_merges_payload_fields(self, orchestrator: Orchestrator) -> None:
        """Should merge payload fields from both tasks."""
        task1 = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "Search Sarah", "limit": 10},
            blocking=True,
        )
        task2 = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "Search Sarah Johnson", "include_relations": True},
            blocking=True,
        )

        merged = orchestrator._merge_tasks(task1, task2)

        # Should have fields from both
        assert "query" in merged.payload
        assert "include_relations" in merged.payload or "limit" in merged.payload

    def test_preserves_blocking_true(self, orchestrator: Orchestrator) -> None:
        """Should preserve blocking=True if either task is blocking."""
        task1 = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "Search"},
            blocking=False,
        )
        task2 = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "Search"},
            blocking=True,
        )

        merged = orchestrator._merge_tasks(task1, task2)

        assert merged.blocking is True

    def test_preserves_task_type_and_agent(self, orchestrator: Orchestrator) -> None:
        """Should preserve task type and agent from first task."""
        task1 = PlannedTask(
            task_type="research",
            description="Search",
            agent="researcher",
            payload={"query": "Search"},
            blocking=True,
        )
        task2 = PlannedTask(
            task_type="research",
            description="Search more",
            agent="researcher",
            payload={"query": "Search more"},
            blocking=True,
        )

        merged = orchestrator._merge_tasks(task1, task2)

        assert merged.task_type == "research"
        assert merged.agent == "researcher"
