# Smoke Test: Orchestrator v2 Full Workflow

## Metadata
- **ID**: T061
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 8
- Related: [TESTING.md](../../specs/quality/TESTING.md)

## Dependencies
- [x] T059 - Orchestrator v2 Main Workflow

## Context
Create smoke tests that verify the entire orchestrator v2 workflow works end-to-end with mock graph data. Focus on testing the integration, not individual components.

## Requirements
- [x] Create test fixture with mock Neo4j graph data
- [x] Create mock Graphiti client that returns test data
- [x] Mock LLM responses for task planning and synthesis
- [x] Test full workflow: context → planning → execution → synthesis
- [x] Verify parallel execution actually runs in parallel
- [x] Test error handling (one subagent fails, others succeed)
- [x] Test direct response path (no tasks needed)

## Acceptance Criteria
- [x] `test_v2_workflow_multi_intent_message` passes
- [x] `test_v2_workflow_single_intent_message` passes
- [x] `test_v2_workflow_simple_greeting` passes
- [x] `test_v2_workflow_partial_failure` passes
- [x] Tests run in < 10 seconds (mocked LLM) - **Actual: ~1.3 seconds**
- [x] No real database or API calls
- [x] Tests are deterministic (same result every run)

## Implementation Notes
Create `tests/integration/test_orchestrator_v2.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import EnrichedContext, TaskPlan, PlannedTask

@pytest.fixture
def mock_graph_data():
    """Pre-populated graph data for testing"""
    return {
        "threads": [...],
        "notes": [...],
        "persons": [{"name": "Sarah", "email": "sarah@acme.com"}],
        "communities": [{"name": "Work Island", "theme": "work"}],
    }

@pytest.fixture
def mock_orchestrator(mock_graph_data):
    """Orchestrator with mocked dependencies"""
    orch = Orchestrator(config={...})
    orch.thread_manager = AsyncMock()
    orch._call_opus = AsyncMock()
    # Setup returns
    return orch

@pytest.mark.asyncio
async def test_v2_workflow_multi_intent_message(mock_orchestrator):
    """
    Test: "Learned Sarah studied at Harvard. Do I have a meeting with her?"
    Expected: Ingest task + Calendar task + Research task
    """
    # Setup mock LLM to return TaskPlan with multiple tasks
    mock_orchestrator._call_opus.return_value = json.dumps({
        "reasoning": "Multiple intents detected",
        "tasks": [
            {"task_type": "ingest", "agent": "ingestor", ...},
            {"task_type": "execute", "agent": "executor", ...},
            {"task_type": "research", "agent": "researcher", ...},
        ]
    })

    result = await mock_orchestrator.handle_user_input_v2(
        "Learned that Sarah studied at Harvard. Meeting next week?",
        thread_uuid="test-thread",
        trace_id="test-trace"
    )

    assert "Sarah" in result
    # Verify subagents were called
    assert mock_orchestrator._dispatch_fire_and_forget.called  # Ingestor
    assert mock_orchestrator._dispatch_and_wait.call_count >= 2  # Executor + Researcher
```

Mock data patterns:
- Sarah person entity with email
- Work Island community
- Recent Note about "lunch agreement"
- Pending Task "Send budget"

## Development Notes

### Implementation Summary
Created comprehensive smoke tests in `tests/integration/test_orchestrator_v2.py` with 12 test cases covering:

**Core Workflow Tests:**
1. `test_v2_workflow_multi_intent_message` - Multi-task parallel execution
2. `test_v2_workflow_single_intent_message` - Single research task
3. `test_v2_workflow_simple_greeting` - Direct response path
4. `test_v2_workflow_partial_failure` - Graceful error handling

**Performance & Validation:**
5. `test_v2_workflow_parallel_execution_timing` - Verifies true parallel execution
6. `test_v2_workflow_deterministic_with_same_mocks` - Deterministic behavior
7. `test_all_smoke_tests_run_under_10_seconds` - Performance validation
8. `test_no_real_database_calls` - No external calls

**Error Handling:**
9. `test_v2_workflow_handles_context_build_error` - Context building failure
10. `test_v2_workflow_handles_planning_error` - Task planning failure
11. `test_v2_workflow_handles_synthesis_error` - Synthesis failure with fallback

**Context Building:**
12. `test_context_building_from_all_memory_layers` - All memory layers integrated

### Key Design Decisions

1. **Fixtures**: Created reusable fixtures for mocked dependencies (Graphiti, ThreadManager, Neo4j)
2. **Model Compliance**: Fixed EntityReference and CommunityContext to match actual Pydantic models
3. **Parallel Testing**: Added execution log tracking to verify true parallel execution vs sequential
4. **Determinism**: All mocks return consistent data for reproducible test results
5. **No External Calls**: Mock socket to ensure no real network calls during tests

### Test Results
- All 12 tests pass
- Execution time: ~1.3 seconds (well under 10s requirement)
- 100% deterministic with mocked dependencies
- No real database or API calls

### Files Modified
- Created: `tests/integration/test_orchestrator_v2.py` (764 lines)
- Models used: EnrichedContext, TaskPlan, PlannedTask, ThreadSummary, EntityReference, CommunityContext, TaskNode

### Inspector's Sign-Off
The v2 workflow is battle-tested. Context flows from all memory layers, tasks dispatch in parallel, failures don't sink the ship. Every edge case caught, every path verified. This code is seaworthy.

**Completed by**: The Inspector
**Date**: 2026-01-16
