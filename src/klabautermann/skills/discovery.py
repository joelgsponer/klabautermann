"""
AI-first skill discovery using LLM semantic matching.

Replaces keyword/regex-based pattern matching with pure LLM understanding
of user intent and skill capabilities. This ensures accurate skill matching
even for novel phrasings and edge cases.

Usage:
    discovery = SkillDiscovery(loader)
    skill = await discovery.discover_skill("Who is Sarah?", trace_id)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anthropic import AsyncAnthropic

from klabautermann.core.config import get_settings
from klabautermann.core.logger import logger
from klabautermann.skills.loader import SkillLoader


if TYPE_CHECKING:
    from klabautermann.skills.models import LoadedSkill


class SkillDiscovery:
    """
    AI-first skill discovery using LLM semantic matching.

    Uses Claude to understand user intent and match to the most appropriate
    skill based on semantic similarity, not keyword patterns.
    """

    def __init__(
        self,
        loader: SkillLoader | None = None,
        model: str | None = None,
    ) -> None:
        """
        Initialize skill discovery.

        Args:
            loader: SkillLoader instance. Creates new one if not provided.
            model: LLM model for discovery. Defaults to fast model from settings.
        """
        self.loader = loader or SkillLoader()
        self.settings = get_settings()
        self.model = model or self.settings.fast_model
        self.client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    def _build_skills_context(self) -> str:
        """
        Build context string listing available skills for LLM.

        Returns:
            Formatted string with skill names and descriptions.
        """
        self.loader.load_all()
        skills = self.loader.registry.skills.values()

        if not skills:
            return "No skills available."

        lines = []
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description}")

        return "\n".join(lines)

    def _build_discovery_prompt(self, user_input: str, skills_context: str) -> str:
        """
        Build the LLM prompt for skill discovery.

        Args:
            user_input: User's message.
            skills_context: Formatted list of available skills.

        Returns:
            Complete prompt for skill matching.
        """
        return f"""Analyze the user's request and determine which skill (if any) best matches their intent.

Available skills:
{skills_context}

User said: "{user_input}"

Instructions:
1. Understand the semantic meaning of the user's request
2. Match it to the most appropriate skill based on what the skill does, not keyword matching
3. Consider the user's likely intent, not just surface-level words
4. If no skill is a good match, respond with "none"

Respond with ONLY a JSON object in this format:
{{"skill": "skill-name-or-none", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}

Examples:
- "Can you find John's email?" -> {{"skill": "search-contacts", "confidence": 0.9, "reasoning": "User wants to look up contact information"}}
- "What's the weather?" -> {{"skill": "none", "confidence": 0.95, "reasoning": "No skill handles weather queries"}}
- "Set up a call with Sarah tomorrow" -> {{"skill": "schedule-meeting", "confidence": 0.85, "reasoning": "User wants to schedule a meeting/call"}}"""

    async def discover_skill(
        self,
        user_input: str,
        trace_id: str,
        min_confidence: float = 0.5,
    ) -> LoadedSkill | None:
        """
        Use LLM to discover the most appropriate skill for user input.

        Args:
            user_input: User's message text.
            trace_id: Request trace ID for logging.
            min_confidence: Minimum confidence threshold (0.0-1.0).

        Returns:
            Matched LoadedSkill or None if no confident match.
        """
        skills_context = self._build_skills_context()

        # No skills available
        if skills_context == "No skills available.":
            logger.debug(
                "[WHISPER] No skills available for discovery",
                extra={"trace_id": trace_id},
            )
            return None

        prompt = self._build_discovery_prompt(user_input, skills_context)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON response
            result = self._parse_discovery_response(response_text)

            if not result:
                logger.warning(
                    "[SWELL] Failed to parse skill discovery response",
                    extra={"trace_id": trace_id, "response": response_text},
                )
                return None

            skill_name = result.get("skill", "none")
            confidence = result.get("confidence", 0.0)
            reasoning = result.get("reasoning", "")

            logger.info(
                "[CHART] Skill discovery result",
                extra={
                    "trace_id": trace_id,
                    "skill": skill_name,
                    "confidence": confidence,
                    "reasoning": reasoning,
                },
            )

            # No match or low confidence
            if skill_name == "none" or confidence < min_confidence:
                return None

            # Get the skill from loader
            skill = self.loader.get(skill_name)
            if not skill:
                logger.warning(
                    "[SWELL] LLM matched non-existent skill",
                    extra={"trace_id": trace_id, "skill": skill_name},
                )
                return None

            return skill

        except Exception as e:
            logger.warning(
                "[SWELL] Skill discovery LLM call failed",
                extra={"trace_id": trace_id, "error": str(e)},
            )
            return None

    def _parse_discovery_response(self, response_text: str) -> dict[str, Any] | None:
        """
        Parse JSON response from discovery LLM.

        Args:
            response_text: Raw LLM response text.

        Returns:
            Parsed dict or None if parsing fails.
        """
        try:
            # Try direct JSON parse
            result: dict[str, Any] = json.loads(response_text)
            return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        import re

        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                return result
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        json_match = re.search(r"\{[^{}]*\}", response_text)
        if json_match:
            try:
                result = json.loads(json_match.group(0))
                return result
            except json.JSONDecodeError:
                pass

        return None

    async def extract_payload_with_llm(
        self,
        skill: LoadedSkill,
        user_input: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """
        Use LLM to extract payload values from user input.

        More sophisticated than simple pattern matching - understands
        context and extracts structured data from natural language.

        Args:
            skill: Target skill with payload schema.
            user_input: User's message text.
            trace_id: Request trace ID for logging.

        Returns:
            Extracted payload dict.
        """
        # Get the skill's parameters from metadata (not klabautermann config)
        # Since we're using simpler SKILL.md format without klabautermann-* fields
        metadata = skill.metadata.model_dump()
        parameters = metadata.get("parameters", [])

        if not parameters:
            return {"query": user_input}

        # Build extraction prompt
        param_desc = []
        for param in parameters:
            if isinstance(param, dict):
                name = param.get("name", "unknown")
                ptype = param.get("type", "string")
                required = param.get("required", False)
                desc = param.get("description", "")
                param_desc.append(
                    f"- {name} ({ptype}, {'required' if required else 'optional'}): {desc}"
                )

        prompt = f"""Extract parameters from the user's message for the "{skill.name}" skill.

Parameters to extract:
{chr(10).join(param_desc)}

User said: "{user_input}"

Respond with ONLY a JSON object containing the extracted values.
Use null for optional parameters that cannot be determined.
Example: {{"title": "Meeting with John", "start_time": null}}"""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()
            result = self._parse_discovery_response(response_text)

            if result:
                # Filter out null values
                return {k: v for k, v in result.items() if v is not None}

        except Exception as e:
            logger.warning(
                "[SWELL] Payload extraction failed",
                extra={"trace_id": trace_id, "error": str(e)},
            )

        # Fallback: return user input as query
        return {"query": user_input}
