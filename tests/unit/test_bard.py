"""
Unit tests for BardOfTheBilge agent.

Tests lore storytelling functionality including tidbit generation,
saga management, LoreEpisode persistence, and response salting.

Issues: #37, #38, #39, #40
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.bard import (
    CANONICAL_TIDBITS,
    ActiveSaga,
    BardConfig,
    BardOfTheBilge,
    ChapterTooSoonError,
    LoreEpisode,
    SagaCompleteError,
    SagaLifecycleError,
    SagaLimitReachedError,
    SagaTimedOutError,
    SaltResult,
    generate_saga_name,
)
from klabautermann.core.models import AgentMessage


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4j client."""
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def captain_uuid() -> str:
    """Fixture for Captain's UUID."""
    return "captain-test-uuid-12345"


@pytest.fixture
def bard(mock_neo4j: MagicMock, captain_uuid: str) -> BardOfTheBilge:
    """Create a BardOfTheBilge instance with mock dependencies."""
    config = BardConfig(
        tidbit_probability=0.5,  # 50% for easier testing
        saga_continuation_probability=0.5,
        max_saga_chapters=5,
        min_chapter_interval_hours=0,  # Disable interval for basic tests
    )
    return BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)


@pytest.fixture
def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


# =============================================================================
# Basic Tests
# =============================================================================


