"""
Unit tests for V2 Pydantic models.

Reference: specs/MAINAGENT.md Sections 4.2, 4.3
Task: T078 - Unit Tests for V2 Models

Tests cover:
- EnrichedContext: Multi-layer memory context for orchestrator
- TaskPlan: Think-Dispatch-Synthesize task planning
- PlannedTask: Individual task validation
- CommunityContext: Knowledge Island summaries
- EntityReference: Recently mentioned entities
- ThreadSummary: Thread summarization output
- TaskNode: Actionable task items

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
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


class TestTaskNode:
    """Tests for TaskNode model."""

    def test_minimal_task(self):
        """Test creating minimal task with required fields."""
        task = TaskNode(action="Send report to Sarah")

        assert task.action == "Send report to Sarah"
        assert task.status == TaskStatus.TODO  # Default
        assert task.priority is None
        assert task.due_date is None
        assert task.completed_at is None

    def test_full_task(self):
        """Test creating task with all fields."""
        task = TaskNode(
            action="Complete quarterly review",
            status=TaskStatus.IN_PROGRESS,
            priority="high",
            due_date=1704153600.0,
        )

        assert task.status == TaskStatus.IN_PROGRESS
        assert task.priority == "high"
        assert task.due_date == 1704153600.0

    def test_completed_task(self):
        """Test creating completed task with completion timestamp."""
        task = TaskNode(
            action="Review PR #123",
            status=TaskStatus.DONE,
            completed_at=1704067200.0,
        )

        assert task.status == TaskStatus.DONE
        assert task.completed_at == 1704067200.0

    def test_cancelled_task(self):
        """Test creating cancelled task."""
        task = TaskNode(
            action="Old task no longer needed",
            status=TaskStatus.CANCELLED,
        )

        assert task.status == TaskStatus.CANCELLED

    def test_task_status_validation(self):
        """Test that task status only accepts valid enum values."""
        with pytest.raises(ValidationError):
            TaskNode(
                action="Test task",
                status="invalid_status",
            )

    def test_uuid_and_timestamps_generated(self):
        """Test that uuid and timestamps are automatically generated."""
        task = TaskNode(action="Test task")

        assert task.uuid is not None
        assert len(task.uuid) > 0
        assert task.created_at > 0
        assert task.updated_at > 0

    def test_json_serialization(self):
        """Test JSON serialization/deserialization."""
        original = TaskNode(
            action="Write documentation",
            status=TaskStatus.TODO,
            priority="medium",
            due_date=1704326400.0,
        )

        json_str = original.model_dump_json()
        data = json.loads(json_str)
        restored = TaskNode(**data)

        assert restored.action == original.action
        assert restored.status == original.status
        assert restored.priority == original.priority
        assert restored.due_date == original.due_date


class TestThreadSummary:
    """Tests for ThreadSummary model."""

    def test_minimal_summary(self):
        """Test creating minimal thread summary."""
        summary = ThreadSummary(
            summary="Brief discussion about project timeline",
        )

        assert summary.summary == "Brief discussion about project timeline"
        assert summary.topics == []
        assert summary.action_items == []
        assert summary.new_facts == []
        assert summary.conflicts == []
        assert summary.participants == []
        assert summary.sentiment == "neutral"

    def test_full_summary(self):
        """Test creating comprehensive thread summary."""
        from klabautermann.core.models import (
            ActionItem,
            ActionStatus,
            ConflictResolution,
            ExtractedFact,
            FactConflict,
        )

        summary = ThreadSummary(
            summary="Discussed Q4 goals and team assignments",
            topics=["Q4 Planning", "Team Structure", "Budget"],
            action_items=[
                ActionItem(
                    action="Send budget proposal to CFO",
                    assignee="Sarah",
                    status=ActionStatus.PENDING,
                    due_date="2024-01-15",
                    confidence=0.9,
                )
            ],
            new_facts=[
                ExtractedFact(
                    entity="Sarah Johnson",
                    entity_type="Person",
                    fact="Promoted to Senior PM",
                    confidence=0.95,
                )
            ],
            conflicts=[
                FactConflict(
                    existing_fact="Sarah works at TechCorp",
                    new_fact="Sarah works at Acme",
                    entity="Sarah Johnson",
                    resolution=ConflictResolution.EXPIRE_OLD,
                )
            ],
            participants=["user", "Sarah", "John"],
            sentiment="positive",
        )

        assert len(summary.topics) == 3
        assert len(summary.action_items) == 1
        assert len(summary.new_facts) == 1
        assert len(summary.conflicts) == 1
        assert len(summary.participants) == 3
        assert summary.sentiment == "positive"

    def test_sentiment_values(self):
        """Test that various sentiment values are accepted."""
        for sentiment in ["positive", "negative", "neutral", "mixed"]:
            summary = ThreadSummary(
                summary="Test",
                sentiment=sentiment,
            )
            assert summary.sentiment == sentiment

    def test_empty_lists_default(self):
        """Test that optional list fields default to empty lists."""
        summary = ThreadSummary(summary="Test summary")

        assert isinstance(summary.topics, list)
        assert isinstance(summary.action_items, list)
        assert isinstance(summary.new_facts, list)
        assert isinstance(summary.conflicts, list)
        assert isinstance(summary.participants, list)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_enriched_context_with_none_islands(self):
        """Test EnrichedContext with explicitly None relevant_islands."""
        ctx = EnrichedContext(
            thread_uuid="test",
            channel_type=ChannelType.CLI,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=None,
        )

        assert ctx.relevant_islands is None

    def test_enriched_context_with_empty_islands(self):
        """Test EnrichedContext with empty but not None relevant_islands."""
        ctx = EnrichedContext(
            thread_uuid="test",
            channel_type=ChannelType.CLI,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=[],
        )

        assert ctx.relevant_islands == []

    def test_task_plan_with_both_tasks_and_response(self):
        """Test TaskPlan with both tasks and direct_response (non-blocking ingestion + response)."""
        plan = TaskPlan(
            reasoning="Store fact and respond immediately",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store conversation",
                    agent="ingestor",
                    payload={"text": "Sarah likes coffee"},
                    blocking=False,
                )
            ],
            direct_response="Got it, I'll remember that!",
        )

        assert len(plan.tasks) == 1
        assert plan.direct_response is not None

    def test_empty_payload(self):
        """Test PlannedTask with empty payload dictionary."""
        task = PlannedTask(
            task_type="research",
            description="Simple search",
            agent="researcher",
            payload={},
            blocking=True,
        )

        assert task.payload == {}

    def test_unicode_in_strings(self):
        """Test that unicode characters are handled correctly."""
        ctx = EnrichedContext(
            thread_uuid="test-unicode",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Hello 世界 🌍"}],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
        )

        assert "世界" in ctx.messages[0]["content"]
        assert "🌍" in ctx.messages[0]["content"]

    def test_very_long_strings(self):
        """Test that very long strings are handled correctly."""
        long_text = "A" * 10000  # 10k characters

        task = PlannedTask(
            task_type="ingest",
            description=long_text[:1000],  # Reasonable description length
            agent="ingestor",
            payload={"text": long_text},
            blocking=False,
        )

        assert len(task.payload["text"]) == 10000

    def test_special_characters_in_names(self):
        """Test that special characters in entity names are handled."""
        entity = EntityReference(
            uuid="test-123",
            name="O'Brien & Associates (NYC)",
            entity_type="Organization",
            created_at=1704067200.0,
        )

        assert "'" in entity.name
        assert "&" in entity.name
        assert "(" in entity.name

    def test_nested_payload_structures(self):
        """Test that complex nested payload structures work."""
        task = PlannedTask(
            task_type="execute",
            description="Complex action",
            agent="executor",
            payload={
                "nested": {"key": "value", "list": [1, 2, 3]},
                "number": 42,
                "boolean": True,
                "null_value": None,
            },
            blocking=False,
        )

        assert task.payload["nested"]["list"] == [1, 2, 3]
        assert task.payload["number"] == 42
        assert task.payload["null_value"] is None

    def test_channel_type_validation(self):
        """Test that invalid channel_type raises ValidationError."""
        with pytest.raises(ValidationError):
            EnrichedContext(
                thread_uuid="test",
                channel_type="invalid_channel",
                messages=[],
                recent_summaries=[],
                pending_tasks=[],
                recent_entities=[],
            )

    def test_all_channel_types(self):
        """Test that all valid channel types work."""
        for channel in [
            ChannelType.CLI,
            ChannelType.TELEGRAM,
            ChannelType.DISCORD,
            ChannelType.TEST,
        ]:
            ctx = EnrichedContext(
                thread_uuid="test",
                channel_type=channel,
                messages=[],
                recent_summaries=[],
                pending_tasks=[],
                recent_entities=[],
            )
            assert ctx.channel_type == channel


class TestJSONRoundtrip:
    """Test JSON serialization and deserialization round-trip for all models."""

    def test_planned_task_roundtrip(self):
        """Test PlannedTask JSON round-trip preserves all data."""
        original = PlannedTask(
            task_type="ingest",
            description="Test task",
            agent="ingestor",
            payload={"key": "value", "nested": {"data": 123}},
            blocking=True,
        )

        json_str = original.model_dump_json()
        restored = PlannedTask.model_validate_json(json_str)

        assert restored.task_type == original.task_type
        assert restored.description == original.description
        assert restored.agent == original.agent
        assert restored.payload == original.payload
        assert restored.blocking == original.blocking

    def test_task_plan_roundtrip(self):
        """Test TaskPlan JSON round-trip preserves all data."""
        original = TaskPlan(
            reasoning="Multiple intents detected",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store fact",
                    agent="ingestor",
                    payload={"text": "Sarah at Harvard"},
                    blocking=False,
                ),
                PlannedTask(
                    task_type="research",
                    description="Find related info",
                    agent="researcher",
                    payload={"query": "Harvard contacts"},
                    blocking=True,
                ),
            ],
            direct_response=None,
        )

        json_str = original.model_dump_json()
        restored = TaskPlan.model_validate_json(json_str)

        assert restored.reasoning == original.reasoning
        assert len(restored.tasks) == 2
        assert restored.tasks[0].task_type == "ingest"
        assert restored.tasks[1].task_type == "research"
        assert restored.direct_response is None

    def test_enriched_context_roundtrip(self):
        """Test EnrichedContext JSON round-trip preserves all data."""
        original = EnrichedContext(
            thread_uuid="test-uuid-005",
            channel_type=ChannelType.TELEGRAM,
            messages=[{"role": "user", "content": "test"}],
            recent_summaries=[
                ThreadSummary(
                    summary="Previous chat",
                    topics=["topic1"],
                )
            ],
            pending_tasks=[TaskNode(action="Task 1", status=TaskStatus.TODO)],
            recent_entities=[
                EntityReference(
                    uuid="e1",
                    name="Entity 1",
                    entity_type="Person",
                    created_at=1704067200.0,
                )
            ],
            relevant_islands=[
                CommunityContext(
                    name="Island",
                    theme="test",
                    summary="summary",
                    pending_tasks=2,
                )
            ],
        )

        json_str = original.model_dump_json()
        restored = EnrichedContext.model_validate_json(json_str)

        assert restored.thread_uuid == original.thread_uuid
        assert restored.channel_type == original.channel_type
        assert restored.messages == original.messages
        assert len(restored.recent_summaries) == 1
        assert len(restored.pending_tasks) == 1
        assert len(restored.recent_entities) == 1
        assert len(restored.relevant_islands) == 1

    def test_community_context_roundtrip(self):
        """Test CommunityContext JSON round-trip preserves all data."""
        original = CommunityContext(
            name="Work Island",
            theme="Professional activities",
            summary="Work-related entities and projects",
            pending_tasks=5,
        )

        json_str = original.model_dump_json()
        restored = CommunityContext.model_validate_json(json_str)

        assert restored.name == original.name
        assert restored.theme == original.theme
        assert restored.summary == original.summary
        assert restored.pending_tasks == original.pending_tasks

    def test_entity_reference_roundtrip(self):
        """Test EntityReference JSON round-trip preserves all data."""
        original = EntityReference(
            uuid="entity-001",
            name="Sarah Johnson",
            entity_type="Person",
            created_at=1704067200.0,
        )

        json_str = original.model_dump_json()
        restored = EntityReference.model_validate_json(json_str)

        assert restored.uuid == original.uuid
        assert restored.name == original.name
        assert restored.entity_type == original.entity_type
        assert restored.created_at == original.created_at

    def test_task_node_roundtrip(self):
        """Test TaskNode JSON round-trip preserves all data."""
        original = TaskNode(
            action="Complete review",
            status=TaskStatus.IN_PROGRESS,
            priority="high",
            due_date=1704326400.0,
        )

        json_str = original.model_dump_json()
        data = json.loads(json_str)
        restored = TaskNode(**data)

        assert restored.action == original.action
        assert restored.status == original.status
        assert restored.priority == original.priority
        assert restored.due_date == original.due_date


class TestDefaultValues:
    """Test that default values are applied correctly."""

    def test_community_context_default_tasks(self):
        """Test CommunityContext defaults pending_tasks to 0."""
        community = CommunityContext(
            name="Test",
            theme="test",
            summary="test",
        )

        assert community.pending_tasks == 0

    def test_planned_task_default_blocking(self):
        """Test PlannedTask defaults blocking to True."""
        task = PlannedTask(
            task_type="research",
            description="test",
            agent="researcher",
            payload={},
        )

        assert task.blocking is True

    def test_task_plan_default_tasks(self):
        """Test TaskPlan defaults tasks to empty list."""
        plan = TaskPlan(
            reasoning="test",
            direct_response="response",
        )

        assert plan.tasks == []
        assert isinstance(plan.tasks, list)

    def test_task_node_default_status(self):
        """Test TaskNode defaults status to TODO."""
        task = TaskNode(action="Test action")

        assert task.status == TaskStatus.TODO

    def test_thread_summary_defaults(self):
        """Test ThreadSummary default values."""
        summary = ThreadSummary(summary="test")

        assert summary.topics == []
        assert summary.action_items == []
        assert summary.new_facts == []
        assert summary.conflicts == []
        assert summary.participants == []
        assert summary.sentiment == "neutral"

    def test_enriched_context_none_islands(self):
        """Test EnrichedContext defaults relevant_islands to None."""
        ctx = EnrichedContext(
            thread_uuid="test",
            channel_type=ChannelType.CLI,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
        )

        assert ctx.relevant_islands is None
