# Orchestrator v2 Main Workflow

## Metadata
- **ID**: T059
- **Priority**: P0
- **Category**: core
- **Effort**: L
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.1
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T051 - Orchestrator v2 Pydantic Models
- [x] T053 - Parallel Context Building
- [x] T054 - Task Planning with Claude Opus
- [x] T055 - Parallel Task Execution
- [x] T056 - Response Synthesis
- [x] T058 - Orchestrator v2 Configuration

## Context
Implement the main `handle_user_input_v2()` method that orchestrates the full Think-Dispatch-Synthesize workflow. This is the new entry point for the orchestrator.

## Requirements
- [x] Implement `async def handle_user_input_v2(text, thread_uuid, trace_id) -> str`
- [x] Wire together: context building → task planning → parallel execution → synthesis
- [x] Implement iterative deepening: `_needs_deeper_research()` and `_deepen_research()`
- [x] Implement `_merge_results()` for combining research rounds
- [x] Handle direct responses (no tasks needed)
- [x] Apply personality formatting (existing `_apply_personality`)
- [x] Store response in thread (existing pattern)
- [x] Comprehensive logging at each phase

## Acceptance Criteria
- [x] Full workflow executes for multi-intent message
- [x] Single-intent messages handled correctly
- [x] Simple greetings return direct response (no task planning)
- [x] Iterative deepening triggers when results insufficient
- [x] Response stored in thread correctly
- [x] Personality applied to final response
- [x] Error handling at each phase doesn't crash workflow

## Implementation Notes
Main flow from spec:
```python
async def handle_user_input_v2(self, text: str, thread_uuid: str, trace_id: str) -> str:
    # 1. Build rich context
    context = await self._build_context(thread_uuid, trace_id)

    # 2. Orchestrator thinks and plans tasks
    task_plan = await self._plan_tasks(text, context, trace_id)

    # 3. Handle direct response (no tasks)
    if task_plan.direct_response and not task_plan.tasks:
        return await self._apply_personality(task_plan.direct_response, trace_id)

    # 4. Execute tasks in parallel
    results = await self._execute_parallel(task_plan, trace_id)

    # 5. Optional: deepen research if needed
    if self._needs_deeper_research(results, task_plan):
        deeper_results = await self._deepen_research(results, trace_id)
        results = self._merge_results(results, deeper_results)

    # 6. Synthesize final response
    response = await self._synthesize_response(text, context, results, trace_id)

    # 7. Apply personality and store
    response = await self._apply_personality(response, trace_id)
    await self._store_response(thread_uuid, response, trace_id)

    return response
```

## Development Notes

### Implementation
**Files Modified**:
- `src/klabautermann/agents/orchestrator.py` - Added main v2 workflow method and helpers
- `tests/unit/test_orchestrator_v2_workflow.py` - New comprehensive test suite

**Core Methods Implemented**:
1. `handle_user_input_v2()` - Main entry point for v2 workflow
2. `_needs_deeper_research()` - Determines if follow-up research is needed
3. `_deepen_research()` - Performs iterative research deepening
4. `_extract_mentions_from_results()` - Extracts entity mentions for follow-up
5. `_merge_results()` - Combines results from multiple research rounds
6. `_store_response()` - Stores assistant response in thread

### Decisions Made

1. **Iterative Deepening Logic**: Deepening is triggered when all research tasks return results shorter than 50 characters or contain errors. This threshold balances avoiding unnecessary follow-ups with ensuring sufficient information.

2. **Result Structure Flexibility**: The `_needs_deeper_research()` method checks for response content in both `result["response"]` and at the root level to handle different result structures from subagents.

3. **Mention Extraction**: Simple regex-based extraction of capitalized words from results. Limited to 3 follow-up queries to prevent infinite loops.

4. **Max Research Depth**: Configured via `orchestrator_v2.yaml` with default of 2 rounds (initial + 1 deepening). Prevents excessive API calls.

5. **Error Handling**: Each phase of the workflow has try-except handling. Failures don't crash the entire workflow - instead they return fallback responses.

6. **Trace ID Generation**: If no trace_id is provided, one is auto-generated using `uuid.uuid4()`. This ensures all workflow steps are traceable.

### Patterns Established

1. **Workflow Orchestration**: 7-step pattern (Build Context → Think → Direct Response Check → Dispatch → Deepen → Synthesize → Store)

2. **Iterative Deepening**: Loop pattern with configurable max depth:
   ```python
   while _needs_deeper_research(results, task_plan) and depth < max_depth:
       deeper_results = await _deepen_research(results, context, trace_id)
       results = _merge_results(results, deeper_results)
       depth += 1
   ```

3. **Logging Pattern**: Each major phase logs with `[CHART]` (start/progress) or `[BEACON]` (completion). Errors log with `[STORM]`.

4. **Graceful Degradation**: If context building fails, workflow still continues with fallback. If storage fails, response is still returned.

### Testing

**Test Coverage**: 20 unit tests covering:
- Full workflow execution
- Direct response handling (no tasks)
- Iterative deepening triggering
- Error handling at each phase
- Response storage
- Personality application
- Trace ID generation
- Helper method edge cases

**Key Test Scenarios**:
1. Multi-intent message → all tasks executed → synthesis combines results
2. Simple greeting → direct response → no task execution
3. Minimal results → deepening triggered → follow-up queries executed
4. Storage failure → logged but doesn't crash workflow
5. Personality applied to all responses before returning

**Test Results**: All 20 tests pass. All 90 orchestrator-related unit tests pass.

### Issues Encountered

1. **Missing Import**: Initial implementation failed because `PlannedTask` wasn't imported. Fixed by adding to imports from `core.models`.

2. **Threshold Logic**: Initial test failed because threshold was `> 50` instead of `>= 50`. Response was exactly 50 chars. Fixed by using `>=`.

3. **Mock Interaction**: Test for iterative deepening initially failed because we mocked both `_execute_parallel` and `_deepen_research`, preventing the parallel execution count assertion. Fixed by removing `_deepen_research` mock to allow real implementation.

### Integration Notes

The v2 workflow is now complete and ready to replace the v1 `handle_user_input()` method. Key integration points:

1. **CLI/TUI Integration**: Update to call `handle_user_input_v2()` instead of `handle_user_input()`
2. **Thread Manager**: Already integrated - stores responses automatically
3. **Subagent Communication**: Uses existing `_dispatch_and_wait()` and `_dispatch_fire_and_forget()` patterns
4. **Configuration**: Reads from `orchestrator_v2.yaml` for execution parameters

### Next Steps

With T059 complete, the Orchestrator v2 implementation is finished. Recommended next tasks:
- **T060**: Switch CLI to use v2 workflow
- **T061**: Switch TUI to use v2 workflow
- **T062**: Deprecate v1 `handle_user_input()` method
- Integration testing with real Neo4j and Graphiti
- Performance testing with parallel task execution
