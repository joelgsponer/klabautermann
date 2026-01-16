"""
Pydantic models for Claude Code skill definitions.

These models parse and validate SKILL.md files that use the standard
Claude Code format with custom klabautermann-* fields for orchestrator
integration.

Reference: https://docs.anthropic.com/en/docs/claude-code/skills
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


if TYPE_CHECKING:
    from pathlib import Path


class PayloadField(BaseModel):
    """Schema for a single payload field in skill config."""

    model_config = ConfigDict(extra="allow")

    type: Literal["string", "boolean", "number", "array", "object"] = "string"
    required: bool = False
    default: Any | None = None
    extract_from: Literal["user-message", "context", "prompt"] = "user-message"
    description: str | None = None


class SkillMetadata(BaseModel):
    """
    Standard Claude Code skill metadata from YAML frontmatter.

    These fields are recognized by Claude Code for skill discovery
    and invocation.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Skill identifier (lowercase, hyphens, max 64 chars)")
    description: str = Field(description="What the skill does and when to use it")
    allowed_tools: list[str] | str | None = Field(
        default=None,
        alias="allowed-tools",
        description="Tools Claude can use without asking",
    )
    model: str | None = Field(
        default=None,
        description="Claude model to use when skill is active",
    )
    context: Literal["fork"] | None = Field(
        default=None,
        description="Set to 'fork' for isolated sub-agent context",
    )
    agent: str | None = Field(
        default=None,
        description="Agent type when context=fork",
    )
    user_invocable: bool = Field(
        default=True,
        alias="user-invocable",
        description="Show in slash command menu",
    )


class KlabautermannSkillConfig(BaseModel):
    """
    Custom klabautermann-* fields for orchestrator integration.

    These fields map the skill to Klabautermann's task planning system,
    enabling automatic conversion to PlannedTask objects.
    """

    model_config = ConfigDict(extra="allow")

    task_type: Literal["ingest", "research", "execute"] | None = Field(
        default=None,
        alias="klabautermann-task-type",
        description="Maps to PlannedTask.task_type",
    )
    agent: Literal["ingestor", "researcher", "executor"] | None = Field(
        default=None,
        alias="klabautermann-agent",
        description="Maps to PlannedTask.agent",
    )
    blocking: bool = Field(
        default=True,
        alias="klabautermann-blocking",
        description="Whether orchestrator waits for result",
    )
    payload_schema: dict[str, PayloadField | dict[str, Any]] | None = Field(
        default=None,
        alias="klabautermann-payload-schema",
        description="Schema for extracting payload from user message",
    )
    requires_confirmation: bool = Field(
        default=False,
        alias="klabautermann-requires-confirmation",
        description="Whether to confirm before execution",
    )

    def get_payload_fields(self) -> dict[str, PayloadField]:
        """Parse payload schema into PayloadField objects."""
        if not self.payload_schema:
            return {}

        result = {}
        for name, field_def in self.payload_schema.items():
            if isinstance(field_def, PayloadField):
                result[name] = field_def
            elif isinstance(field_def, dict):
                result[name] = PayloadField(**field_def)
        return result


class LoadedSkill(BaseModel):
    """
    Complete loaded skill with metadata, config, and content.

    Combines standard Claude Code metadata with Klabautermann-specific
    configuration and the full markdown body.
    """

    model_config = ConfigDict(extra="allow")

    # Standard Claude Code fields
    metadata: SkillMetadata

    # Klabautermann orchestrator fields
    klabautermann: KlabautermannSkillConfig

    # Full content
    body: str = Field(description="Markdown body after frontmatter")
    path: Path = Field(description="Path to SKILL.md file")

    @property
    def name(self) -> str:
        """Skill name for indexing."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Skill description for matching."""
        return self.metadata.description

    @property
    def is_orchestrator_enabled(self) -> bool:
        """Whether this skill has Klabautermann integration configured."""
        return self.klabautermann.task_type is not None and self.klabautermann.agent is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "task_type": self.klabautermann.task_type,
            "agent": self.klabautermann.agent,
            "blocking": self.klabautermann.blocking,
            "path": str(self.path),
        }


class SkillRegistry(BaseModel):
    """Registry of loaded skills indexed by name."""

    model_config = ConfigDict(extra="allow")

    skills: dict[str, LoadedSkill] = Field(default_factory=dict)

    def add(self, skill: LoadedSkill) -> None:
        """Add a skill to the registry."""
        self.skills[skill.name] = skill

    def get(self, name: str) -> LoadedSkill | None:
        """Get skill by name."""
        return self.skills.get(name)

    def list_names(self) -> list[str]:
        """List all skill names."""
        return list(self.skills.keys())

    def list_orchestrator_enabled(self) -> list[LoadedSkill]:
        """List skills with Klabautermann integration."""
        return [s for s in self.skills.values() if s.is_orchestrator_enabled]

    def get_descriptions(self) -> dict[str, str]:
        """Get skill name to description mapping."""
        return {name: skill.description for name, skill in self.skills.items()}
