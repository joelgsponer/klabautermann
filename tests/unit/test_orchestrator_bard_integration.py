"""
Unit tests for Orchestrator Bard integration (#109).

Tests the salt_response integration in _apply_personality method.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.bard import BardOfTheBilge, SaltResult
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
    async def test_apply_personality_with_bard_adds_tidbit(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """_apply_personality calls Bard and adds tidbit when probability hits."""
        salt_result = SaltResult(
            original_response="Hello",
            salted_response="Hello\n\n_A tale from the sea..._",
            tidbit_added=True,
            tidbit="A tale from the sea...",
            saga_id=None,
            chapter=None,
            is_continuation=False,
        )

        with patch.object(
            orchestrator_with_bard._bard,
            "salt_response",
            new_callable=AsyncMock,
            return_value=salt_result,
        ):
            response = await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            assert response == "Hello\n\n_A tale from the sea..._"

    @pytest.mark.asyncio
    async def test_apply_personality_with_bard_no_tidbit(
        self, orchestrator_with_bard: Orchestrator
    ) -> None:
        """_apply_personality returns original when Bard doesn't add tidbit."""
        salt_result = SaltResult(
            original_response="Hello",
            salted_response="Hello",
            tidbit_added=False,
            tidbit=None,
        )

        with patch.object(
            orchestrator_with_bard._bard,
            "salt_response",
            new_callable=AsyncMock,
            return_value=salt_result,
        ):
            response = await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            assert response == "Hello"

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
            "salt_response",
            new_callable=AsyncMock,
            side_effect=Exception("Bard error"),
        ):
            response = await orchestrator_with_bard._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            # Should return original response, not crash
            assert response == "Hello"


class TestStormModeDetection:
    """Tests for storm mode detection."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with default config."""
        return Orchestrator(
            graphiti=MagicMock(),
            thread_manager=MagicMock(),
            neo4j_client=MagicMock(),
            captain_uuid="captain-123",
        )

    def test_detect_storm_mode_urgent(self, orchestrator: Orchestrator) -> None:
        """Storm mode detected with 'urgent' keyword."""
        assert orchestrator._detect_storm_mode("This is URGENT!") is True

    def test_detect_storm_mode_emergency(self, orchestrator: Orchestrator) -> None:
        """Storm mode detected with 'emergency' keyword."""
        assert orchestrator._detect_storm_mode("Emergency meeting now") is True

    def test_detect_storm_mode_critical(self, orchestrator: Orchestrator) -> None:
        """Storm mode detected with 'critical' keyword."""
        assert orchestrator._detect_storm_mode("Critical bug found") is True

    def test_detect_storm_mode_asap(self, orchestrator: Orchestrator) -> None:
        """Storm mode detected with 'asap' keyword."""
        assert orchestrator._detect_storm_mode("Need this ASAP") is True

    def test_detect_storm_mode_normal(self, orchestrator: Orchestrator) -> None:
        """No storm mode for normal responses."""
        assert orchestrator._detect_storm_mode("Here's your calendar for today") is False

    def test_detect_storm_mode_case_insensitive(self, orchestrator: Orchestrator) -> None:
        """Storm mode detection is case-insensitive."""
        assert orchestrator._detect_storm_mode("URGENT task") is True
        assert orchestrator._detect_storm_mode("urgent task") is True

    @pytest.mark.asyncio
    async def test_storm_mode_passed_to_bard(self, orchestrator: Orchestrator) -> None:
        """Storm mode flag is passed to Bard salt_response."""
        salt_result = SaltResult(
            original_response="Urgent response",
            salted_response="Urgent response",
            tidbit_added=False,
            tidbit=None,
        )

        with patch.object(
            orchestrator._bard,
            "salt_response",
            new_callable=AsyncMock,
            return_value=salt_result,
        ) as mock_salt:
            await orchestrator._apply_personality(
                response="This is URGENT!",
                trace_id="trace-123",
            )

            # Verify storm_mode=True was passed
            mock_salt.assert_called_once()
            call_kwargs = mock_salt.call_args.kwargs
            assert call_kwargs.get("storm_mode") is True


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
        salt_result = SaltResult(
            original_response="Hello",
            salted_response="Hello\n\n_Chapter 3 of the saga..._",
            tidbit_added=True,
            tidbit="Chapter 3 of the saga...",
            saga_id="saga-123",
            chapter=3,
            is_continuation=True,
        )

        with patch.object(
            orchestrator._bard,
            "salt_response",
            new_callable=AsyncMock,
            return_value=salt_result,
        ):
            response = await orchestrator._apply_personality(
                response="Hello",
                trace_id="trace-123",
            )

            assert "Chapter 3 of the saga..." in response
