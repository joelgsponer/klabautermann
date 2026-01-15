"""
Unit tests for journal generation pipeline.

Tests journal generation with mocked Anthropic API to verify:
- Analytics formatting
- LLM prompt construction
- Response parsing and validation
- Various day scenarios (busy, quiet, productive)

Reference: T045 - Journal Generation Pipeline
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.journal_generation import (
    format_analytics_for_prompt,
    generate_journal,
)
from klabautermann.core.models import DailyAnalytics, JournalEntry


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def busy_day_analytics() -> DailyAnalytics:
    """Analytics for a busy, productive day."""
    return DailyAnalytics(
        date="2026-01-15",
        interaction_count=47,
        new_entities={"Person": 3, "Organization": 2, "Project": 1},
        tasks_completed=8,
        tasks_created=5,
        top_projects=[
            {"name": "Q1 Budget", "mentions": 12},
            {"name": "Marketing Campaign", "mentions": 7},
            {"name": "Product Launch", "mentions": 5},
        ],
        notes_created=4,
        events_count=6,
    )


@pytest.fixture
def quiet_day_analytics() -> DailyAnalytics:
    """Analytics for a quiet, calm day."""
    return DailyAnalytics(
        date="2026-01-15",
        interaction_count=5,
        new_entities={},
        tasks_completed=1,
        tasks_created=0,
        top_projects=[],
        notes_created=0,
        events_count=1,
    )


@pytest.fixture
def challenging_day_analytics() -> DailyAnalytics:
    """Analytics for a challenging day (many tasks created, few completed)."""
    return DailyAnalytics(
        date="2026-01-15",
        interaction_count=32,
        new_entities={"Person": 1},
        tasks_completed=2,
        tasks_created=15,
        top_projects=[{"name": "Crisis Response", "mentions": 20}],
        notes_created=3,
        events_count=8,
    )


@pytest.fixture
def mock_journal_response() -> dict[str, Any]:
    """Mock LLM response for journal generation."""
    return {
        "content": """VOYAGE SUMMARY
Today the Captain navigated choppy waters with 47 messages across The Bridge.
The day brought a flurry of activity—new contacts from three organizations,
and significant progress on the Q1 Budget voyage.

KEY INTERACTIONS
Sarah from Acme signaled progress on the budget proposal.
Met representatives from two new organizations: TechCorp and DataWorks.
The Marketing Campaign gained momentum with input from the new Product Lead.

PROGRESS REPORT
Eight tasks walked the plank today—a strong showing.
The Manifest grew by five new items, keeping our bearing steady.
Four notes captured key decisions and observations.

WORKFLOW OBSERVATIONS
I notice the Captain maintains good momentum when projects have clear milestones.
The back-to-back meetings on budget planning were productive but intense.
Perhaps we schedule breathing room between high-stakes discussions next time.

