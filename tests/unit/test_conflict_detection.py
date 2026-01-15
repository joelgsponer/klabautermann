"""
Unit tests for Conflict Detection in Summaries.

Tests the detect_conflicts and apply_conflict_resolutions functions with
mocked Neo4j client to verify conflict detection logic.

Reference: specs/architecture/AGENTS.md Section 1.5
Task: T048 - Conflict Detection in Summaries
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from klabautermann.agents.summarization import (
    _check_person_conflicts,
    _check_project_conflicts,
    _check_task_conflicts,
    _extract_employer_from_fact,
    _extract_manager_from_fact,
    _extract_project_status_from_fact,
    _extract_task_action_fragment,
    apply_conflict_resolutions,
    detect_conflicts,
)
from klabautermann.core.models import (
    ConflictResolution,
    ExtractedFact,
    FactConflict,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4jClient for testing."""
    mock_client = AsyncMock()
    return mock_client


@pytest.fixture
def employment_change_fact():
    """Sample fact representing an employment change."""
    return ExtractedFact(
        entity="Sarah",
        entity_type="Person",
        fact="Sarah now works at TechCorp as VP of Engineering",
        confidence=0.9,
    )


@pytest.fixture
def manager_change_fact():
    """Sample fact representing a manager change."""
    return ExtractedFact(
        entity="John",
        entity_type="Person",
        fact="John now reports to Maria",
        confidence=0.85,
    )


@pytest.fixture
def project_status_fact():
    """Sample fact representing a project status change."""
    return ExtractedFact(
        entity="Project Phoenix",
        entity_type="Project",
        fact="Project Phoenix was completed last week",
        confidence=0.95,
    )


@pytest.fixture
def task_completion_fact():
    """Sample fact representing task completion."""
    return ExtractedFact(
        entity="budget proposal",
        entity_type="Task",
        fact="Completed sending the budget proposal to Sarah",
        confidence=0.9,
    )


# ===========================================================================
# Test Extraction Helper Functions
# ===========================================================================


def test_extract_employer_from_fact_works_at():
    """Test extracting employer from 'works at' pattern."""
    fact = "Sarah works at TechCorp as VP"
    result = _extract_employer_from_fact(fact)
    assert result == "TechCorp"


def test_extract_employer_from_fact_joined():
    """Test extracting employer from 'joined' pattern."""
    fact = "Sarah joined Acme Corp in January"
    result = _extract_employer_from_fact(fact)
    assert result == "Acme Corp"


def test_extract_employer_from_fact_now_at():
    """Test extracting employer from 'now at' pattern."""
    fact = "Sarah is now at Google"
    result = _extract_employer_from_fact(fact)
    assert result == "Google"


def test_extract_employer_from_fact_no_match():
    """Test extraction returns None when no pattern matches."""
    fact = "Sarah is a great engineer"
    result = _extract_employer_from_fact(fact)
    assert result is None


def test_extract_manager_from_fact_reports_to():
    """Test extracting manager from 'reports to' pattern."""
    fact = "John reports to Maria"
    result = _extract_manager_from_fact(fact)
    assert result == "Maria"


def test_extract_manager_from_fact_manager_is():
    """Test extracting manager from 'manager is' pattern."""
    fact = "John's manager is David Smith"
    result = _extract_manager_from_fact(fact)
    assert result == "David Smith"


def test_extract_manager_from_fact_no_match():
    """Test extraction returns None when no pattern matches."""
    fact = "John is doing great work"
    result = _extract_manager_from_fact(fact)
    assert result is None


def test_extract_project_status_completed():
    """Test extracting 'completed' status."""
    fact = "Project Phoenix was completed successfully"
    result = _extract_project_status_from_fact(fact)
    assert result == "completed"


def test_extract_project_status_cancelled():
    """Test extracting 'cancelled' status."""
    fact = "Project Alpha has been cancelled due to budget cuts"
    result = _extract_project_status_from_fact(fact)
    assert result == "cancelled"


def test_extract_project_status_on_hold():
    """Test extracting 'on_hold' status."""
    fact = "Project Beta is now on hold pending approval"
    result = _extract_project_status_from_fact(fact)
    assert result == "on_hold"


