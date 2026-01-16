"""
Skill-aware task planner for orchestrator integration.

Bridges Claude Code skills with Klabautermann's task planning system,
enabling automatic conversion of skill invocations to PlannedTask objects.

Usage:
    from klabautermann.skills import SkillLoader, SkillAwarePlanner

    loader = SkillLoader()
    planner = SkillAwarePlanner(loader)

    # Match user message to skill and convert to PlannedTask
    result = await planner.match_and_plan("Who is Sarah?", trace_id)
    if result:
        skill, task = result
        # Dispatch task to appropriate agent
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.models import PlannedTask
from klabautermann.skills.loader import SkillLoader


if TYPE_CHECKING:
    from klabautermann.skills.models import LoadedSkill


class SkillAwarePlanner:
    """
    Integrates Claude Code skills with orchestrator task planning.

    Provides methods to:
    - Match user messages to skills by description/pattern
    - Convert matched skills to PlannedTask objects
    - Extract payload values from user messages
    """

    def __init__(self, loader: SkillLoader | None = None) -> None:
        """
        Initialize skill-aware planner.

        Args:
            loader: SkillLoader instance. Creates new one if not provided.
        """
        self.loader = loader or SkillLoader()
        self._description_patterns: dict[str, list[re.Pattern[str]]] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure skills are loaded and patterns compiled."""
        if self._initialized:
            return

        self.loader.load_all()
        self._compile_patterns()
        self._initialized = True

    def _compile_patterns(self) -> None:
        """Compile regex patterns from skill descriptions."""
        for skill in self.loader.get_orchestrator_skills():
            patterns = self._extract_patterns_from_description(skill.description)
            if patterns:
                self._description_patterns[skill.name] = patterns

    def _extract_patterns_from_description(self, description: str) -> list[re.Pattern[str]]:
        """
        Extract matching patterns from skill description.

        Looks for common pattern indicators like "when user asks",
        "use when", quoted examples, etc.

        Args:
            description: Skill description text.

        Returns:
            List of compiled regex patterns.
        """
        patterns = []

        # Extract quoted phrases as exact match patterns
        quoted = re.findall(r'"([^"]+)"', description)
        for phrase in quoted:
            try:
                # Convert "who is X" to regex "who is .+"
                pattern_str = re.sub(r"\bX\b", r".+", phrase, flags=re.IGNORECASE)
                patterns.append(re.compile(pattern_str, re.IGNORECASE))
            except re.error:
                continue

        # Extract common trigger phrases
        trigger_phrases = [
            r"who is",
            r"find contact",
            r"lookup",
            r"search for",
            r"send email",
            r"email .+ about",
            r"schedule",
            r"create event",
            r"remind me",
        ]

        description_lower = description.lower()
        for phrase in trigger_phrases:
            if phrase.replace(r".+", "").replace(r"\b", "").strip() in description_lower:
                try:
                    patterns.append(re.compile(phrase, re.IGNORECASE))
                except re.error:
                    continue

        return patterns

    def match_skill(self, user_message: str) -> LoadedSkill | None:
        """
        Match user message to a skill using pattern matching.

        Args:
            user_message: User's message text.

        Returns:
            Matched LoadedSkill or None.
        """
        self._ensure_initialized()

        # Check explicit skill invocation (e.g., "/lookup-person")
        if user_message.startswith("/"):
            skill_name = user_message.split()[0][1:]  # Remove leading /
            skill = self.loader.get(skill_name)
            if skill and skill.is_orchestrator_enabled:
                return skill

        # Pattern matching against descriptions
        for skill_name, patterns in self._description_patterns.items():
            for pattern in patterns:
                if pattern.search(user_message):
                    skill = self.loader.get(skill_name)
                    if skill:
                        logger.debug(
                            "[WHISPER] Skill matched by pattern",
                            extra={
                                "skill": skill_name,
                                "pattern": pattern.pattern,
                            },
                        )
                        return skill

        return None

    def skill_to_planned_task(
        self,
        skill: LoadedSkill,
        payload: dict[str, Any] | None = None,
    ) -> PlannedTask:
        """
        Convert a skill to a PlannedTask for orchestrator dispatch.

        Args:
            skill: Loaded skill definition.
            payload: Extracted payload values.

        Returns:
            PlannedTask ready for dispatch.
        """
        config = skill.klabautermann

        return PlannedTask(
            task_type=config.task_type or "research",
            description=f"Skill: {skill.name} - {skill.description[:50]}...",
            agent=config.agent or "researcher",
            payload=payload or {},
            blocking=config.blocking,
        )

    def extract_payload(
        self,
        skill: LoadedSkill,
        user_message: str,
    ) -> dict[str, Any]:
        """
        Extract payload values from user message based on skill schema.

        Args:
            skill: Loaded skill with payload schema.
            user_message: User's message text.

        Returns:
            Extracted payload dict.
        """
        payload: dict[str, Any] = {}
        fields = skill.klabautermann.get_payload_fields()

        for field_name, field_def in fields.items():
            if field_def.extract_from == "user-message":
                # Simple extraction: use the full message as query
                # More sophisticated extraction would use LLM
                payload[field_name] = user_message

        return payload

    def match_and_plan(
        self,
        user_message: str,
        trace_id: str,
    ) -> tuple[LoadedSkill, PlannedTask] | None:
        """
        Match user message to skill and create PlannedTask.

        This is the main entry point for orchestrator integration.

        Args:
            user_message: User's message text.
            trace_id: Request trace ID for logging.

        Returns:
            Tuple of (matched skill, planned task) or None if no match.
        """
        self._ensure_initialized()

        skill = self.match_skill(user_message)
        if not skill:
            return None

        logger.info(
            "[BEACON] Matched skill for task planning",
            extra={
                "trace_id": trace_id,
                "skill": skill.name,
                "task_type": skill.klabautermann.task_type,
                "agent": skill.klabautermann.agent,
            },
        )

        payload = self.extract_payload(skill, user_message)
        task = self.skill_to_planned_task(skill, payload)

        return skill, task

    def get_skills_context(self) -> str:
        """
        Generate context string describing available skills.

        Used to inject skill awareness into LLM planning prompts.

        Returns:
            Formatted string with skill descriptions.
        """
        self._ensure_initialized()

        skills = self.loader.get_orchestrator_skills()
        if not skills:
            return "No skills available."

        lines = ["Available skills for task routing:"]
        for skill in skills:
            config = skill.klabautermann
            lines.append(f"- {skill.name}: {skill.description[:80]}")
            lines.append(f"    task_type={config.task_type}, agent={config.agent}")

        return "\n".join(lines)
