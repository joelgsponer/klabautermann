"""
Unit tests for Pydantic models.

Tests model instantiation, validation, serialization, and defaults.
"""

import json

import pytest
from pydantic import ValidationError

from klabautermann.core.models import (
    ActionItem,
    ActionStatus,
    ConflictResolution,
    ExtractedFact,
    FactConflict,
    ThreadSummary,
)


class TestActionStatus:
    """Test suite for ActionStatus enum."""

    def test_enum_values(self) -> None:
        """Verify ActionStatus has correct values."""
        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.COMPLETED.value == "completed"
        assert ActionStatus.MENTIONED.value == "mentioned"

    def test_enum_from_string(self) -> None:
        """ActionStatus can be created from string."""
        assert ActionStatus("pending") == ActionStatus.PENDING
        assert ActionStatus("completed") == ActionStatus.COMPLETED
        assert ActionStatus("mentioned") == ActionStatus.MENTIONED


class TestConflictResolution:
    """Test suite for ConflictResolution enum."""

    def test_enum_values(self) -> None:
        """Verify ConflictResolution has correct values."""
        assert ConflictResolution.EXPIRE_OLD.value == "expire_old"
        assert ConflictResolution.KEEP_BOTH.value == "keep_both"
        assert ConflictResolution.USER_REVIEW.value == "user_review"
        assert ConflictResolution.IGNORE_NEW.value == "ignore_new"

    def test_enum_from_string(self) -> None:
        """ConflictResolution can be created from string."""
        assert ConflictResolution("expire_old") == ConflictResolution.EXPIRE_OLD
        assert ConflictResolution("user_review") == ConflictResolution.USER_REVIEW


class TestActionItem:
    """Test suite for ActionItem model."""

    def test_minimal_instantiation(self) -> None:
        """ActionItem can be created with just an action."""
        item = ActionItem(action="Follow up with John")
        assert item.action == "Follow up with John"
        assert item.assignee is None
        assert item.status == ActionStatus.PENDING
        assert item.due_date is None
        assert item.confidence == 0.8  # Default value

    def test_full_instantiation(self) -> None:
        """ActionItem can be created with all fields."""
        item = ActionItem(
            action="Send proposal",
            assignee="Alice",
            status=ActionStatus.COMPLETED,
            due_date="2026-01-20",
            confidence=0.95,
        )
        assert item.action == "Send proposal"
        assert item.assignee == "Alice"
        assert item.status == ActionStatus.COMPLETED
        assert item.due_date == "2026-01-20"
        assert item.confidence == 0.95

    def test_from_dict(self) -> None:
        """ActionItem can be instantiated from dict (LLM output)."""
        data = {
            "action": "Review PR",
            "assignee": "Bob",
            "status": "pending",
            "due_date": "2026-01-18",
            "confidence": 0.9,
        }
        item = ActionItem(**data)
        assert item.action == "Review PR"
        assert item.assignee == "Bob"
        assert item.status == ActionStatus.PENDING
        assert item.confidence == 0.9

    def test_confidence_validation_valid(self) -> None:
        """Confidence values between 0.0 and 1.0 are valid."""
        item1 = ActionItem(action="Test", confidence=0.0)
        assert item1.confidence == 0.0

        item2 = ActionItem(action="Test", confidence=0.5)
        assert item2.confidence == 0.5

        item3 = ActionItem(action="Test", confidence=1.0)
        assert item3.confidence == 1.0

    def test_confidence_validation_invalid_high(self) -> None:
        """Confidence > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActionItem(action="Test", confidence=1.5)
        assert "confidence" in str(exc_info.value).lower()

    def test_confidence_validation_invalid_low(self) -> None:
        """Confidence < 0.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActionItem(action="Test", confidence=-0.1)
        assert "confidence" in str(exc_info.value).lower()

    def test_json_serialization(self) -> None:
        """ActionItem can be serialized to JSON."""
        item = ActionItem(
            action="Write tests",
            assignee="Charlie",
            status=ActionStatus.COMPLETED,
            confidence=0.85,
        )
        json_str = item.model_dump_json()
        data = json.loads(json_str)

        assert data["action"] == "Write tests"
        assert data["assignee"] == "Charlie"
        assert data["status"] == "completed"
        assert data["confidence"] == 0.85

    def test_json_deserialization(self) -> None:
        """ActionItem can be deserialized from JSON."""
        json_str = '{"action": "Deploy", "status": "completed", "confidence": 1.0}'
        item = ActionItem.model_validate_json(json_str)
        assert item.action == "Deploy"
        assert item.status == ActionStatus.COMPLETED
        assert item.confidence == 1.0


