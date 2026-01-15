"""
Unit tests for Scribe Agent.

Reference: specs/architecture/AGENTS.md Section 1.6
Task: T046 - Scribe Agent Implementation

The Scribe's job is to:
1. Generate daily reflection journal entries
2. Gather analytics for the specified day
3. Create JournalEntry nodes in the graph
4. Link journal entries to Day nodes via [:OCCURRED_ON]
5. Ensure idempotency (no duplicate journals for same day)

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from klabautermann.agents.scribe import Scribe
from klabautermann.core.models import AgentMessage, DailyAnalytics, JournalEntry


class TestScribeInitialization:
    """Test suite for Scribe agent initialization."""

    def test_initializes_with_defaults(self) -> None:
        """Should initialize with default configuration."""
        scribe = Scribe()

        assert scribe.name == "scribe"
        assert scribe.min_interactions == 1
        assert scribe.include_highlights is True
        assert scribe.max_content_length == 2000

    def test_applies_custom_config(self) -> None:
        """Should apply custom configuration values."""
        config = {
            "min_interactions": 5,
            "journal": {
                "include_highlights": False,
                "max_content_length": 1000,
            },
        }
        scribe = Scribe(config=config)

        assert scribe.min_interactions == 5
        assert scribe.include_highlights is False
        assert scribe.max_content_length == 1000

    def test_accepts_neo4j_client(self) -> None:
        """Should accept and store Neo4jClient."""
        mock_neo4j = Mock()
        scribe = Scribe(neo4j_client=mock_neo4j)

        assert scribe.neo4j is mock_neo4j


class TestGenerateDailyReflection:
    """Test suite for daily reflection generation."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[{"uuid": "journal-uuid-123"}])
        return mock

    @pytest.fixture
    def scribe(self, mock_neo4j: Mock) -> Scribe:
        """Create a Scribe instance with mocked Neo4j."""
        return Scribe(
            name="scribe",
            config={"min_interactions": 1},
            neo4j_client=mock_neo4j,
        )

    @pytest.fixture
    def sample_analytics(self) -> DailyAnalytics:
        """Create sample DailyAnalytics for testing."""
        return DailyAnalytics(
            date="2026-01-15",
            interaction_count=23,
            new_entities={"Person": 2, "Organization": 1},
            tasks_completed=3,
            tasks_created=2,
            top_projects=[{"name": "Q1 Budget", "uuid": "proj-1"}],
            notes_created=1,
            events_count=4,
        )

    @pytest.fixture
    def sample_journal(self) -> JournalEntry:
        """Create sample JournalEntry for testing."""
        return JournalEntry(
            content="Today the Captain navigated choppy waters...",
            summary="Productive day with 23 messages",
            highlights=["Q1 Budget progress", "Meeting with Sarah", "3 tasks completed"],
            mood="productive",
            forward_look="Tomorrow looks promising with board meeting scheduled.",
        )

    @pytest.mark.asyncio
    async def test_defaults_to_yesterday(
        self, scribe: Scribe, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should default to yesterday's date when no date provided."""
        # Mock the analytics and journal generation
        mock_analytics = DailyAnalytics(
            date="2026-01-14",
            interaction_count=5,
            new_entities={},
            tasks_completed=1,
            tasks_created=0,
            top_projects=[],
            notes_created=0,
            events_count=0,
        )
        mock_journal = JournalEntry(
            content="Test content",
            summary="Test summary",
            highlights=["Test"],
            mood="calm",
            forward_look="Test forward look",
        )

        async def mock_get_analytics(*args, **kwargs):
            return mock_analytics

        async def mock_generate_journal(*args, **kwargs):
            return mock_journal

        monkeypatch.setattr(
            "klabautermann.agents.scribe.get_daily_analytics",
            mock_get_analytics,
        )
        monkeypatch.setattr(
            "klabautermann.agents.scribe.generate_journal",
            mock_generate_journal,
        )

        # Mock datetime to control "today"
        fake_now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(
            "klabautermann.agents.scribe.datetime",
            Mock(now=Mock(return_value=fake_now), strptime=datetime.strptime),
        )

        result = await scribe.generate_daily_reflection()

        # Should have checked for date "2026-01-14" (yesterday)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_if_journal_exists(self, scribe: Scribe, mock_neo4j: Mock) -> None:
        """Should return None if journal already exists for date."""
        # Mock journal exists
        mock_neo4j.execute_read = AsyncMock(return_value=[{"uuid": "existing-journal"}])

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_insufficient_activity(
        self, scribe: Scribe, mock_neo4j: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return None if activity below minimum threshold."""
        # Configure higher threshold
        scribe.min_interactions = 10

        # Mock low activity analytics
        low_activity_analytics = DailyAnalytics(
            date="2026-01-15",
            interaction_count=3,  # Below threshold of 10
            new_entities={},
            tasks_completed=0,
            tasks_created=0,
            top_projects=[],
            notes_created=0,
            events_count=0,
        )

        async def mock_get_analytics(*args, **kwargs):
            return low_activity_analytics

        monkeypatch.setattr(
            "klabautermann.agents.scribe.get_daily_analytics",
            mock_get_analytics,
        )

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is None

    @pytest.mark.asyncio
    async def test_generates_journal_with_sufficient_activity(
        self,
        scribe: Scribe,
        mock_neo4j: Mock,
        sample_analytics: DailyAnalytics,
        sample_journal: JournalEntry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should generate journal when activity meets threshold."""

        async def mock_get_analytics(*args, **kwargs):
            return sample_analytics

        async def mock_generate_journal(*args, **kwargs):
            return sample_journal

        monkeypatch.setattr(
            "klabautermann.agents.scribe.get_daily_analytics",
            mock_get_analytics,
        )
        monkeypatch.setattr(
            "klabautermann.agents.scribe.generate_journal",
            mock_generate_journal,
        )

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is not None
        # Should have created journal node
        mock_neo4j.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_without_neo4j_client(self) -> None:
        """Should return None if Neo4jClient not configured."""
        scribe = Scribe(neo4j_client=None)

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_analytics_error_gracefully(
        self, scribe: Scribe, mock_neo4j: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should handle analytics gathering errors gracefully."""

        async def mock_get_analytics(*args, **kwargs):
            raise Exception("Database connection failed")

        monkeypatch.setattr(
            "klabautermann.agents.scribe.get_daily_analytics",
            mock_get_analytics,
        )

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_journal_generation_error(
        self,
        scribe: Scribe,
        mock_neo4j: Mock,
        sample_analytics: DailyAnalytics,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should handle journal generation errors gracefully."""

        async def mock_get_analytics(*args, **kwargs):
            return sample_analytics

        async def mock_generate_journal(*args, **kwargs):
            raise Exception("LLM call failed")

        monkeypatch.setattr(
            "klabautermann.agents.scribe.get_daily_analytics",
            mock_get_analytics,
        )
        monkeypatch.setattr(
            "klabautermann.agents.scribe.generate_journal",
            mock_generate_journal,
        )

        result = await scribe.generate_daily_reflection(date="2026-01-15")

        assert result is None


class TestJournalNodeCreation:
    """Test suite for journal node creation."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_write = AsyncMock(return_value=[{"uuid": "journal-uuid-123"}])
        return mock

    @pytest.fixture
    def scribe(self, mock_neo4j: Mock) -> Scribe:
        """Create a Scribe instance with mocked Neo4j."""
        return Scribe(neo4j_client=mock_neo4j)

    @pytest.fixture
    def sample_journal(self) -> JournalEntry:
        """Create sample JournalEntry for testing."""
        return JournalEntry(
            content="Today the Captain navigated choppy waters...",
            summary="Productive day with 23 messages",
            highlights=["Q1 Budget progress", "Meeting with Sarah", "3 tasks completed"],
            mood="productive",
            forward_look="Tomorrow looks promising.",
        )

    @pytest.fixture
    def sample_analytics(self) -> DailyAnalytics:
        """Create sample DailyAnalytics for testing."""
        return DailyAnalytics(
            date="2026-01-15",
            interaction_count=23,
            new_entities={"Person": 2, "Organization": 1},
            tasks_completed=3,
            tasks_created=2,
            top_projects=[],
            notes_created=1,
            events_count=4,
        )

    @pytest.mark.asyncio
    async def test_creates_journal_node_with_all_fields(
        self,
        scribe: Scribe,
        mock_neo4j: Mock,
        sample_journal: JournalEntry,
        sample_analytics: DailyAnalytics,
    ) -> None:
        """Should create JournalEntry node with all required fields."""
        journal_uuid = await scribe._create_journal_node(
            date="2026-01-15",
            journal=sample_journal,
            analytics=sample_analytics,
        )

        assert journal_uuid is not None
        mock_neo4j.execute_write.assert_called_once()

        # Verify the query parameters
        call_args = mock_neo4j.execute_write.call_args
        params = call_args[0][1]

        assert params["date"] == "2026-01-15"
        assert params["content"] == sample_journal.content
        assert params["summary"] == sample_journal.summary
        assert params["mood"] == sample_journal.mood
        assert params["forward_look"] == sample_journal.forward_look
        assert params["highlights"] == sample_journal.highlights
        assert params["interaction_count"] == 23
        assert params["tasks_completed"] == 3
        assert params["new_entities_count"] == 3  # 2 Person + 1 Organization

    @pytest.mark.asyncio
    async def test_truncates_content_to_max_length(
        self,
        scribe: Scribe,
        mock_neo4j: Mock,
        sample_analytics: DailyAnalytics,
    ) -> None:
        """Should truncate content to configured max length."""
        # Set low max length
        scribe.max_content_length = 50

        long_journal = JournalEntry(
            content="A" * 1000,  # Very long content
            summary="Test",
            highlights=["Test"],
            mood="productive",
            forward_look="Test",
        )

        await scribe._create_journal_node(
            date="2026-01-15",
            journal=long_journal,
            analytics=sample_analytics,
        )

        # Verify content was truncated
        call_args = mock_neo4j.execute_write.call_args
        params = call_args[0][1]
        assert len(params["content"]) == 50

    @pytest.mark.asyncio
    async def test_excludes_highlights_when_disabled(
        self,
        mock_neo4j: Mock,
        sample_journal: JournalEntry,
        sample_analytics: DailyAnalytics,
    ) -> None:
        """Should exclude highlights when include_highlights is False."""
        scribe = Scribe(
            config={"journal": {"include_highlights": False}},
            neo4j_client=mock_neo4j,
        )

        await scribe._create_journal_node(
            date="2026-01-15",
            journal=sample_journal,
            analytics=sample_analytics,
        )

        # Verify highlights array is empty
        call_args = mock_neo4j.execute_write.call_args
        params = call_args[0][1]
        assert params["highlights"] == []

    @pytest.mark.asyncio
    async def test_raises_error_without_neo4j_client(
        self, sample_journal: JournalEntry, sample_analytics: DailyAnalytics
    ) -> None:
        """Should raise error if Neo4jClient not configured."""
        scribe = Scribe(neo4j_client=None)

        with pytest.raises(ValueError, match="Neo4jClient not configured"):
            await scribe._create_journal_node(
                date="2026-01-15",
                journal=sample_journal,
                analytics=sample_analytics,
            )


class TestGetRecentJournals:
    """Test suite for retrieving recent journals."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(
            return_value=[
                {
                    "uuid": "journal-1",
                    "date": "2026-01-15",
                    "summary": "Productive day",
                    "mood": "productive",
                    "interaction_count": 23,
                    "tasks_completed": 3,
                    "generated_at": 1737000000.0,
                },
                {
                    "uuid": "journal-2",
                    "date": "2026-01-14",
                    "summary": "Calm day",
                    "mood": "calm",
                    "interaction_count": 5,
                    "tasks_completed": 1,
                    "generated_at": 1736900000.0,
                },
            ]
        )
        return mock

    @pytest.fixture
    def scribe(self, mock_neo4j: Mock) -> Scribe:
        """Create a Scribe instance with mocked Neo4j."""
        return Scribe(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_retrieves_recent_journals(self, scribe: Scribe, mock_neo4j: Mock) -> None:
        """Should retrieve recent journal entries."""
        journals = await scribe.get_recent_journals(days=7)

        assert len(journals) == 2
        assert journals[0]["uuid"] == "journal-1"
        assert journals[0]["date"] == "2026-01-15"
        assert journals[1]["uuid"] == "journal-2"

        # Verify query was called with correct limit
        call_args = mock_neo4j.execute_read.call_args
        params = call_args[0][1]
        assert params["days"] == 7

    @pytest.mark.asyncio
    async def test_returns_empty_list_without_neo4j(self) -> None:
        """Should return empty list if Neo4jClient not configured."""
        scribe = Scribe(neo4j_client=None)

        journals = await scribe.get_recent_journals()

        assert journals == []

    @pytest.mark.asyncio
    async def test_handles_query_error_gracefully(self, scribe: Scribe, mock_neo4j: Mock) -> None:
        """Should handle query errors gracefully."""
        mock_neo4j.execute_read = AsyncMock(side_effect=Exception("Query failed"))

        journals = await scribe.get_recent_journals()

        assert journals == []


class TestProcessMessage:
    """Test suite for agent message processing."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[{"uuid": "journal-uuid-123"}])
        return mock

    @pytest.fixture
    def scribe(self, mock_neo4j: Mock) -> Scribe:
        """Create a Scribe instance with mocked Neo4j."""
        scribe = Scribe(neo4j_client=mock_neo4j)
        # Mock the generate_daily_reflection method
        scribe.generate_daily_reflection = AsyncMock(return_value="journal-uuid-123")
        return scribe

    @pytest.mark.asyncio
    async def test_handles_generate_journal_intent(self, scribe: Scribe) -> None:
        """Should handle generate_journal intent."""
        msg = AgentMessage(
            trace_id="test-trace-001",
            source_agent="scheduler",
            target_agent="scribe",
            intent="generate_journal",
            payload={"date": "2026-01-15"},
        )

        response = await scribe.process_message(msg)

        assert response is not None
        assert response.intent == "journal_generated"
        assert response.payload["journal_uuid"] == "journal-uuid-123"
        assert response.payload["date"] == "2026-01-15"
        assert response.payload["success"] is True

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_intent(self, scribe: Scribe) -> None:
        """Should return None for unknown intent."""
        msg = AgentMessage(
            trace_id="test-trace-001",
            source_agent="orchestrator",
            target_agent="scribe",
            intent="unknown_intent",
            payload={},
        )

        response = await scribe.process_message(msg)

        assert response is None


class TestIdempotency:
    """Test suite for idempotency guarantees."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        # First call: journal exists
        # Second call: journal doesn't exist
        mock.execute_read = AsyncMock(
            side_effect=[
                [{"uuid": "existing-journal"}],  # Journal exists
                [],  # Journal doesn't exist (for second check)
            ]
        )
        mock.execute_write = AsyncMock(return_value=[{"uuid": "new-journal-uuid"}])
        return mock

    @pytest.fixture
    def scribe(self, mock_neo4j: Mock) -> Scribe:
        """Create a Scribe instance with mocked Neo4j."""
        return Scribe(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_does_not_create_duplicate_journal(
        self, scribe: Scribe, mock_neo4j: Mock
    ) -> None:
        """Should not create duplicate journal if one already exists."""
        # First call - journal exists
        result = await scribe.generate_daily_reflection(date="2026-01-15")
        assert result is None  # Should skip because journal already exists


# ===========================================================================
# Integration Test Markers
# ===========================================================================


@pytest.mark.integration
class TestScribeIntegration:
    """Integration tests requiring real Neo4j connection."""

    @pytest.mark.skip(reason="Requires Neo4j and full setup")
    @pytest.mark.asyncio
    async def test_end_to_end_journal_generation(self) -> None:
        """End-to-end test: generate journal, verify in graph."""
        # This would test with real Neo4j and Anthropic API
        pass