SAILOR'S THINKING
A productive voyage indeed. The crew is aligned, the wind is fair, and The Charts
show promising waters ahead. Tomorrow brings the board meeting—I've prepared
the Q1 materials in The Locker. Steady as she goes.""",
        "summary": "Busy day with 47 interactions, 8 tasks completed, strong progress on Q1 Budget",
        "highlights": [
            "Met representatives from TechCorp and DataWorks",
            "Completed 8 tasks including budget milestones",
            "Made significant progress on Q1 Budget planning",
            "Captured 4 key decision notes",
        ],
        "mood": "productive",
        "forward_look": "Tomorrow brings the board meeting—I've prepared the Q1 materials in The Locker.",
    }


# ===========================================================================
# Tests: Analytics Formatting
# ===========================================================================


def test_format_analytics_busy_day(busy_day_analytics: DailyAnalytics) -> None:
    """Test formatting of analytics for a busy day."""
    result = format_analytics_for_prompt(busy_day_analytics)

    assert "2026-01-15" in result
    assert "47 messages" in result
    assert "8 tasks walked the plank" in result
    assert "5 new tasks added" in result
    assert "3 Persons" in result or "3 Person" in result
    assert "2 Organizations" in result or "2 Organization" in result
    assert "Q1 Budget" in result
    assert "4 notes" in result
    assert "6 events" in result


def test_format_analytics_quiet_day(quiet_day_analytics: DailyAnalytics) -> None:
    """Test formatting of analytics for a quiet day."""
    result = format_analytics_for_prompt(quiet_day_analytics)

    assert "2026-01-15" in result
    assert "5 messages" in result
    assert "1 tasks walked the plank" in result or "1 task walked the plank" in result
    assert "0 new tasks" in result
    assert "no new entries" in result
    assert "no specific projects" in result


def test_format_analytics_empty_entities() -> None:
    """Test formatting when new_entities dict is empty."""
    analytics = DailyAnalytics(
        date="2026-01-15",
        interaction_count=10,
        new_entities={},
        tasks_completed=2,
        tasks_created=1,
        top_projects=[],
        notes_created=0,
        events_count=0,
    )

    result = format_analytics_for_prompt(analytics)
    assert "no new entries" in result


def test_format_analytics_zero_count_entities() -> None:
    """Test formatting when entities have zero counts."""
    analytics = DailyAnalytics(
        date="2026-01-15",
        interaction_count=10,
        new_entities={"Person": 0, "Organization": 0},
        tasks_completed=2,
        tasks_created=1,
        top_projects=[],
        notes_created=0,
        events_count=0,
    )

    result = format_analytics_for_prompt(analytics)
    assert "no new entries" in result


# ===========================================================================
# Tests: Journal Generation
# ===========================================================================


@pytest.mark.asyncio
async def test_generate_journal_busy_day(
    busy_day_analytics: DailyAnalytics, mock_journal_response: dict[str, Any]
) -> None:
    """Test journal generation for a busy day."""
    # Mock Anthropic API response
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = mock_journal_response
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        # Generate journal
        entry = await generate_journal(busy_day_analytics)

        # Verify it's a valid JournalEntry
        assert isinstance(entry, JournalEntry)
        assert entry.content
        assert entry.summary
        assert entry.mood in ["productive", "challenging", "calm", "busy", "mixed", "quiet"]
        assert entry.forward_look
        assert len(entry.highlights) > 0

        # Verify Anthropic API was called correctly
        mock_instance.messages.create.assert_called_once()
        call_kwargs = mock_instance.messages.create.call_args.kwargs

        assert call_kwargs["model"] == "claude-3-haiku-20240307"
        assert call_kwargs["max_tokens"] == 1500
        assert call_kwargs["temperature"] == 0.7
        assert "system" in call_kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "write_journal"}


@pytest.mark.asyncio
async def test_generate_journal_quiet_day(quiet_day_analytics: DailyAnalytics) -> None:
    """Test journal generation for a quiet day."""
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "content": "VOYAGE SUMMARY\nA quiet day on The Bridge with just 5 messages.",
        "summary": "Quiet day with minimal activity",
        "highlights": ["Completed one task", "Calm and focused work"],
        "mood": "calm",
        "forward_look": "Tomorrow brings new opportunities.",
    }
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        entry = await generate_journal(quiet_day_analytics)

        assert isinstance(entry, JournalEntry)
        assert entry.mood == "calm"
        assert entry.content
        assert entry.summary


@pytest.mark.asyncio
async def test_generate_journal_challenging_day(
    challenging_day_analytics: DailyAnalytics,
) -> None:
    """Test journal generation for a challenging day."""
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "content": "VOYAGE SUMMARY\nRough waters today with Crisis Response dominating the charts.",
        "summary": "Challenging day with crisis response, many new tasks",
        "highlights": [
            "Managed crisis response effectively",
            "Created 15 new tasks to track action items",
            "Maintained composure under pressure",
        ],
        "mood": "challenging",
        "forward_look": "The storm will pass. We sail on.",
    }
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        entry = await generate_journal(challenging_day_analytics)

        assert isinstance(entry, JournalEntry)
        assert entry.mood == "challenging"
        assert "Crisis" in entry.content or "crisis" in entry.content


@pytest.mark.asyncio
async def test_generate_journal_prompt_includes_analytics(
    busy_day_analytics: DailyAnalytics,
) -> None:
    """Test that the prompt includes all analytics data."""
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "content": "Test content",
        "summary": "Test summary",
        "highlights": ["Test"],
        "mood": "productive",
        "forward_look": "Test forward",
    }
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        await generate_journal(busy_day_analytics)

        # Check that the user prompt includes key analytics
        call_kwargs = mock_instance.messages.create.call_args.kwargs
        user_message = call_kwargs["messages"][0]["content"]

        assert "47 messages" in user_message
        assert "8 tasks walked the plank" in user_message
        assert "Q1 Budget" in user_message
        assert "2026-01-15" in user_message


# ===========================================================================
# Tests: Error Handling
# ===========================================================================


@pytest.mark.asyncio
async def test_generate_journal_missing_tool_use(busy_day_analytics: DailyAnalytics) -> None:
    """Test error handling when LLM doesn't return tool_use block."""
    mock_response = MagicMock()
    mock_response.content = []  # No tool_use block

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        with pytest.raises(ValueError, match="missing tool_use block"):
            await generate_journal(busy_day_analytics)