class TestExtractedFact:
    """Test suite for ExtractedFact model."""

    def test_minimal_instantiation(self) -> None:
        """ExtractedFact can be created with required fields."""
        fact = ExtractedFact(
            entity="John Doe",
            entity_type="Person",
            fact="Works at Acme Corp",
        )
        assert fact.entity == "John Doe"
        assert fact.entity_type == "Person"
        assert fact.fact == "Works at Acme Corp"
        assert fact.confidence == 0.8  # Default

    def test_full_instantiation(self) -> None:
        """ExtractedFact can be created with all fields."""
        fact = ExtractedFact(
            entity="Project Alpha",
            entity_type="Project",
            fact="Deadline is March 2026",
            confidence=0.95,
        )
        assert fact.entity == "Project Alpha"
        assert fact.entity_type == "Project"
        assert fact.fact == "Deadline is March 2026"
        assert fact.confidence == 0.95

    def test_from_dict(self) -> None:
        """ExtractedFact can be instantiated from dict."""
        data = {
            "entity": "Sarah Chen",
            "entity_type": "Person",
            "fact": "Moved to San Francisco",
            "confidence": 0.9,
        }
        fact = ExtractedFact(**data)
        assert fact.entity == "Sarah Chen"
        assert fact.entity_type == "Person"
        assert fact.fact == "Moved to San Francisco"
        assert fact.confidence == 0.9

    def test_confidence_validation_valid(self) -> None:
        """Confidence values between 0.0 and 1.0 are valid."""
        fact = ExtractedFact(
            entity="Test",
            entity_type="Test",
            fact="Test fact",
            confidence=0.75,
        )
        assert fact.confidence == 0.75

    def test_confidence_validation_invalid(self) -> None:
        """Invalid confidence raises ValidationError."""
        with pytest.raises(ValidationError):
            ExtractedFact(
                entity="Test",
                entity_type="Test",
                fact="Test",
                confidence=2.0,
            )

    def test_json_serialization(self) -> None:
        """ExtractedFact can be serialized to JSON."""
        fact = ExtractedFact(
            entity="Acme Corp",
            entity_type="Organization",
            fact="Raised $50M Series B",
            confidence=0.92,
        )
        json_str = fact.model_dump_json()
        data = json.loads(json_str)

        assert data["entity"] == "Acme Corp"
        assert data["entity_type"] == "Organization"
        assert data["fact"] == "Raised $50M Series B"
        assert data["confidence"] == 0.92


class TestFactConflict:
    """Test suite for FactConflict model."""

    def test_minimal_instantiation(self) -> None:
        """FactConflict can be created with required fields."""
        conflict = FactConflict(
            existing_fact="Works at Google",
            new_fact="Works at Meta",
            entity="John Doe",
        )
        assert conflict.existing_fact == "Works at Google"
        assert conflict.new_fact == "Works at Meta"
        assert conflict.entity == "John Doe"
        assert conflict.resolution == ConflictResolution.USER_REVIEW  # Default

    def test_full_instantiation(self) -> None:
        """FactConflict can be created with all fields."""
        conflict = FactConflict(
            existing_fact="Lives in NYC",
            new_fact="Lives in SF",
            entity="Alice Smith",
            resolution=ConflictResolution.EXPIRE_OLD,
        )
        assert conflict.existing_fact == "Lives in NYC"
        assert conflict.new_fact == "Lives in SF"
        assert conflict.entity == "Alice Smith"
        assert conflict.resolution == ConflictResolution.EXPIRE_OLD

    def test_from_dict(self) -> None:
        """FactConflict can be instantiated from dict."""
        data = {
            "existing_fact": "CEO of StartupX",
            "new_fact": "CTO of StartupX",
            "entity": "Bob Johnson",
            "resolution": "keep_both",
        }
        conflict = FactConflict(**data)
        assert conflict.existing_fact == "CEO of StartupX"
        assert conflict.new_fact == "CTO of StartupX"
        assert conflict.entity == "Bob Johnson"
        assert conflict.resolution == ConflictResolution.KEEP_BOTH

    def test_json_serialization(self) -> None:
        """FactConflict can be serialized to JSON."""
        conflict = FactConflict(
            existing_fact="Graduated 2015",
            new_fact="Graduated 2016",
            entity="Charlie Brown",
            resolution=ConflictResolution.IGNORE_NEW,
        )
        json_str = conflict.model_dump_json()
        data = json.loads(json_str)

        assert data["existing_fact"] == "Graduated 2015"
        assert data["new_fact"] == "Graduated 2016"
        assert data["entity"] == "Charlie Brown"
        assert data["resolution"] == "ignore_new"


