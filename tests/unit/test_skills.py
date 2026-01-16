"""
Unit tests for the skills package.

Tests skill loading, parsing, and orchestrator integration.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from klabautermann.skills.loader import SkillLoader
from klabautermann.skills.models import (
    KlabautermannSkillConfig,
    LoadedSkill,
    PayloadField,
    SkillMetadata,
    SkillRegistry,
)
from klabautermann.skills.planner import SkillAwarePlanner


class TestSkillMetadata:
    """Tests for SkillMetadata model."""

    def test_basic_metadata(self) -> None:
        """Test parsing basic metadata fields."""
        metadata = SkillMetadata(
            name="test-skill",
            description="A test skill for testing",
        )
        assert metadata.name == "test-skill"
        assert metadata.description == "A test skill for testing"
        assert metadata.user_invocable is True  # Default
        assert metadata.allowed_tools is None
        assert metadata.model is None

    def test_metadata_with_all_fields(self) -> None:
        """Test parsing metadata with all optional fields."""
        metadata = SkillMetadata(
            name="full-skill",
            description="A fully configured skill",
            **{
                "allowed-tools": ["Read", "Grep"],
                "model": "claude-sonnet-4-20250514",
                "context": "fork",
                "agent": "Explore",
                "user-invocable": False,
            },
        )
        assert metadata.name == "full-skill"
        assert metadata.allowed_tools == ["Read", "Grep"]
        assert metadata.model == "claude-sonnet-4-20250514"
        assert metadata.context == "fork"
        assert metadata.agent == "Explore"
        assert metadata.user_invocable is False


class TestKlabautermannSkillConfig:
    """Tests for KlabautermannSkillConfig model."""

    def test_basic_config(self) -> None:
        """Test parsing klabautermann config fields."""
        config = KlabautermannSkillConfig(
            **{
                "klabautermann-task-type": "research",
                "klabautermann-agent": "researcher",
            }
        )
        assert config.task_type == "research"
        assert config.agent == "researcher"
        assert config.blocking is True  # Default

    def test_config_with_payload_schema(self) -> None:
        """Test parsing config with payload schema."""
        config = KlabautermannSkillConfig(
            **{
                "klabautermann-task-type": "execute",
                "klabautermann-agent": "executor",
                "klabautermann-blocking": False,
                "klabautermann-requires-confirmation": True,
                "klabautermann-payload-schema": {
                    "query": {
                        "type": "string",
                        "required": True,
                        "extract-from": "user-message",
                    },
                    "limit": {
                        "type": "number",
                        "default": 10,
                    },
                },
            }
        )
        assert config.task_type == "execute"
        assert config.agent == "executor"
        assert config.blocking is False
        assert config.requires_confirmation is True

        fields = config.get_payload_fields()
        assert "query" in fields
        assert fields["query"].type == "string"
        assert fields["query"].required is True
        assert "limit" in fields
        assert fields["limit"].default == 10


class TestPayloadField:
    """Tests for PayloadField model."""

    def test_default_values(self) -> None:
        """Test payload field defaults."""
        field = PayloadField()
        assert field.type == "string"
        assert field.required is False
        assert field.default is None
        assert field.extract_from == "user-message"

    def test_custom_values(self) -> None:
        """Test payload field with custom values."""
        field = PayloadField(
            type="boolean",
            required=True,
            default=False,
            extract_from="context",
            description="A boolean flag",
        )
        assert field.type == "boolean"
        assert field.required is True
        assert field.default is False
        assert field.extract_from == "context"
        assert field.description == "A boolean flag"


class TestLoadedSkill:
    """Tests for LoadedSkill model."""

    def test_loaded_skill_properties(self) -> None:
        """Test LoadedSkill computed properties."""
        skill = LoadedSkill(
            metadata=SkillMetadata(
                name="test-skill",
                description="Test skill description",
            ),
            klabautermann=KlabautermannSkillConfig(
                **{
                    "klabautermann-task-type": "research",
                    "klabautermann-agent": "researcher",
                }
            ),
            body="# Test Skill\n\nInstructions here.",
            path=Path("/tmp/test-skill/SKILL.md"),
        )

        assert skill.name == "test-skill"
        assert skill.description == "Test skill description"
        assert skill.is_orchestrator_enabled is True

    def test_skill_without_orchestrator_config(self) -> None:
        """Test skill without klabautermann config is not orchestrator-enabled."""
        skill = LoadedSkill(
            metadata=SkillMetadata(
                name="basic-skill",
                description="Basic skill without orchestrator config",
            ),
            klabautermann=KlabautermannSkillConfig(),
            body="# Basic Skill",
            path=Path("/tmp/basic-skill/SKILL.md"),
        )

        assert skill.is_orchestrator_enabled is False


class TestSkillRegistry:
    """Tests for SkillRegistry model."""

    def test_add_and_get_skill(self) -> None:
        """Test adding and retrieving skills."""
        registry = SkillRegistry()

        skill = LoadedSkill(
            metadata=SkillMetadata(name="my-skill", description="My skill"),
            klabautermann=KlabautermannSkillConfig(),
            body="# My Skill",
            path=Path("/tmp/my-skill/SKILL.md"),
        )

        registry.add(skill)
        assert registry.get("my-skill") == skill
        assert registry.get("nonexistent") is None
        assert "my-skill" in registry.list_names()

    def test_list_orchestrator_enabled(self) -> None:
        """Test filtering orchestrator-enabled skills."""
        registry = SkillRegistry()

        # Add orchestrator-enabled skill
        enabled_skill = LoadedSkill(
            metadata=SkillMetadata(name="enabled", description="Enabled skill"),
            klabautermann=KlabautermannSkillConfig(
                **{"klabautermann-task-type": "research", "klabautermann-agent": "researcher"}
            ),
            body="# Enabled",
            path=Path("/tmp/enabled/SKILL.md"),
        )
        registry.add(enabled_skill)

        # Add non-orchestrator skill
        basic_skill = LoadedSkill(
            metadata=SkillMetadata(name="basic", description="Basic skill"),
            klabautermann=KlabautermannSkillConfig(),
            body="# Basic",
            path=Path("/tmp/basic/SKILL.md"),
        )
        registry.add(basic_skill)

        enabled_list = registry.list_orchestrator_enabled()
        assert len(enabled_list) == 1
        assert enabled_list[0].name == "enabled"


class TestSkillLoader:
    """Tests for SkillLoader."""

    def test_parse_frontmatter(self, tmp_path: Path) -> None:
        """Test parsing YAML frontmatter from SKILL.md."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()

        skill_content = dedent("""
            ---
            name: test-skill
            description: A test skill
            allowed-tools: Read, Grep
            klabautermann-task-type: research
            klabautermann-agent: researcher
            ---

            # Test Skill

            Instructions for the skill.
        """).strip()

        (skill_dir / "SKILL.md").write_text(skill_content)

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        loader.load_all()

        skill = loader.get("test-skill")
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.klabautermann.task_type == "research"
        assert skill.klabautermann.agent == "researcher"
        assert "# Test Skill" in skill.body

    def test_load_multiple_skills(self, tmp_path: Path) -> None:
        """Test loading multiple skills from directory."""
        # Create two skill directories
        for name in ["skill-one", "skill-two"]:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                dedent(f"""
                ---
                name: {name}
                description: Skill {name}
                klabautermann-task-type: research
                klabautermann-agent: researcher
                ---

                # {name}
            """).strip()
            )

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        loader.load_all()

        assert len(loader.list_skills()) == 2
        assert loader.get("skill-one") is not None
        assert loader.get("skill-two") is not None

    def test_skip_invalid_skills(self, tmp_path: Path) -> None:
        """Test that invalid skills are skipped with warning."""
        skill_dir = tmp_path / "invalid-skill"
        skill_dir.mkdir()

        # Write invalid content (no frontmatter)
        (skill_dir / "SKILL.md").write_text("# No frontmatter here")

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        loader.load_all()

        # Should not crash, just skip the invalid skill
        assert loader.get("invalid-skill") is None


