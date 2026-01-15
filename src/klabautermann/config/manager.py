"""
Agent Configuration Manager for Klabautermann.

Loads, validates, and provides typed access to agent configurations from YAML files.
Supports hot-reload via checksum tracking.

Reference: specs/architecture/AGENTS.md Section 4
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field

from klabautermann.core.logger import logger


# ===========================================================================
# Configuration Models
# ===========================================================================


class ModelConfig(BaseModel):
    """LLM model configuration."""

    model_config = ConfigDict(extra="forbid")

    primary: str = "claude-sonnet-4-20250514"
    fallback: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_context_tokens: int = Field(default=8000, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)


class PersonalityConfig(BaseModel):
    """Personality configuration for response formatting."""

    model_config = ConfigDict(extra="forbid")

    name: str = "klabautermann"
    wit_level: float = Field(default=0.3, ge=0.0, le=1.0)


class IntentConfig(BaseModel):
    """Intent classification keyword configuration."""

    model_config = ConfigDict(extra="forbid")

    search_keywords: list[str] = Field(default_factory=list)
    action_keywords: list[str] = Field(default_factory=list)
    ingestion_keywords: list[str] = Field(default_factory=list)


class DelegationConfig(BaseModel):
    """Agent delegation mappings."""

    model_config = ConfigDict(extra="forbid")

    search: str = "researcher"
    action: str = "executor"
    ingest: str = "ingestor"


class TimeoutConfig(BaseModel):
    """Timeout configuration in seconds."""

    model_config = ConfigDict(extra="forbid")

    agent_response: float = Field(default=30.0, gt=0.0)
    llm_call: float = Field(default=60.0, gt=0.0)
    mcp_call: float = Field(default=30.0, gt=0.0)


class RetryConfig(BaseModel):
    """Retry configuration for external calls."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    base_delay: float = Field(default=1.0, gt=0.0)
    max_delay: float = Field(default=30.0, gt=0.0)
    jitter: float = Field(default=0.25, ge=0.0, le=1.0)


class ExtractionConfig(BaseModel):
    """Entity extraction configuration for Ingestor."""

    model_config = ConfigDict(extra="forbid")

    entity_types: list[str] = Field(
        default_factory=lambda: [
            "Person",
            "Organization",
            "Project",
            "Goal",
            "Task",
            "Event",
            "Location",
        ]
    )
    relationship_types: list[str] = Field(
        default_factory=lambda: [
            "WORKS_AT",
            "PART_OF",
            "CONTRIBUTES_TO",
            "ATTENDED",
            "HELD_AT",
            "BLOCKS",
            "MENTIONED_IN",
        ]
    )
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class SearchConfig(BaseModel):
    """Search configuration for Researcher."""

    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(default=10, ge=1)
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    use_vector_search: bool = True
    use_graph_traversal: bool = True
    max_hops: int = Field(default=2, ge=1, le=5)


class ToolsConfig(BaseModel):
    """Tools configuration for Executor."""

    model_config = ConfigDict(extra="forbid")

    enabled_tools: list[str] = Field(default_factory=lambda: ["gmail", "calendar", "filesystem"])
    require_confirmation: bool = True
    dry_run: bool = False


# ===========================================================================
# Agent Configuration Models
# ===========================================================================


class AgentConfigBase(BaseModel):
    """Base configuration for all agents."""

    model_config = ConfigDict(extra="allow")

    model: ModelConfig = Field(default_factory=ModelConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


class OrchestratorConfig(AgentConfigBase):
    """Orchestrator-specific configuration."""

    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    intent_classification: IntentConfig = Field(default_factory=IntentConfig)
    delegation: DelegationConfig = Field(default_factory=DelegationConfig)


class IngestorConfig(AgentConfigBase):
    """Ingestor-specific configuration."""

    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)


class ResearcherConfig(AgentConfigBase):
    """Researcher-specific configuration."""

    search: SearchConfig = Field(default_factory=SearchConfig)


class ExecutorConfig(AgentConfigBase):
    """Executor-specific configuration."""

    tools: ToolsConfig = Field(default_factory=ToolsConfig)


# ===========================================================================
# Configuration Manager
# ===========================================================================

T = TypeVar("T", bound=BaseModel)