class TestBardOfTheBilgeInit:
    """Tests for BardOfTheBilge initialization."""

    def test_init_default_config(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """BardOfTheBilge should initialize with default config."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        assert bard.name == "bard_of_the_bilge"
        assert bard.captain_uuid == captain_uuid
        assert bard.bard_config.tidbit_probability == 0.07

    def test_init_custom_config(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """BardOfTheBilge should accept custom config."""
        config = BardConfig(
            tidbit_probability=0.15,
            saga_continuation_probability=0.4,
            max_saga_chapters=3,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        assert bard.bard_config.tidbit_probability == 0.15
        assert bard.bard_config.saga_continuation_probability == 0.4
        assert bard.bard_config.max_saga_chapters == 3

    def test_canonical_tidbits_available(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """BardOfTheBilge should have access to canonical tidbits."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        assert len(bard.CANONICAL_TIDBITS) == 10
        assert len(CANONICAL_TIDBITS) == 10


# =============================================================================
# Salt Response Tests
# =============================================================================


class TestSaltResponse:
    """Tests for response salting functionality."""

    @pytest.mark.asyncio
    async def test_salt_response_storm_mode_skips(self, bard: BardOfTheBilge) -> None:
        """Storm mode should always skip tidbit addition."""
        clean_response = "Task completed successfully."

        result = await bard.salt_response(clean_response, storm_mode=True, trace_id="test-123")

        assert result.tidbit_added is False
        assert result.storm_mode_skipped is True
        assert result.salted_response == clean_response
        assert result.original_response == clean_response

    @pytest.mark.asyncio
    async def test_salt_response_probability_skip(self, bard: BardOfTheBilge) -> None:
        """Should skip tidbit when probability roll fails."""
        clean_response = "Task completed successfully."

        # Force probability to fail
        with patch("klabautermann.agents.bard.random.random", return_value=0.99):
            result = await bard.salt_response(clean_response, trace_id="test-123")

        assert result.tidbit_added is False
        assert result.storm_mode_skipped is False
        assert result.salted_response == clean_response

    @pytest.mark.asyncio
    async def test_salt_response_adds_tidbit(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should add tidbit when probability passes and no active saga."""
        clean_response = "Task completed successfully."
        mock_neo4j.execute_query.return_value = []  # No active saga

        # Force probability to pass
        with patch("klabautermann.agents.bard.random.random", return_value=0.01):
            result = await bard.salt_response(clean_response, trace_id="test-123")

        assert result.tidbit_added is True
        assert result.tidbit is not None
        assert result.tidbit in CANONICAL_TIDBITS
        assert f"_{result.tidbit}_" in result.salted_response
        assert clean_response in result.salted_response

    @pytest.mark.asyncio
    async def test_salt_response_continues_saga(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should continue saga when active and probability passes."""
        clean_response = "Task completed successfully."

        # Mock active saga exists
        mock_neo4j.execute_query.side_effect = [
            # First call: _get_active_saga
            [
                {
                    "saga_id": "saga-123",
                    "saga_name": "The Tale of the Lost Packet",
                    "last_chapter": 2,
                    "last_told": now_ms - 1000,
                }
            ],
            # Second call: _save_episode
            [{"uuid": "episode-456"}],
        ]

        # Force both probability checks to pass
        with patch("klabautermann.agents.bard.random.random", side_effect=[0.01, 0.01]):
            result = await bard.salt_response(clean_response, trace_id="test-123")

        assert result.tidbit_added is True
        assert result.is_continuation is True
        assert result.saga_id == "saga-123"
        assert result.chapter == 3


# =============================================================================
# Saga Management Tests
# =============================================================================


class TestSagaManagement:
    """Tests for saga management functionality."""

    @pytest.mark.asyncio
    async def test_get_active_saga_none(self, bard: BardOfTheBilge, mock_neo4j: MagicMock) -> None:
        """Should return None when no active saga exists."""
        mock_neo4j.execute_query.return_value = []

        saga = await bard._get_active_saga(trace_id="test-123")

        assert saga is None

    @pytest.mark.asyncio
    async def test_get_active_saga_found(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return ActiveSaga when one exists."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-123",
                "saga_name": "The Chronicle of the Haunted Hash",
                "last_chapter": 3,
                "last_told": now_ms,
            }
        ]

        saga = await bard._get_active_saga(trace_id="test-123")

        assert saga is not None
        assert saga.saga_id == "saga-123"
        assert saga.saga_name == "The Chronicle of the Haunted Hash"
        assert saga.last_chapter == 3

    @pytest.mark.asyncio
    async def test_get_saga_chapters(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should retrieve saga chapters in order."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Chapter one content",
                "told_at": now_ms - 2000,
                "created_at": now_ms - 2000,
                "captain_uuid": "captain-123",
            },
            {
                "uuid": "ep-2",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 2,
                "content": "Chapter two content",
                "told_at": now_ms - 1000,
                "created_at": now_ms - 1000,
                "captain_uuid": "captain-123",
            },
        ]

        chapters = await bard._get_saga_chapters("saga-123", limit=5, trace_id="test-123")

        assert len(chapters) == 2
        assert chapters[0].chapter == 1
        assert chapters[1].chapter == 2
        assert chapters[0].content == "Chapter one content"

    @pytest.mark.asyncio
    async def test_start_new_saga(self, bard: BardOfTheBilge, mock_neo4j: MagicMock) -> None:
        """Should create a new saga with chapter 1."""
        mock_neo4j.execute_query.side_effect = [
            # First call: _get_active_sagas (returns empty - below limit)
            [],
            # Second call: _save_episode
            [{"uuid": "episode-new"}],
        ]

        content, saga_id, chapter = await bard.start_new_saga(trace_id="test-123")

        assert content in CANONICAL_TIDBITS
        assert saga_id is not None
        assert chapter == 1
        assert mock_neo4j.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_save_episode_creates_node(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should create LoreEpisode with correct relationships."""
        mock_neo4j.execute_query.return_value = [{"uuid": "episode-123"}]

        uuid = await bard._save_episode(
            saga_id="saga-test",
            saga_name="The Ballad of Testing",
            chapter=2,
            content="A test tidbit for the ages.",
            trace_id="test-123",
        )

        assert uuid is not None
        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]

        # Verify query creates proper relationships
        assert "CREATE (le:LoreEpisode" in query
        assert "TOLD_TO" in query
        assert "EXPANDS_UPON" in query
        assert call_args[0][1]["saga_id"] == "saga-test"
        assert call_args[0][1]["chapter"] == 2


# =============================================================================
# LoreEpisode Model Tests
# =============================================================================


class TestLoreEpisodeModel:
    """Tests for LoreEpisode dataclass."""

    def test_lore_episode_to_dict(self, now_ms: int) -> None:
        """LoreEpisode should serialize to dict."""
        episode = LoreEpisode(
            uuid="ep-123",
            saga_id="saga-456",
            saga_name="The Tale of Testing",
            chapter=1,
            content="Once upon a test...",
            told_at=now_ms,
            created_at=now_ms,
            captain_uuid="captain-789",
        )

        d = episode.to_dict()

        assert d["uuid"] == "ep-123"
        assert d["saga_id"] == "saga-456"
        assert d["saga_name"] == "The Tale of Testing"
        assert d["chapter"] == 1
        assert d["content"] == "Once upon a test..."
        assert d["captain_uuid"] == "captain-789"


# =============================================================================
# SaltResult Model Tests
# =============================================================================


class TestSaltResultModel:
    """Tests for SaltResult dataclass."""

    def test_salt_result_to_dict_with_tidbit(self) -> None:
        """SaltResult should serialize to dict with tidbit."""
        result = SaltResult(
            original_response="Hello",
            salted_response="Hello\n\n_A tidbit_",
            tidbit_added=True,
            tidbit="A tidbit",
            saga_id="saga-123",
            chapter=2,
            is_continuation=True,
        )

        d = result.to_dict()

        assert d["tidbit_added"] is True
        assert d["tidbit"] == "A tidbit"
        assert d["saga_id"] == "saga-123"
        assert d["chapter"] == 2
        assert d["is_continuation"] is True

    def test_salt_result_to_dict_no_tidbit(self) -> None:
        """SaltResult should serialize correctly when no tidbit added."""
        result = SaltResult(
            original_response="Hello",
            salted_response="Hello",
            tidbit_added=False,
            storm_mode_skipped=True,
        )

        d = result.to_dict()

        assert d["tidbit_added"] is False
        assert d["tidbit"] is None
        assert d["storm_mode_skipped"] is True


# =============================================================================
# ActiveSaga Model Tests
# =============================================================================


class TestActiveSagaModel:
    """Tests for ActiveSaga dataclass."""

    def test_active_saga_creation(self, now_ms: int) -> None:
        """ActiveSaga should store saga metadata."""
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="The Legend of the Daemon",
            last_chapter=3,
            last_told=now_ms,
        )

        assert saga.saga_id == "saga-123"
        assert saga.saga_name == "The Legend of the Daemon"
        assert saga.last_chapter == 3
        assert saga.chapters == []  # Default empty list


# =============================================================================
# BardConfig Tests
# =============================================================================


class TestBardConfig:
    """Tests for BardConfig dataclass."""

    def test_default_config_values(self) -> None:
        """BardConfig should have sensible defaults."""
        config = BardConfig()

        assert config.tidbit_probability == 0.07
        assert config.saga_continuation_probability == 0.3
        assert config.max_saga_chapters == 5
        assert config.max_tidbit_words == 50

    def test_custom_config_values(self) -> None:
        """BardConfig should accept custom values."""
        config = BardConfig(
            tidbit_probability=0.2,
            saga_continuation_probability=0.6,
            max_saga_chapters=10,
        )

        assert config.tidbit_probability == 0.2
        assert config.saga_continuation_probability == 0.6
        assert config.max_saga_chapters == 10


# =============================================================================
# Saga Name Generator Tests
# =============================================================================


class TestSagaNameGenerator:
    """Tests for saga name generation."""

    def test_generate_saga_name_format(self) -> None:
        """Generated names should have prefix and subject."""
        name = generate_saga_name()

        # Should have format "The X of Y"
        assert name.startswith("The ")
        assert " of " in name or " to " in name or " for " in name

    def test_generate_saga_name_variety(self) -> None:
        """Should generate varied names."""
        names = {generate_saga_name() for _ in range(100)}

        # Should have some variety (not all identical)
        assert len(names) > 5


# =============================================================================
# Process Message Tests
# =============================================================================


class TestProcessMessage:
    """Tests for message processing."""

    @pytest.mark.asyncio
    async def test_process_salt_response_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should handle salt_response operation."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="salt",
            payload={
                "operation": "salt_response",
                "response": "Task done.",
                "storm_mode": True,
            },
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.intent == "bard_result"
        assert response.payload["storm_mode_skipped"] is True
        assert response.payload["salted_response"] == "Task done."

    @pytest.mark.asyncio
    async def test_process_get_active_saga_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_active_saga operation."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "last_chapter": 2,
                "last_told": now_ms,
            }
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_active_saga"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["saga"]["saga_id"] == "saga-123"

    @pytest.mark.asyncio
    async def test_process_get_all_sagas_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_all_sagas operation."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-1",
                "saga_name": "Saga One",
                "chapter_count": 3,
                "last_told": now_ms,
                "status": "active",
            },
            {
                "saga_id": "saga-2",
                "saga_name": "Saga Two",
                "chapter_count": 5,
                "last_told": now_ms - 1000,
                "status": "complete",
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_all_sagas"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 2
        assert len(response.payload["sagas"]) == 2

    @pytest.mark.asyncio
    async def test_process_unknown_operation(self, bard: BardOfTheBilge) -> None:
        """Should return error for unknown operation."""
        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="unknown",
            payload={"operation": "invalid_operation"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert "error" in response.payload
        assert "invalid_operation" in response.payload["error"]


# =============================================================================
# Statistics Tests
# =============================================================================


class TestLoreStatistics:
    """Tests for lore statistics."""

    @pytest.mark.asyncio
    async def test_get_lore_statistics_empty(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should return zero stats when no lore exists."""
        mock_neo4j.execute_query.return_value = [
            {
                "total_sagas": 0,
                "total_episodes": 0,
                "avg_chapters_per_saga": None,
            }
        ]

        stats = await bard.get_lore_statistics(trace_id="test-123")

        assert stats["total_sagas"] == 0
        assert stats["total_episodes"] == 0
        assert stats["avg_chapters_per_saga"] == 0
        assert stats["captain_uuid"] == captain_uuid
        assert stats["canonical_tidbits_available"] == 10

    @pytest.mark.asyncio
    async def test_get_lore_statistics_with_data(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return correct stats when lore exists."""
        mock_neo4j.execute_query.return_value = [
            {
                "total_sagas": 5,
                "total_episodes": 15,
                "avg_chapters_per_saga": 3.0,
            }
        ]

        stats = await bard.get_lore_statistics(trace_id="test-123")

        assert stats["total_sagas"] == 5
        assert stats["total_episodes"] == 15
        assert stats["avg_chapters_per_saga"] == 3.0


# =============================================================================
# Saga Query Tests
# =============================================================================


class TestSagaQueries:
    """Tests for saga query methods."""

    @pytest.mark.asyncio
    async def test_get_saga_by_id_found(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return saga with chapters when found."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Chapter 1",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
            {
                "uuid": "ep-2",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 2,
                "content": "Chapter 2",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
        ]

        saga = await bard.get_saga_by_id("saga-123", trace_id="test-123")

        assert saga is not None
        assert saga["saga_id"] == "saga-123"
        assert saga["chapter_count"] == 2
        assert len(saga["chapters"]) == 2
        assert saga["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_saga_by_id_not_found(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return None when saga not found."""
        mock_neo4j.execute_query.return_value = []

        saga = await bard.get_saga_by_id("nonexistent", trace_id="test-123")

        assert saga is None

    @pytest.mark.asyncio
    async def test_get_saga_by_id_complete(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should mark saga as complete when max chapters reached."""
        # Create 5 chapters (max_saga_chapters)
        chapters = [
            {
                "uuid": f"ep-{i}",
                "saga_id": "saga-123",
                "saga_name": "Complete Saga",
                "chapter": i,
                "content": f"Chapter {i}",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            }
            for i in range(1, 6)
        ]
        mock_neo4j.execute_query.return_value = chapters

        saga = await bard.get_saga_by_id("saga-123", trace_id="test-123")

        assert saga is not None
        assert saga["status"] == "complete"
        assert saga["chapter_count"] == 5


# =============================================================================
# Standalone Tidbit Tests
# =============================================================================


class TestStandaloneTidbit:
    """Tests for standalone tidbit generation."""

    def test_generate_standalone_tidbit_from_canonical(self, bard: BardOfTheBilge) -> None:
        """Should return a canonical tidbit."""
        tidbit = bard._generate_standalone_tidbit()

        assert tidbit in CANONICAL_TIDBITS

    def test_canonical_tidbits_not_empty(self) -> None:
        """Canonical tidbits list should not be empty."""
        assert len(CANONICAL_TIDBITS) > 0

    def test_canonical_tidbits_are_strings(self) -> None:
        """All canonical tidbits should be strings."""
        for tidbit in CANONICAL_TIDBITS:
            assert isinstance(tidbit, str)
            assert len(tidbit) > 0


# =============================================================================
# Export Tests
# =============================================================================


class TestExports:
    """Tests for module exports."""

    def test_all_exports_available(self) -> None:
        """All expected items should be exported."""
        from klabautermann.agents.bard import __all__

        expected = [
            "CANONICAL_TIDBITS",
            "ActiveSaga",
            "BardConfig",
            "BardOfTheBilge",
            "ChapterTooSoonError",
            "LoreEpisode",
            "SagaCompleteError",
            "SagaLifecycleError",
            "SagaLimitReachedError",
            "SagaTimedOutError",
            "SaltResult",
            "generate_saga_name",
        ]

        for item in expected:
            assert item in __all__

    def test_agents_init_exports_bard(self) -> None:
        """Bard should be exported from agents package."""
        from klabautermann.agents import BardConfig, BardOfTheBilge, LoreEpisode

        assert BardOfTheBilge is not None
        assert BardConfig is not None
        assert LoreEpisode is not None


# =============================================================================
# Saga Lifecycle Exception Tests (#118, #119, #120, #121)
# =============================================================================


class TestSagaLifecycleExceptions:
    """Tests for saga lifecycle custom exceptions."""

    def test_saga_complete_error(self) -> None:
        """SagaCompleteError should have correct message."""
        error = SagaCompleteError("The Tale of Testing", 5)

        assert error.saga_name == "The Tale of Testing"
        assert error.max_chapters == 5
        assert "complete" in str(error).lower()
        assert "5 chapters" in str(error)

    def test_saga_limit_reached_error(self) -> None:
        """SagaLimitReachedError should list active sagas."""
        active = ["Saga A", "Saga B", "Saga C"]
        error = SagaLimitReachedError(3, active)

        assert error.max_active == 3
        assert error.active_names == active
        assert "3 active sagas" in str(error)
        assert "Saga A" in str(error)

    def test_chapter_too_soon_error(self) -> None:
        """ChapterTooSoonError should show time remaining."""
        error = ChapterTooSoonError("The Chronicle", 0.5, 1.0)

        assert error.saga_name == "The Chronicle"
        assert error.hours_remaining == 0.5
        assert error.min_hours == 1.0
        assert "0.5" in str(error)

    def test_saga_timed_out_error(self) -> None:
        """SagaTimedOutError should show days inactive."""
        error = SagaTimedOutError("The Legend", 45)

        assert error.saga_name == "The Legend"
        assert error.days_inactive == 45
        assert "45 days" in str(error)
        assert "auto-completed" in str(error)

    def test_exception_inheritance(self) -> None:
        """All saga exceptions should inherit from SagaLifecycleError."""
        assert issubclass(SagaCompleteError, SagaLifecycleError)
        assert issubclass(SagaLimitReachedError, SagaLifecycleError)
        assert issubclass(ChapterTooSoonError, SagaLifecycleError)
        assert issubclass(SagaTimedOutError, SagaLifecycleError)


# =============================================================================
# Saga Lifecycle Config Tests (#118, #119, #120, #121)
# =============================================================================


class TestSagaLifecycleConfig:
    """Tests for new saga lifecycle configuration options."""

    def test_default_max_active_sagas(self) -> None:
        """Default max_active_sagas should be 3."""
        config = BardConfig()
        assert config.max_active_sagas == 3

    def test_default_saga_timeout_days(self) -> None:
        """Default saga_timeout_days should be 30."""
        config = BardConfig()
        assert config.saga_timeout_days == 30

    def test_default_min_chapter_interval_hours(self) -> None:
        """Default min_chapter_interval_hours should be 1.0."""
        config = BardConfig()
        assert config.min_chapter_interval_hours == 1.0

    def test_custom_lifecycle_config(self) -> None:
        """Should accept custom lifecycle values."""
        config = BardConfig(
            max_active_sagas=5,
            saga_timeout_days=60,
            min_chapter_interval_hours=2.5,
        )

        assert config.max_active_sagas == 5
        assert config.saga_timeout_days == 60
        assert config.min_chapter_interval_hours == 2.5


# =============================================================================
# Max Chapters Enforcement Tests (#118)
# =============================================================================


class TestMaxChaptersEnforcement:
    """Tests for max chapters per saga (#118)."""

    @pytest.mark.asyncio
    async def test_continue_saga_at_max_chapters_raises(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should raise SagaCompleteError when saga is at max chapters."""
        config = BardConfig(max_saga_chapters=5)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="The Complete Tale",
            last_chapter=5,  # Already at max
            last_told=now_ms,
        )

        with pytest.raises(SagaCompleteError) as exc_info:
            await bard._continue_saga(saga, trace_id="test-123")

        assert exc_info.value.max_chapters == 5
        assert "Complete Tale" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_continue_saga_below_max_allowed(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should allow continuation when below max chapters."""
        config = BardConfig(max_saga_chapters=5, min_chapter_interval_hours=0)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)
        mock_neo4j.execute_query.return_value = [{"uuid": "ep-new"}]

        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="The Ongoing Tale",
            last_chapter=3,
            last_told=now_ms,
        )

        content, chapter = await bard._continue_saga(saga, trace_id="test-123")

        assert chapter == 4
        assert content in CANONICAL_TIDBITS


# =============================================================================
# Max Active Sagas Enforcement Tests (#119)
# =============================================================================


class TestMaxActiveSagasEnforcement:
    """Tests for max active sagas limit (#119)."""

    @pytest.mark.asyncio
    async def test_start_saga_at_limit_raises(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should raise SagaLimitReachedError when at max active sagas."""
        config = BardConfig(max_active_sagas=3, saga_timeout_days=30)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # Mock 3 active sagas already exist
        mock_neo4j.execute_query.return_value = [
            {"saga_id": "s1", "saga_name": "Saga One", "last_chapter": 2, "last_told": now_ms},
            {"saga_id": "s2", "saga_name": "Saga Two", "last_chapter": 1, "last_told": now_ms},
            {"saga_id": "s3", "saga_name": "Saga Three", "last_chapter": 3, "last_told": now_ms},
        ]

        with pytest.raises(SagaLimitReachedError) as exc_info:
            await bard.start_new_saga(trace_id="test-123")

        assert exc_info.value.max_active == 3
        assert "Saga One" in exc_info.value.active_names

    @pytest.mark.asyncio
    async def test_start_saga_below_limit_allowed(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should allow new saga when below limit."""
        config = BardConfig(max_active_sagas=3, saga_timeout_days=30)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        mock_neo4j.execute_query.side_effect = [
            # First call: _get_active_sagas (only 2 active)
            [
                {"saga_id": "s1", "saga_name": "Saga One", "last_chapter": 2, "last_told": now_ms},
                {"saga_id": "s2", "saga_name": "Saga Two", "last_chapter": 1, "last_told": now_ms},
            ],
            # Second call: _save_episode
            [{"uuid": "ep-new"}],
        ]

        content, saga_id, chapter = await bard.start_new_saga(trace_id="test-123")

        assert chapter == 1
        assert saga_id is not None


# =============================================================================
# Saga Timeout Enforcement Tests (#120)
# =============================================================================


class TestSagaTimeoutEnforcement:
    """Tests for saga timeout auto-completion (#120)."""

    @pytest.mark.asyncio
    async def test_get_active_saga_marks_timed_out(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should mark saga as timed_out when exceeded timeout."""
        config = BardConfig(saga_timeout_days=30)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 45 days ago in ms
        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)

        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-old",
                "saga_name": "The Ancient Tale",
                "last_chapter": 2,
                "last_told": old_time,
            }
        ]

        saga = await bard._get_active_saga(trace_id="test-123")

        assert saga is not None
        assert saga.is_timed_out is True

    @pytest.mark.asyncio
    async def test_get_active_saga_not_timed_out(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should not mark saga as timed_out when within timeout."""
        config = BardConfig(saga_timeout_days=30)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-recent",
                "saga_name": "The Recent Tale",
                "last_chapter": 2,
                "last_told": now_ms - 1000,  # Very recent
            }
        ]

        saga = await bard._get_active_saga(trace_id="test-123")

        assert saga is not None
        assert saga.is_timed_out is False

    @pytest.mark.asyncio
    async def test_continue_timed_out_saga_raises(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should raise SagaTimedOutError when continuing timed-out saga."""
        config = BardConfig(saga_timeout_days=30)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)
        saga = ActiveSaga(
            saga_id="saga-old",
            saga_name="The Ancient Tale",
            last_chapter=2,
            last_told=old_time,
            is_timed_out=True,
        )

        with pytest.raises(SagaTimedOutError) as exc_info:
            await bard._continue_saga(saga, trace_id="test-123")

        assert "Ancient Tale" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_archive_timed_out_sagas(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """Should archive timed-out sagas with closing chapter."""
        config = BardConfig(saga_timeout_days=30, max_saga_chapters=5)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)

        mock_neo4j.execute_query.side_effect = [
            # First call: find timed-out sagas
            [
                {
                    "saga_id": "saga-old",
                    "saga_name": "The Ancient Tale",
                    "last_chapter": 2,
                    "last_told": old_time,
                }
            ],
            # Second call: _save_episode for closing chapter
            [{"uuid": "ep-closing"}],
        ]

        archived = await bard.archive_timed_out_sagas(trace_id="test-123")

        assert len(archived) == 1
        assert archived[0]["saga_name"] == "The Ancient Tale"
        assert archived[0]["closing_chapter"] == 5  # max_saga_chapters


# =============================================================================
# Min Chapter Interval Enforcement Tests (#121)
# =============================================================================


class TestMinChapterIntervalEnforcement:
    """Tests for minimum time between chapters (#121)."""

    def test_can_add_chapter_after_interval(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should allow chapter when interval has passed."""
        config = BardConfig(min_chapter_interval_hours=1.0)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 2 hours ago
        old_time = now_ms - int(2 * 60 * 60 * 1000)
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="Test Saga",
            last_chapter=2,
            last_told=old_time,
        )

        can_add, hours_remaining = bard._can_add_chapter(saga)

        assert can_add is True
        assert hours_remaining == 0.0

    def test_cannot_add_chapter_before_interval(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should block chapter when interval hasn't passed."""
        config = BardConfig(min_chapter_interval_hours=1.0)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 30 minutes ago
        recent_time = now_ms - int(0.5 * 60 * 60 * 1000)
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="Test Saga",
            last_chapter=2,
            last_told=recent_time,
        )

        can_add, hours_remaining = bard._can_add_chapter(saga)

        assert can_add is False
        assert 0.4 < hours_remaining < 0.6  # Approximately 0.5 hours

    @pytest.mark.asyncio
    async def test_continue_saga_too_soon_raises(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should raise ChapterTooSoonError when interval not met."""
        config = BardConfig(min_chapter_interval_hours=1.0)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 15 minutes ago
        recent_time = now_ms - int(0.25 * 60 * 60 * 1000)
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="The Impatient Tale",
            last_chapter=2,
            last_told=recent_time,
        )

        with pytest.raises(ChapterTooSoonError) as exc_info:
            await bard._continue_saga(saga, trace_id="test-123")

        assert exc_info.value.min_hours == 1.0
        assert exc_info.value.hours_remaining > 0


# =============================================================================
# Salt Response Lifecycle Integration Tests
# =============================================================================


class TestSaltResponseLifecycleIntegration:
    """Tests for salt_response handling lifecycle errors gracefully."""

    @pytest.mark.asyncio
    async def test_salt_response_falls_back_on_too_soon(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should fall back to standalone tidbit when chapter too soon."""
        config = BardConfig(
            tidbit_probability=1.0,  # Always add tidbit
            saga_continuation_probability=1.0,  # Always try to continue
            min_chapter_interval_hours=1.0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 10 minutes ago - too soon
        recent_time = now_ms - int(0.17 * 60 * 60 * 1000)

        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-123",
                "saga_name": "The Impatient Tale",
                "last_chapter": 2,
                "last_told": recent_time,
            }
        ]

        result = await bard.salt_response("Hello", trace_id="test-123")

        # Should have added standalone tidbit instead
        assert result.tidbit_added is True
        assert result.is_continuation is False
        assert result.tidbit in CANONICAL_TIDBITS

    @pytest.mark.asyncio
    async def test_salt_response_falls_back_on_timed_out(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should fall back to standalone tidbit when saga timed out."""
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            saga_timeout_days=30,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 45 days ago - timed out
        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)

        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-old",
                "saga_name": "The Ancient Tale",
                "last_chapter": 2,
                "last_told": old_time,
            }
        ]

        result = await bard.salt_response("Hello", trace_id="test-123")

        # Should have added standalone tidbit instead
        assert result.tidbit_added is True
        assert result.is_continuation is False


# =============================================================================
# Process Message Lifecycle Operations Tests
# =============================================================================


class TestProcessMessageLifecycleOperations:
    """Tests for new process_message operations."""

    @pytest.mark.asyncio
    async def test_process_archive_timed_out_operation(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should handle archive_timed_out operation."""
        config = BardConfig(saga_timeout_days=30, max_saga_chapters=5)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)

        mock_neo4j.execute_query.side_effect = [
            # Find timed-out sagas
            [{"saga_id": "s1", "saga_name": "Old Saga", "last_chapter": 2, "last_told": old_time}],
            # Save closing chapter
            [{"uuid": "ep-close"}],
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="maintenance",
            payload={"operation": "archive_timed_out"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert response.payload["archived"][0]["saga_name"] == "Old Saga"

    @pytest.mark.asyncio
    async def test_process_get_active_sagas_operation(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should handle get_active_sagas operation."""
        config = BardConfig(max_active_sagas=3)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        mock_neo4j.execute_query.return_value = [
            {"saga_id": "s1", "saga_name": "Active One", "last_chapter": 2, "last_told": now_ms},
            {"saga_id": "s2", "saga_name": "Active Two", "last_chapter": 1, "last_told": now_ms},
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_active_sagas"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 2
        assert response.payload["max_active"] == 3
        assert len(response.payload["active_sagas"]) == 2


# =============================================================================
# ActiveSaga Model Extension Tests
# =============================================================================


class TestActiveSagaTimedOutFlag:
    """Tests for ActiveSaga is_timed_out flag."""

    def test_active_saga_default_not_timed_out(self, now_ms: int) -> None:
        """ActiveSaga should default to not timed out."""
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="Test Saga",
            last_chapter=2,
            last_told=now_ms,
        )

        assert saga.is_timed_out is False

    def test_active_saga_timed_out_flag(self, now_ms: int) -> None:
        """ActiveSaga should accept is_timed_out flag."""
        saga = ActiveSaga(
            saga_id="saga-123",
            saga_name="Test Saga",
            last_chapter=2,
            last_told=now_ms,
            is_timed_out=True,
        )

        assert saga.is_timed_out is True


# =============================================================================
# Export Tests for Lifecycle Exceptions
# =============================================================================


class TestLifecycleExceptionExports:
    """Tests for lifecycle exception exports."""

    def test_lifecycle_exceptions_exported(self) -> None:
        """All lifecycle exceptions should be in __all__."""
        from klabautermann.agents.bard import __all__

        expected = [
            "SagaLifecycleError",
            "SagaCompleteError",
            "SagaLimitReachedError",
            "ChapterTooSoonError",
            "SagaTimedOutError",
        ]

        for item in expected:
            assert item in __all__


# =============================================================================
# Lore Query Tests (#112, #113, #114, #115)
# =============================================================================


class TestGetRecentLore:
    """Tests for get_recent_lore query (#112)."""

    @pytest.mark.asyncio
    async def test_get_recent_lore_returns_episodes(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return recent episodes ordered by told_at DESC."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-3",
                "saga_id": "saga-123",
                "saga_name": "Recent Saga",
                "chapter": 3,
                "content": "Most recent",
                "channel": "telegram",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
            {
                "uuid": "ep-2",
                "saga_id": "saga-123",
                "saga_name": "Recent Saga",
                "chapter": 2,
                "content": "Second most recent",
                "channel": "cli",
                "told_at": now_ms - 1000,
                "created_at": now_ms - 1000,
                "captain_uuid": "captain-123",
            },
        ]

        episodes = await bard.get_recent_lore(limit=5, trace_id="test-123")

        assert len(episodes) == 2
        assert episodes[0].content == "Most recent"
        assert episodes[0].channel == "telegram"
        assert episodes[1].content == "Second most recent"

    @pytest.mark.asyncio
    async def test_get_recent_lore_empty(self, bard: BardOfTheBilge, mock_neo4j: MagicMock) -> None:
        """Should return empty list when no lore exists."""
        mock_neo4j.execute_query.return_value = []

        episodes = await bard.get_recent_lore(limit=5, trace_id="test-123")

        assert episodes == []

    @pytest.mark.asyncio
    async def test_get_recent_lore_respects_limit(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should pass limit to query."""
        mock_neo4j.execute_query.return_value = []

        await bard.get_recent_lore(limit=3, trace_id="test-123")

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["limit"] == 3


class TestGetSagaChain:
    """Tests for get_saga_chain query (#113)."""

    @pytest.mark.asyncio
    async def test_get_saga_chain_returns_chapters_in_order(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return all saga chapters ordered by chapter ASC."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Chapter one",
                "channel": "cli",
                "told_at": now_ms - 2000,
                "created_at": now_ms - 2000,
                "captain_uuid": "captain-123",
            },
            {
                "uuid": "ep-2",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 2,
                "content": "Chapter two",
                "channel": "telegram",
                "told_at": now_ms - 1000,
                "created_at": now_ms - 1000,
                "captain_uuid": "captain-123",
            },
            {
                "uuid": "ep-3",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 3,
                "content": "Chapter three",
                "channel": "cli",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
        ]

        chapters = await bard.get_saga_chain(saga_id="saga-123", trace_id="test-123")

        assert len(chapters) == 3
        assert chapters[0].chapter == 1
        assert chapters[1].chapter == 2
        assert chapters[2].chapter == 3

    @pytest.mark.asyncio
    async def test_get_saga_chain_includes_all_metadata(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should include channel and all metadata."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Content",
                "channel": "telegram",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
        ]

        chapters = await bard.get_saga_chain(saga_id="saga-123", trace_id="test-123")

        assert chapters[0].channel == "telegram"
        assert chapters[0].saga_name == "Test Saga"


class TestGetCrossChannelStory:
    """Tests for get_cross_channel_story query (#114)."""

    @pytest.mark.asyncio
    async def test_get_cross_channel_story_shows_channel_travel(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should show how story traveled across channels."""
        mock_neo4j.execute_query.return_value = [
            {
                "chapter": 1,
                "content": "Started on CLI",
                "channel": "cli",
                "told_at": now_ms - 2000,
                "saga_name": "Traveling Tale",
            },
            {
                "chapter": 2,
                "content": "Continued on Telegram",
                "channel": "telegram",
                "told_at": now_ms - 1000,
                "saga_name": "Traveling Tale",
            },
            {
                "chapter": 3,
                "content": "Back to CLI",
                "channel": "cli",
                "told_at": now_ms,
                "saga_name": "Traveling Tale",
            },
        ]

        chapters = await bard.get_cross_channel_story(saga_id="saga-123", trace_id="test-123")

        assert len(chapters) == 3
        assert chapters[0]["channel"] == "cli"
        assert chapters[1]["channel"] == "telegram"
        assert chapters[2]["channel"] == "cli"

    @pytest.mark.asyncio
    async def test_get_cross_channel_story_empty_saga(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list for nonexistent saga."""
        mock_neo4j.execute_query.return_value = []

        chapters = await bard.get_cross_channel_story(saga_id="nonexistent", trace_id="test-123")

        assert chapters == []


class TestGetSagaStatisticsByCaptain:
    """Tests for get_saga_statistics_by_captain query (#115)."""

    @pytest.mark.asyncio
    async def test_get_saga_statistics_by_captain_returns_grouped_stats(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return statistics grouped by Captain."""
        mock_neo4j.execute_query.return_value = [
            {
                "captain_uuid": "captain-1",
                "captain_name": "Alice",
                "total_sagas": 5,
                "total_chapters": 15,
            },
            {
                "captain_uuid": "captain-2",
                "captain_name": "Bob",
                "total_sagas": 3,
                "total_chapters": 9,
            },
        ]

        stats = await bard.get_saga_statistics_by_captain(trace_id="test-123")

        assert len(stats) == 2
        assert stats[0]["captain_uuid"] == "captain-1"
        assert stats[0]["captain_name"] == "Alice"
        assert stats[0]["total_sagas"] == 5
        assert stats[0]["total_chapters"] == 15
        assert stats[1]["captain_uuid"] == "captain-2"

    @pytest.mark.asyncio
    async def test_get_saga_statistics_by_captain_empty(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list when no lore exists."""
        mock_neo4j.execute_query.return_value = []

        stats = await bard.get_saga_statistics_by_captain(trace_id="test-123")

        assert stats == []


class TestProcessMessageLoreQueries:
    """Tests for process_message handling of new lore query operations."""

    @pytest.mark.asyncio
    async def test_process_get_recent_lore_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_recent_lore operation (#112)."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Content",
                "channel": "cli",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_recent_lore", "limit": 5},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["episodes"]) == 1

    @pytest.mark.asyncio
    async def test_process_get_saga_chain_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_saga_chain operation (#113)."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-123",
                "saga_name": "Test Saga",
                "chapter": 1,
                "content": "Content",
                "channel": "cli",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-123",
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_saga_chain", "saga_id": "saga-123"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["chapters"]) == 1

    @pytest.mark.asyncio
    async def test_process_get_cross_channel_story_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_cross_channel_story operation (#114)."""
        mock_neo4j.execute_query.return_value = [
            {
                "chapter": 1,
                "content": "Content",
                "channel": "cli",
                "told_at": now_ms,
                "saga_name": "Test Saga",
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_cross_channel_story", "saga_id": "saga-123"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["chapters"]) == 1

    @pytest.mark.asyncio
    async def test_process_get_saga_statistics_by_captain_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should handle get_saga_statistics_by_captain operation (#115)."""
        mock_neo4j.execute_query.return_value = [
            {
                "captain_uuid": "captain-1",
                "captain_name": "Alice",
                "total_sagas": 5,
                "total_chapters": 15,
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_saga_statistics_by_captain"},
            trace_id="test-123",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["captain_count"] == 1
        assert len(response.payload["statistics"]) == 1


class TestLoreEpisodeChannelField:
    """Tests for LoreEpisode channel field."""

    def test_lore_episode_with_channel(self, now_ms: int) -> None:
        """LoreEpisode should store channel."""
        episode = LoreEpisode(
            uuid="ep-123",
            saga_id="saga-456",
            saga_name="Test Saga",
            chapter=1,
            content="Content",
            told_at=now_ms,
            created_at=now_ms,
            captain_uuid="captain-789",
            channel="telegram",
        )

        assert episode.channel == "telegram"

    def test_lore_episode_channel_in_to_dict(self, now_ms: int) -> None:
        """LoreEpisode.to_dict should include channel."""
        episode = LoreEpisode(
            uuid="ep-123",
            saga_id="saga-456",
            saga_name="Test Saga",
            chapter=1,
            content="Content",
            told_at=now_ms,
            created_at=now_ms,
            captain_uuid="captain-789",
            channel="cli",
        )

        d = episode.to_dict()

        assert "channel" in d
        assert d["channel"] == "cli"

    def test_lore_episode_channel_defaults_to_none(self, now_ms: int) -> None:
        """LoreEpisode channel should default to None."""
        episode = LoreEpisode(
            uuid="ep-123",
            saga_id="saga-456",
            saga_name="Test Saga",
            chapter=1,
            content="Content",
            told_at=now_ms,
            created_at=now_ms,
        )

        assert episode.channel is None


class TestSaltResponseChannel:
    """Tests for salt_response channel parameter."""

    @pytest.mark.asyncio
    async def test_salt_response_passes_channel_to_continue_saga(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Should pass channel when continuing a saga."""
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            min_chapter_interval_hours=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga
            [
                {
                    "saga_id": "saga-123",
                    "saga_name": "Test Saga",
                    "last_chapter": 2,
                    "last_told": now_ms - 1000,
                }
            ],
            # _save_episode
            [{"uuid": "ep-new"}],
        ]

        await bard.salt_response("Hello", channel="telegram", trace_id="test-123")

        # Verify channel was passed to _save_episode
        save_call = mock_neo4j.execute_query.call_args_list[1]
        assert save_call[0][1]["channel"] == "telegram"
