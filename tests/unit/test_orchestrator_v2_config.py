"""
Tests for Orchestrator v2 Configuration.

Reference: specs/MAINAGENT.md Section 7
"""

from pathlib import Path

import pytest

from klabautermann.config.manager import (
    ConfigManager,
    ContextConfig,
    ExecutionConfig,
    OrchestratorV2Config,
    ProactiveBehaviorConfig,
)


class TestOrchestratorV2Config:
    """Test orchestrator_v2.yaml config loading and validation."""

    def test_config_file_exists(self):
        """Verify orchestrator_v2.yaml exists in config/agents."""
        config_dir = Path(__file__).parent.parent.parent / "config" / "agents"
        config_file = config_dir / "orchestrator_v2.yaml"
        assert config_file.exists(), "orchestrator_v2.yaml must exist"

    def test_config_loads_successfully(self):
        """Config file should load without errors."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None, "orchestrator_v2 config should load"

    def test_model_configuration(self):
        """Model should be Claude Opus as specified in MAINAGENT.md."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        assert config.model == "claude-opus-4-5-20251101"
        assert config.synthesis_model == "claude-opus-4-5-20251101"

    def test_context_configuration(self):
        """Context config should have correct defaults from spec."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        ctx = config.context
        assert ctx.message_window == 20
        assert ctx.summary_hours == 12
        assert ctx.include_pending_tasks is True
        assert ctx.include_recent_entities is True
        assert ctx.recent_entity_hours == 24
        assert ctx.include_islands is True

    def test_execution_configuration(self):
        """Execution config should match spec defaults."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        exec_cfg = config.execution
        assert exec_cfg.max_research_depth == 2
        assert exec_cfg.parallel_timeout_seconds == 30.0
        assert exec_cfg.fire_and_forget_timeout_seconds == 60.0

    def test_proactive_behavior_configuration(self):
        """Proactive behavior should all be enabled by default."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        behavior = config.proactive_behavior
        assert behavior.suggest_calendar_events is True
        assert behavior.suggest_follow_ups is True
        assert behavior.ask_clarifications is True

    def test_context_config_validation(self):
        """ContextConfig should validate field constraints."""
        # Valid config
        valid = ContextConfig(
            message_window=10,
            summary_hours=6,
            include_pending_tasks=False,
            include_recent_entities=False,
            recent_entity_hours=12,
            include_islands=False,
        )
        assert valid.message_window == 10
        assert valid.summary_hours == 6

        # Invalid: message_window must be > 0
        with pytest.raises(ValueError):
            ContextConfig(message_window=0)

        # Invalid: summary_hours must be > 0
        with pytest.raises(ValueError):
            ContextConfig(summary_hours=0)

        # Invalid: recent_entity_hours must be > 0
        with pytest.raises(ValueError):
            ContextConfig(recent_entity_hours=-1)

    def test_execution_config_validation(self):
        """ExecutionConfig should validate field constraints."""
        # Valid config
        valid = ExecutionConfig(
            max_research_depth=1,
            parallel_timeout_seconds=15.0,
            fire_and_forget_timeout_seconds=30.0,
        )
        assert valid.max_research_depth == 1
        assert valid.parallel_timeout_seconds == 15.0

        # Invalid: max_research_depth must be >= 1
        with pytest.raises(ValueError):
            ExecutionConfig(max_research_depth=0)

        # Invalid: max_research_depth must be <= 5
        with pytest.raises(ValueError):
            ExecutionConfig(max_research_depth=6)

        # Invalid: timeouts must be > 0
        with pytest.raises(ValueError):
            ExecutionConfig(parallel_timeout_seconds=0.0)

    def test_proactive_behavior_config_defaults(self):
        """ProactiveBehaviorConfig should have sensible defaults."""
        config = ProactiveBehaviorConfig()
        assert config.suggest_calendar_events is True
        assert config.suggest_follow_ups is True
        assert config.ask_clarifications is True

        # Allow customization
        custom = ProactiveBehaviorConfig(
            suggest_calendar_events=False,
            suggest_follow_ups=False,
            ask_clarifications=False,
        )
        assert custom.suggest_calendar_events is False
        assert custom.suggest_follow_ups is False
        assert custom.ask_clarifications is False

    def test_config_manager_has_orchestrator_v2(self):
        """ConfigManager should recognize orchestrator_v2."""
        config_manager = ConfigManager()
        assert config_manager.has_config("orchestrator_v2")
        assert "orchestrator_v2" in config_manager.agent_names

    def test_missing_config_uses_defaults(self, tmp_path):
        """If orchestrator_v2.yaml is missing, use default config."""
        # Create empty config directory
        empty_config_dir = tmp_path / "config"
        empty_config_dir.mkdir()

        config_manager = ConfigManager(config_dir=empty_config_dir)
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)

        # Should still work with defaults
        assert config is not None
        assert config.model == "claude-opus-4-5-20251101"
        assert config.context.message_window == 20
        assert config.execution.max_research_depth == 2

    def test_config_reload_detects_changes(self):
        """ConfigManager.reload should detect file changes."""
        config_manager = ConfigManager()

        # Get initial checksum
        initial_checksum = config_manager.get_checksum("orchestrator_v2")
        assert initial_checksum is not None

        # Reload without changes
        changed = config_manager.reload("orchestrator_v2")
        assert not changed, "Reload should return False if file unchanged"

        # Verify checksum hasn't changed
        new_checksum = config_manager.get_checksum("orchestrator_v2")
        assert new_checksum == initial_checksum

    def test_orchestrator_v2_config_structure(self):
        """Orchestrator v2 should have all expected fields."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        # Top-level fields
        assert hasattr(config, "model")
        assert hasattr(config, "synthesis_model")
        assert hasattr(config, "context")
        assert hasattr(config, "execution")
        assert hasattr(config, "proactive_behavior")

        # Context fields
        assert hasattr(config.context, "message_window")
        assert hasattr(config.context, "summary_hours")
        assert hasattr(config.context, "include_pending_tasks")
        assert hasattr(config.context, "include_recent_entities")
        assert hasattr(config.context, "recent_entity_hours")
        assert hasattr(config.context, "include_islands")

        # Execution fields
        assert hasattr(config.execution, "max_research_depth")
        assert hasattr(config.execution, "parallel_timeout_seconds")
        assert hasattr(config.execution, "fire_and_forget_timeout_seconds")

        # Proactive behavior fields
        assert hasattr(config.proactive_behavior, "suggest_calendar_events")
        assert hasattr(config.proactive_behavior, "suggest_follow_ups")
        assert hasattr(config.proactive_behavior, "ask_clarifications")

    def test_all_config_values_accessible(self):
        """All config values should be accessible through dot notation."""
        config_manager = ConfigManager()
        config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)
        assert config is not None

        # Direct access should work
        _ = config.model
        _ = config.synthesis_model
        _ = config.context.message_window
        _ = config.context.summary_hours
        _ = config.execution.max_research_depth
        _ = config.proactive_behavior.suggest_calendar_events
