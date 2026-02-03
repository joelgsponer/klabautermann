"""
Unit tests for Orchestrator Bard integration (#109).

Tests the apply_personality integration where Orchestrator delegates
personality/voice handling entirely to the Bard agent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.bard import BardOfTheBilge, PersonalityResult
from klabautermann.agents.orchestrator import Orchestrator


class TestOrchestratorBardIntegration:
    """Tests for Bard integration in Orchestrator (#109)."""

    @pytest.fixture
    def mock_neo4j(self) -> MagicMock:
        """Create mock Neo4j client."""
        return MagicMock()

    @pytest.fixture
    def orchestrator_with_bard(self, mock_neo4j: MagicMock) -> Orchestrator:
        """Create orchestrator with Bard initialized."""
        return Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=mock_neo4j,
            captain_uuid="captain-123",
        )

    @pytest.fixture
    def orchestrator_without_bard(self) -> Orchestrator:
        """Create orchestrator without Bard (no captain_uuid)."""
        return Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=MagicMock(),
            captain_uuid=None,  # No captain UUID means no Bard
        )

    @pytest.mark.asyncio
    async def test_bard_initialized_with_captain_uuid(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """Bard is initialized when captain_uuid is provided."""
        assert orchestrator_with_bard._bard is not None
        assert isinstance(orchestrator_with_bard._bard, BardOfTheBilge)
        assert "bard" in orchestrator_with_bard._agent_registry

    @pytest.mark.asyncio
    async def test_bard_not_initialized_without_captain_uuid(
        self, orchestrator_without_bard: Orchestrator
    ) -> None:
        """Bard is not initialized when captain_uuid is missing."""
        assert orchestrator_without_bard._bard is None
        assert "bard" not in orchestrator_without_bard._agent_registry

    @pytest.mark.asyncio
    async def test_apply_personality_delegates_to_bard(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """_apply_personality delegates to Bard's apply_personality method."""
        personality_result = PersonalityResult(
            original_response="Hello",
            final_response="Ahoy, Captain! Hello.\n\n_A tale from the sea..._",
            personality_applied=True,
            tidbit_added=True,
            tidbit="A tale from the sea...",
            llm_rewrite_used=True,
        )

        with patch.object(
            orchestrator_with_bard._bard,
            "apply_personality",
            new_callable=AsyncMock,
            return_value=personality_result,
        ):
            response = await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            assert response == "Ahoy, Captain! Hello.\n\n_A tale from the sea..._"

    @pytest.mark.asyncio
    async def test_apply_personality_passes_channel(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """_apply_personality passes channel to Bard."""
        personality_result = PersonalityResult(
            original_response="Hello",
            final_response="Hello",
            personality_applied=True,
            channel="telegram",
        )

        with patch.object(
            orchestrator_with_bard._bard,
            "apply_personality",
            new_callable=AsyncMock,
            return_value=personality_result,
        ) as mock_apply:
            await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
                channel="telegram",
            )

            mock_apply.assert_called_once()
            call_kwargs = mock_apply.call_args.kwargs
            assert call_kwargs.get("channel") == "telegram"

    @pytest.mark.asyncio
    async def test_apply_personality_without_bard_passthrough(
        self, orchestrator_without_bard: Orchestrator
    ) -> None:
        """_apply_personality passes through when Bard is not initialized."""
        response = await orchestrator_without_bard._apply_personality(
            response="Hello",
            trace_id="trace-123",
        )

        assert response == "Hello"

    @pytest.mark.asyncio
    async def test_apply_personality_bard_error_fallback(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """_apply_personality returns original on Bard error."""
        with patch.object(
            orchestrator_with_bard._bard,
            "apply_personality",
            new_callable=AsyncMock,
            side_effect=Exception("Bard error"),
        ):
            response = await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            # Should return original response, not crash
            assert response == "Hello"


class TestStormModeInBard:
    """Tests for storm mode detection (now handled by Bard)."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with default config."""
        return Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=MagicMock(),
            captain_uuid="captain-123",
        )

    @pytest.mark.asyncio
    async def test_bard_handles_storm_mode_detection(self, orchestrator: Orchestrator) -> None:
        """Storm mode is now detected by Bard, not Orchestrator."""
        # Bard's apply_personality auto-detects storm mode
        personality_result = PersonalityResult(
            original_response="URGENT: Server down!",
            final_response="URGENT: Server down!",
            personality_applied=False,  # Skipped due to storm mode
            storm_mode=True,
        )

        with patch.object(
            orchestrator._bard,
            "apply_personality",
            new_callable=AsyncMock,
            return_value=personality_result,
        ):
            response = await orchestrator._apply_personality(
                response="URGENT: Server down!",
                trace_id="trace-123",
            )

            # Storm mode should return clean response
            assert response == "URGENT: Server down!"

    def test_bard_storm_mode_detection(self, orchestrator: Orchestrator) -> None:
        """Bard's _detect_storm_mode works correctly."""
        bard = orchestrator._bard
        assert bard is not None

        # Test storm keywords
        assert bard._detect_storm_mode("This is URGENT!") is True
        assert bard._detect_storm_mode("Emergency meeting now") is True
        assert bard._detect_storm_mode("Critical bug found") is True
        assert bard._detect_storm_mode("Need this ASAP") is True

        # Test normal messages
        assert bard._detect_storm_mode("Here's your calendar for today") is False
        assert bard._detect_storm_mode("Hello, how are you?") is False


class TestBardConfigLoading:
    """Tests for Bard config loading in Orchestrator."""

    def test_load_bard_config_defaults(self) -> None:
        """_load_bard_config returns sensible defaults."""
        orchestrator = Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=MagicMock(),
        )

        config = orchestrator._bard_config

        assert "tidbit_probability" in config
        assert "saga_rules" in config
        assert "storm_mode" in config
        assert config["tidbit_probability"] == 0.07

    def test_bard_config_from_file(self) -> None:
        """Bard config is loaded from bard.yaml."""
        with patch("klabautermann.config.manager.ConfigManager") as mock_cm:
            mock_config = MagicMock()
            mock_config.model_dump.return_value = {
                "enabled": True,
                "tidbit_probability": 0.10,  # Custom value
                "saga_continuation_probability": 0.4,
                "saga_rules": {"max_chapters": 7},
            }
            mock_cm.return_value.get.return_value = mock_config

            orchestrator = Orchestrator(
                graphiti=MagicMock(),
                thread_manager=MagicMock(),
                neo4j_client=MagicMock(),
                captain_uuid="captain-123",
            )

            # Should use config from file
            assert orchestrator._bard_config["tidbit_probability"] == 0.10


class TestBardSagaContinuation:
    """Tests for saga continuation through Orchestrator."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with Bard."""
        return Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=MagicMock(),
            captain_uuid="captain-123",
        )

    @pytest.mark.asyncio
    async def test_saga_continuation_logged(self, orchestrator: Orchestrator) -> None:
        """Saga continuation is logged with chapter info."""
        personality_result = PersonalityResult(
            original_response="Hello",
            final_response="Hello\n\n_Chapter 3 of the saga..._",
            personality_applied=True,
            tidbit_added=True,
            tidbit="Chapter 3 of the saga...",
            saga_id="saga-123",
            chapter=3,
            llm_rewrite_used=True,
        )

        with patch.object(
            orchestrator._bard,
            "apply_personality",
            new_callable=AsyncMock,
            return_value=personality_result,
        ):
            response = await orchestrator._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            assert "Chapter 3 of the saga..." in response
