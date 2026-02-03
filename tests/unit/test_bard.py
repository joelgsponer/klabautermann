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
    CANONICAL_SAGAS,
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
        """BardOfTheBilge should have access to canonical tidbits (#107)."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        # 12 standalone tidbits + 5 saga tidbits = 17 total (#107)
        assert len(bard.CANONICAL_TIDBITS) == 17
        assert len(CANONICAL_TIDBITS) == 17

    def test_canonical_sagas_available(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """BardOfTheBilge should have access to canonical sagas (#102-106)."""
        # Verify BardOfTheBilge can be instantiated (has access to sagas)
        _ = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        # 5 canonical sagas from LORE_SYSTEM.md Section 4.1
        assert len(CANONICAL_SAGAS) == 5

        # Verify each saga has required fields
        for saga_id, saga_data in CANONICAL_SAGAS.items():
            assert "name" in saga_data, f"Saga {saga_id} missing name"
            assert "theme" in saga_data, f"Saga {saga_id} missing theme"
            assert "chapters" in saga_data, f"Saga {saga_id} missing chapters"
            assert len(saga_data["chapters"]) == 5, f"Saga {saga_id} should have 5 chapters"

    def test_canonical_sagas_content_matches_spec(self) -> None:
        """Canonical sagas should match LORE_SYSTEM.md Section 4.1 exactly (#102-106)."""
        # #102: The Great Maelstrom of '98
        assert "great-maelstrom" in CANONICAL_SAGAS
        assert CANONICAL_SAGAS["great-maelstrom"]["name"] == "The Great Maelstrom of '98"
        assert CANONICAL_SAGAS["great-maelstrom"]["theme"] == "origin"

        # #103: The Kraken of the Infinite Scroll
        assert "kraken-scroll" in CANONICAL_SAGAS
        assert CANONICAL_SAGAS["kraken-scroll"]["name"] == "The Kraken of the Infinite Scroll"
        assert CANONICAL_SAGAS["kraken-scroll"]["theme"] == "battle"

        # #104: The Sirens of the Inbox
        assert "sirens-inbox" in CANONICAL_SAGAS
        assert CANONICAL_SAGAS["sirens-inbox"]["name"] == "The Sirens of the Inbox"
        assert CANONICAL_SAGAS["sirens-inbox"]["theme"] == "warning"

        # #105: The Ghost Ship of Abandoned Projects
        assert "ghost-ship" in CANONICAL_SAGAS
        assert CANONICAL_SAGAS["ghost-ship"]["name"] == "The Ghost Ship of Abandoned Projects"
        assert CANONICAL_SAGAS["ghost-ship"]["theme"] == "melancholy"

        # #106: The Lighthouse of Forgotten Passwords
        assert "lighthouse-passwords" in CANONICAL_SAGAS
        assert (
            CANONICAL_SAGAS["lighthouse-passwords"]["name"]
            == "The Lighthouse of Forgotten Passwords"
        )
        assert CANONICAL_SAGAS["lighthouse-passwords"]["theme"] == "humor"


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

        # Verify query creates proper relationships (#98, #99, #100)
        assert "CREATE (le:LoreEpisode" in query
        assert "TOLD_TO" in query  # #98
        assert "EXPANDS_UPON" in query  # #99
        assert "SAGA_STARTED_BY" in query  # #100
        assert call_args[0][1]["saga_id"] == "saga-test"
        assert call_args[0][1]["chapter"] == 2

    @pytest.mark.asyncio
    async def test_save_episode_chapter_one_has_saga_started_by(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Chapter 1 should create SAGA_STARTED_BY relationship (#100)."""
        mock_neo4j.execute_query.return_value = [{"uuid": "episode-ch1"}]

        await bard._save_episode(
            saga_id="saga-origin",
            saga_name="The Origin Story",
            chapter=1,  # First chapter
            content="It all began...",
            trace_id="test-origin",
        )

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        # SAGA_STARTED_BY is in the query (conditional FOREACH)
        assert "SAGA_STARTED_BY" in query
        # Chapter is 1, so the FOREACH condition will create the relationship
        assert params["chapter"] == 1


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
        assert stats["canonical_tidbits_available"] == 17  # 12 standalone + 5 saga (#107)

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
        """Should archive timed-out sagas with closing chapter and summary."""
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
            # Third call: _get_saga_chapters for archive_saga (#125, #126)
            [
                {
                    "uuid": "ep-1",
                    "saga_id": "saga-old",
                    "saga_name": "The Ancient Tale",
                    "chapter": 1,
                    "content": "Chapter one.",
                    "channel": "cli",
                    "told_at": old_time - 1000,
                    "created_at": old_time - 1000,
                    "captain_uuid": captain_uuid,
                },
            ],
            # Fourth call: _create_archive_note
            [{"uuid": "note-archive"}],
        ]

        archived = await bard.archive_timed_out_sagas(trace_id="test-123")

        assert len(archived) == 1
        assert archived[0]["saga_name"] == "The Ancient Tale"
        assert archived[0]["closing_chapter"] == 5  # max_saga_chapters
        assert archived[0]["note_uuid"] is not None  # #125, #126: Summary note created
        assert "summary" in archived[0]


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
        """Should handle archive_timed_out operation with summary generation."""
        config = BardConfig(saga_timeout_days=30, max_saga_chapters=5)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        old_time = int((time.time() - 45 * 24 * 60 * 60) * 1000)

        mock_neo4j.execute_query.side_effect = [
            # Find timed-out sagas
            [{"saga_id": "s1", "saga_name": "Old Saga", "last_chapter": 2, "last_told": old_time}],
            # Save closing chapter
            [{"uuid": "ep-close"}],
            # _get_saga_chapters for archive_saga (#125, #126)
            [
                {
                    "uuid": "ep-1",
                    "saga_id": "s1",
                    "saga_name": "Old Saga",
                    "chapter": 1,
                    "content": "Content.",
                    "channel": "cli",
                    "told_at": old_time - 1000,
                    "created_at": old_time - 1000,
                    "captain_uuid": captain_uuid,
                },
            ],
            # _create_archive_note
            [{"uuid": "note-archive"}],
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
        assert response.payload["archived"][0]["note_uuid"] is not None  # #125, #126

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


class TestGetSagaOrigins:
    """Tests for get_saga_origins method (#100)."""

    @pytest.mark.asyncio
    async def test_get_saga_origins_returns_initiator_info(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return saga initiator information via SAGA_STARTED_BY relationship."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-origin-1",
                "saga_name": "The First Voyage",
                "captain_uuid": "captain-alice",
                "captain_name": "Alice",
                "started_at": now_ms - 86400000,  # 1 day ago
                "started_channel": "cli",
            },
            {
                "saga_id": "saga-origin-2",
                "saga_name": "The Second Tale",
                "captain_uuid": "captain-bob",
                "captain_name": "Bob",
                "started_at": now_ms,
                "started_channel": "telegram",
            },
        ]

        origins = await bard.get_saga_origins(trace_id="test-100")

        assert len(origins) == 2
        assert origins[0]["saga_id"] == "saga-origin-1"
        assert origins[0]["captain_uuid"] == "captain-alice"
        assert origins[0]["started_channel"] == "cli"
        assert origins[1]["saga_id"] == "saga-origin-2"
        assert origins[1]["started_channel"] == "telegram"

    @pytest.mark.asyncio
    async def test_get_saga_origins_empty(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list when no sagas exist."""
        mock_neo4j.execute_query.return_value = []

        origins = await bard.get_saga_origins(trace_id="test-100")

        assert origins == []


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

    @pytest.mark.asyncio
    async def test_process_get_saga_origins_operation(
        self, bard: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_saga_origins operation (#100)."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "saga-origin-1",
                "saga_name": "The Origin Saga",
                "captain_uuid": "captain-1",
                "captain_name": "Alice",
                "started_at": now_ms,
                "started_channel": "cli",
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard_of_the_bilge",
            intent="query",
            payload={"operation": "get_saga_origins"},
            trace_id="test-100",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["origins"]) == 1
        assert response.payload["origins"][0]["saga_id"] == "saga-origin-1"
        assert response.payload["origins"][0]["captain_uuid"] == "captain-1"


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
            # Force saga continuation path in weighted selection (#108)
            continue_saga_weight=1.0,
            start_saga_weight=0.0,
            standalone_weight=0.0,
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


# =============================================================================
# Tests for Saga Summary Generation (#125) and SUMMARIZES Relationship (#126)
# =============================================================================


class TestSagaSummaryGeneration:
    """Tests for saga summary generation (#125)."""

    @pytest.mark.asyncio
    async def test_generate_saga_summary(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Summary should include chapter count and content excerpts."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        episodes = [
            LoreEpisode(
                uuid="ep-1",
                saga_id="saga-test",
                saga_name="The Test Saga",
                chapter=1,
                content="The adventure begins in the digital seas.",
                told_at=now_ms - 2000,
                created_at=now_ms - 2000,
            ),
            LoreEpisode(
                uuid="ep-2",
                saga_id="saga-test",
                saga_name="The Test Saga",
                chapter=2,
                content="The journey continues through encrypted waters.",
                told_at=now_ms - 1000,
                created_at=now_ms - 1000,
            ),
            LoreEpisode(
                uuid="ep-3",
                saga_id="saga-test",
                saga_name="The Test Saga",
                chapter=3,
                content="The tale concludes with newfound wisdom.",
                told_at=now_ms,
                created_at=now_ms,
            ),
        ]

        summary = await bard._generate_saga_summary(episodes, trace_id="test-125")

        assert "The Test Saga" in summary
        assert "3 chapters" in summary
        assert "adventure begins" in summary
        assert "concludes" in summary

    @pytest.mark.asyncio
    async def test_generate_saga_summary_empty_episodes(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Empty episodes should return default message."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        summary = await bard._generate_saga_summary([], trace_id="test-125-empty")

        assert "untold tale" in summary.lower()


class TestArchiveSaga:
    """Tests for archive_saga method (#125, #126)."""

    @pytest.mark.asyncio
    async def test_archive_saga_creates_note_and_summarizes(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """archive_saga should create Note with SUMMARIZES relationships."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        # Mock _get_saga_chapters to return episodes
        mock_neo4j.execute_query.side_effect = [
            # First call: _get_saga_chapters
            [
                {
                    "uuid": "ep-1",
                    "saga_id": "saga-archive-test",
                    "saga_name": "The Archive Saga",
                    "chapter": 1,
                    "content": "Chapter one content.",
                    "channel": "cli",
                    "told_at": now_ms - 2000,
                    "created_at": now_ms - 2000,
                    "captain_uuid": captain_uuid,
                },
                {
                    "uuid": "ep-2",
                    "saga_id": "saga-archive-test",
                    "saga_name": "The Archive Saga",
                    "chapter": 2,
                    "content": "Chapter two content.",
                    "channel": "telegram",
                    "told_at": now_ms - 1000,
                    "created_at": now_ms - 1000,
                    "captain_uuid": captain_uuid,
                },
            ],
            # Second call: _create_archive_note
            [{"uuid": "note-archive-123"}],
        ]

        result = await bard.archive_saga(saga_id="saga-archive-test", trace_id="test-126")

        assert result["saga_id"] == "saga-archive-test"
        assert result["saga_name"] == "The Archive Saga"
        assert result["chapter_count"] == 2
        assert result["note_uuid"] is not None
        assert "summary" in result

        # Verify Note creation query was called
        create_note_call = mock_neo4j.execute_query.call_args_list[1]
        query = create_note_call[0][0]
        params = create_note_call[0][1]

        assert "CREATE (n:Note" in query
        assert "SUMMARIZES" in query
        assert "archived = true" in query
        assert params["title"] == "Saga: The Archive Saga"
        assert params["saga_id"] == "saga-archive-test"

    @pytest.mark.asyncio
    async def test_archive_saga_no_episodes_raises_error(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """archive_saga with no episodes should raise ValueError."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        # Mock _get_saga_chapters to return empty list
        mock_neo4j.execute_query.return_value = []

        with pytest.raises(ValueError, match="No episodes found"):
            await bard.archive_saga(saga_id="nonexistent-saga", trace_id="test-126-error")


class TestGetArchivedSaga:
    """Tests for get_archived_saga method (#125, #126)."""

    @pytest.mark.asyncio
    async def test_get_archived_saga_returns_summary(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """get_archived_saga should return saga with summary."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        mock_neo4j.execute_query.return_value = [
            {
                "note_uuid": "note-123",
                "title": "Saga: The Archived Tale",
                "summary": "A summary of the archived saga.",
                "archived_at": now_ms,
                "chapters": [
                    {
                        "uuid": "ep-1",
                        "chapter": 1,
                        "content": "Chapter one.",
                        "channel": "cli",
                        "told_at": now_ms - 1000,
                    },
                    {
                        "uuid": "ep-2",
                        "chapter": 2,
                        "content": "Chapter two.",
                        "channel": "telegram",
                        "told_at": now_ms,
                    },
                ],
            }
        ]

        result = await bard.get_archived_saga(saga_id="saga-archived", trace_id="test-126-get")

        assert result is not None
        assert result["saga_id"] == "saga-archived"
        assert result["note_uuid"] == "note-123"
        assert result["summary"] == "A summary of the archived saga."
        assert len(result["chapters"]) == 2

    @pytest.mark.asyncio
    async def test_get_archived_saga_not_found(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """get_archived_saga should return None if not archived."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        mock_neo4j.execute_query.return_value = []

        result = await bard.get_archived_saga(saga_id="not-archived", trace_id="test-126-none")

        assert result is None


class TestProcessMessageArchiveOperations:
    """Tests for process_message archive operations (#125, #126)."""

    @pytest.mark.asyncio
    async def test_process_message_archive_saga(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """process_message should handle archive_saga operation."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        mock_neo4j.execute_query.side_effect = [
            # _get_saga_chapters
            [
                {
                    "uuid": "ep-1",
                    "saga_id": "saga-pm-test",
                    "saga_name": "Process Message Saga",
                    "chapter": 1,
                    "content": "Content.",
                    "channel": "cli",
                    "told_at": now_ms,
                    "created_at": now_ms,
                    "captain_uuid": captain_uuid,
                }
            ],
            # _create_archive_note
            [{"uuid": "note-pm-123"}],
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard",
            intent="bard_request",
            payload={"operation": "archive_saga", "saga_id": "saga-pm-test"},
            trace_id="test-pm-archive",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["archived"] is True
        assert response.payload["saga_id"] == "saga-pm-test"
        assert "note_uuid" in response.payload

    @pytest.mark.asyncio
    async def test_process_message_archive_saga_missing_id(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """process_message archive_saga should error without saga_id."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard",
            intent="bard_request",
            payload={"operation": "archive_saga"},
            trace_id="test-pm-missing",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert "error" in response.payload
        assert "saga_id is required" in response.payload["error"]

    @pytest.mark.asyncio
    async def test_process_message_get_archived_saga(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """process_message should handle get_archived_saga operation."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        mock_neo4j.execute_query.return_value = [
            {
                "note_uuid": "note-get-123",
                "title": "Saga: Get Test",
                "summary": "Summary here.",
                "archived_at": now_ms,
                "chapters": [],
            }
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="bard",
            intent="bard_request",
            payload={"operation": "get_archived_saga", "saga_id": "saga-get-test"},
            trace_id="test-pm-get-archived",
        )

        response = await bard.process_message(msg)

        assert response is not None
        assert response.payload["found"] is True
        assert response.payload["saga"]["note_uuid"] == "note-get-123"


class TestArchiveTimedOutSagasWithSummary:
    """Tests for archive_timed_out_sagas including summary generation (#125, #126)."""

    @pytest.mark.asyncio
    async def test_archive_timed_out_creates_summary(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """archive_timed_out_sagas should create summary for each archived saga."""
        config = BardConfig(
            saga_timeout_days=30,
            max_saga_chapters=5,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # 31 days ago in ms
        old_told_at = now_ms - (31 * 24 * 60 * 60 * 1000)

        mock_neo4j.execute_query.side_effect = [
            # Find timed-out sagas
            [
                {
                    "saga_id": "old-saga-1",
                    "saga_name": "The Old Tale",
                    "last_chapter": 3,
                    "last_told": old_told_at,
                }
            ],
            # _save_episode (closing chapter)
            [{"uuid": "ep-closing"}],
            # _get_saga_chapters for archive_saga
            [
                {
                    "uuid": "ep-1",
                    "saga_id": "old-saga-1",
                    "saga_name": "The Old Tale",
                    "chapter": 1,
                    "content": "Opening.",
                    "channel": "cli",
                    "told_at": old_told_at - 1000,
                    "created_at": old_told_at - 1000,
                    "captain_uuid": captain_uuid,
                },
                {
                    "uuid": "ep-2",
                    "saga_id": "old-saga-1",
                    "saga_name": "The Old Tale",
                    "chapter": 2,
                    "content": "Middle.",
                    "channel": "cli",
                    "told_at": old_told_at,
                    "created_at": old_told_at,
                    "captain_uuid": captain_uuid,
                },
            ],
            # _create_archive_note
            [{"uuid": "note-timeout-123"}],
        ]

        archived = await bard.archive_timed_out_sagas(trace_id="test-timeout-summary")

        assert len(archived) == 1
        assert archived[0]["saga_id"] == "old-saga-1"
        assert archived[0]["note_uuid"] is not None  # UUID is generated internally
        assert "summary" in archived[0]


# =============================================================================
# Storm Mode Detection Tests (Bard as sole owner)
# =============================================================================


class TestStormModeDetection:
    """Tests for storm mode detection in Bard."""

    def test_detect_storm_mode_with_urgent_keyword(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should detect storm mode when urgent keywords present."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        assert bard._detect_storm_mode("This is an urgent matter") is True
        assert bard._detect_storm_mode("EMERGENCY: System down") is True
        assert bard._detect_storm_mode("Critical issue detected") is True
        assert bard._detect_storm_mode("Need this ASAP") is True

    def test_detect_storm_mode_without_keywords(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should not detect storm mode when no urgent keywords."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        assert bard._detect_storm_mode("Hello, how are you?") is False
        assert bard._detect_storm_mode("What do you know about Sarah?") is False
        assert bard._detect_storm_mode("Please remind me about the meeting") is False

    def test_detect_storm_mode_disabled(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """Should not detect storm mode when disabled in config."""
        config = BardConfig(storm_mode_enabled=False)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # Even with urgent keywords, should return False when disabled
        assert bard._detect_storm_mode("This is URGENT!") is False

    def test_detect_storm_mode_custom_keywords(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should use custom storm keywords from config."""
        config = BardConfig(storm_keywords=["fire", "alert"])
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        assert bard._detect_storm_mode("Fire alarm triggered") is True
        assert bard._detect_storm_mode("Alert: Server down") is True
        # Default keywords should not trigger
        assert bard._detect_storm_mode("This is urgent") is False


# =============================================================================
# PersonalityResult Model Tests
# =============================================================================


class TestPersonalityResultModel:
    """Tests for PersonalityResult dataclass."""

    def test_personality_result_to_dict(self) -> None:
        """PersonalityResult should serialize to dict."""
        from klabautermann.agents.bard import PersonalityResult

        result = PersonalityResult(
            original_response="Hello",
            final_response="Ahoy, Captain!",
            personality_applied=True,
            storm_mode=False,
            tidbit_added=True,
            tidbit="A wise tidbit",
            saga_id="saga-123",
            chapter=2,
            channel="telegram",
            llm_rewrite_used=True,
        )

        d = result.to_dict()

        assert d["personality_applied"] is True
        assert d["storm_mode"] is False
        assert d["tidbit_added"] is True
        assert d["tidbit"] == "A wise tidbit"
        assert d["saga_id"] == "saga-123"
        assert d["chapter"] == 2
        assert d["channel"] == "telegram"
        assert d["llm_rewrite_used"] is True

    def test_personality_result_storm_mode(self) -> None:
        """PersonalityResult should track storm mode."""
        from klabautermann.agents.bard import PersonalityResult

        result = PersonalityResult(
            original_response="Urgent alert",
            final_response="Urgent alert",
            personality_applied=False,
            storm_mode=True,
        )

        assert result.personality_applied is False
        assert result.storm_mode is True
        assert result.final_response == result.original_response


# =============================================================================
# Channel Formatting Tests
# =============================================================================


class TestChannelFormatting:
    """Tests for format_for_channel method."""

    def test_format_for_cli(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """CLI should get plain text."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        response = "Hello, _Captain_!"
        formatted = bard.format_for_channel(response, channel="cli")

        # CLI passes through as-is
        assert formatted == response

    def test_format_for_telegram(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """Telegram should get markdown formatting."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        response = "Hello, _Captain_!"
        formatted = bard.format_for_channel(response, channel="telegram")

        # Telegram passes through markdown
        assert formatted == response

    def test_format_for_api(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """API should get clean text."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        response = "Hello, Captain!"
        formatted = bard.format_for_channel(response, channel="api")

        assert formatted == response

    def test_format_for_none_channel(self, mock_neo4j: MagicMock, captain_uuid: str) -> None:
        """None channel should pass through."""
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid)

        response = "Hello!"
        formatted = bard.format_for_channel(response, channel=None)

        assert formatted == response


# =============================================================================
# Apply Personality Tests (Main Entry Point)
# =============================================================================


class TestApplyPersonality:
    """Tests for apply_personality method."""

    @pytest.mark.asyncio
    async def test_apply_personality_storm_mode_skips_rewrite(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Storm mode should skip personality rewriting."""
        config = BardConfig(personality_rewrite_enabled=True)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        result = await bard.apply_personality(
            clean_response="URGENT: Server is down!",
            trace_id="test-storm",
        )

        assert result.storm_mode is True
        assert result.personality_applied is False
        assert result.llm_rewrite_used is False
        # Response should be unchanged
        assert result.final_response == "URGENT: Server is down!"

    @pytest.mark.asyncio
    async def test_apply_personality_explicit_storm_mode(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Explicit storm_mode=True should skip personality."""
        config = BardConfig(personality_rewrite_enabled=True)
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        result = await bard.apply_personality(
            clean_response="Hello there!",  # No storm keywords
            storm_mode=True,  # Explicit override
            trace_id="test-explicit-storm",
        )

        assert result.storm_mode is True
        assert result.personality_applied is False

    @pytest.mark.asyncio
    async def test_apply_personality_passes_channel(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should pass channel to formatting."""
        config = BardConfig(
            personality_rewrite_enabled=False,  # Disable LLM rewrite for test simplicity
            tidbit_probability=0,  # Disable tidbits
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        result = await bard.apply_personality(
            clean_response="Hello!",
            channel="telegram",
            trace_id="test-channel",
        )

        assert result.channel == "telegram"
        assert result.personality_applied is True

    @pytest.mark.asyncio
    async def test_apply_personality_llm_disabled(
        self, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """Should skip LLM rewrite when disabled."""
        config = BardConfig(
            personality_rewrite_enabled=False,
            tidbit_probability=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)
        mock_neo4j.execute_query.return_value = []

        result = await bard.apply_personality(
            clean_response="Hello there!",
            trace_id="test-no-llm",
        )

        assert result.llm_rewrite_used is False
        assert result.personality_applied is True  # Still applies (via salt_response)


# =============================================================================
# Bard Config New Fields Tests
# =============================================================================


class TestBardConfigNewFields:
    """Tests for new BardConfig fields."""

    def test_default_personality_config(self) -> None:
        """Default personality config should be set."""
        config = BardConfig()

        assert config.personality_rewrite_enabled is True
        assert config.personality_model == "claude-3-5-haiku-20241022"
        assert config.personality_temperature == 0.8
        assert config.personality_max_tokens == 1024

    def test_default_storm_config(self) -> None:
        """Default storm mode config should be set."""
        config = BardConfig()

        assert config.storm_mode_enabled is True
        assert "urgent" in config.storm_keywords
        assert "emergency" in config.storm_keywords
        assert "critical" in config.storm_keywords

    def test_custom_personality_config(self) -> None:
        """Should accept custom personality config."""
        config = BardConfig(
            personality_rewrite_enabled=False,
            personality_model="claude-3-opus-20240229",
            personality_temperature=0.5,
            personality_max_tokens=512,
        )

        assert config.personality_rewrite_enabled is False
        assert config.personality_model == "claude-3-opus-20240229"
        assert config.personality_temperature == 0.5
        assert config.personality_max_tokens == 512

    def test_custom_storm_config(self) -> None:
        """Should accept custom storm mode config."""
        config = BardConfig(
            storm_mode_enabled=False,
            storm_keywords=["danger", "alert"],
        )

        assert config.storm_mode_enabled is False
        assert config.storm_keywords == ["danger", "alert"]


# =============================================================================
# Export Tests for New Items
# =============================================================================


class TestNewExports:
    """Tests for new module exports."""

    def test_personality_result_exported(self) -> None:
        """PersonalityResult should be in __all__."""
        from klabautermann.agents.bard import __all__

        assert "PersonalityResult" in __all__

    def test_personality_prompt_exported(self) -> None:
        """PERSONALITY_PROMPT should be in __all__."""
        from klabautermann.agents.bard import __all__

        assert "PERSONALITY_PROMPT" in __all__

    def test_storm_keywords_exported(self) -> None:
        """STORM_KEYWORDS should be in __all__."""
        from klabautermann.agents.bard import __all__

        assert "STORM_KEYWORDS" in __all__