def test_extract_project_status_resumed():
    """Test extracting 'active' status from 'resumed'."""
    fact = "Project Gamma has been resumed after the break"
    result = _extract_project_status_from_fact(fact)
    assert result == "active"


def test_extract_project_status_no_match():
    """Test extraction returns None when no status found."""
    fact = "Project Omega is going well"
    result = _extract_project_status_from_fact(fact)
    assert result is None


def test_extract_task_action_fragment_basic():
    """Test extracting task action fragment."""
    fact = "Completed sending the budget proposal to Sarah"
    result = _extract_task_action_fragment(fact)
    assert "sending" in result.lower()
    assert "budget" in result.lower()


def test_extract_task_action_fragment_filters_stopwords():
    """Test that extraction filters out common stopwords."""
    fact = "Done with the meeting and the planning"
    result = _extract_task_action_fragment(fact)
    # Should skip short words and common stopwords
    assert "the" not in result.lower()
    assert "with" not in result.lower()


def test_extract_task_action_fragment_empty():
    """Test extraction with only stopwords."""
    fact = "the and for"
    result = _extract_task_action_fragment(fact)
    # Should fall back to first 20 chars
    assert len(result) <= 20


# ===========================================================================
# Test Person Conflict Detection
# ===========================================================================


@pytest.mark.asyncio
async def test_check_person_conflicts_employment_change(employment_change_fact, mock_neo4j_client):
    """Test detection of employment change conflict."""
    # Mock existing employment in graph
    mock_neo4j_client.execute_read.return_value = [
        {
            "person_uuid": "uuid-123",
            "current_employer": "Acme Corp",
            "r": {"expired_at": None},
        }
    ]

    conflict = await _check_person_conflicts(
        employment_change_fact, mock_neo4j_client, "test-trace"
    )

    assert conflict is not None
    assert conflict.entity == "Sarah"
    assert "Acme Corp" in conflict.existing_fact
    assert conflict.resolution == ConflictResolution.EXPIRE_OLD


@pytest.mark.asyncio
async def test_check_person_conflicts_same_employer(employment_change_fact, mock_neo4j_client):
    """Test no conflict when employer hasn't changed."""
    # Mock same employer in graph
    mock_neo4j_client.execute_read.return_value = [
        {
            "person_uuid": "uuid-123",
            "current_employer": "TechCorp",
            "r": {"expired_at": None},
        }
    ]

    conflict = await _check_person_conflicts(
        employment_change_fact, mock_neo4j_client, "test-trace"
    )

    assert conflict is None


@pytest.mark.asyncio
async def test_check_person_conflicts_no_existing_employment(
    employment_change_fact, mock_neo4j_client
):
    """Test no conflict when person has no current employer."""
    # Mock no existing employment
    mock_neo4j_client.execute_read.return_value = [
        {"person_uuid": "uuid-123", "current_employer": None, "r": None}
    ]

    conflict = await _check_person_conflicts(
        employment_change_fact, mock_neo4j_client, "test-trace"
    )

    assert conflict is None


@pytest.mark.asyncio
async def test_check_person_conflicts_manager_change(manager_change_fact, mock_neo4j_client):
    """Test detection of manager change conflict."""
    # Mock existing manager in graph
    mock_neo4j_client.execute_read.return_value = [
        {"person_uuid": "uuid-456", "current_manager": "David"}
    ]

    conflict = await _check_person_conflicts(manager_change_fact, mock_neo4j_client, "test-trace")

    assert conflict is not None
    assert conflict.entity == "John"
    assert "David" in conflict.existing_fact
    assert "Maria" in conflict.new_fact
    assert conflict.resolution == ConflictResolution.EXPIRE_OLD


@pytest.mark.asyncio
async def test_check_person_conflicts_no_manager_keyword(mock_neo4j_client):
    """Test no conflict check when fact doesn't mention employment or manager."""
    fact = ExtractedFact(
        entity="Sarah",
        entity_type="Person",
        fact="Sarah likes coffee",
        confidence=0.8,
    )

    conflict = await _check_person_conflicts(fact, mock_neo4j_client, "test-trace")

    assert conflict is None
    # Should not have queried the database
    mock_neo4j_client.execute_read.assert_not_called()


