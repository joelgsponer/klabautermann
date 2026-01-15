"""
Unit tests for the Agent Configuration Manager (T032).

Tests YAML loading, validation, typed access, and hot-reload.
"""
# ruff: noqa: B017

import tempfile
from pathlib import Path

import pytest

from klabautermann.config.manager import (
    AgentConfigBase,
    ConfigManager,
    ExecutorConfig,
    IngestorConfig,
    IntentConfig,
    ModelConfig,
    OrchestratorConfig,
    ResearcherConfig,
    RetryConfig,
    TimeoutConfig,
)


class TestModelConfig:
    """Tests for ModelConfig validation."""

    def test_default_values(self) -> None:
        """ModelConfig has sensible defaults."""
        config = ModelConfig()
        assert config.primary == "claude-sonnet-4-20250514"
        assert config.fallback is None
        assert config.temperature == 0.7
        assert config.max_context_tokens == 8000
        assert config.max_output_tokens == 4096

    def test_temperature_validation(self) -> None:
        """Temperature must be between 0 and 2."""
        config = ModelConfig(temperature=1.5)
        assert config.temperature == 1.5

        with pytest.raises(ValueError):
            ModelConfig(temperature=-0.1)

        with pytest.raises(ValueError):
            ModelConfig(temperature=2.1)

    def test_tokens_must_be_positive(self) -> None:
        """Token limits must be positive."""
        with pytest.raises(ValueError):
            ModelConfig(max_context_tokens=0)

        with pytest.raises(ValueError):
            ModelConfig(max_output_tokens=-100)


class TestAgentConfigs:
    """Tests for agent-specific configs."""

    def test_orchestrator_config_defaults(self) -> None:
        """OrchestratorConfig has all expected fields."""
        config = OrchestratorConfig()
        assert config.personality.name == "klabautermann"
        assert config.personality.wit_level == 0.3
        assert isinstance(config.intent_classification, IntentConfig)
        assert config.delegation.search == "researcher"

    def test_ingestor_config_defaults(self) -> None:
        """IngestorConfig has extraction settings."""
        config = IngestorConfig()
        assert "Person" in config.extraction.entity_types
        assert "WORKS_AT" in config.extraction.relationship_types
        assert config.extraction.confidence_threshold == 0.7

    def test_researcher_config_defaults(self) -> None:
        """ResearcherConfig has search settings."""
        config = ResearcherConfig()
        assert config.search.max_results == 10
        assert config.search.use_vector_search is True
        assert config.search.max_hops == 2

    def test_executor_config_defaults(self) -> None:
        """ExecutorConfig has tools settings."""
        config = ExecutorConfig()
        assert "gmail" in config.tools.enabled_tools
        assert config.tools.require_confirmation is True
        assert config.tools.dry_run is False


class TestConfigManager:
    """Tests for ConfigManager class."""

    @pytest.fixture
    def temp_config_dir(self) -> Path:
        """Create temporary config directory with test YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write test orchestrator config
            (config_dir / "orchestrator.yaml").write_text("""
model:
  primary: test-model
  temperature: 0.5

personality:
  wit_level: 0.8

intent_classification:
  model: claude-3-5-haiku-20241022
  timeout: 5.0
""")

            # Write test ingestor config
            (config_dir / "ingestor.yaml").write_text("""
model:
  primary: haiku-test
  temperature: 0.2

extraction:
  entity_types:
    - Person
    - Project
  confidence_threshold: 0.9
