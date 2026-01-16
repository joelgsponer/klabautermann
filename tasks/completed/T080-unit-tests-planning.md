# Unit Tests: Task Planning

## Metadata
- **ID**: T080
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.3
- Related: [TESTING.md](../../specs/quality/TESTING.md)

## Dependencies
- [x] T054 - Task Planning with Claude Opus

## Context
Unit tests for task planning logic with mocked LLM responses.

## Requirements
- [x] Test multi-intent message produces multiple tasks
- [x] Test single-intent message produces single task
- [x] Test greeting produces direct response
- [x] Test malformed LLM response fallback
- [x] Test task type classification (ingest/research/execute)
- [x] Test blocking flag assignment

## Acceptance Criteria
- [x] Correct task decomposition for various inputs
- [x] Ingest tasks marked as non-blocking
- [x] Research/execute tasks marked as blocking
- [x] LLM timeout triggers fallback
- [x] Invalid JSON triggers fallback

## Implementation Notes
Create `tests/unit/test_v2_planning.py`:

```python
import pytest
from unittest.mock import AsyncMock
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import EnrichedContext, TaskPlan

@pytest.fixture
def mock_orchestrator():
    orch = Orchestrator(config={})
    orch._call_opus = AsyncMock()
    return orch

@pytest.fixture
def empty_context():
    return EnrichedContext(
        thread_uuid="test",
        channel_type="cli",
        messages=[],
        recent_summaries=[],
        pending_tasks=[],
        recent_entities=[],
    )

class TestTaskPlanning:
    @pytest.mark.asyncio
    async def test_multi_intent_message(self, mock_orchestrator, empty_context):
        """Multi-intent message should produce multiple tasks."""
        mock_orchestrator._call_opus.return_value = '''
        {
            "reasoning": "User is telling me about Sarah AND asking about meetings AND food preferences",
            "tasks": [
                {"task_type": "ingest", "description": "Store Sarah Harvard fact", "agent": "ingestor", "payload": {"text": "Sarah studied at Harvard"}, "blocking": false},
                {"task_type": "execute", "description": "Check calendar", "agent": "executor", "payload": {"action": "calendar_search"}, "blocking": true},
                {"task_type": "research", "description": "Food preferences", "agent": "researcher", "payload": {"query": "Sarah food"}, "blocking": true}
            ],
            "direct_response": null
        }
        '''

        plan = await mock_orchestrator._plan_tasks(
            "Learned Sarah studied at Harvard. Meeting next week? Does she like italian?",
            empty_context,
            "trace-1"
        )

        assert len(plan.tasks) == 3
        assert plan.tasks[0].task_type == "ingest"
        assert plan.tasks[0].blocking is False
        assert plan.tasks[1].blocking is True

    @pytest.mark.asyncio
    async def test_greeting_direct_response(self, mock_orchestrator, empty_context):
        """Simple greeting should return direct response."""
        mock_orchestrator._call_opus.return_value = '''
        {
            "reasoning": "Simple greeting, no tasks needed",
            "tasks": [],
            "direct_response": "Ahoy! How can I help you today?"
        }
        '''

        plan = await mock_orchestrator._plan_tasks("Hello!", empty_context, "trace-1")

        assert len(plan.tasks) == 0
        assert plan.direct_response is not None

    @pytest.mark.asyncio
    async def test_malformed_json_fallback(self, mock_orchestrator, empty_context):
        """Malformed LLM response should trigger fallback."""
        mock_orchestrator._call_opus.return_value = "This is not JSON"

        plan = await mock_orchestrator._plan_tasks("Test message", empty_context, "trace-1")

        # Should fall back to direct response
        assert plan.direct_response is not None
        assert len(plan.tasks) == 0
```

## Development Notes

### Implementation Summary
Created comprehensive unit test suite at `tests/unit/test_v2_planning.py` with 18 tests covering all aspects of the v2 task planning functionality.

### Test Coverage
1. **Multi-Intent Messages** (2 tests)
   - test_multi_intent_message: Validates decomposition of complex messages into multiple tasks
   - test_single_intent_message: Validates simple single-task scenarios

2. **Direct Response** (2 tests)
   - test_greeting_direct_response: Greetings return direct response without tasks
   - test_acknowledgment_direct_response: Acknowledgments handled appropriately

3. **Task Type Classification** (3 tests)
   - test_task_type_classification_ingest: Validates ingest task classification
   - test_task_type_classification_research: Validates research task classification
   - test_task_type_classification_execute: Validates execute task classification

4. **Blocking Flag Assignment** (1 test)
   - test_blocking_flag_assignment: Verifies ingest=non-blocking, research/execute=blocking

5. **Error Handling** (4 tests)
   - test_malformed_json_fallback: Invalid JSON triggers fallback plan
   - test_timeout_triggers_fallback: asyncio.TimeoutError handled gracefully
   - test_llm_exception_fallback: Generic exceptions trigger fallback
   - test_empty_message_handling: Empty/whitespace messages handled

6. **Context Integration** (1 test)
   - test_prompt_includes_context: Verifies enriched context is passed to LLM

7. **JSON Parsing Edge Cases** (2 tests)
   - test_handles_markdown_code_block: Handles ```json code blocks
   - test_handles_json_with_extra_text: Extracts JSON from text with preamble/postamble

8. **Model Validation** (2 tests)
   - test_task_plan_model_validation: TaskPlan Pydantic model validation
   - test_planned_task_model_fields: PlannedTask model field validation

9. **Complex Scenarios** (1 test)
   - test_complex_multi_step_workflow: Multi-step workflow decomposition

### Key Implementation Details
- Used `unittest.mock.patch` to mock `Orchestrator.__init__` to avoid dependency injection
- Mocked `_anthropic` private attribute (not the property) to avoid AttributeError
- Mocked `_call_opus_for_planning` AsyncMock to simulate LLM responses
- Used real `_parse_task_plan` and `_format_context_for_planning` methods for integration testing
- Created helper function `mock_task_plan_response()` for JSON response generation
- All tests use `@pytest.mark.asyncio` for async test support

### Test Results
All 18 tests pass in 1.04s:
```
tests/unit/test_v2_planning.py::TestTaskPlanning::test_multi_intent_message PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_single_intent_message PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_greeting_direct_response PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_acknowledgment_direct_response PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_task_type_classification_ingest PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_task_type_classification_research PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_task_type_classification_execute PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_blocking_flag_assignment PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_malformed_json_fallback PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_timeout_triggers_fallback PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_llm_exception_fallback PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_empty_message_handling PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_prompt_includes_context PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_handles_markdown_code_block PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_handles_json_with_extra_text PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_task_plan_model_validation PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_planned_task_model_fields PASSED
tests/unit/test_v2_planning.py::TestTaskPlanning::test_complex_multi_step_workflow PASSED
```

### Files Modified
- Created: `tests/unit/test_v2_planning.py` (18 tests, 623 lines)
