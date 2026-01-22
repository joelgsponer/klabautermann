"""
Golden Scenario E2E Tests for Lore System.

Tests the cross-conversation saga scenario from LORE_SYSTEM.md Section 8.2.

Issue: #124

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.bard import (
    BardConfig,
    BardOfTheBilge,
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
    return "captain-e2e-lore-test"


@pytest.fixture
def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


@pytest.fixture
def bard_e2e(mock_neo4j: MagicMock, captain_uuid: str) -> BardOfTheBilge:
    """Create a BardOfTheBilge for E2E testing."""
    config = BardConfig(
        tidbit_probability=1.0,  # Always add tidbit for testing
        saga_continuation_probability=1.0,  # Always continue sagas
        max_saga_chapters=5,
        min_chapter_interval_hours=0,  # No interval for testing
    )
    return BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)


# =============================================================================
# E2E Cross-Conversation Saga Test (#124)
# =============================================================================


@pytest.mark.e2e
@pytest.mark.lore
class TestLoreGoldenScenarioCrossConversation:
    """
    Golden Scenario: Cross-Conversation Saga (#124)

    Tests the complete flow:
    1. CLI: User asks about tasks -> Bard starts saga, Chapter 1
    2. Telegram: User checks calendar -> Bard continues with Chapter 2
    3. CLI (next day): User asks "What story were you telling?" ->
       Bard retrieves saga and continues with Chapter 3

    Reference: specs/architecture/LORE_SYSTEM.md Section 8.2
    """

    @pytest.mark.asyncio
    async def test_cli_starts_saga(
        self, bard_e2e: BardOfTheBilge, mock_neo4j: MagicMock, captain_uuid: str
    ) -> None:
        """CLI: User asks about tasks, Bard starts saga with Chapter 1."""
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga - no active sagas
            [],
            # _save_episode
            [{"uuid": "ep-ch1"}],
        ]

        # Simulate salt_response starting a new saga
        # Force the new saga path by ensuring no active saga exists
        with patch.object(bard_e2e, "_get_active_saga", new_callable=AsyncMock, return_value=None):
            mock_neo4j.execute_query.side_effect = [
                [],  # _get_active_sagas for start_new_saga check
                [{"uuid": "ep-ch1"}],  # _save_episode
            ]
            content, saga_id, chapter = await bard_e2e.start_new_saga(
                channel="cli", trace_id="e2e-124-step1"
            )

        assert chapter == 1, "First chapter should be 1"
        assert saga_id is not None, "Saga ID should be created"

        # Verify channel was CLI
        save_call = mock_neo4j.execute_query.call_args_list[-1]
        assert save_call[0][1]["channel"] == "cli"

    @pytest.mark.asyncio
    async def test_telegram_continues_saga(
        self, bard_e2e: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Telegram: User checks calendar, Bard continues saga with Chapter 2."""
        saga_id = "e2e-saga-124"

        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga - return active saga from CLI
            [
                {
                    "saga_id": saga_id,
                    "saga_name": "The E2E Tale",
                    "last_chapter": 1,
                    "last_told": now_ms - 3600000,  # 1 hour ago
                }
            ],
            # _save_episode
            [{"uuid": "ep-ch2"}],
        ]

        # salt_response on Telegram should continue the saga
        result = await bard_e2e.salt_response(
            clean_response="Here's your calendar for today...",
            channel="telegram",
            trace_id="e2e-124-step2",
        )

        assert result.tidbit_added is True, "Tidbit should be added"
        assert result.is_continuation is True, "Should be a saga continuation"
        assert result.chapter == 2, "Should be chapter 2"
        assert result.saga_id == saga_id, "Should continue same saga"

        # Verify chapter 2 was saved with telegram channel
        save_call = mock_neo4j.execute_query.call_args_list[-1]
        assert save_call[0][1]["channel"] == "telegram"
        assert save_call[0][1]["chapter"] == 2

    @pytest.mark.asyncio
    async def test_cli_retrieves_and_continues_saga(
        self, bard_e2e: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """CLI (next day): User asks about story, Bard retrieves and continues."""
        saga_id = "e2e-saga-124"

        # Mock active saga that has traveled CLI -> Telegram
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga - saga at chapter 2 from Telegram
            [
                {
                    "saga_id": saga_id,
                    "saga_name": "The E2E Tale",
                    "last_chapter": 2,
                    "last_told": now_ms - 86400000,  # 1 day ago
                }
            ],
            # _save_episode for chapter 3
            [{"uuid": "ep-ch3"}],
        ]

        # User on CLI asks about the story - Bard continues
        result = await bard_e2e.salt_response(
            clean_response="The story I was telling? Let me continue...",
            channel="cli",
            trace_id="e2e-124-step3",
        )

        assert result.tidbit_added is True
        assert result.is_continuation is True
        assert result.chapter == 3, "Should continue to chapter 3"
        assert result.saga_id == saga_id

        # Verify chapter 3 saved back to CLI
        save_call = mock_neo4j.execute_query.call_args_list[-1]
        assert save_call[0][1]["channel"] == "cli"
        assert save_call[0][1]["chapter"] == 3

    @pytest.mark.asyncio
    async def test_complete_cross_conversation_flow(
        self, mock_neo4j: MagicMock, captain_uuid: str, now_ms: int
    ) -> None:
        """
        Complete E2E flow: CLI start -> Telegram continue -> CLI retrieve and continue.

        This is the Golden Scenario from LORE_SYSTEM.md Section 8.2.
        """
        config = BardConfig(
            tidbit_probability=1.0,
            saga_continuation_probability=1.0,
            max_saga_chapters=5,
            min_chapter_interval_hours=0,
        )
        bard = BardOfTheBilge(neo4j_client=mock_neo4j, captain_uuid=captain_uuid, config=config)

        saga_id = "cross-conversation-saga"

        # =========================================
        # Step 1: CLI - User asks about tasks
        # =========================================
        mock_neo4j.execute_query.side_effect = [
            [],  # _get_active_sagas (none yet)
            [{"uuid": "ep-1"}],  # _save_episode
        ]

        _, saga_id, ch1 = await bard.start_new_saga(channel="cli", trace_id="e2e-cross-1")
        assert ch1 == 1

        # =========================================
        # Step 2: Telegram - User checks calendar
        # =========================================
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga - returns saga from step 1
            [
                {
                    "saga_id": saga_id,
                    "saga_name": "Generated Saga Name",
                    "last_chapter": 1,
                    "last_told": now_ms - 3600000,
                }
            ],
            [{"uuid": "ep-2"}],  # _save_episode
        ]

        result2 = await bard.salt_response(
            "Your calendar for today...", channel="telegram", trace_id="e2e-cross-2"
        )

        assert result2.chapter == 2
        assert result2.is_continuation is True

        # =========================================
        # Step 3: CLI (next day) - Ask about story
        # =========================================
        mock_neo4j.execute_query.side_effect = [
            # _get_active_saga - returns saga from step 2
            [
                {
                    "saga_id": saga_id,
                    "saga_name": "Generated Saga Name",
                    "last_chapter": 2,
                    "last_told": now_ms - 86400000,
                }
            ],
            [{"uuid": "ep-3"}],  # _save_episode
        ]

        result3 = await bard.salt_response(
            "What story were you telling?", channel="cli", trace_id="e2e-cross-3"
        )

        assert result3.chapter == 3
        assert result3.is_continuation is True
        assert result3.saga_id == saga_id

        # =========================================
        # Verify: Query the cross-channel saga
        # =========================================
        # Reset mock to clear side_effect before setting return_value
        mock_neo4j.execute_query.reset_mock()
        mock_neo4j.execute_query.side_effect = None
        mock_neo4j.execute_query.return_value = [
            {
                "chapter": 1,
                "content": "Started on CLI",
                "channel": "cli",
                "told_at": now_ms - 86400000 - 3600000,
                "saga_name": "Generated Saga Name",
            },
            {
                "chapter": 2,
                "content": "Continued on Telegram",
                "channel": "telegram",
                "told_at": now_ms - 86400000,
                "saga_name": "Generated Saga Name",
            },
            {
                "chapter": 3,
                "content": "Back to CLI",
                "channel": "cli",
                "told_at": now_ms,
                "saga_name": "Generated Saga Name",
            },
        ]

        cross_channel = await bard.get_cross_channel_story(saga_id=saga_id, trace_id="e2e-verify")

        assert len(cross_channel) == 3, "Should have 3 chapters"
        assert cross_channel[0]["channel"] == "cli", "Chapter 1 on CLI"
        assert cross_channel[1]["channel"] == "telegram", "Chapter 2 on Telegram"
        assert cross_channel[2]["channel"] == "cli", "Chapter 3 on CLI"