""")

            yield config_dir

    def test_loads_yaml_configs(self, temp_config_dir: Path) -> None:
        """ConfigManager loads configs from YAML files."""
        manager = ConfigManager(temp_config_dir)

        assert manager.has_config("orchestrator")
        assert manager.has_config("ingestor")

    def test_get_returns_config(self, temp_config_dir: Path) -> None:
        """get() returns config for known agent."""
        manager = ConfigManager(temp_config_dir)

        config = manager.get("orchestrator")
        assert config is not None
        assert config.model.primary == "test-model"

    def test_get_returns_none_for_unknown(self, temp_config_dir: Path) -> None:
        """get() returns None for unknown agent."""
        manager = ConfigManager(temp_config_dir)

        config = manager.get("unknown_agent")
        assert config is None

    def test_get_typed_returns_correct_type(self, temp_config_dir: Path) -> None:
        """get_typed() returns correctly typed config."""
        manager = ConfigManager(temp_config_dir)

        config = manager.get_typed("orchestrator", OrchestratorConfig)
        assert config is not None
        assert isinstance(config, OrchestratorConfig)
        assert config.personality.wit_level == 0.8

    def test_get_typed_returns_none_for_wrong_type(self, temp_config_dir: Path) -> None:
        """get_typed() returns None when type doesn't match."""
        manager = ConfigManager(temp_config_dir)

        # Orchestrator config can't be cast to IngestorConfig
        config = manager.get_typed("orchestrator", IngestorConfig)
        assert config is None

    def test_agent_names_property(self, temp_config_dir: Path) -> None:
        """agent_names returns list of configured agents."""
        manager = ConfigManager(temp_config_dir)

        names = manager.agent_names
        assert "orchestrator" in names
        assert "ingestor" in names

    def test_creates_defaults_for_missing_configs(self) -> None:
        """ConfigManager creates defaults when config dir doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_dir = Path(tmpdir) / "nonexistent"

            manager = ConfigManager(nonexistent_dir)

            # Should have defaults for all known agents
            assert manager.has_config("orchestrator")
            assert manager.has_config("researcher")
            assert manager.has_config("executor")

    def test_checksum_changes_on_reload(self, temp_config_dir: Path) -> None:
        """Checksum changes when config file is modified."""
        manager = ConfigManager(temp_config_dir)

        original_checksum = manager.get_checksum("orchestrator")

        # Modify config file
        config_file = temp_config_dir / "orchestrator.yaml"
        config_file.write_text("""
model:
  primary: modified-model
  temperature: 0.9
""")

        # Reload
        changed = manager.reload("orchestrator")

        assert changed is True
        assert manager.get_checksum("orchestrator") != original_checksum
        assert manager.get("orchestrator").model.primary == "modified-model"

    def test_reload_returns_false_when_unchanged(self, temp_config_dir: Path) -> None:
        """reload() returns False when config hasn't changed."""
        manager = ConfigManager(temp_config_dir)

        changed = manager.reload("orchestrator")

        assert changed is False

    def test_reload_all_returns_dict(self, temp_config_dir: Path) -> None:
        """reload_all() returns dict of changes."""
        manager = ConfigManager(temp_config_dir)

        results = manager.reload_all()

        assert isinstance(results, dict)
        assert "orchestrator" in results
        assert results["orchestrator"] is False  # No change


class TestConfigValidation:
    """Tests for config validation."""

    def test_invalid_yaml_raises_error(self) -> None:
        """Invalid YAML raises error on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "orchestrator.yaml").write_text("""
model:
  temperature: not_a_number
""")

            with pytest.raises(Exception):
                ConfigManager(config_dir)

    def test_extra_fields_allowed_in_base(self) -> None:
        """AgentConfigBase allows extra fields."""
        config = AgentConfigBase(
            model=ModelConfig(),
            custom_field="value",  # Extra field
        )
        assert config.model.primary == "claude-sonnet-4-20250514"

    def test_timeout_validation(self) -> None:
        """TimeoutConfig validates positive values."""
        config = TimeoutConfig(agent_response=10.0)
        assert config.agent_response == 10.0

        with pytest.raises(ValueError):
            TimeoutConfig(agent_response=0.0)

    def test_retry_validation(self) -> None:
        """RetryConfig validates bounds."""
        config = RetryConfig(max_attempts=5, jitter=0.5)
        assert config.max_attempts == 5
        assert config.jitter == 0.5

        with pytest.raises(ValueError):
            RetryConfig(max_attempts=0)

        with pytest.raises(ValueError):
            RetryConfig(jitter=1.5)


class TestIntegrationWithRealConfigs:
    """Tests using the actual config files."""

    def test_loads_real_config_files(self) -> None:
        """ConfigManager loads config files from config/agents/."""
        # Use the real config directory
        config_dir = Path(__file__).parent.parent.parent / "config" / "agents"
        if not config_dir.exists():
            pytest.skip("Real config directory not found")

        manager = ConfigManager(config_dir)

        # Should load real configs
        orchestrator = manager.get_typed("orchestrator", OrchestratorConfig)
        if orchestrator:
            assert orchestrator.model.primary is not None
            assert orchestrator.intent_classification.model is not None
            assert orchestrator.intent_classification.timeout > 0