class TestThreadSummary:
    """Test suite for ThreadSummary model."""

    def test_minimal_instantiation(self) -> None:
        """ThreadSummary can be created with just a summary."""
        summary = ThreadSummary(summary="Discussed project timeline and next steps.")
        assert summary.summary == "Discussed project timeline and next steps."
        assert summary.topics == []
        assert summary.action_items == []
        assert summary.new_facts == []
        assert summary.conflicts == []
        assert summary.participants == []
        assert summary.sentiment == "neutral"

    def test_full_instantiation(self) -> None:
        """ThreadSummary can be created with all fields."""
        action = ActionItem(action="Send email", assignee="Alice")
        fact = ExtractedFact(
            entity="Project X",
            entity_type="Project",
            fact="Due in March",
        )
        conflict = FactConflict(
            existing_fact="Due in April",
            new_fact="Due in March",
            entity="Project X",
        )

        summary = ThreadSummary(
            summary="Team discussed project deadlines and resource allocation.",
            topics=["project management", "resources", "deadlines"],
            action_items=[action],
            new_facts=[fact],
            conflicts=[conflict],
            participants=["Alice", "Bob", "Charlie"],
            sentiment="positive",
        )

        assert summary.summary == "Team discussed project deadlines and resource allocation."
        assert len(summary.topics) == 3
        assert len(summary.action_items) == 1
        assert len(summary.new_facts) == 1
        assert len(summary.conflicts) == 1
        assert len(summary.participants) == 3
        assert summary.sentiment == "positive"

    def test_from_dict_complex(self) -> None:
        """ThreadSummary can be instantiated from complex dict (LLM output)."""
        data = {
            "summary": "Discussed Q1 goals and hiring plans.",
            "topics": ["hiring", "goals", "budget"],
            "action_items": [
                {
                    "action": "Post job listing",
                    "assignee": "HR",
                    "status": "pending",
                    "confidence": 0.9,
                },
                {
                    "action": "Review candidates",
                    "status": "completed",
                    "confidence": 1.0,
                },
            ],
            "new_facts": [
                {
                    "entity": "Engineering Team",
                    "entity_type": "Organization",
                    "fact": "Planning to hire 3 engineers",
                    "confidence": 0.95,
                }
            ],
            "conflicts": [],
            "participants": ["John", "Sarah", "Mike"],
            "sentiment": "positive",
        }

        summary = ThreadSummary(**data)
        assert summary.summary == "Discussed Q1 goals and hiring plans."
        assert len(summary.topics) == 3
        assert len(summary.action_items) == 2
        assert summary.action_items[0].assignee == "HR"
        assert summary.action_items[1].status == ActionStatus.COMPLETED
        assert len(summary.new_facts) == 1
        assert summary.new_facts[0].entity == "Engineering Team"
        assert len(summary.participants) == 3
        assert summary.sentiment == "positive"

    def test_json_serialization(self) -> None:
        """ThreadSummary can be serialized to JSON."""
        summary = ThreadSummary(
            summary="Brief discussion about lunch plans.",
            topics=["food", "social"],
            participants=["Alice", "Bob"],
            sentiment="neutral",
        )
        json_str = summary.model_dump_json()
        data = json.loads(json_str)

        assert data["summary"] == "Brief discussion about lunch plans."
        assert data["topics"] == ["food", "social"]
        assert data["participants"] == ["Alice", "Bob"]
        assert data["sentiment"] == "neutral"
        assert data["action_items"] == []
        assert data["new_facts"] == []
        assert data["conflicts"] == []

    def test_json_deserialization(self) -> None:
        """ThreadSummary can be deserialized from JSON."""
        json_str = """
        {
            "summary": "Planning meeting for Sprint 3.",
            "topics": ["sprint planning", "tasks"],
            "action_items": [],
            "new_facts": [],
            "conflicts": [],
            "participants": ["Team"],
            "sentiment": "neutral"
        }
        """
        summary = ThreadSummary.model_validate_json(json_str)
        assert summary.summary == "Planning meeting for Sprint 3."
        assert "sprint planning" in summary.topics
        assert summary.participants == ["Team"]

    def test_empty_lists_default(self) -> None:
        """Empty list fields default to empty lists, not None."""
        summary = ThreadSummary(summary="Test summary")
        assert isinstance(summary.topics, list)
        assert isinstance(summary.action_items, list)
        assert isinstance(summary.new_facts, list)
        assert isinstance(summary.conflicts, list)
        assert isinstance(summary.participants, list)
        assert len(summary.topics) == 0

    def test_nested_validation(self) -> None:
        """Nested model validation works correctly."""
        # Invalid confidence in nested ActionItem should raise error
        data = {
            "summary": "Test",
            "action_items": [
                {
                    "action": "Task",
                    "confidence": 5.0,  # Invalid
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            ThreadSummary(**data)
        assert "confidence" in str(exc_info.value).lower()

    def test_real_world_example(self) -> None:
        """Test with realistic data from Archivist output."""
        data = {
            "summary": "User discussed meeting Sarah at a conference. "
            "She works at Google as a PM and can help with the API integration.",
            "topics": ["networking", "api integration", "google"],
            "action_items": [
                {
                    "action": "Email Sarah about API integration help",
                    "assignee": "user",
                    "status": "pending",
                    "due_date": "2026-01-20",
                    "confidence": 0.9,
                }
            ],
            "new_facts": [
                {
                    "entity": "Sarah Chen",
                    "entity_type": "Person",
                    "fact": "Works at Google as Product Manager",
                    "confidence": 0.95,
                },
                {
                    "entity": "Sarah Chen",
                    "entity_type": "Person",
                    "fact": "Met at TechConf 2026",
                    "confidence": 1.0,
                },
            ],
            "conflicts": [],
            "participants": ["Sarah Chen"],
            "sentiment": "positive",
        }

        summary = ThreadSummary(**data)
        assert "Sarah" in summary.summary
        assert len(summary.action_items) == 1
        assert len(summary.new_facts) == 2
        assert summary.new_facts[0].entity == "Sarah Chen"
        assert summary.new_facts[1].confidence == 1.0
        assert summary.sentiment == "positive"
