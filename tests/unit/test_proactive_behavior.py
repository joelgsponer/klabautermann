"""
Unit tests for ProactiveBehavior module.

Tests the proactive suggestion logic including calendar suggestions,
follow-up suggestions, clarification requests, and cooldown tracking.
"""

import time
from unittest.mock import MagicMock

from klabautermann.agents.proactive_behavior import ProactiveBehavior
from klabautermann.core.models import EnrichedContext, TaskPlan


class TestProactiveBehaviorInit:
    """Test ProactiveBehavior initialization."""

    def test_default_config(self) -> None:
        """Test default configuration enables all suggestions."""
        pb = ProactiveBehavior()

        assert pb.suggest_calendar is True
        assert pb.suggest_followups is True
        assert pb.ask_clarifications is True

    def test_custom_config(self) -> None:
        """Test custom configuration is respected."""
        config = {
            "suggest_calendar_events": False,
            "suggest_follow_ups": True,
            "ask_clarifications": False,
        }
        pb = ProactiveBehavior(config)

        assert pb.suggest_calendar is False
        assert pb.suggest_followups is True
        assert pb.ask_clarifications is False

    def test_none_config(self) -> None:
        """Test None config uses defaults."""
        pb = ProactiveBehavior(None)

        assert pb.suggest_calendar is True
        assert pb.suggest_followups is True
        assert pb.ask_clarifications is True


class TestCalendarSuggestions:
    """Test calendar suggestion logic."""

    def test_suggests_for_time_mention(self) -> None:
        """Test calendar suggestion triggers on time mentions."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_calendar(
            context=None,
            results={},
            text="Let's meet tomorrow to discuss the project",
        )

        assert result is True

    def test_suggests_for_day_mention(self) -> None:
        """Test calendar suggestion triggers on day names."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_calendar(
            context=None,
            results={},
            text="Can we schedule a call for Monday?",
        )

        assert result is True

    def test_no_suggestion_without_time(self) -> None:
        """Test no suggestion when no time is mentioned."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_calendar(
            context=None,
            results={},
            text="I need to finish this report",
        )

        assert result is False

    def test_no_suggestion_with_existing_event(self) -> None:
        """Test no suggestion when calendar event already exists."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_calendar(
            context=None,
            results={"calendar": {"events": [{"title": "Meeting"}]}},
            text="What about next week's meeting?",
        )

        assert result is False

    def test_no_suggestion_when_disabled(self) -> None:
        """Test no suggestion when calendar suggestions disabled."""
        pb = ProactiveBehavior({"suggest_calendar_events": False})

        result = pb.should_suggest_calendar(
            context=None,
            results={},
            text="Let's meet tomorrow",
        )

        assert result is False

    def test_cooldown_prevents_repeat(self) -> None:
        """Test cooldown prevents repeated suggestions."""
        pb = ProactiveBehavior()

        # First suggestion should work
        result1 = pb.should_suggest_calendar(None, {}, "Meet tomorrow")
        assert result1 is True

        # Second suggestion should be blocked by cooldown
        result2 = pb.should_suggest_calendar(None, {}, "Also next week")
        assert result2 is False

    def test_cooldown_expires(self) -> None:
        """Test suggestions resume after cooldown expires."""
        pb = ProactiveBehavior()

        # Make first suggestion
        pb.should_suggest_calendar(None, {}, "Meet tomorrow")

        # Manually expire the cooldown
        pb._recent_suggestions["calendar"] = time.time() - 400  # Past cooldown

        # Now should suggest again
        result = pb.should_suggest_calendar(None, {}, "How about Friday?")
        assert result is True


class TestFollowupSuggestions:
    """Test follow-up suggestion logic."""

    def test_suggests_for_action_phrase(self) -> None:
        """Test follow-up suggestion triggers on action phrases."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_followup(
            context=None,
            results={},
            text="I need to call John about the proposal",
        )

        assert result is True

    def test_suggests_for_reminder_phrase(self) -> None:
        """Test follow-up suggestion triggers on reminder phrases."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_followup(
            context=None,
            results={},
            text="Remind me to send the report",
        )

        assert result is True

    def test_no_suggestion_without_action(self) -> None:
        """Test no suggestion when no action is mentioned."""
        pb = ProactiveBehavior()

        result = pb.should_suggest_followup(
            context=None,
            results={},
            text="The weather is nice today",
        )

        assert result is False

    def test_no_suggestion_with_pending_tasks(self) -> None:
        """Test no suggestion when pending tasks exist."""
        pb = ProactiveBehavior()
        context = MagicMock(spec=EnrichedContext)
        context.pending_tasks = [{"task": "Existing task"}]

        result = pb.should_suggest_followup(
            context=context,
            results={},
            text="I should follow up with Sarah",
        )

        assert result is False

    def test_no_suggestion_when_disabled(self) -> None:
        """Test no suggestion when follow-ups disabled."""
        pb = ProactiveBehavior({"suggest_follow_ups": False})

        result = pb.should_suggest_followup(
            context=None,
            results={},
            text="I need to call John",
        )

        assert result is False

    def test_cooldown_prevents_repeat(self) -> None:
        """Test cooldown prevents repeated suggestions."""
        pb = ProactiveBehavior()

        # First suggestion
        result1 = pb.should_suggest_followup(None, {}, "Need to call John")
        assert result1 is True

        # Second should be blocked
        result2 = pb.should_suggest_followup(None, {}, "Should email Sarah")
        assert result2 is False