# ===========================================================================
# Test Project Conflict Detection
# ===========================================================================


@pytest.mark.asyncio
async def test_check_project_conflicts_status_change(project_status_fact, mock_neo4j_client):
    """Test detection of project status change conflict."""
    # Mock existing status in graph
    mock_neo4j_client.execute_read.return_value = [
        {"project_uuid": "uuid-789", "current_status": "active"}
    ]

    conflict = await _check_project_conflicts(project_status_fact, mock_neo4j_client, "test-trace")

    assert conflict is not None
    assert conflict.entity == "Project Phoenix"
    assert "active" in conflict.existing_fact
    assert "completed" in conflict.new_fact.lower()
    assert conflict.resolution == ConflictResolution.EXPIRE_OLD


@pytest.mark.asyncio
async def test_check_project_conflicts_same_status(project_status_fact, mock_neo4j_client):
    """Test no conflict when project status hasn't changed."""
    # Mock same status in graph
    mock_neo4j_client.execute_read.return_value = [
        {"project_uuid": "uuid-789", "current_status": "completed"}
    ]

    conflict = await _check_project_conflicts(project_status_fact, mock_neo4j_client, "test-trace")

    assert conflict is None


@pytest.mark.asyncio
async def test_check_project_conflicts_no_existing_project(project_status_fact, mock_neo4j_client):
    """Test no conflict when project doesn't exist in graph."""
    # Mock no existing project
    mock_neo4j_client.execute_read.return_value = []

    conflict = await _check_project_conflicts(project_status_fact, mock_neo4j_client, "test-trace")

    assert conflict is None


@pytest.mark.asyncio
async def test_check_project_conflicts_no_status_keyword(mock_neo4j_client):
    """Test no conflict check when fact doesn't mention status."""
    fact = ExtractedFact(
        entity="Project Phoenix",
        entity_type="Project",
        fact="Project Phoenix has a large team",
        confidence=0.8,
    )

    conflict = await _check_project_conflicts(fact, mock_neo4j_client, "test-trace")

    assert conflict is None
    mock_neo4j_client.execute_read.assert_not_called()


# ===========================================================================
# Test Task Conflict Detection
# ===========================================================================


@pytest.mark.asyncio
async def test_check_task_conflicts_completion(task_completion_fact, mock_neo4j_client):
    """Test detection of task completion conflict."""
    # Mock existing task in todo status
    mock_neo4j_client.execute_read.return_value = [
        {
            "task_uuid": "uuid-abc",
            "current_status": "todo",
            "action": "Send budget proposal to Sarah",
        }
    ]

    conflict = await _check_task_conflicts(task_completion_fact, mock_neo4j_client, "test-trace")

    assert conflict is not None
    assert "budget proposal" in conflict.entity.lower()
    assert "todo" in conflict.existing_fact
    assert conflict.resolution == ConflictResolution.EXPIRE_OLD


@pytest.mark.asyncio
async def test_check_task_conflicts_already_done(task_completion_fact, mock_neo4j_client):
    """Test no conflict when task already marked as done."""
    # Mock task already in done status
    mock_neo4j_client.execute_read.return_value = [
        {
            "task_uuid": "uuid-abc",
            "current_status": "done",
            "action": "Send budget proposal to Sarah",
        }
    ]

    conflict = await _check_task_conflicts(task_completion_fact, mock_neo4j_client, "test-trace")

    # Should not flag as conflict since it's already terminal state
    assert conflict is None


@pytest.mark.asyncio
async def test_check_task_conflicts_no_existing_task(task_completion_fact, mock_neo4j_client):
    """Test no conflict when task doesn't exist in graph."""
    # Mock no existing task
    mock_neo4j_client.execute_read.return_value = []

    conflict = await _check_task_conflicts(task_completion_fact, mock_neo4j_client, "test-trace")

    assert conflict is None


@pytest.mark.asyncio
async def test_check_task_conflicts_no_completion_keyword(mock_neo4j_client):
    """Test no conflict check when fact doesn't mention completion."""
    fact = ExtractedFact(
        entity="budget proposal",
        entity_type="Task",
        fact="Budget proposal is important",
        confidence=0.8,
    )

    conflict = await _check_task_conflicts(fact, mock_neo4j_client, "test-trace")

    assert conflict is None
    mock_neo4j_client.execute_read.assert_not_called()


