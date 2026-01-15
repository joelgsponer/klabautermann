# Create Agent Configuration System

## Metadata
- **ID**: T032
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: completed
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 4
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [x] T003 - Project structure

## Context
Each agent needs configurable parameters (model, temperature, prompts, keywords). This task creates a YAML-based configuration system that allows tuning agent behavior without code changes. This is the foundation for the hot-reload system (T033).

## Requirements
- [x] Create configuration infrastructure:

### Directory Structure
- [x] Create `config/agents/` directory
- [x] One YAML file per agent:
  - `orchestrator.yaml`
  - `ingestor.yaml`
  - `researcher.yaml`
  - `executor.yaml`

### Configuration Schema
- [x] Model settings (model name, fallback, temperature)
- [x] Token limits (max_context, max_output)
- [x] Intent classification keywords
- [x] Delegation mappings
- [x] Timeout settings
- [x] Retry configuration

### Config Manager
- [x] Create `src/klabautermann/config/manager.py`
- [x] Load all configs on startup
- [x] Validate configs against schema
- [x] Provide typed access to configs

### Pydantic Models
- [x] `AgentConfig` base model
- [x] Agent-specific config models
- [x] Validation with helpful errors

## Acceptance Criteria
- [x] All agent configs defined in YAML
- [x] Configs validated on load
- [x] Invalid config raises clear error
- [x] Configs accessible via typed interface
- [x] Missing optional fields use defaults

## Implementation Notes

### Config Schema

```yaml
# config/agents/orchestrator.yaml
model:
  primary: claude-3-5-sonnet-20241022
  fallback: claude-3-haiku-20240307
  temperature: 0.7
  max_context_tokens: 8000
  max_output_tokens: 4096

personality:
  name: klabautermann
  wit_level: 0.3  # 0.0 = terse, 1.0 = very witty

intent_classification:
  search_keywords:
    - "who"
    - "what"
    - "when"
    - "where"
    - "find"
    - "tell me about"
    - "remind me"
  action_keywords:
    - "send"
    - "email"
    - "schedule"
    - "create"
    - "draft"
    - "book"
  ingestion_keywords:
    - "i met"
    - "i talked to"
    - "i'm working on"
    - "i learned"

delegation:
  search: researcher
  action: executor
  ingest: ingestor

timeouts:
  agent_response: 30.0
  llm_call: 60.0

retry:
  max_attempts: 3
  base_delay: 1.0
  max_delay: 30.0
```

```yaml
# config/agents/ingestor.yaml
model:
  primary: claude-3-haiku-20240307
  temperature: 0.3
  max_output_tokens: 1024

extraction:
  entity_types:
    - Person
    - Organization
    - Project
    - Goal
    - Task
    - Event
    - Location
  relationship_types:
    - WORKS_AT
    - PART_OF
    - CONTRIBUTES_TO
    - ATTENDED
    - HELD_AT
    - BLOCKS
    - MENTIONED_IN
```

### Config Manager Implementation