class ConfigManager:
    """
    Manages agent configuration from YAML files.

    Loads, validates, and provides typed access to configs.
    Supports hot-reload via checksum tracking.

    Usage:
        config_manager = ConfigManager(Path("config/agents"))
        orchestrator_config = config_manager.get_typed("orchestrator", OrchestratorConfig)
        print(orchestrator_config.intent_classification.search_keywords)
    """

    CONFIG_CLASSES: dict[str, type[AgentConfigBase]] = {
        "orchestrator": OrchestratorConfig,
        "ingestor": IngestorConfig,
        "researcher": ResearcherConfig,
        "executor": ExecutorConfig,
    }

    def __init__(self, config_dir: Path | str | None = None) -> None:
        """
        Initialize config manager.

        Args:
            config_dir: Directory containing agent YAML files.
                        Defaults to 'config/agents' in project root.
        """
        if config_dir is None:
            # Default to project root config/agents
            config_dir = Path(__file__).parent.parent.parent.parent / "config" / "agents"
        self.config_dir = Path(config_dir)
        self._configs: dict[str, AgentConfigBase] = {}
        self._checksums: dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all configuration files."""
        if not self.config_dir.exists():
            logger.warning(
                f"[SWELL] Config directory not found: {self.config_dir}. Using defaults."
            )
            # Create default configs for all known agents
            for agent_name, config_class in self.CONFIG_CLASSES.items():
                self._configs[agent_name] = config_class()
            return

        # Load from YAML files
        for yaml_file in self.config_dir.glob("*.yaml"):
            agent_name = yaml_file.stem
            try:
                self._load_config(agent_name, yaml_file)
            except Exception as e:
                logger.error(f"[STORM] Failed to load config {yaml_file}: {e}")
                raise

        # Create defaults for missing agents
        for agent_name, config_class in self.CONFIG_CLASSES.items():
            if agent_name not in self._configs:
                logger.debug(f"[WHISPER] Using default config for {agent_name}")
                self._configs[agent_name] = config_class()

    def _load_config(self, agent_name: str, yaml_file: Path) -> None:
        """
        Load a single configuration file.

        Args:
            agent_name: Name of the agent.
            yaml_file: Path to the YAML file.
        """
        content = yaml_file.read_text()
        checksum = hashlib.md5(content.encode()).hexdigest()

        # Parse YAML
        data = yaml.safe_load(content) or {}

        # Get config class (fall back to base if unknown agent)
        config_class = self.CONFIG_CLASSES.get(agent_name, AgentConfigBase)

        # Validate and store
        config = config_class(**data)
        self._configs[agent_name] = config
        self._checksums[agent_name] = checksum

        logger.debug(
            f"[WHISPER] Loaded config for {agent_name}",
            extra={"agent_name": agent_name, "checksum": checksum[:8]},
        )

    def get(self, agent_name: str) -> AgentConfigBase | None:
        """
        Get configuration for an agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            Agent configuration or None if not found.
        """
        return self._configs.get(agent_name)

    def get_typed(self, agent_name: str, config_type: type[T]) -> T | None:
        """
        Get typed configuration for an agent.

        Args:
            agent_name: Name of the agent.
            config_type: Expected config class.

        Returns:
            Typed agent configuration or None.
        """
        config = self._configs.get(agent_name)
        if config and isinstance(config, config_type):
            return config
        return None

    def get_checksum(self, agent_name: str) -> str | None:
        """
        Get checksum for an agent's config file.

        Used for hot-reload detection.

        Args:
            agent_name: Name of the agent.

        Returns:
            MD5 checksum of config file or None.
        """
        return self._checksums.get(agent_name)

    def reload(self, agent_name: str) -> bool:
        """
        Reload a specific agent's configuration.

        Args:
            agent_name: Name of the agent to reload.

        Returns:
            True if config changed, False otherwise.
        """
        yaml_file = self.config_dir / f"{agent_name}.yaml"
        if not yaml_file.exists():
            return False

        content = yaml_file.read_text()
        new_checksum = hashlib.md5(content.encode()).hexdigest()

        if new_checksum == self._checksums.get(agent_name):
            return False  # No change

        self._load_config(agent_name, yaml_file)
        logger.info(
            f"[CHART] Reloaded config for {agent_name}",
            extra={"agent_name": agent_name},
        )
        return True

    def reload_all(self) -> dict[str, bool]:
        """
        Reload all configurations.

        Returns:
            Dict mapping agent name to whether config changed.
        """
        results = {}
        for agent_name in list(self._configs.keys()):
            results[agent_name] = self.reload(agent_name)
        return results

    @property
    def agent_names(self) -> list[str]:
        """Get list of configured agent names."""
        return list(self._configs.keys())

    def has_config(self, agent_name: str) -> bool:
        """Check if config exists for an agent."""
        return agent_name in self._configs


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "ConfigManager",
    "AgentConfigBase",
    "ModelConfig",
    "PersonalityConfig",
    "IntentConfig",
    "DelegationConfig",
    "TimeoutConfig",
    "RetryConfig",
    "OrchestratorConfig",
    "IngestorConfig",
    "ResearcherConfig",
    "ExecutorConfig",
    "ExtractionConfig",
    "SearchConfig",
    "ToolsConfig",
]
