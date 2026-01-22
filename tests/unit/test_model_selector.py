"""
Tests for multi-model orchestration (model_selector.py).

Tests the ModelSelector's ability to dynamically select models based on
task complexity, purpose, and agent-specific overrides.

Reference: Issue #3 [AGT-P-002]
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from klabautermann.core.model_selector import (
    COMPLEXITY_TO_TIER,
    DEFAULT_MODELS,
    PURPOSE_TO_TIER,
    ModelCallResult,
    ModelSelectionConfig,
    ModelSelector,
    ModelTier,
    TaskComplexity,
    TaskPurpose,
    get_model_for_agent,
)


# ===========================================================================
# ModelTier Tests
# ===========================================================================


class TestModelTier:
    """Tests for ModelTier enum."""

    def test_model_tiers_defined(self) -> None:
        """All expected model tiers exist."""
        assert ModelTier.HAIKU == "haiku"
        assert ModelTier.SONNET == "sonnet"
        assert ModelTier.OPUS == "opus"

    def test_all_tiers_have_default_models(self) -> None:
        """Each tier has a default model ID."""
        for tier in ModelTier:
            assert tier in DEFAULT_MODELS
            assert DEFAULT_MODELS[tier].startswith("claude")


# ===========================================================================
# TaskComplexity Tests
# ===========================================================================


class TestTaskComplexity:
    """Tests for TaskComplexity enum."""

    def test_complexity_levels_defined(self) -> None:
        """All expected complexity levels exist."""
        assert TaskComplexity.SIMPLE == "simple"
        assert TaskComplexity.MODERATE == "moderate"
        assert TaskComplexity.COMPLEX == "complex"

    def test_complexity_maps_to_tier(self) -> None:
        """Each complexity level maps to a model tier."""
        assert COMPLEXITY_TO_TIER[TaskComplexity.SIMPLE] == ModelTier.HAIKU
        assert COMPLEXITY_TO_TIER[TaskComplexity.MODERATE] == ModelTier.SONNET
        assert COMPLEXITY_TO_TIER[TaskComplexity.COMPLEX] == ModelTier.OPUS


# ===========================================================================
# TaskPurpose Tests
# ===========================================================================


class TestTaskPurpose:
    """Tests for TaskPurpose enum."""

    def test_purpose_types_defined(self) -> None:
        """All expected purpose types exist."""
        assert TaskPurpose.CLASSIFICATION == "classification"
        assert TaskPurpose.EXTRACTION == "extraction"
        assert TaskPurpose.SEARCH_PLANNING == "search_planning"
        assert TaskPurpose.REASONING == "reasoning"
        assert TaskPurpose.SYNTHESIS == "synthesis"
        assert TaskPurpose.PLANNING == "planning"
        assert TaskPurpose.ACTION == "action"

    def test_purpose_maps_to_tier(self) -> None:
        """Each purpose maps to a default model tier."""
        # Simple tasks -> Haiku
        assert PURPOSE_TO_TIER[TaskPurpose.CLASSIFICATION] == ModelTier.HAIKU
        assert PURPOSE_TO_TIER[TaskPurpose.EXTRACTION] == ModelTier.HAIKU
        assert PURPOSE_TO_TIER[TaskPurpose.SEARCH_PLANNING] == ModelTier.HAIKU

        # Moderate tasks -> Sonnet
        assert PURPOSE_TO_TIER[TaskPurpose.REASONING] == ModelTier.SONNET
        assert PURPOSE_TO_TIER[TaskPurpose.SYNTHESIS] == ModelTier.SONNET
        assert PURPOSE_TO_TIER[TaskPurpose.ACTION] == ModelTier.SONNET

        # Complex tasks -> Opus
        assert PURPOSE_TO_TIER[TaskPurpose.PLANNING] == ModelTier.OPUS


# ===========================================================================
# ModelSelectionConfig Tests
# ===========================================================================


class TestModelSelectionConfig:
    """Tests for ModelSelectionConfig."""

    def test_default_config(self) -> None:
        """Default config uses default models and tiers."""
        config = ModelSelectionConfig()

        assert config.models == DEFAULT_MODELS
        assert config.purpose_overrides == {}
        assert config.agent_overrides == {}
        assert config.fallback_tier == ModelTier.SONNET
        assert config.record_metrics is True

    def test_from_config_empty(self) -> None:
        """from_config with None returns default config."""
        config = ModelSelectionConfig.from_config(None)
        assert config.models == DEFAULT_MODELS

    def test_from_config_with_model_overrides(self) -> None:
        """from_config parses model overrides."""
        config_dict = {
            "model_selection": {
                "models": {
                    "haiku": "claude-3-haiku-custom",
                    "sonnet": "claude-sonnet-custom",
                }
            }
        }
        config = ModelSelectionConfig.from_config(config_dict)

        assert config.models[ModelTier.HAIKU] == "claude-3-haiku-custom"
        assert config.models[ModelTier.SONNET] == "claude-sonnet-custom"
        # Opus should still be default
        assert config.models[ModelTier.OPUS] == DEFAULT_MODELS[ModelTier.OPUS]

    def test_from_config_with_purpose_overrides(self) -> None:
        """from_config parses purpose overrides."""
        config_dict = {
            "model_selection": {
                "purpose_overrides": {
                    "extraction": "sonnet",  # Upgrade extraction to Sonnet
                    "synthesis": "opus",  # Upgrade synthesis to Opus
                }
            }
        }
        config = ModelSelectionConfig.from_config(config_dict)

        assert config.purpose_overrides[TaskPurpose.EXTRACTION] == ModelTier.SONNET
        assert config.purpose_overrides[TaskPurpose.SYNTHESIS] == ModelTier.OPUS

    def test_from_config_with_agent_overrides(self) -> None:
        """from_config parses agent overrides."""
        config_dict = {
            "model_selection": {
                "agent_overrides": {
                    "researcher": "opus",  # Always use Opus for researcher
                    "ingestor": "sonnet",  # Upgrade ingestor to Sonnet
                }
            }
        }
        config = ModelSelectionConfig.from_config(config_dict)

        assert config.agent_overrides["researcher"] == ModelTier.OPUS
        assert config.agent_overrides["ingestor"] == ModelTier.SONNET

    def test_from_config_with_fallback(self) -> None:
        """from_config parses fallback tier."""
        config_dict = {"model_selection": {"fallback_tier": "haiku"}}
        config = ModelSelectionConfig.from_config(config_dict)

        assert config.fallback_tier == ModelTier.HAIKU

    def test_from_config_ignores_invalid_tiers(self) -> None:
        """from_config ignores invalid tier names."""
        config_dict = {
            "model_selection": {
                "models": {"invalid_tier": "some-model"},
                "purpose_overrides": {"invalid_purpose": "haiku"},
                "agent_overrides": {"test": "invalid_tier"},
            }
        }
        config = ModelSelectionConfig.from_config(config_dict)

        # Should still have defaults
        assert config.models == DEFAULT_MODELS
        assert config.purpose_overrides == {}
        assert config.agent_overrides == {}


# ===========================================================================
# ModelSelector Tests
# ===========================================================================


class TestModelSelector:
    """Tests for ModelSelector."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Anthropic client."""
        return MagicMock()

    @pytest.fixture
    def selector(self, mock_client: MagicMock) -> ModelSelector:
        """Create a ModelSelector with default config."""
        return ModelSelector(mock_client)

    def test_select_by_purpose(self, selector: ModelSelector) -> None:
        """select_model selects by purpose."""
        # Classification -> Haiku
        model_id, tier = selector.select_model(purpose=TaskPurpose.CLASSIFICATION)
        assert tier == ModelTier.HAIKU
        assert model_id == DEFAULT_MODELS[ModelTier.HAIKU]

        # Planning -> Opus
        model_id, tier = selector.select_model(purpose=TaskPurpose.PLANNING)
        assert tier == ModelTier.OPUS
        assert model_id == DEFAULT_MODELS[ModelTier.OPUS]

        # Action -> Sonnet
        model_id, tier = selector.select_model(purpose=TaskPurpose.ACTION)
        assert tier == ModelTier.SONNET
        assert model_id == DEFAULT_MODELS[ModelTier.SONNET]

    def test_select_by_complexity(self, selector: ModelSelector) -> None:
        """select_model selects by complexity."""
        # Simple -> Haiku
        _model_id, tier = selector.select_model(complexity=TaskComplexity.SIMPLE)
        assert tier == ModelTier.HAIKU

        # Moderate -> Sonnet
        _model_id, tier = selector.select_model(complexity=TaskComplexity.MODERATE)
        assert tier == ModelTier.SONNET

        # Complex -> Opus
        _model_id, tier = selector.select_model(complexity=TaskComplexity.COMPLEX)
        assert tier == ModelTier.OPUS

    def test_complexity_overrides_purpose(self, selector: ModelSelector) -> None:
        """Complexity takes precedence over purpose default."""
        # Classification (default Haiku) with Complex -> Opus
        _model_id, tier = selector.select_model(
            purpose=TaskPurpose.CLASSIFICATION, complexity=TaskComplexity.COMPLEX
        )
        assert tier == ModelTier.OPUS

    def test_agent_override_takes_precedence(self, mock_client: MagicMock) -> None:
        """Agent override takes highest precedence."""
        config = ModelSelectionConfig(
            agent_overrides={"test_agent": ModelTier.OPUS},
            purpose_overrides={TaskPurpose.CLASSIFICATION: ModelTier.SONNET},
        )
        selector = ModelSelector(mock_client, config)

        # Even with classification purpose (default Haiku, override Sonnet),
        # agent override should win
        _model_id, tier = selector.select_model(
            purpose=TaskPurpose.CLASSIFICATION,
            agent_name="test_agent",
        )
        assert tier == ModelTier.OPUS

    def test_purpose_override_takes_precedence_over_default(self, mock_client: MagicMock) -> None:
        """Purpose override takes precedence over default."""
        config = ModelSelectionConfig(purpose_overrides={TaskPurpose.EXTRACTION: ModelTier.SONNET})
        selector = ModelSelector(mock_client, config)

        # Extraction default is Haiku, override is Sonnet
        _model_id, tier = selector.select_model(purpose=TaskPurpose.EXTRACTION)
        assert tier == ModelTier.SONNET

    def test_fallback_when_no_criteria(self, selector: ModelSelector) -> None:
        """Falls back to config fallback tier when no criteria provided."""
        _model_id, tier = selector.select_model()
        assert tier == ModelTier.SONNET  # Default fallback

    def test_get_model_for_purpose(self, selector: ModelSelector) -> None:
        """get_model_for_purpose returns model ID."""
        model_id = selector.get_model_for_purpose(TaskPurpose.CLASSIFICATION)
        assert model_id == DEFAULT_MODELS[ModelTier.HAIKU]

    def test_get_model_for_complexity(self, selector: ModelSelector) -> None:
        """get_model_for_complexity returns model ID."""
        model_id = selector.get_model_for_complexity(TaskComplexity.COMPLEX)
        assert model_id == DEFAULT_MODELS[ModelTier.OPUS]


