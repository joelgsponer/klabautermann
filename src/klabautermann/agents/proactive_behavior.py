"""
Proactive Behavior Module for Orchestrator v2.

Implements logic for suggesting follow-up actions (calendar events, emails,
clarifications) when appropriate. Makes the assistant more helpful without
being annoying.

Reference: specs/MAINAGENT.md Section 3.2, 8.3
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.core.models import EnrichedContext, TaskPlan


class ProactiveBehavior:
    """
    Logic for when to make proactive suggestions.

    Implements suggestion triggers with cooldown tracking to prevent
    spam and considers conversation context to avoid repetition.
    """

    # Time indicators for calendar suggestions
    TIME_INDICATORS = frozenset(
        [
            "tomorrow",
            "next week",
            "next month",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "next monday",
            "next tuesday",
            "this weekend",
            "this week",
            "in a few days",
            "later this week",
            "early next week",
        ]
    )

    # Action item indicators for follow-up suggestions
    ACTION_INDICATORS = frozenset(
        [
            "need to",
            "should",
            "have to",
            "must",
            "will",
            "going to",
            "remind me",
            "don't forget",
            "remember to",
            "follow up",
            "get back to",
            "reach out",
            "send",
            "email",
            "call",
            "schedule",
        ]
    )

    # Ambiguity indicators for clarification suggestions
    AMBIGUITY_INDICATORS = frozenset(
        [
            "maybe",
            "perhaps",
            "not sure",
            "i think",
            "might",
            "could be",
            "possibly",
            "probably",
            "or something",
            "kind of",
            "sort of",
            "something like",
            "i guess",
            "unsure",
        ]
    )

    # Cooldown periods in seconds
    CALENDAR_COOLDOWN = 300  # 5 minutes
    FOLLOWUP_COOLDOWN = 180  # 3 minutes
    CLARIFICATION_COOLDOWN = 60  # 1 minute

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize proactive behavior with configuration.

        Args:
            config: Dict with keys suggest_calendar_events, suggest_follow_ups,
                   ask_clarifications (all bool, default True).
        """
        config = config or {}
        self.suggest_calendar = config.get("suggest_calendar_events", True)
        self.suggest_followups = config.get("suggest_follow_ups", True)
        self.ask_clarifications = config.get("ask_clarifications", True)
        self._recent_suggestions: dict[str, float] = {}

    def _recently_suggested(self, suggestion_type: str, cooldown_seconds: float) -> bool:
        """
        Check if a suggestion type was made recently.

        Args:
            suggestion_type: Type of suggestion (calendar, followup, clarification).
            cooldown_seconds: Cooldown period in seconds.

        Returns:
            True if suggestion was made within cooldown period.
        """
        last_time = self._recent_suggestions.get(suggestion_type, 0.0)
        return (time.time() - last_time) < cooldown_seconds

    def _mark_suggested(self, suggestion_type: str) -> None:
        """Mark a suggestion type as recently made."""
        self._recent_suggestions[suggestion_type] = time.time()

    def should_suggest_calendar(
        self,
        context: EnrichedContext | None,  # noqa: ARG002
        results: dict[str, Any],
        text: str,
    ) -> bool:
        """
        Check if we should suggest creating a calendar event.

        Triggers when:
        - User mentions future time ("next week", "tomorrow")
        - No calendar event exists for that time
        - Haven't suggested calendar recently

        Args:
            context: Enriched context from conversation.
            results: Results from task execution (may contain calendar data).
            text: User's message text.

        Returns:
            True if calendar suggestion is appropriate.
        """
        if not self.suggest_calendar:
            return False

        # Check cooldown
        if self._recently_suggested("calendar", self.CALENDAR_COOLDOWN):
            logger.debug(
                "[WHISPER] Calendar suggestion on cooldown",
                extra={"cooldown_remaining": self.CALENDAR_COOLDOWN},
            )
            return False

        # Look for time indicators
        text_lower = text.lower()
        has_time_mention = any(indicator in text_lower for indicator in self.TIME_INDICATORS)

        if not has_time_mention:
            return False

        # Check if calendar results already exist
        calendar_results = results.get("calendar", {})
        has_existing_event = bool(calendar_results.get("events", []))

        if has_existing_event:
            return False

        # All conditions met - mark as suggested and return True
        self._mark_suggested("calendar")
        logger.debug(
            "[WHISPER] Triggering calendar suggestion",
            extra={"text_snippet": text[:50]},
        )
        return True

    def should_suggest_followup(
        self,
        context: EnrichedContext | None,
        results: dict[str, Any],  # noqa: ARG002
        text: str,
    ) -> bool:
        """
        Check if we should suggest a follow-up action.

        Triggers when:
        - User mentions action items ("need to", "should", "remind me")
        - No pending task exists for this action
        - Haven't suggested follow-up recently

        Args:
            context: Enriched context from conversation.
            results: Results from task execution (may contain task data).
            text: User's message text.

        Returns:
            True if follow-up suggestion is appropriate.
        """
        if not self.suggest_followups:
            return False

        # Check cooldown
        if self._recently_suggested("followup", self.FOLLOWUP_COOLDOWN):
            logger.debug(
                "[WHISPER] Follow-up suggestion on cooldown",
                extra={"cooldown_remaining": self.FOLLOWUP_COOLDOWN},
            )
            return False

        # Look for action indicators
        text_lower = text.lower()
        has_action_mention = any(indicator in text_lower for indicator in self.ACTION_INDICATORS)

        if not has_action_mention:
            return False

        # Check if task already exists in context
        if context and context.pending_tasks:
            # Don't suggest if there are pending tasks already
            return False

        # All conditions met
        self._mark_suggested("followup")
        logger.debug(
            "[WHISPER] Triggering follow-up suggestion",
            extra={"text_snippet": text[:50]},
        )
        return True

    def should_ask_clarification(
        self,
        text: str,
        task_plan: TaskPlan | None,
    ) -> bool:
        """
        Check if we should ask for clarification.

        Triggers when:
        - User input contains ambiguity indicators ("maybe", "not sure")
        - Task plan has low confidence or few tasks
        - Haven't asked for clarification recently

        Args:
            text: User's message text.
            task_plan: Generated task plan (may be weak if input is ambiguous).

        Returns:
            True if clarification request is appropriate.
        """
        if not self.ask_clarifications:
            return False

        # Check cooldown
        if self._recently_suggested("clarification", self.CLARIFICATION_COOLDOWN):
            logger.debug(
                "[WHISPER] Clarification on cooldown",
                extra={"cooldown_remaining": self.CLARIFICATION_COOLDOWN},
            )
            return False

        # Look for ambiguity indicators
        text_lower = text.lower()
        has_ambiguity = any(indicator in text_lower for indicator in self.AMBIGUITY_INDICATORS)

        if not has_ambiguity:
            return False

        # Check if task plan is weak - if we have a clear task plan, don't ask for clarification
        if task_plan is not None and len(task_plan.tasks) > 0:
            return False

        # All conditions met
        self._mark_suggested("clarification")
        logger.debug(
            "[WHISPER] Triggering clarification request",
            extra={"text_snippet": text[:50]},
        )
        return True

    def get_suggestion_text(self, suggestion_type: str, context_hint: str = "") -> str:
        """
        Get natural suggestion text for a given type.

        Args:
            suggestion_type: Type of suggestion (calendar, followup, clarification).
            context_hint: Optional context to include in suggestion.

        Returns:
            Natural language suggestion text.
        """
        suggestions = {
            "calendar": (
                "Would you like me to create a calendar event for this? " f"{context_hint}"
            ).strip(),
            "followup": (
                "Should I add this to your task list so you don't forget? " f"{context_hint}"
            ).strip(),
            "clarification": (
                "I want to make sure I understand correctly. "
                "Could you clarify what you'd like me to help with? "
                f"{context_hint}"
            ).strip(),
        }
        return suggestions.get(suggestion_type, "")

    def reset_cooldowns(self) -> None:
        """Reset all cooldown timers (useful for testing)."""
        self._recent_suggestions.clear()


__all__ = ["ProactiveBehavior"]
