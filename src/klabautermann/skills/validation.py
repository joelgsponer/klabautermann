"""
Skill validation for Claude Code SKILL.md files.

Validates skill definitions against schema rules and checks for common
issues like invalid names, missing required fields, and unknown dependencies.

Usage:
    from klabautermann.skills.validation import SkillValidator, validate_skill

    # Validate a loaded skill
    validator = SkillValidator()
    result = validator.validate(skill)
    if not result.is_valid:
        for error in result.errors:
            print(f"Error: {error}")

    # Validate a skill file directly
    result = validate_skill_file(Path(".claude/skills/my-skill/SKILL.md"))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.skills.loader import SkillLoader
    from klabautermann.skills.models import LoadedSkill


# ===========================================================================
# Constants
# ===========================================================================

# Maximum skill name length
MAX_NAME_LENGTH = 64

# Valid name pattern: lowercase letters, numbers, and hyphens
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

# Known valid tools that can be used in allowed-tools
KNOWN_TOOLS = frozenset(
    {
        "Read",
        "Write",
        "Edit",
        "Grep",
        "Glob",
        "Bash",
        "Task",
        "WebFetch",
        "WebSearch",
        "NotebookEdit",
        "AskUserQuestion",
    }
)

# Known valid agents for klabautermann-agent
KNOWN_AGENTS = frozenset(
    {
        "ingestor",
        "researcher",
        "executor",
        "archivist",
        "scribe",
    }
)

# Known valid task types for klabautermann-task-type
KNOWN_TASK_TYPES = frozenset(
    {
        "ingest",
        "research",
        "execute",
    }
)

# Known valid Claude models
KNOWN_MODELS = frozenset(
    {
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-sonnet-4-20250514",
        "claude-opus-4-5-20251101",
    }
)


# ===========================================================================
# Result Types
# ===========================================================================


@dataclass
class ValidationError:
    """A single validation error."""

    field: str
    message: str
    severity: str = "error"  # "error" or "warning"

    def __str__(self) -> str:
        """Format as human-readable string."""
        prefix = "WARNING" if self.severity == "warning" else "ERROR"
        return f"[{prefix}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    """Result of validating a skill definition."""

    skill_name: str
    skill_path: Path | None = None
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Whether the skill passed validation (no errors, warnings OK)."""
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        """Whether validation produced any warnings."""
        return len(self.warnings) > 0

    def add_error(self, field: str, message: str) -> None:
        """Add a validation error."""
        self.errors.append(ValidationError(field=field, message=message, severity="error"))

    def add_warning(self, field: str, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append(ValidationError(field=field, message=message, severity="warning"))

    def format_report(self) -> str:
        """Format validation result as a human-readable report."""
        lines = [f"Validation result for skill: {self.skill_name}"]
        if self.skill_path:
            lines.append(f"Path: {self.skill_path}")
        lines.append("")

        if self.is_valid and not self.has_warnings:
            lines.append("OK - No issues found")
        else:
            if self.errors:
                lines.append(f"Errors ({len(self.errors)}):")
                for error in self.errors:
                    lines.append(f"  - {error}")
            if self.warnings:
                lines.append(f"Warnings ({len(self.warnings)}):")
                for warning in self.warnings:
                    lines.append(f"  - {warning}")

        return "\n".join(lines)


# ===========================================================================
# Validator
# ===========================================================================


class SkillValidator:
    """
    Validates skill definitions against schema and dependency rules.

    Checks:
    - Name format (lowercase, hyphens, max 64 chars)
    - Required fields (name, description)
    - Description quality (min length, contains trigger phrases)
    - Tool references (warns if unknown)
    - Agent references (warns if unknown)
    - Model references (warns if unknown)
    - Orchestrator config completeness (task_type requires agent)
    - Payload schema validity
    """

    def __init__(
        self,
        *,
        strict: bool = False,
        known_tools: frozenset[str] | None = None,
        known_agents: frozenset[str] | None = None,
        known_models: frozenset[str] | None = None,
    ) -> None:
        """
        Initialize validator.

        Args:
            strict: If True, treat warnings as errors.
            known_tools: Custom set of known tools. Defaults to KNOWN_TOOLS.
            known_agents: Custom set of known agents. Defaults to KNOWN_AGENTS.
            known_models: Custom set of known models. Defaults to KNOWN_MODELS.
        """
        self.strict = strict
        self.known_tools = known_tools or KNOWN_TOOLS
        self.known_agents = known_agents or KNOWN_AGENTS
        self.known_models = known_models or KNOWN_MODELS

    def validate(self, skill: LoadedSkill) -> ValidationResult:
        """
        Validate a loaded skill definition.

        Args:
            skill: Loaded skill to validate.

        Returns:
            ValidationResult with errors and warnings.
        """
        result = ValidationResult(
            skill_name=skill.name,
            skill_path=skill.path,
        )

        # Validate metadata
        self._validate_name(skill, result)
        self._validate_description(skill, result)
        self._validate_allowed_tools(skill, result)
        self._validate_model(skill, result)

        # Validate klabautermann config
        self._validate_orchestrator_config(skill, result)
        self._validate_payload_schema(skill, result)

        # Validate body
        self._validate_body(skill, result)

        # In strict mode, promote warnings to errors
        if self.strict:
            result.errors.extend(result.warnings)
            result.warnings = []

        # Log validation result
        if result.is_valid:
            logger.debug(
                "[WHISPER] Skill validation passed",
                extra={"skill": skill.name},
            )
        else:
            logger.warning(
                "[SWELL] Skill validation failed",
                extra={
                    "skill": skill.name,
                    "error_count": len(result.errors),
                    "warning_count": len(result.warnings),
                },
            )

        return result

    def _validate_name(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate skill name format."""
        name = skill.name

        # Check length
        if len(name) > MAX_NAME_LENGTH:
            result.add_error(
                "name",
                f"Name too long ({len(name)} chars, max {MAX_NAME_LENGTH})",
            )

        # Check format
        if not NAME_PATTERN.match(name):
            result.add_error(
                "name",
                "Name must be lowercase, start with a letter, and contain only "
                "letters, numbers, and hyphens",
            )

        # Warn about very short names
        if len(name) < 3:
            result.add_warning(
                "name",
                "Name is very short - consider using a more descriptive name",
            )

    def _validate_description(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate skill description quality."""
        description = skill.description

        # Check minimum length
        if len(description) < 10:
            result.add_error(
                "description",
                "Description too short (min 10 chars) - describe what the skill does",
            )

        # Warn if no trigger phrases
        trigger_indicators = ["when", "use when", "use for", "triggers on", "say"]
        has_trigger = any(indicator in description.lower() for indicator in trigger_indicators)
        if not has_trigger:
            result.add_warning(
                "description",
                "Description should include trigger phrases (e.g., 'Use when user asks...')",
            )

    def _validate_allowed_tools(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate allowed-tools references."""
        allowed_tools = skill.metadata.allowed_tools
        if not allowed_tools:
            return

        # Normalize to list
        if isinstance(allowed_tools, str):
            tools = [t.strip() for t in allowed_tools.split(",")]
        else:
            tools = allowed_tools

        # Check each tool
        for tool in tools:
            if tool not in self.known_tools:
                result.add_warning(
                    "allowed-tools",
                    f"Unknown tool '{tool}' - verify it exists",
                )

    def _validate_model(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate model reference."""
        model = skill.metadata.model
        if not model:
            return

        if model not in self.known_models:
            result.add_warning(
                "model",
                f"Unknown model '{model}' - verify it's a valid Claude model ID",
            )

    def _validate_orchestrator_config(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate klabautermann orchestrator config consistency."""
        config = skill.klabautermann

        # If task_type is set, agent should be set too
        if config.task_type and not config.agent:
            result.add_error(
                "klabautermann-agent",
                f"klabautermann-task-type is '{config.task_type}' but klabautermann-agent is missing",
            )

        # If agent is set, task_type should be set too
        if config.agent and not config.task_type:
            result.add_error(
                "klabautermann-task-type",
                f"klabautermann-agent is '{config.agent}' but klabautermann-task-type is missing",
            )

        # Validate task_type value
        if config.task_type and config.task_type not in KNOWN_TASK_TYPES:
            result.add_error(
                "klabautermann-task-type",
                f"Unknown task type '{config.task_type}' - must be one of: {', '.join(sorted(KNOWN_TASK_TYPES))}",
            )

        # Validate agent value
        if config.agent and config.agent not in self.known_agents:
            result.add_warning(
                "klabautermann-agent",
                f"Unknown agent '{config.agent}' - verify it exists",
            )

        # Validate task_type and agent consistency
        if config.task_type and config.agent:
            expected_agents = {
                "ingest": "ingestor",
                "research": "researcher",
                "execute": "executor",
            }
            expected = expected_agents.get(config.task_type)
            if expected and config.agent != expected:
                result.add_warning(
                    "klabautermann-agent",
                    f"Task type '{config.task_type}' typically uses agent '{expected}', not '{config.agent}'",
                )

        # Warn if requires-confirmation is set without execute task type
        if config.requires_confirmation and config.task_type != "execute":
            result.add_warning(
                "klabautermann-requires-confirmation",
                "requires-confirmation is typically only used with task-type 'execute'",
            )

    def _validate_payload_schema(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate payload schema if present."""
        if not skill.klabautermann.payload_schema:
            return

        try:
            fields = skill.klabautermann.get_payload_fields()

            # Check for at least one field if schema is defined
            if not fields:
                result.add_warning(
                    "klabautermann-payload-schema",
                    "Payload schema is defined but empty",
                )
                return

            # Validate each field
            for field_name, field_def in fields.items():
                # Warn about missing descriptions
                if not field_def.description:
                    result.add_warning(
                        f"klabautermann-payload-schema.{field_name}",
                        "Field is missing description - add one to improve extraction",
                    )

                # Validate field name format
                if not re.match(r"^[a-z_][a-z0-9_]*$", field_name):
                    result.add_warning(
                        f"klabautermann-payload-schema.{field_name}",
                        "Field name should be lowercase with underscores",
                    )

        except Exception as e:
            result.add_error(
                "klabautermann-payload-schema",
                f"Failed to parse payload schema: {e}",
            )

    def _validate_body(self, skill: LoadedSkill, result: ValidationResult) -> None:
        """Validate markdown body content."""
        body = skill.body

        # Check for minimum content
        if len(body) < 50:
            result.add_warning(
                "body",
                "Skill body is very short - consider adding instructions and examples",
            )

        # Check for common sections
        has_instructions = "instruction" in body.lower() or "## " in body
        if not has_instructions:
            result.add_warning(
                "body",
                "Skill body should include instructions (use ## headers)",
            )


# ===========================================================================
# Convenience Functions
# ===========================================================================


def validate_skill(skill: LoadedSkill, *, strict: bool = False) -> ValidationResult:
    """
    Validate a loaded skill with default settings.

    Args:
        skill: Loaded skill to validate.
        strict: If True, treat warnings as errors.

    Returns:
        ValidationResult with errors and warnings.
    """
    validator = SkillValidator(strict=strict)
    return validator.validate(skill)


def validate_skill_file(
    skill_file: Path,
    *,
    strict: bool = False,
) -> ValidationResult:
    """
    Validate a skill file directly.

    Args:
        skill_file: Path to SKILL.md file.
        strict: If True, treat warnings as errors.

    Returns:
        ValidationResult with errors and warnings.
    """
    from klabautermann.skills.loader import SkillLoader

    # Create a temporary loader to parse the file
    loader = SkillLoader(
        project_skills_dir=skill_file.parent.parent,
        personal_skills_dir=Path("/nonexistent"),
    )

    try:
        skill = loader._load_skill(skill_file)
    except Exception as e:
        # Return result with parse error
        result = ValidationResult(
            skill_name=skill_file.parent.name,
            skill_path=skill_file,
        )
        result.add_error("frontmatter", f"Failed to parse skill file: {e}")
        return result

    return validate_skill(skill, strict=strict)


def validate_all_skills(
    loader: SkillLoader,
    *,
    strict: bool = False,
) -> dict[str, ValidationResult]:
    """
    Validate all loaded skills.

    Args:
        loader: SkillLoader with skills loaded.
        strict: If True, treat warnings as errors.

    Returns:
        Dict mapping skill name to ValidationResult.
    """
    from klabautermann.skills.loader import SkillLoader

    if not isinstance(loader, SkillLoader):
        raise TypeError("loader must be a SkillLoader instance")

    # Ensure skills are loaded
    loader.load_all()

    validator = SkillValidator(strict=strict)
    results = {}

    for skill_name in loader.list_skills():
        skill = loader.get(skill_name)
        if skill:
            results[skill_name] = validator.validate(skill)

    return results