```python
from pathlib import Path
from typing import Dict, Any, Optional, Type, TypeVar
import yaml
from pydantic import BaseModel, Field, validator
import hashlib

from klabautermann.core.logger import logger


# ====================
# CONFIG MODELS
# ====================

class ModelConfig(BaseModel):
    """LLM model configuration."""
    primary: str
    fallback: Optional[str] = None
    temperature: float = 0.7
    max_context_tokens: int = 8000
    max_output_tokens: int = 4096


class PersonalityConfig(BaseModel):
    """Personality configuration."""
    name: str = "klabautermann"
    wit_level: float = Field(default=0.3, ge=0.0, le=1.0)


class IntentConfig(BaseModel):
    """Intent classification configuration."""
    search_keywords: list[str] = Field(default_factory=list)
    action_keywords: list[str] = Field(default_factory=list)
    ingestion_keywords: list[str] = Field(default_factory=list)


class DelegationConfig(BaseModel):
    """Agent delegation mappings."""
    search: str = "researcher"
    action: str = "executor"
    ingest: str = "ingestor"


class TimeoutConfig(BaseModel):
    """Timeout configuration."""
    agent_response: float = 30.0
    llm_call: float = 60.0


class RetryConfig(BaseModel):
    """Retry configuration."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


class AgentConfig(BaseModel):
    """Base agent configuration."""
    model: ModelConfig
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


class OrchestratorConfig(AgentConfig):
    """Orchestrator-specific configuration."""
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    intent_classification: IntentConfig = Field(default_factory=IntentConfig)
    delegation: DelegationConfig = Field(default_factory=DelegationConfig)


class IngestorConfig(AgentConfig):
    """Ingestor-specific configuration."""
    extraction: Dict[str, list[str]] = Field(default_factory=dict)


class ResearcherConfig(AgentConfig):
    """Researcher-specific configuration."""
    search: Dict[str, Any] = Field(default_factory=dict)


class ExecutorConfig(AgentConfig):
    """Executor-specific configuration."""
    tools: Dict[str, Any] = Field(default_factory=dict)


# ====================
# CONFIG MANAGER
# ====================

T = TypeVar("T", bound=BaseModel)


class ConfigManager:
    """
    Manages agent configuration from YAML files.

    Loads, validates, and provides typed access to configs.
    Supports hot-reload via checksum tracking.
    """

    CONFIG_CLASSES: Dict[str, Type[AgentConfig]] = {
        "orchestrator": OrchestratorConfig,
        "ingestor": IngestorConfig,
        "researcher": ResearcherConfig,
        "executor": ExecutorConfig,
    }

    def __init__(self, config_dir: Path):
        """
        Initialize config manager.

        Args:
            config_dir: Directory containing agent YAML files.
        """
        self.config_dir = Path(config_dir)
        self._configs: Dict[str, AgentConfig] = {}
        self._checksums: Dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all configuration files."""
        if not self.config_dir.exists():
            logger.warning(f"[SWELL] Config directory not found: {self.config_dir}")
            return

        for yaml_file in self.config_dir.glob("*.yaml"):
            agent_name = yaml_file.stem
            try:
                self._load_config(agent_name, yaml_file)
            except Exception as e:
                logger.error(f"[STORM] Failed to load config {yaml_file}: {e}")
                raise

    def _load_config(self, agent_name: str, yaml_file: Path) -> None:
        """Load a single configuration file."""
        content = yaml_file.read_text()
        checksum = hashlib.md5(content.encode()).hexdigest()

        # Parse YAML
        data = yaml.safe_load(content) or {}

        # Get config class
        config_class = self.CONFIG_CLASSES.get(agent_name, AgentConfig)

        # Validate and store
        config = config_class(**data)
        self._configs[agent_name] = config
        self._checksums[agent_name] = checksum

        logger.debug(f"[WHISPER] Loaded config for {agent_name}")

    def get(self, agent_name: str) -> Optional[AgentConfig]:
        """
        Get configuration for an agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            Agent configuration or None if not found.
        """
        return self._configs.get(agent_name)

    def get_typed(self, agent_name: str, config_type: Type[T]) -> Optional[T]:
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

    def get_checksum(self, agent_name: str) -> Optional[str]:
        """Get checksum for an agent's config."""
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
            return False

        self._load_config(agent_name, yaml_file)
        logger.info(f"[CHART] Reloaded config for {agent_name}")
        return True

    def reload_all(self) -> Dict[str, bool]:
        """
        Reload all configurations.

        Returns:
            Dict mapping agent name to whether config changed.
        """
        results = {}
        for agent_name in self._configs.keys():
            results[agent_name] = self.reload(agent_name)
        return results

    @property
    def agent_names(self) -> list[str]:
        """Get list of configured agent names."""
        return list(self._configs.keys())


# Usage example:
# config_manager = ConfigManager(Path("config/agents"))
# orchestrator_config = config_manager.get_typed("orchestrator", OrchestratorConfig)
# print(orchestrator_config.intent_classification.search_keywords)
```

Create default YAML files for each agent during setup.

## Development Notes

**Files Created:**
- `src/klabautermann/config/__init__.py` - Module exports
- `src/klabautermann/config/manager.py` - ConfigManager and Pydantic models
- `config/agents/orchestrator.yaml` - Orchestrator configuration
- `config/agents/ingestor.yaml` - Ingestor configuration
- `config/agents/researcher.yaml` - Researcher configuration
- `config/agents/executor.yaml` - Executor configuration
- `tests/unit/test_config_manager.py` - 22 unit tests

**Implementation Details:**
- Pydantic models with validation for all config fields
- ConfigManager with YAML loading and typed access
- Checksum-based hot-reload detection
- Graceful defaults when config files missing
- Agent-specific config models (OrchestratorConfig, IngestorConfig, etc.)

**Testing:**
- All 22 unit tests pass
- Tests cover: validation, loading, typed access, reload, missing configs

**Patterns Established:**
- YAML config in `config/agents/<agent>.yaml`
- `ConfigManager.get_typed()` for typed config access
- Checksum tracking for hot-reload detection