# ===========================================================================
# Test detect_conflicts (Main Function)
# ===========================================================================


@pytest.mark.asyncio
async def test_detect_conflicts_multiple_types(mock_neo4j_client):
    """Test conflict detection with multiple entity types."""
    facts = [
        ExtractedFact(
            entity="Sarah",
            entity_type="Person",
            fact="Sarah works at TechCorp",
            confidence=0.9,
        ),
        ExtractedFact(
            entity="Project Phoenix",
            entity_type="Project",
            fact="Project Phoenix was completed",
            confidence=0.95,
        ),
        ExtractedFact(
            entity="Budget task",
            entity_type="Task",
            fact="Completed the budget task",
            confidence=0.85,
        ),
    ]

    # Mock responses for each query
    mock_neo4j_client.execute_read.side_effect = [
        [{"person_uuid": "uuid-1", "current_employer": "Acme", "r": {}}],  # Person
        [{"project_uuid": "uuid-2", "current_status": "active"}],  # Project
        [{"task_uuid": "uuid-3", "current_status": "todo", "action": "Budget task"}],  # Task
    ]

    conflicts = await detect_conflicts(facts, mock_neo4j_client, "test-trace")

    # Should detect 3 conflicts (one for each entity type)
    assert len(conflicts) == 3
    assert all(c.resolution == ConflictResolution.EXPIRE_OLD for c in conflicts)


@pytest.mark.asyncio
async def test_detect_conflicts_empty_facts(mock_neo4j_client):
    """Test conflict detection with no facts."""
    conflicts = await detect_conflicts([], mock_neo4j_client, "test-trace")

    assert len(conflicts) == 0
    mock_neo4j_client.execute_read.assert_not_called()


@pytest.mark.asyncio
async def test_detect_conflicts_no_conflicts_found(mock_neo4j_client):
    """Test when facts don't conflict with graph state."""
    facts = [
        ExtractedFact(
            entity="New Person",
            entity_type="Person",
            fact="New Person is friendly",
            confidence=0.8,
        )
    ]

    # Mock no existing data
    mock_neo4j_client.execute_read.return_value = []

    conflicts = await detect_conflicts(facts, mock_neo4j_client, "test-trace")

    assert len(conflicts) == 0


@pytest.mark.asyncio
async def test_detect_conflicts_unrecognized_entity_type(mock_neo4j_client):
    """Test handling of unrecognized entity types."""
    facts = [
        ExtractedFact(
            entity="Random",
            entity_type="UnknownType",
            fact="Random fact about something",
            confidence=0.7,
        )
    ]

    conflicts = await detect_conflicts(facts, mock_neo4j_client, "test-trace")

    # Should skip unrecognized types without error
    assert len(conflicts) == 0
    mock_neo4j_client.execute_read.assert_not_called()


