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
    LoreEpisode,
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
        mock_neo4j.execute_query.return_value = [{"uuid": "episode-new"}]

        content, saga_id, chapter = await bard.start_new_saga(trace_id="test-123")

        assert content in CANONICAL_TIDBITS
        assert saga_id is not None
        assert chapter == 1
        mock_neo4j.execute_query.assert_called_once()

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
            "LoreEpisode",
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
