# Proactive Behavior Module

## Metadata
- **ID**: T065
- **Priority**: P2
- **Category**: core
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 3.2, 8.3
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T056 - Response Synthesis
- [x] T058 - Orchestrator v2 Configuration

## Context
Implement the proactive behavior logic that enables the orchestrator to suggest follow-up actions (calendar events, emails, clarifications) when appropriate. This makes the assistant more helpful without being annoying.

## Requirements
- [ ] Implement `_should_suggest_calendar(context, results) -> bool`
- [ ] Implement `_should_suggest_followup(context, results) -> bool`
- [ ] Implement `_should_ask_clarification(text, task_plan) -> bool`
- [ ] Read behavior flags from config (suggest_calendar_events, etc.)
- [ ] Consider conversation context (don't repeat suggestions)
- [ ] Implement cooldown to prevent spam suggestions

## Acceptance Criteria
- [ ] Calendar suggestion triggers when discussing future events without calendar entry
- [ ] Follow-up suggestion triggers when action items are mentioned
- [ ] Clarification triggers when user intent is ambiguous
- [ ] Disabled when config flags are false
- [ ] No repeated suggestions in same conversation
- [ ] Suggestions feel natural, not robotic

## Implementation Notes
```python
class ProactiveBehavior:
    """Logic for when to make proactive suggestions."""

    def __init__(self, config: dict):
        self.suggest_calendar = config.get("suggest_calendar_events", True)
        self.suggest_followups = config.get("suggest_follow_ups", True)
        self.ask_clarifications = config.get("ask_clarifications", True)
        self._recent_suggestions: dict[str, float] = {}  # Cooldown tracking

    def should_suggest_calendar(
        self,
        context: EnrichedContext,
        results: dict,
        text: str
    ) -> bool:
        """
        Suggest calendar when:
        - User mentions future time ("next week", "tomorrow")
        - No calendar event exists for that time
        - Haven't suggested calendar recently
        """
        if not self.suggest_calendar:
            return False

        # Check cooldown (don't suggest twice in 5 minutes)
        if self._recently_suggested("calendar", cooldown_seconds=300):
            return False

        # Look for time indicators
        time_indicators = ["next week", "tomorrow", "monday", "tuesday", ...]
        has_time_mention = any(t in text.lower() for t in time_indicators)

        # Check if calendar result is empty
        calendar_results = results.get("calendar", {})
        no_existing_event = not calendar_results.get("events", [])

        return has_time_mention and no_existing_event
```

Integration in synthesis prompt:
```
If appropriate based on context, you may suggest:
- Creating a calendar event (if discussing future plans with no event)
- Following up via email (if action items were discussed)
- Asking for clarification (if the request is ambiguous)

Only suggest if it feels natural and helpful.
```