# ===========================================================================
# Test apply_conflict_resolutions
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_expire_old_employment(mock_neo4j_client):
    """Test applying EXPIRE_OLD resolution for employment change."""
    conflicts = [
        FactConflict(
            existing_fact="Sarah works at Acme Corp",
            new_fact="Sarah works at TechCorp",
            entity="Sarah",
            resolution=ConflictResolution.EXPIRE_OLD,
        )
    ]

    # Mock successful expiration
    mock_neo4j_client.execute_write.return_value = [{"expired_count": 1}]

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 1
    mock_neo4j_client.execute_write.assert_called_once()


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_expire_old_status(mock_neo4j_client):
    """Test applying EXPIRE_OLD resolution for status change."""
    conflicts = [
        FactConflict(
            existing_fact="Project Phoenix status is active",
            new_fact="Project Phoenix was completed",
            entity="Project Phoenix",
            resolution=ConflictResolution.EXPIRE_OLD,
        )
    ]

    # Mock successful property update
    mock_neo4j_client.execute_write.return_value = [{"updated_count": 1}]

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 1
    mock_neo4j_client.execute_write.assert_called_once()


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_user_review(mock_neo4j_client):
    """Test that USER_REVIEW conflicts are not automatically applied."""
    conflicts = [
        FactConflict(
            existing_fact="Sarah works at Acme",
            new_fact="Sarah might work at TechCorp",
            entity="Sarah",
            resolution=ConflictResolution.USER_REVIEW,
        )
    ]

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 0
    mock_neo4j_client.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_keep_both(mock_neo4j_client):
    """Test that KEEP_BOTH conflicts are not automatically applied."""
    conflicts = [
        FactConflict(
            existing_fact="Sarah knows John",
            new_fact="Sarah knows John from work",
            entity="Sarah",
            resolution=ConflictResolution.KEEP_BOTH,
        )
    ]

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 0
    mock_neo4j_client.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_multiple_conflicts(mock_neo4j_client):
    """Test applying resolutions to multiple conflicts."""
    conflicts = [
        FactConflict(
            existing_fact="Sarah works at Acme",
            new_fact="Sarah works at TechCorp",
            entity="Sarah",
            resolution=ConflictResolution.EXPIRE_OLD,
        ),
        FactConflict(
            existing_fact="John works at Beta",
            new_fact="John works at Gamma",
            entity="John",
            resolution=ConflictResolution.EXPIRE_OLD,
        ),
        FactConflict(
            existing_fact="Task A is todo",
            new_fact="Task A is done",
            entity="Task A",
            resolution=ConflictResolution.USER_REVIEW,
        ),
    ]

    # Mock successful expiration for both EXPIRE_OLD conflicts
    mock_neo4j_client.execute_write.side_effect = [
        [{"expired_count": 1}],
        [{"expired_count": 1}],
    ]

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 2  # Only EXPIRE_OLD resolutions applied
    assert mock_neo4j_client.execute_write.call_count == 2


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_database_error(mock_neo4j_client):
    """Test handling of database errors during resolution."""
    conflicts = [
        FactConflict(
            existing_fact="Sarah works at Acme",
            new_fact="Sarah works at TechCorp",
            entity="Sarah",
            resolution=ConflictResolution.EXPIRE_OLD,
        )
    ]

    # Mock database error
    mock_neo4j_client.execute_write.side_effect = Exception("Database connection lost")

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 0  # Should handle error gracefully


@pytest.mark.asyncio
async def test_apply_conflict_resolutions_empty_list(mock_neo4j_client):
    """Test applying resolutions with empty conflict list."""
    conflicts = []

    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 0
    mock_neo4j_client.execute_write.assert_not_called()


# ===========================================================================
# Integration Test: Full Conflict Detection Pipeline
# ===========================================================================


@pytest.mark.asyncio
async def test_full_conflict_detection_pipeline(mock_neo4j_client):
    """Test complete pipeline: detect conflicts and apply resolutions."""
    # Sample facts with various conflict types
    facts = [
        ExtractedFact(
            entity="Sarah",
            entity_type="Person",
            fact="Sarah joined TechCorp as VP of Engineering",
            confidence=0.95,
        ),
        ExtractedFact(
            entity="Project Phoenix",
            entity_type="Project",
            fact="Project Phoenix was completed successfully",
            confidence=0.9,
        ),
    ]

    # Mock graph state showing conflicts
    mock_neo4j_client.execute_read.side_effect = [
        # Sarah currently works at Acme
        [{"person_uuid": "uuid-1", "current_employer": "Acme Corp", "r": {}}],
        # Project Phoenix is currently active
        [{"project_uuid": "uuid-2", "current_status": "active"}],
    ]

    # Mock successful resolution applications
    mock_neo4j_client.execute_write.side_effect = [
        [{"expired_count": 1}],  # Expire old employment
        [{"updated_count": 1}],  # Update project status
    ]

    # Step 1: Detect conflicts
    conflicts = await detect_conflicts(facts, mock_neo4j_client, "test-trace")

    assert len(conflicts) == 2
    assert all(c.resolution == ConflictResolution.EXPIRE_OLD for c in conflicts)

    # Step 2: Apply resolutions
    applied = await apply_conflict_resolutions(conflicts, mock_neo4j_client, "test-trace")

    assert applied == 2
    assert mock_neo4j_client.execute_write.call_count == 2
