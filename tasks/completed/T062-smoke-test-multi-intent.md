# Smoke Test: Multi-Intent Message Handling

## Metadata
- **ID**: T062
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 8.1
- Related: [TESTING.md](../../specs/quality/TESTING.md)

## Dependencies
- [x] T061 - Smoke Test: Orchestrator v2 Full Workflow

## Context
Create specific smoke tests for the example flows from MAINAGENT.md Section 8. These tests verify the key scenarios that motivated the v2 redesign.

## Requirements
- [ ] Test example 8.1: Multi-intent "Sarah studied at Harvard + meeting + italian"
- [ ] Test example 8.2: Follow-up "let's follow up with her"
- [ ] Test example 8.3: Proactive suggestion "no all good"
- [ ] Verify correct task decomposition for each scenario
- [ ] Verify correct agent routing (ingestor, researcher, executor)
- [ ] Verify proactive behavior triggers appropriately

## Acceptance Criteria
- [ ] `test_scenario_multi_intent_sarah` matches expected task plan
- [ ] `test_scenario_followup_email` triggers email draft
- [ ] `test_scenario_proactive_calendar` suggests calendar event
- [ ] Task plans match spec examples exactly
- [ ] Response synthesis includes all gathered information
- [ ] Tests document expected behavior for regression

## Implementation Notes
Add to `tests/integration/test_orchestrator_v2.py`:

```python
class TestMainAgentScenarios:
    """Tests for MAINAGENT.md Section 8 example flows"""

    @pytest.mark.asyncio
    async def test_scenario_multi_intent_sarah(self, mock_orchestrator):
        """
        MAINAGENT.md 8.1: Multi-Intent Message

        Input: "Learned that Sarah has studied at Harvard.
                Do I have a meeting with her next week for lunch?
                Does she like italian?"

        Expected Tasks:
        1. INGEST: "Sarah studied at Harvard" → @ingestor (fire-and-forget)
        2. EXECUTE: Check calendar for meetings with Sarah → @executor (wait)
        3. RESEARCH: Events/notes about Sarah next week → @researcher (wait)
        4. RESEARCH: Sarah's food preferences → @researcher (wait)
        """
        # Setup mock context with Note "Agreed to lunch with Sarah"
        mock_orchestrator._get_recent_summaries.return_value = [
            {"summary": "Agreed to lunch with Sarah next week", "channel": "cli"}
        ]

        # Setup mock Graphiti search to return food preference
        mock_orchestrator.graphiti.search.return_value = [
            {"fact": "Sarah loves italian food", "score": 0.9}
        ]

        # Setup mock calendar to return no events
        mock_orchestrator._dispatch_and_wait.side_effect = [
            {"events": []},  # Calendar
            {"results": [{"fact": "Agreed to lunch"}]},  # Events search
            {"results": [{"fact": "Sarah loves italian"}]},  # Food prefs
        ]

        result = await mock_orchestrator.handle_user_input_v2(
            "Learned that Sarah has studied at Harvard. "
            "Do I have a meeting with her next week for lunch? "
            "Does she like italian?",
            thread_uuid="test",
            trace_id="test"
        )

        # Verify response mentions:
        # - No calendar event
        # - Note about lunch agreement
        # - Italian preference
        # - Proactive follow-up suggestion
        assert "calendar" in result.lower() or "event" in result.lower()
        assert "italian" in result.lower()
        assert "follow" in result.lower() or "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_scenario_followup_email(self, mock_orchestrator):
        """
        MAINAGENT.md 8.2: Follow-Up Email

        Input: "Oh yes let's follow up with her."
        Context: Previous conversation about Sarah lunch

        Expected Tasks:
        1. RESEARCH: Get Sarah's email address → @researcher (wait)
        2. EXECUTE: Draft email to Sarah → @executor (wait)
        """
        # Setup context from previous turn
        mock_orchestrator.thread_manager.get_context_window.return_value = {
            "messages": [
                {"role": "user", "content": "Does Sarah like italian?"},
                {"role": "assistant", "content": "She does! Should I follow up?"},
            ]
        }

        result = await mock_orchestrator.handle_user_input_v2(
            "Oh yes let's follow up with her.",
            thread_uuid="test",
            trace_id="test"
        )

        # Verify email draft in response
        assert "email" in result.lower() or "dear sarah" in result.lower()

    @pytest.mark.asyncio
    async def test_scenario_proactive_calendar(self, mock_orchestrator):
        """
        MAINAGENT.md 8.3: Proactive Calendar Suggestion

        Input: "Oh now I remember, no all good."
        Context: Discussion about lunch with Sarah, no calendar event

        Expected: Proactive suggestion to add calendar event
        """
        result = await mock_orchestrator.handle_user_input_v2(
            "Oh now I remember, no all good.",
            thread_uuid="test",
            trace_id="test"
        )

        # Verify proactive calendar suggestion
        assert "calendar" in result.lower() or "event" in result.lower()
```