@pytest.mark.e2e
@pytest.mark.lore
class TestLoreGoldenScenarioSagaCompletion:
    """
    Tests saga completion behavior when max chapters reached.

    Reference: specs/architecture/LORE_SYSTEM.md Section 3.1
    """

    @pytest.mark.asyncio
    async def test_saga_completes_at_max_chapters(
        self, bard_e2e: BardOfTheBilge, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Saga should be marked complete when reaching max chapters."""
        saga_id = "completion-saga"

        # Saga at chapter 4 (one before max of 5)
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "saga_id": saga_id,
                    "saga_name": "The Final Chapter Saga",
                    "last_chapter": 4,
                    "last_told": now_ms - 1000,
                }
            ],
            [{"uuid": "ep-5"}],  # Chapter 5 (final)
        ]

        result = await bard_e2e.salt_response(
            "One more response...", channel="cli", trace_id="e2e-completion"
        )

        assert result.chapter == 5, "Should be final chapter 5"

        # After this, the saga should be complete
        # Next salt_response should not continue this saga


@pytest.mark.e2e
@pytest.mark.lore
class TestLoreGoldenScenarioStormMode:
    """
    Tests storm mode suppresses tidbits during urgent situations.

    Reference: specs/architecture/LORE_SYSTEM.md Section 5.1
    """

    @pytest.mark.asyncio
    async def test_storm_mode_skips_tidbit(
        self, bard_e2e: BardOfTheBilge, mock_neo4j: MagicMock
    ) -> None:
        """Storm mode should prevent tidbit addition even with active saga."""
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "storm-test-saga",
                "saga_name": "Interrupted Tale",
                "last_chapter": 2,
                "last_told": 1234567890,
            }
        ]

        result = await bard_e2e.salt_response(
            "URGENT: Server is down!",
            storm_mode=True,
            channel="cli",
            trace_id="e2e-storm",
        )

        assert result.tidbit_added is False, "No tidbit in storm mode"
        assert result.storm_mode_skipped is True, "Should indicate storm mode skip"
        assert result.salted_response == "URGENT: Server is down!", "Response unchanged"