@pytest.mark.asyncio
async def test_generate_journal_invalid_schema(busy_day_analytics: DailyAnalytics) -> None:
    """Test error handling when LLM returns invalid schema."""
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "content": "Test",
        # Missing required fields: summary, highlights, mood, forward_look
    }
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        with pytest.raises(ValueError, match="Invalid journal entry schema"):
            await generate_journal(busy_day_analytics)


# ===========================================================================
# Tests: Mood Classification
# ===========================================================================


@pytest.mark.asyncio
async def test_generate_journal_mood_values() -> None:
    """Test that all valid mood values are accepted."""
    valid_moods = ["productive", "challenging", "calm", "busy", "mixed", "quiet"]

    for mood in valid_moods:
        mock_response = MagicMock()
        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.input = {
            "content": f"Test content for {mood}",
            "summary": "Test summary",
            "highlights": ["Test"],
            "mood": mood,
            "forward_look": "Test forward",
        }
        mock_response.content = [mock_tool_use]

        with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.messages.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            analytics = DailyAnalytics(
                date="2026-01-15",
                interaction_count=10,
                new_entities={},
                tasks_completed=2,
                tasks_created=1,
                top_projects=[],
                notes_created=0,
                events_count=0,
            )

            entry = await generate_journal(analytics)
            assert entry.mood == mood


@pytest.mark.asyncio
async def test_generate_journal_all_fields_populated(
    busy_day_analytics: DailyAnalytics, mock_journal_response: dict[str, Any]
) -> None:
    """Test that all JournalEntry fields are populated correctly."""
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = mock_journal_response
    mock_response.content = [mock_tool_use]

    with patch("klabautermann.agents.journal_generation.AsyncAnthropic") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        entry = await generate_journal(busy_day_analytics)

        # Verify all fields
        assert entry.content == mock_journal_response["content"]
        assert entry.summary == mock_journal_response["summary"]
        assert entry.highlights == mock_journal_response["highlights"]
        assert entry.mood == mock_journal_response["mood"]
        assert entry.forward_look == mock_journal_response["forward_look"]

        # Verify content structure (should have five sections)
        assert "VOYAGE SUMMARY" in entry.content
        assert "KEY INTERACTIONS" in entry.content
        assert "PROGRESS REPORT" in entry.content
        assert "WORKFLOW OBSERVATIONS" in entry.content
        assert "SAILOR'S THINKING" in entry.content
