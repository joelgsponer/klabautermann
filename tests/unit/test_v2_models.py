"""
Unit tests for Orchestrator v2 Pydantic models.

Tests the new models used in the Think-Dispatch-Synthesize workflow.
Reference: specs/MAINAGENT.md
"""

import json

import pytest
from pydantic import ValidationError

from klabautermann.core.models import (
    ChannelType,
    CommunityContext,
    EnrichedContext,
    EntityReference,
    PlannedTask,
    TaskNode,
    TaskPlan,
    TaskStatus,
    ThreadSummary,
)


class TestCommunityContext:
    """Tests for CommunityContext model."""

    def test_valid_instantiation(self):
        """Test creating a valid CommunityContext."""
        context = CommunityContext(
            name="Work Island",
            theme="Professional activities",
            summary="Projects and collaborations related to work",
            pending_tasks=5,
        )

        assert context.name == "Work Island"
        assert context.theme == "Professional activities"
        assert context.pending_tasks == 5

    def test_default_pending_tasks(self):
        """Test that pending_tasks defaults to 0."""
        context = CommunityContext(
            name="Personal Island",
            theme="Personal life",
            summary="Family and personal matters",
        )

        assert context.pending_tasks == 0

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        context = CommunityContext(
            name="Work Island",
            theme="Professional activities",
            summary="Work-related entities",
            pending_tasks=3,
        )

        # Serialize to JSON
        json_str = context.model_dump_json()
        data = json.loads(json_str)

        assert data["name"] == "Work Island"
        assert data["pending_tasks"] == 3

        # Deserialize from dict
        restored = CommunityContext(**data)
        assert restored.name == context.name
        assert restored.pending_tasks == context.pending_tasks


class TestEntityReference:
    """Tests for EntityReference model."""

    def test_valid_instantiation(self):
        """Test creating a valid EntityReference."""
        ref = EntityReference(
            uuid="123e4567-e89b-12d3-a456-426614174000",
            name="Sarah Johnson",
            entity_type="Person",
            created_at=1700000000.0,
        )

        assert ref.uuid == "123e4567-e89b-12d3-a456-426614174000"
        assert ref.name == "Sarah Johnson"
        assert ref.entity_type == "Person"
        assert ref.created_at == 1700000000.0

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        ref = EntityReference(
            uuid="test-uuid",
            name="Acme Corp",
            entity_type="Organization",
            created_at=1700000000.0,
        )

        json_str = ref.model_dump_json()
        data = json.loads(json_str)

        assert data["entity_type"] == "Organization"

        restored = EntityReference(**data)
        assert restored.name == ref.name


class TestEnrichedContext:
    """Tests for EnrichedContext model."""

    def test_valid_instantiation(self):
        """Test creating a valid EnrichedContext."""
        context = EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            recent_summaries=[
                ThreadSummary(
                    summary="Discussed project status",
                    topics=["project", "deadline"],
                )
            ],
            pending_tasks=[
                TaskNode(
                    action="Send email to Sarah",
                    status=TaskStatus.TODO,
                    priority="high",
                )
            ],
            recent_entities=[
                EntityReference(
                    uuid="entity-1",
                    name="Sarah",
                    entity_type="Person",
                    created_at=1700000000.0,
                )
            ],
            relevant_islands=[
                CommunityContext(
                    name="Work Island",
                    theme="Professional",
                    summary="Work stuff",
                    pending_tasks=3,
                )
            ],
        )

        assert context.thread_uuid == "thread-123"
        assert context.channel_type == ChannelType.CLI
        assert len(context.messages) == 2
        assert len(context.recent_summaries) == 1
        assert len(context.pending_tasks) == 1
        assert len(context.recent_entities) == 1
        assert len(context.relevant_islands) == 1

    def test_optional_islands(self):
        """Test that relevant_islands is optional."""
        context = EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.TELEGRAM,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
        )

        assert context.relevant_islands is None

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        context = EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=None,
        )

        json_str = context.model_dump_json()
        data = json.loads(json_str)

        assert data["thread_uuid"] == "thread-123"
        assert data["channel_type"] == "cli"


class TestPlannedTask:
    """Tests for PlannedTask model."""

    def test_valid_instantiation(self):
        """Test creating a valid PlannedTask."""
        task = PlannedTask(
            task_type="ingest",
            description="Extract entities from message",
            agent="ingestor",
            payload={"text": "Sarah works at Acme Corp"},
            blocking=False,
        )

        assert task.task_type == "ingest"
        assert task.description == "Extract entities from message"
        assert task.agent == "ingestor"
        assert task.blocking is False

    def test_blocking_default(self):
        """Test that blocking defaults to True."""
        task = PlannedTask(
            task_type="research",
            description="Search for Sarah's email",
            agent="researcher",
            payload={"query": "Sarah email"},
        )

        assert task.blocking is True

    def test_task_type_validation(self):
        """Test that task_type only accepts valid values."""
        # Valid types should work
        for task_type in ["ingest", "research", "execute"]:
            task = PlannedTask(
                task_type=task_type,
                description="Test",
                agent="ingestor",
                payload={},
            )
            assert task.task_type == task_type

        # Invalid type should fail
        with pytest.raises(ValidationError):
            PlannedTask(
                task_type="invalid",
                description="Test",
                agent="ingestor",
                payload={},
            )

    def test_agent_validation(self):
        """Test that agent only accepts valid values."""
        # Valid agents should work
        for agent in ["ingestor", "researcher", "executor"]:
            task = PlannedTask(
                task_type="ingest",
                description="Test",
                agent=agent,
                payload={},
            )
            assert task.agent == agent

        # Invalid agent should fail
        with pytest.raises(ValidationError):
            PlannedTask(
                task_type="ingest",
                description="Test",
                agent="invalid_agent",
                payload={},
            )

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        task = PlannedTask(
            task_type="execute",
            description="Send email",
            agent="executor",
            payload={"to": "sarah@example.com", "subject": "Meeting"},
            blocking=True,
        )

        json_str = task.model_dump_json()
        data = json.loads(json_str)

        assert data["task_type"] == "execute"
        assert data["blocking"] is True

        restored = PlannedTask(**data)
        assert restored.description == task.description