class TestSkillAwarePlanner:
    """Tests for SkillAwarePlanner."""

    @pytest.fixture
    def planner_with_skills(self, tmp_path: Path) -> SkillAwarePlanner:
        """Create planner with test skills loaded."""
        # Create lookup-person skill
        lookup_dir = tmp_path / "lookup-person"
        lookup_dir.mkdir()
        (lookup_dir / "SKILL.md").write_text(
            dedent("""
            ---
            name: lookup-person
            description: Search for a person. Use when user asks "who is X".
            klabautermann-task-type: research
            klabautermann-agent: researcher
            klabautermann-blocking: true
            klabautermann-payload-schema:
              query:
                type: string
                required: true
                extract-from: user-message
            ---

            # Lookup Person

            Find person info.
        """).strip()
        )

        # Create send-email skill
        email_dir = tmp_path / "send-email"
        email_dir.mkdir()
        (email_dir / "SKILL.md").write_text(
            dedent("""
            ---
            name: send-email
            description: Send an email. Use when user says "send email to X".
            klabautermann-task-type: execute
            klabautermann-agent: executor
            klabautermann-blocking: true
            ---

            # Send Email

            Send emails.
        """).strip()
        )

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        return SkillAwarePlanner(loader)

    def test_match_skill_by_pattern(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test matching skill by description pattern."""
        skill = planner_with_skills.match_skill("who is Sarah?")
        assert skill is not None
        assert skill.name == "lookup-person"

    def test_match_skill_by_command(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test matching skill by explicit /command."""
        skill = planner_with_skills.match_skill("/lookup-person John")
        assert skill is not None
        assert skill.name == "lookup-person"

    def test_no_match(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test no skill matches for unrelated query."""
        skill = planner_with_skills.match_skill("What's the weather today?")
        assert skill is None

    def test_skill_to_planned_task(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test converting skill to PlannedTask."""
        skill = planner_with_skills.match_skill("/lookup-person")
        assert skill is not None

        task = planner_with_skills.skill_to_planned_task(skill, {"query": "Sarah"})
        assert task.task_type == "research"
        assert task.agent == "researcher"
        assert task.blocking is True
        assert task.payload == {"query": "Sarah"}

    def test_match_and_plan(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test full match and plan flow."""
        result = planner_with_skills.match_and_plan("who is John?", "trace-123")
        assert result is not None

        skill, task = result
        assert skill.name == "lookup-person"
        assert task.task_type == "research"
        assert task.agent == "researcher"

    def test_get_skills_context(self, planner_with_skills: SkillAwarePlanner) -> None:
        """Test generating skills context for LLM prompt."""
        context = planner_with_skills.get_skills_context()
        assert "lookup-person" in context
        assert "send-email" in context
        assert "research" in context
        assert "execute" in context
