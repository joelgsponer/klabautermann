"""
Unit tests for the skills package.

Tests skill loading, parsing, and orchestrator integration.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.skills.discovery import SkillDiscovery
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


class TestSkillDiscovery:
    """Tests for AI-first skill discovery."""

    @pytest.fixture
    def discovery_with_skills(self, tmp_path: Path) -> SkillDiscovery:
        """Create discovery with test skills loaded."""
        # Create test skills
        for skill_data in [
            ("schedule-meeting", "Schedule calendar meetings and events"),
            ("search-contacts", "Find contacts and people in the knowledge graph"),
            ("create-note", "Create and save notes to the knowledge graph"),
            ("add-task", "Create tasks and todo items"),
        ]:
            skill_dir = tmp_path / skill_data[0]
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                dedent(f"""
                ---
                name: {skill_data[0]}
                description: {skill_data[1]}
                ---

                # {skill_data[0]}

                Skill content.
            """).strip()
            )

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        return SkillDiscovery(loader=loader)

    def test_build_skills_context(self, discovery_with_skills: SkillDiscovery) -> None:
        """Build context string for LLM."""
        context = discovery_with_skills._build_skills_context()

        assert "schedule-meeting" in context
        assert "search-contacts" in context
        assert "create-note" in context
        assert "add-task" in context

    def test_build_skills_context_empty(self, tmp_path: Path) -> None:
        """Handle no skills available."""
        loader = SkillLoader(
            project_skills_dir=tmp_path / "empty", personal_skills_dir=tmp_path / "none"
        )
        discovery = SkillDiscovery(loader=loader)
        context = discovery._build_skills_context()

        assert context == "No skills available."

    def test_parse_discovery_response_json(self, discovery_with_skills: SkillDiscovery) -> None:
        """Parse clean JSON response."""
        result = discovery_with_skills._parse_discovery_response(
            '{"skill": "schedule-meeting", "confidence": 0.9, "reasoning": "test"}'
        )

        assert result is not None
        assert result["skill"] == "schedule-meeting"
        assert result["confidence"] == 0.9

    def test_parse_discovery_response_code_block(
        self, discovery_with_skills: SkillDiscovery
    ) -> None:
        """Parse JSON in markdown code block."""
        result = discovery_with_skills._parse_discovery_response(
            dedent("""
            Here's the match:
            ```json
            {"skill": "search-contacts", "confidence": 0.85, "reasoning": "user wants contact info"}
            ```
        """)
        )

        assert result is not None
        assert result["skill"] == "search-contacts"

    def test_parse_discovery_response_invalid(self, discovery_with_skills: SkillDiscovery) -> None:
        """Handle invalid response."""
        result = discovery_with_skills._parse_discovery_response("I don't understand")

        assert result is None

    @pytest.mark.asyncio
    async def test_discover_skill_success(self, discovery_with_skills: SkillDiscovery) -> None:
        """Discover skill with LLM (mocked)."""
        # Mock the Anthropic client
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"skill": "search-contacts", "confidence": 0.9, "reasoning": "user wants contact"}'
            )
        ]

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            skill = await discovery_with_skills.discover_skill("Who is John?", "test-trace-123")

        assert skill is not None
        assert skill.name == "search-contacts"

    @pytest.mark.asyncio
    async def test_discover_skill_no_match(self, discovery_with_skills: SkillDiscovery) -> None:
        """No skill matches user input."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"skill": "none", "confidence": 0.95, "reasoning": "no matching skill"}'
            )
        ]

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            skill = await discovery_with_skills.discover_skill(
                "What's the weather?", "test-trace-123"
            )

        assert skill is None

    @pytest.mark.asyncio
    async def test_discover_skill_low_confidence(
        self, discovery_with_skills: SkillDiscovery
    ) -> None:
        """Reject low confidence matches."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"skill": "search-contacts", "confidence": 0.3, "reasoning": "uncertain"}'
            )
        ]

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            skill = await discovery_with_skills.discover_skill(
                "Do something", "test-trace-123", min_confidence=0.5
            )

        assert skill is None

    @pytest.mark.asyncio
    async def test_discover_skill_llm_error(self, discovery_with_skills: SkillDiscovery) -> None:
        """Handle LLM call failure gracefully."""
        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = Exception("API error")
            skill = await discovery_with_skills.discover_skill("Find John", "test-trace-123")

        assert skill is None

    @pytest.mark.asyncio
    async def test_discover_skill_nonexistent_skill(
        self, discovery_with_skills: SkillDiscovery
    ) -> None:
        """Handle LLM returning non-existent skill name."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"skill": "nonexistent-skill", "confidence": 0.9, "reasoning": "oops"}')
        ]

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            skill = await discovery_with_skills.discover_skill("Find something", "test-trace-123")

        assert skill is None

    @pytest.mark.asyncio
    async def test_extract_payload_with_llm(self, discovery_with_skills: SkillDiscovery) -> None:
        """Test LLM-based payload extraction."""
        # Create a skill with parameters
        skill = LoadedSkill(
            metadata=SkillMetadata(
                name="test-skill",
                description="Test skill",
                **{
                    "parameters": [
                        {
                            "name": "recipient",
                            "type": "string",
                            "required": True,
                            "description": "Email recipient",
                        },
                        {
                            "name": "subject",
                            "type": "string",
                            "required": False,
                            "description": "Email subject",
                        },
                    ]
                },
            ),
            klabautermann=KlabautermannSkillConfig(),
            body="# Test",
            path=Path("/tmp/test-skill/SKILL.md"),
        )

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text='{"recipient": "john@example.com", "subject": "Meeting"}')
        ]

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            payload = await discovery_with_skills.extract_payload_with_llm(
                skill, "Send email to john@example.com about Meeting", "test-trace-123"
            )

        assert payload["recipient"] == "john@example.com"
        assert payload["subject"] == "Meeting"

    @pytest.mark.asyncio
    async def test_extract_payload_with_llm_fallback(
        self, discovery_with_skills: SkillDiscovery
    ) -> None:
        """Test fallback to full message when extraction fails."""
        skill = LoadedSkill(
            metadata=SkillMetadata(name="test-skill", description="Test"),
            klabautermann=KlabautermannSkillConfig(),
            body="# Test",
            path=Path("/tmp/test-skill/SKILL.md"),
        )

        with patch.object(
            discovery_with_skills.client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = Exception("API error")
            payload = await discovery_with_skills.extract_payload_with_llm(
                skill, "Some user message", "test-trace-123"
            )

        # Should fallback to returning user message as query
        assert payload == {"query": "Some user message"}


class TestLoadedSkillToDict:
    """Tests for LoadedSkill.to_dict() serialization."""

    def test_to_dict_with_orchestrator_config(self) -> None:
        """Serialize orchestrator-enabled skill."""
        skill = LoadedSkill(
            metadata=SkillMetadata(
                name="test-skill",
                description="Test skill for serialization",
            ),
            klabautermann=KlabautermannSkillConfig(
                **{
                    "klabautermann-task-type": "execute",
                    "klabautermann-agent": "executor",
                    "klabautermann-blocking": False,
                }
            ),
            body="# Test Skill",
            path=Path("/tmp/test-skill/SKILL.md"),
        )

        result = skill.to_dict()

        assert result["name"] == "test-skill"
        assert result["description"] == "Test skill for serialization"
        assert result["task_type"] == "execute"
        assert result["agent"] == "executor"
        assert result["blocking"] is False
        assert result["path"] == "/tmp/test-skill/SKILL.md"

    def test_to_dict_without_orchestrator_config(self) -> None:
        """Serialize basic skill without orchestrator config."""
        skill = LoadedSkill(
            metadata=SkillMetadata(name="basic", description="Basic skill"),
            klabautermann=KlabautermannSkillConfig(),
            body="# Basic",
            path=Path("/tmp/basic/SKILL.md"),
        )

        result = skill.to_dict()

        assert result["name"] == "basic"
        assert result["task_type"] is None
        assert result["agent"] is None


class TestSkillChaining:
    """Tests for skill chaining patterns."""

    @pytest.fixture
    def multi_skill_planner(self, tmp_path: Path) -> SkillAwarePlanner:
        """Create planner with multiple skills that can be chained."""
        skills_data = [
            (
                "lookup-person",
                'Find person info. Use when asked "who is X" or "find contact".',
                "research",
                "researcher",
            ),
            (
                "send-email",
                'Send email. Use when asked "send email to X" or "email X about Y".',
                "execute",
                "executor",
            ),
            (
                "schedule-meeting",
                'Schedule meetings. Use when asked to "schedule" or "set up call".',
                "execute",
                "executor",
            ),
        ]

        for name, desc, task_type, agent in skills_data:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                dedent(f"""
                ---
                name: {name}
                description: {desc}
                klabautermann-task-type: {task_type}
                klabautermann-agent: {agent}
                ---

                # {name}

                Skill content.
            """).strip()
            )

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        return SkillAwarePlanner(loader)

    def test_sequential_skill_matching(self, multi_skill_planner: SkillAwarePlanner) -> None:
        """Test matching multiple skills in sequence (simulating multi-step task)."""
        # First step: lookup person
        skill1 = multi_skill_planner.match_skill("Who is John?")
        assert skill1 is not None
        assert skill1.name == "lookup-person"

        # Second step: send email using explicit command
        skill2 = multi_skill_planner.match_skill("/send-email to John")
        assert skill2 is not None
        assert skill2.name == "send-email"

    def test_match_returns_most_specific_skill(
        self, multi_skill_planner: SkillAwarePlanner
    ) -> None:
        """Test that pattern matching returns appropriate skill."""
        # Should match lookup-person via "who is" pattern
        skill = multi_skill_planner.match_skill("who is Sarah from Acme?")
        assert skill is not None
        assert skill.name == "lookup-person"

        # Should match send-email via "send email" pattern
        skill = multi_skill_planner.match_skill("send email to john about the meeting")
        assert skill is not None
        assert skill.name == "send-email"

    def test_generate_multiple_tasks(self, multi_skill_planner: SkillAwarePlanner) -> None:
        """Test generating tasks for a multi-step workflow."""
        # Simulate a workflow: find person, then email them
        # Using patterns that match the skill descriptions
        messages = ["Who is John?", "send email to John about the project"]

        tasks = []
        for msg in messages:
            result = multi_skill_planner.match_and_plan(msg, f"trace-{len(tasks)}")
            if result:
                skill, task = result
                tasks.append((skill.name, task))

        # Should have matched both skills
        assert len(tasks) == 2
        assert tasks[0][0] == "lookup-person"
        assert tasks[0][1].task_type == "research"
        assert tasks[1][0] == "send-email"
        assert tasks[1][1].task_type == "execute"


