"""
Skill loader for Claude Code SKILL.md files.

Discovers and parses skill definitions from .claude/skills/ directories,
extracting both standard Claude Code metadata and custom klabautermann-*
fields for orchestrator integration.

Usage:
    loader = SkillLoader()
    loader.load_all()

    skill = loader.get("lookup-person")
    if skill and skill.is_orchestrator_enabled:
        # Use skill.klabautermann config for task planning
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from klabautermann.core.logger import logger
from klabautermann.skills.models import (
    KlabautermannSkillConfig,
    LoadedSkill,
    SkillMetadata,
    SkillRegistry,
)


class SkillLoader:
    """
    Loads and manages Claude Code skill definitions.

    Discovers SKILL.md files in standard locations:
    - .claude/skills/ (project skills)
    - ~/.claude/skills/ (personal skills)

    Parses YAML frontmatter and extracts both standard Claude Code
    fields and custom klabautermann-* fields.
    """

    SKILL_FILENAME = "SKILL.md"

    def __init__(
        self,
        project_skills_dir: Path | str | None = None,
        personal_skills_dir: Path | str | None = None,
    ) -> None:
        """
        Initialize skill loader.

        Args:
            project_skills_dir: Project .claude/skills/ directory.
                              Defaults to .claude/skills/ in cwd.
            personal_skills_dir: Personal ~/.claude/skills/ directory.
                               Defaults to ~/.claude/skills/.
        """
        self.project_dir = (
            Path(project_skills_dir) if project_skills_dir else Path.cwd() / ".claude" / "skills"
        )
        self.personal_dir = (
            Path(personal_skills_dir) if personal_skills_dir else Path.home() / ".claude" / "skills"
        )
        self.registry = SkillRegistry()
        self._loaded = False

    def load_all(self) -> SkillRegistry:
        """
        Load all skills from configured directories.

        Returns:
            SkillRegistry with all loaded skills.
        """
        if self._loaded:
            return self.registry

        # Load from both directories (project takes precedence)
        self._load_from_directory(self.personal_dir)
        self._load_from_directory(self.project_dir)

        self._loaded = True
        logger.info(
            "[CHART] Loaded skills",
            extra={"count": len(self.registry.skills)},
        )
        return self.registry

    def reload(self) -> SkillRegistry:
        """Force reload all skills."""
        self.registry = SkillRegistry()
        self._loaded = False
        return self.load_all()

    def _load_from_directory(self, skills_dir: Path) -> None:
        """Load skills from a directory."""
        if not skills_dir.exists():
            logger.debug(
                "[WHISPER] Skills directory not found",
                extra={"path": str(skills_dir)},
            )
            return

        for skill_path in skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / self.SKILL_FILENAME
            if not skill_file.exists():
                continue

            try:
                skill = self._load_skill(skill_file)
                self.registry.add(skill)
                logger.debug(
                    "[WHISPER] Loaded skill",
                    extra={
                        "name": skill.name,
                        "orchestrator_enabled": skill.is_orchestrator_enabled,
                    },
                )
            except Exception as e:
                logger.warning(
                    "[SWELL] Failed to load skill",
                    extra={"path": str(skill_file), "error": str(e)},
                )

    def _load_skill(self, skill_file: Path) -> LoadedSkill:
        """
        Load a single skill from SKILL.md file.

        Args:
            skill_file: Path to SKILL.md file.

        Returns:
            LoadedSkill with parsed metadata and content.
        """
        content = skill_file.read_text(encoding="utf-8")

        # Parse frontmatter and body
        frontmatter, body = self._parse_frontmatter(content)

        # Extract standard metadata
        metadata = SkillMetadata(**frontmatter)

        # Extract klabautermann-* fields
        klabautermann_data = self._extract_klabautermann_fields(frontmatter)
        klabautermann = KlabautermannSkillConfig(**klabautermann_data)

        return LoadedSkill(
            metadata=metadata,
            klabautermann=klabautermann,
            body=body,
            path=skill_file,
        )

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """
        Parse YAML frontmatter from markdown content.

        Args:
            content: Full SKILL.md content.

        Returns:
            Tuple of (frontmatter dict, markdown body).
        """
        # Match frontmatter between --- markers
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            raise ValueError("Invalid SKILL.md format: missing frontmatter")

        frontmatter_str = match.group(1)
        body = match.group(2).strip()

        frontmatter = yaml.safe_load(frontmatter_str) or {}
        return frontmatter, body

    def _extract_klabautermann_fields(self, frontmatter: dict[str, Any]) -> dict[str, Any]:
        """
        Extract klabautermann-* fields from frontmatter.

        Converts kebab-case field names to the aliased format
        expected by KlabautermannSkillConfig.

        Args:
            frontmatter: Parsed YAML frontmatter.

        Returns:
            Dict with klabautermann-* fields.
        """
        result = {}
        for key, value in frontmatter.items():
            if key.startswith("klabautermann-"):
                result[key] = value
        return result

    def get(self, name: str) -> LoadedSkill | None:
        """
        Get a skill by name.

        Args:
            name: Skill name.

        Returns:
            LoadedSkill or None if not found.
        """
        if not self._loaded:
            self.load_all()
        return self.registry.get(name)

    def list_skills(self) -> list[str]:
        """List all loaded skill names."""
        if not self._loaded:
            self.load_all()
        return self.registry.list_names()

    def get_orchestrator_skills(self) -> list[LoadedSkill]:
        """Get skills with Klabautermann integration enabled."""
        if not self._loaded:
            self.load_all()
        return self.registry.list_orchestrator_enabled()