class TestClarificationSuggestions:
    """Test clarification suggestion logic."""

    def test_suggests_for_ambiguity(self) -> None:
        """Test clarification triggers on ambiguous language."""
        pb = ProactiveBehavior()

        result = pb.should_ask_clarification(
            text="Maybe I should look into something like that",
            task_plan=None,
        )

        assert result is True

    def test_suggests_for_uncertainty(self) -> None:
        """Test clarification triggers on uncertain language."""
        pb = ProactiveBehavior()

        result = pb.should_ask_clarification(
            text="I'm not sure what I want to do here",
            task_plan=None,
        )

        assert result is True

    def test_no_suggestion_for_clear_input(self) -> None:
        """Test no clarification for clear input."""
        pb = ProactiveBehavior()

        result = pb.should_ask_clarification(
            text="Send an email to John about the meeting",
            task_plan=None,
        )

        assert result is False

    def test_no_suggestion_with_clear_task_plan(self) -> None:
        """Test no clarification when task plan exists."""
        pb = ProactiveBehavior()
        task_plan = MagicMock(spec=TaskPlan)
        task_plan.tasks = [{"type": "research"}]

        result = pb.should_ask_clarification(
            text="Maybe we should look into this",
            task_plan=task_plan,
        )

        assert result is False

    def test_no_suggestion_when_disabled(self) -> None:
        """Test no clarification when disabled."""
        pb = ProactiveBehavior({"ask_clarifications": False})

        result = pb.should_ask_clarification(
            text="I'm not sure about this",
            task_plan=None,
        )

        assert result is False

    def test_cooldown_prevents_repeat(self) -> None:
        """Test cooldown prevents repeated clarifications."""
        pb = ProactiveBehavior()

        # First clarification
        result1 = pb.should_ask_clarification("Maybe something", None)
        assert result1 is True

        # Second should be blocked
        result2 = pb.should_ask_clarification("I'm not sure", None)
        assert result2 is False


class TestSuggestionText:
    """Test suggestion text generation."""

    def test_calendar_suggestion_text(self) -> None:
        """Test calendar suggestion text."""
        pb = ProactiveBehavior()

        text = pb.get_suggestion_text("calendar")
        assert "calendar event" in text.lower()

    def test_followup_suggestion_text(self) -> None:
        """Test follow-up suggestion text."""
        pb = ProactiveBehavior()

        text = pb.get_suggestion_text("followup")
        assert "task list" in text.lower()

    def test_clarification_suggestion_text(self) -> None:
        """Test clarification suggestion text."""
        pb = ProactiveBehavior()

        text = pb.get_suggestion_text("clarification")
        assert "clarify" in text.lower()

    def test_suggestion_with_context_hint(self) -> None:
        """Test suggestion text with context hint."""
        pb = ProactiveBehavior()

        text = pb.get_suggestion_text("calendar", "For the meeting on Tuesday")
        assert "Tuesday" in text

    def test_unknown_suggestion_type(self) -> None:
        """Test unknown suggestion type returns empty string."""
        pb = ProactiveBehavior()

        text = pb.get_suggestion_text("unknown")
        assert text == ""


class TestCooldownManagement:
    """Test cooldown reset functionality."""

    def test_reset_cooldowns(self) -> None:
        """Test reset_cooldowns clears all cooldowns."""
        pb = ProactiveBehavior()

        # Trigger all suggestion types
        pb.should_suggest_calendar(None, {}, "Meet tomorrow")
        pb.should_suggest_followup(None, {}, "Need to call John")
        pb.should_ask_clarification("Maybe something", None)

        # Verify all are on cooldown
        assert pb._recently_suggested("calendar", 300)
        assert pb._recently_suggested("followup", 180)
        assert pb._recently_suggested("clarification", 60)

        # Reset cooldowns
        pb.reset_cooldowns()

        # Verify all cooldowns cleared
        assert not pb._recently_suggested("calendar", 300)
        assert not pb._recently_suggested("followup", 180)
        assert not pb._recently_suggested("clarification", 60)