class TestModelSelectorCall:
    """Tests for ModelSelector.call method."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Anthropic client with response."""
        client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Test response")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        client.messages.create.return_value = mock_response
        return client

    @pytest.fixture
    def selector(self, mock_client: MagicMock) -> ModelSelector:
        """Create ModelSelector with mock client."""
        config = ModelSelectionConfig(record_metrics=False)
        return ModelSelector(mock_client, config)

    @pytest.mark.asyncio
    async def test_call_returns_result(self, selector: ModelSelector) -> None:
        """call returns ModelCallResult with response."""
        result = await selector.call(
            prompt="Test prompt",
            purpose=TaskPurpose.CLASSIFICATION,
            trace_id="test-123",
        )

        assert isinstance(result, ModelCallResult)
        assert result.response == "Test response"
        assert result.model_tier == ModelTier.HAIKU
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.used_fallback is False

    @pytest.mark.asyncio
    async def test_call_uses_correct_model(
        self, mock_client: MagicMock, selector: ModelSelector
    ) -> None:
        """call uses the model selected for the purpose."""
        await selector.call(
            prompt="Test prompt",
            purpose=TaskPurpose.PLANNING,  # Should use Opus
        )

        # Check that Opus was used
        call_args = mock_client.messages.create.call_args
        assert DEFAULT_MODELS[ModelTier.OPUS] in str(call_args)

    @pytest.mark.asyncio
    async def test_call_with_fallback(self, mock_client: MagicMock) -> None:
        """call uses fallback model when primary fails."""
        # Make first call fail, second succeed
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Fallback response")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client.messages.create.side_effect = [
            Exception("Primary failed"),
            mock_response,
        ]

        config = ModelSelectionConfig(fallback_tier=ModelTier.SONNET, record_metrics=False)
        selector = ModelSelector(mock_client, config)

        result = await selector.call(
            prompt="Test prompt",
            purpose=TaskPurpose.PLANNING,  # Primary is Opus
        )

        assert result.response == "Fallback response"
        assert result.model_tier == ModelTier.SONNET  # Fell back to Sonnet
        assert result.used_fallback is True

    @pytest.mark.asyncio
    async def test_call_records_metrics(self, mock_client: MagicMock) -> None:
        """call records LLM metrics when enabled."""
        config = ModelSelectionConfig(record_metrics=True)
        selector = ModelSelector(mock_client, config)

        with (
            patch("klabautermann.core.model_selector.record_llm_call") as mock_record_call,
            patch("klabautermann.core.model_selector.record_llm_tokens") as mock_record_tokens,
            patch("klabautermann.core.model_selector.record_llm_latency") as mock_record_latency,
        ):
            await selector.call(
                prompt="Test prompt",
                purpose=TaskPurpose.CLASSIFICATION,
            )

            mock_record_call.assert_called_once_with(model="haiku", purpose="classification")
            mock_record_tokens.assert_called_once()
            mock_record_latency.assert_called_once()