class TestTaskPlan:
    """Tests for TaskPlan model."""

    def test_valid_instantiation(self):
        """Test creating a valid TaskPlan."""
        plan = TaskPlan(
            reasoning="User wants to know about Sarah and send an email",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Find Sarah's contact info",
                    agent="researcher",
                    payload={"query": "Sarah email"},
                ),
                PlannedTask(
                    task_type="execute",
                    description="Send email to Sarah",
                    agent="executor",
                    payload={"to": "sarah@example.com"},
                ),
            ],
        )

        assert "Sarah" in plan.reasoning
        assert len(plan.tasks) == 2
        assert plan.direct_response is None

    def test_direct_response_only(self):
        """Test TaskPlan with direct response and no tasks."""
        plan = TaskPlan(
            reasoning="Simple greeting, no tasks needed",
            tasks=[],
            direct_response="Hello! How can I help you today?",
        )

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    def test_default_empty_tasks(self):
        """Test that tasks defaults to empty list."""
        plan = TaskPlan(
            reasoning="No tasks needed",
            direct_response="All done!",
        )

        assert plan.tasks == []

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        plan = TaskPlan(
            reasoning="Test reasoning",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store fact",
                    agent="ingestor",
                    payload={"text": "Test"},
                )
            ],
            direct_response=None,
        )

        json_str = plan.model_dump_json()
        data = json.loads(json_str)

        assert data["reasoning"] == "Test reasoning"
        assert len(data["tasks"]) == 1

        restored = TaskPlan(**data)
        assert len(restored.tasks) == 1


class TestModelIntegration:
    """Integration tests for models working together."""

    def test_enriched_context_with_all_fields(self):
        """Test EnrichedContext populated with all field types."""
        context = EnrichedContext(
            thread_uuid="thread-abc",
            channel_type=ChannelType.CLI,
            messages=[
                {"role": "user", "content": "I met Sarah today"},
                {"role": "assistant", "content": "Tell me more"},
            ],
            recent_summaries=[
                ThreadSummary(
                    summary="Previous conversation about work",
                    topics=["work", "project"],
                    participants=["Sarah"],
                )
            ],
            pending_tasks=[
                TaskNode(
                    action="Email Sarah about meeting",
                    status=TaskStatus.TODO,
                ),
                TaskNode(
                    action="Review project proposal",
                    status=TaskStatus.IN_PROGRESS,
                ),
            ],
            recent_entities=[
                EntityReference(
                    uuid="person-1",
                    name="Sarah Johnson",
                    entity_type="Person",
                    created_at=1700000000.0,
                ),
                EntityReference(
                    uuid="org-1",
                    name="Acme Corp",
                    entity_type="Organization",
                    created_at=1700000100.0,
                ),
            ],
            relevant_islands=[
                CommunityContext(
                    name="Work Island",
                    theme="Professional activities",
                    summary="Work and career",
                    pending_tasks=5,
                ),
                CommunityContext(
                    name="Personal Island",
                    theme="Personal life",
                    summary="Family and friends",
                    pending_tasks=2,
                ),
            ],
        )

        # Verify all fields are properly set
        assert len(context.messages) == 2
        assert len(context.recent_summaries) == 1
        assert len(context.pending_tasks) == 2
        assert len(context.recent_entities) == 2
        assert len(context.relevant_islands) == 2

        # Test serialization of complex structure
        json_str = context.model_dump_json()
        data = json.loads(json_str)

        # Verify nested structures serialize correctly
        assert data["channel_type"] == "cli"
        assert len(data["messages"]) == 2
        assert len(data["recent_entities"]) == 2

    def test_task_plan_with_multiple_task_types(self):
        """Test TaskPlan with different task types."""
        plan = TaskPlan(
            reasoning="Multi-intent message requires ingestion, research, and execution",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store fact about Sarah",
                    agent="ingestor",
                    payload={"text": "Sarah studied at Harvard"},
                    blocking=False,
                ),
                PlannedTask(
                    task_type="research",
                    description="Find events with Sarah",
                    agent="researcher",
                    payload={"query": "events with Sarah", "zoom_level": "meso"},
                    blocking=True,
                ),
                PlannedTask(
                    task_type="research",
                    description="Find Sarah's food preferences",
                    agent="researcher",
                    payload={"query": "Sarah food preferences"},
                    blocking=True,
                ),
                PlannedTask(
                    task_type="execute",
                    description="Check calendar for meetings with Sarah",
                    agent="executor",
                    payload={
                        "action": "calendar_search",
                        "query": "lunch with Sarah",
                    },
                    blocking=True,
                ),
            ],
        )

        # Verify task types
        task_types = [t.task_type for t in plan.tasks]
        assert "ingest" in task_types
        assert "research" in task_types
        assert "execute" in task_types

        # Verify blocking/non-blocking
        blocking_count = sum(1 for t in plan.tasks if t.blocking)
        assert blocking_count == 3

        # Test serialization
        json_str = plan.model_dump_json()
        restored = TaskPlan(**json.loads(json_str))
        assert len(restored.tasks) == 4
