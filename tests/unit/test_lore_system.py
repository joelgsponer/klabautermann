"""
Unit tests for Lore System saga continuation and cross-channel persistence.

Tests the saga lifecycle features based on LORE_SYSTEM.md Section 8.1.

Issues: #122, #123
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.bard import (
    CANONICAL_TIDBITS,
    ActiveSaga,
    BardConfig,
    BardOfTheBilge,
    LoreEpisode,
)


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
    return "captain-lore-test-uuid"


@pytest.fixture
def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


@pytest.fixture
def bard_with_no_interval(mock_neo4j: MagicMock, captain_uuid: str) -> BardOfTheBilge:
    """Create a BardOfTheBilge instance with no chapter interval."""
    config = BardConfig(
        tidbit_probability=1.0,  # Always add tidbit for testing
        saga_continuation_probability=1.0,  # Always try to continue
        max_saga_chapters=5,
        min_chapter_interval_hours=0,  # No interval for testing
    )
    return BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)


# =============================================================================
# Test Saga Continuation (#122)
# =============================================================================


class TestSagaContinuation:
    """
    Tests for saga continuation functionality (#122).

    Reference: specs/architecture/LORE_SYSTEM.md Section 8.1
    """

    @pytest.mark.asyncio
    async def test_start_saga_creates_chapter_one(
        self, bard_with_no_interval: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Starting a saga should create chapter 1."""
        mock_neo4j.execute_query.side_effect = [
            # First call: _get_active_sagas (no active sagas)
            [],
            # Second call: _save_episode
            [{"uuid": "ep-chapter-1"}],
        ]

        content, saga_id, chapter = await bard_with_no_interval.start_new_saga(trace_id="test-122")

        assert chapter == 1
        assert saga_id is not None
        assert content in CANONICAL_TIDBITS

        # Verify _save_episode was called with chapter=1
        save_call = mock_neo4j.execute_query.call_args_list[1]
        assert save_call[0][1]["chapter"] == 1

    @pytest.mark.asyncio
    async def test_continue_saga_increments_chapter(
        self, bard_with_no_interval: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Continuing a saga should increment the chapter number."""
        # Create an active saga at chapter 2
        saga = ActiveSaga(
            saga_id="saga-continuation-test",
            saga_name="The Tale of Testing",
            last_chapter=2,
            last_told=now_ms - 1000,  # Told 1 second ago
        )

        mock_neo4j.execute_query.return_value = [{"uuid": "ep-chapter-3"}]

        content, chapter = await bard_with_no_interval._continue_saga(saga, trace_id="test-122")

        assert chapter == 3
        assert content in CANONICAL_TIDBITS

    @pytest.mark.asyncio
    async def test_verify_saga_chain_after_continuation(
        self, bard_with_no_interval: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """After continuation, get_saga_chain should return all chapters in order."""
        # Mock the saga chain query to return 3 chapters
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": "saga-chain-test",
                "saga_name": "The Chronicle of Chains",
                "chapter": 1,
                "content": "Chapter one begins",
                "channel": "cli",
                "told_at": now_ms - 2000,
                "created_at": now_ms - 2000,
                "captain_uuid": "captain-lore-test-uuid",
            },
            {
                "uuid": "ep-2",
                "saga_id": "saga-chain-test",
                "saga_name": "The Chronicle of Chains",
                "chapter": 2,
                "content": "Chapter two continues",
                "channel": "cli",
                "told_at": now_ms - 1000,
                "created_at": now_ms - 1000,
                "captain_uuid": "captain-lore-test-uuid",
            },
            {
                "uuid": "ep-3",
                "saga_id": "saga-chain-test",
                "saga_name": "The Chronicle of Chains",
                "chapter": 3,
                "content": "Chapter three concludes",
                "channel": "cli",
                "told_at": now_ms,
                "created_at": now_ms,
                "captain_uuid": "captain-lore-test-uuid",
            },
        ]

        chapters = await bard_with_no_interval.get_saga_chain(
            saga_id="saga-chain-test", trace_id="test-122"
        )

        assert len(chapters) == 3
        assert chapters[0].chapter == 1
        assert chapters[1].chapter == 2
        assert chapters[2].chapter == 3
        assert chapters[0].content == "Chapter one begins"
        assert chapters[2].content == "Chapter three concludes"

    @pytest.mark.asyncio
    async def test_full_saga_continuation_flow(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Test complete flow: start saga -> continue -> continue -> verify chain."""
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            max_saga_chapters=5,
            min_chapter_interval_hours=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # Step 1: Start new saga
        mock_neo4j.execute_query.side_effect = [
            [],  # No active sagas
            [{"uuid": "ep-1"}],  # _save_episode for chapter 1
        ]

        content1, saga_id, chapter1 = await bard.start_new_saga(trace_id="test-122-flow")
        assert chapter1 == 1

        # Reset mock for step 2
        mock_neo4j.execute_query.reset_mock()
        mock_neo4j.execute_query.side_effect = None
        mock_neo4j.execute_query.return_value = [{"uuid": "ep-2"}]

        # Step 2: Continue saga to chapter 2
        saga = ActiveSaga(
            saga_id=saga_id,
            saga_name="Test Flow Saga",
            last_chapter=1,
            last_told=now_ms,
        )

        content2, chapter2 = await bard._continue_saga(saga, trace_id="test-122-flow")
        assert chapter2 == 2

        # Reset mock for step 3
        mock_neo4j.execute_query.reset_mock()
        mock_neo4j.execute_query.return_value = [{"uuid": "ep-3"}]

        # Step 3: Continue saga to chapter 3
        saga.last_chapter = 2

        content3, chapter3 = await bard._continue_saga(saga, trace_id="test-122-flow")
        assert chapter3 == 3


# =============================================================================
# Test Cross-Channel Persistence (#123)
# =============================================================================


class TestCrossChannelPersistence:
    """
    Tests for cross-channel story persistence (#123).

    Stories should persist across channels (CLI, Telegram).

    Reference: specs/architecture/LORE_SYSTEM.md Section 8.1
    """

    @pytest.mark.asyncio
    async def test_tell_story_on_cli_channel(
        self, bard_with_no_interval: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Story told on CLI should have channel='cli'."""
        # Mock active saga exists
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga
            [
                {
                    "saga_id": "saga-cli-test",
                    "saga_name": "The CLI Tale",
                    "last_chapter": 1,
                    "last_told": now_ms - 1000,
                }
            ],
            # _save_episode
            [{"uuid": "ep-cli"}],
        ]

        result = await bard_with_no_interval.salt_response(
            clean_response="Hello from CLI",
            channel="cli",
            trace_id="test-123-cli",
        )

        assert result.tidbit_added is True

        # Verify channel was passed to _save_episode
        save_call = mock_neo4j.execute_query.call_args_list[1]
        assert save_call[0][1]["channel"] == "cli"

    @pytest.mark.asyncio
    async def test_continue_story_on_telegram_channel(
        self, bard_with_no_interval: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Story continued on Telegram should have channel='telegram'."""
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga
            [
                {
                    "saga_id": "saga-telegram-test",
                    "saga_name": "The Telegram Tale",
                    "last_chapter": 2,
                    "last_told": now_ms - 1000,
                }
            ],
            # _save_episode
            [{"uuid": "ep-telegram"}],
        ]

        result = await bard_with_no_interval.salt_response(
            clean_response="Hello from Telegram",
            channel="telegram",
            trace_id="test-123-telegram",
        )

        assert result.tidbit_added is True

        # Verify channel was passed to _save_episode
        save_call = mock_neo4j.execute_query.call_args_list[1]
        assert save_call[0][1]["channel"] == "telegram"

    @pytest.mark.asyncio
    async def test_same_saga_across_channels(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Same saga should be accessible from different channels."""
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            max_saga_chapters=5,
            min_chapter_interval_hours=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        # Tell on CLI (chapter 1)
        mock_neo4j.execute_query.side_effect = [
            [],  # No active sagas
            [{"uuid": "ep-1"}],  # _save_episode
        ]

        _, saga_id, _ = await bard.start_new_saga(channel="cli", trace_id="test-123-cross")

        # Reset mock for continue
        mock_neo4j.execute_query.reset_mock()
        mock_neo4j.execute_query.side_effect = None
        mock_neo4j.execute_query.return_value = [{"uuid": "ep-2"}]

        # Continue on Telegram (chapter 2)
        saga = ActiveSaga(
            saga_id=saga_id,
            saga_name="Cross Channel Saga",
            last_chapter=1,
            last_told=now_ms,
        )

        _, chapter = await bard._continue_saga(saga, channel="telegram", trace_id="test-123-cross")

        assert chapter == 2

        # Reset mock for cross-channel query
        mock_neo4j.execute_query.reset_mock()
        mock_neo4j.execute_query.return_value = [
            {
                "chapter": 1,
                "content": "Started on CLI",
                "channel": "cli",
                "told_at": now_ms - 1000,
                "saga_name": "Cross Channel Saga",
            },
            {
                "chapter": 2,
                "content": "Continued on Telegram",
                "channel": "telegram",
                "told_at": now_ms,
                "saga_name": "Cross Channel Saga",
            },
        ]

        cross_channel = await bard.get_cross_channel_story(
            saga_id=saga_id, trace_id="test-123-cross"
        )

        assert len(cross_channel) == 2
        assert cross_channel[0]["channel"] == "cli"
        assert cross_channel[1]["channel"] == "telegram"

    @pytest.mark.asyncio
    async def test_saga_persists_after_channel_switch(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """Saga should be retrievable after switching channels."""
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            max_saga_chapters=5,
            min_chapter_interval_hours=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        saga_id = "saga-persist-test"

        # Mock get_saga_chain to return chapters from different channels
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "ep-1",
                "saga_id": saga_id,
                "saga_name": "Persistent Saga",
                "chapter": 1,
                "content": "CLI chapter",
                "channel": "cli",
                "told_at": now_ms - 3000,
                "created_at": now_ms - 3000,
                "captain_uuid": captain_uuid,
            },
            {
                "uuid": "ep-2",
                "saga_id": saga_id,
                "saga_name": "Persistent Saga",
                "chapter": 2,
                "content": "Telegram chapter",
                "channel": "telegram",
                "told_at": now_ms - 2000,
                "created_at": now_ms - 2000,
                "captain_uuid": captain_uuid,
            },
            {
                "uuid": "ep-3",
                "saga_id": saga_id,
                "saga_name": "Persistent Saga",
                "chapter": 3,
                "content": "Back to CLI",
                "channel": "cli",
                "told_at": now_ms - 1000,
                "created_at": now_ms - 1000,
                "captain_uuid": captain_uuid,
            },
        ]

        # Query from "CLI" perspective - should see all chapters
        chapters = await bard.get_saga_chain(saga_id=saga_id, trace_id="test-123-persist")

        assert len(chapters) == 3
        assert all(c.saga_id == saga_id for c in chapters)

        # Verify channels are tracked
        assert chapters[0].channel == "cli"
        assert chapters[1].channel == "telegram"
        assert chapters[2].channel == "cli"


# =============================================================================
# Test LoreEpisode with Channel (#122, #123)
# =============================================================================


class TestLoreEpisodeChannel:
    """Tests for LoreEpisode channel tracking."""

    def test_lore_episode_stores_channel(self, now_ms: int) -> None:
        """LoreEpisode should store channel information."""
        episode = LoreEpisode(
            uuid="ep-channel-test",
            saga_id="saga-123",
            saga_name="Channel Test Saga",
            chapter=1,
            content="Test content",
            told_at=now_ms,
            created_at=now_ms,
            captain_uuid="captain-test",
            channel="telegram",
        )

        assert episode.channel == "telegram"
        assert episode.to_dict()["channel"] == "telegram"

    def test_lore_episode_channel_defaults_none(self, now_ms: int) -> None:
        """LoreEpisode channel should default to None for backwards compatibility."""
        episode = LoreEpisode(
            uuid="ep-no-channel",
            saga_id="saga-123",
            saga_name="No Channel Saga",
            chapter=1,
            content="Test content",
            told_at=now_ms,
            created_at=now_ms,
        )

        assert episode.channel is None

    def test_lore_episode_to_dict_includes_channel(self, now_ms: int) -> None:
        """LoreEpisode.to_dict() should include channel in output."""
        episode = LoreEpisode(
            uuid="ep-dict-test",
            saga_id="saga-123",
            saga_name="Dict Test Saga",
            chapter=1,
            content="Test content",
            told_at=now_ms,
            created_at=now_ms,
            channel="cli",
        )

        d = episode.to_dict()

        assert "channel" in d
        assert d["channel"] == "cli"