# ===========================================================================
# get_model_for_agent Tests
# ===========================================================================


class TestGetModelForAgent:
    """Tests for get_model_for_agent helper function."""

    def test_default_agent_models(self) -> None:
        """Default models for known agents."""
        # Haiku agents
        assert get_model_for_agent("ingestor") == DEFAULT_MODELS[ModelTier.HAIKU]
        assert get_model_for_agent("researcher") == DEFAULT_MODELS[ModelTier.HAIKU]
        assert get_model_for_agent("archivist") == DEFAULT_MODELS[ModelTier.HAIKU]
        assert get_model_for_agent("scribe") == DEFAULT_MODELS[ModelTier.HAIKU]
        assert get_model_for_agent("bard") == DEFAULT_MODELS[ModelTier.HAIKU]
        assert get_model_for_agent("officer") == DEFAULT_MODELS[ModelTier.HAIKU]

        # Sonnet agents
        assert get_model_for_agent("orchestrator") == DEFAULT_MODELS[ModelTier.SONNET]
        assert get_model_for_agent("executor") == DEFAULT_MODELS[ModelTier.SONNET]

    def test_unknown_agent_uses_fallback(self) -> None:
        """Unknown agents use fallback tier (Sonnet)."""
        assert get_model_for_agent("unknown_agent") == DEFAULT_MODELS[ModelTier.SONNET]

    def test_agent_override_from_config(self) -> None:
        """Agent override from config takes precedence."""
        config = {
            "model_selection": {
                "agent_overrides": {
                    "ingestor": "opus",  # Override ingestor to use Opus
                }
            }
        }
        assert get_model_for_agent("ingestor", config) == DEFAULT_MODELS[ModelTier.OPUS]


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestModelSelectorIntegration:
    """Integration tests for complete model selection workflows."""

    def test_full_config_chain(self) -> None:
        """Test complete configuration chain."""
        config_dict = {
            "model_selection": {
                "models": {
                    "haiku": "claude-3-5-haiku-custom",
                    "sonnet": "claude-sonnet-4-custom",
                    "opus": "claude-opus-4-custom",
                },
                "purpose_overrides": {
                    "extraction": "sonnet",  # Upgrade extraction
                },
                "agent_overrides": {
                    "critical_agent": "opus",  # Always Opus
                },
                "fallback_tier": "haiku",
            }
        }

        config = ModelSelectionConfig.from_config(config_dict)
        client = MagicMock()
        selector = ModelSelector(client, config)

        # Agent override takes precedence
        model_id, tier = selector.select_model(
            purpose=TaskPurpose.EXTRACTION,  # Would be Sonnet from override
            agent_name="critical_agent",  # Opus override wins
        )
        assert tier == ModelTier.OPUS
        assert model_id == "claude-opus-4-custom"

        # Purpose override works when no agent override
        model_id, tier = selector.select_model(purpose=TaskPurpose.EXTRACTION)
        assert tier == ModelTier.SONNET
        assert model_id == "claude-sonnet-4-custom"

        # Default purpose still works
        model_id, tier = selector.select_model(purpose=TaskPurpose.CLASSIFICATION)
        assert tier == ModelTier.HAIKU
        assert model_id == "claude-3-5-haiku-custom"