class TestSkillPayloadExtraction:
    """Tests for payload extraction from user messages."""

    @pytest.fixture
    def planner_with_schema(self, tmp_path: Path) -> SkillAwarePlanner:
        """Create planner with skill that has complex payload schema."""
        skill_dir = tmp_path / "complex-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            dedent("""
            ---
            name: complex-skill
            description: A skill with complex payload schema
            klabautermann-task-type: execute
            klabautermann-agent: executor
            klabautermann-payload-schema:
              query:
                type: string
                required: true
                extract-from: user-message
                description: Main search query
              limit:
                type: number
                required: false
                default: 10
                extract-from: user-message
                description: Number of results
              include_archived:
                type: boolean
                required: false
                default: false
                extract-from: context
            ---

            # Complex Skill

            Skill content.
        """).strip()
        )

        loader = SkillLoader(project_skills_dir=tmp_path, personal_skills_dir=tmp_path / "none")
        return SkillAwarePlanner(loader)

    def test_extract_simple_payload(self, planner_with_schema: SkillAwarePlanner) -> None:
        """Test extracting payload from user message."""
        skill = planner_with_schema.loader.get("complex-skill")
        assert skill is not None

        payload = planner_with_schema.extract_payload(skill, "Find all projects about AI")

        # Simple extraction puts full message in 'query' field
        assert "query" in payload
        assert payload["query"] == "Find all projects about AI"

    def test_payload_field_schema_parsing(self, planner_with_schema: SkillAwarePlanner) -> None:
        """Test that payload schema is correctly parsed."""
        skill = planner_with_schema.loader.get("complex-skill")
        assert skill is not None

        fields = skill.klabautermann.get_payload_fields()

        assert "query" in fields
        assert fields["query"].type == "string"
        assert fields["query"].required is True

        assert "limit" in fields
        assert fields["limit"].type == "number"
        assert fields["limit"].default == 10

        assert "include_archived" in fields
        assert fields["include_archived"].type == "boolean"
        # Note: extract_from defaults to "user-message" since PayloadField doesn't use alias
        assert fields["include_archived"].extract_from == "user-message"


class TestSkillRegistryDescriptions:
    """Tests for SkillRegistry.get_descriptions()."""

    def test_get_descriptions(self) -> None:
        """Get all skill descriptions."""
        registry = SkillRegistry()

        skill1 = LoadedSkill(
            metadata=SkillMetadata(name="skill-a", description="Description A"),
            klabautermann=KlabautermannSkillConfig(),
            body="# A",
            path=Path("/tmp/skill-a/SKILL.md"),
        )
        skill2 = LoadedSkill(
            metadata=SkillMetadata(name="skill-b", description="Description B"),
            klabautermann=KlabautermannSkillConfig(),
            body="# B",
            path=Path("/tmp/skill-b/SKILL.md"),
        )

        registry.add(skill1)
        registry.add(skill2)

        descriptions = registry.get_descriptions()

        assert descriptions["skill-a"] == "Description A"
        assert descriptions["skill-b"] == "Description B"
