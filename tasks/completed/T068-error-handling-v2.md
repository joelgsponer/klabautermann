# Error Handling for v2 Workflow

## Metadata
- **ID**: T068
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 5

## Dependencies
- [x] T059 - Orchestrator v2 Main Workflow

## Context
Implement comprehensive error handling for the v2 workflow. Each phase (context, planning, execution, synthesis) can fail independently, and the system should degrade gracefully.

## Requirements
- [x] Handle context building failures (partial context is OK)
- [x] Handle task planning LLM failures (fallback to direct response)
- [x] Handle individual task execution failures (continue with others)
- [x] Handle synthesis LLM failures (return raw results summary)
- [x] Log all errors with trace_id for debugging
- [ ] Implement circuit breaker for repeated failures (deferred to future task)

## Acceptance Criteria
- [x] Context query failure doesn't crash workflow
- [x] LLM timeout triggers graceful fallback
- [x] One subagent failing doesn't block others
- [x] User always gets some response (even if degraded)
- [x] Errors logged with full context
- [ ] Circuit breaker prevents cascade failures (deferred to future task)

## Implementation Notes
```python
async def handle_user_input_v2(self, text: str, thread_uuid: str, trace_id: str) -> str:
    try:
        # 1. Build context (partial failure OK)
        context = await self._build_context_safe(thread_uuid, trace_id)

        # 2. Plan tasks (fallback to direct response on failure)
        try:
            task_plan = await asyncio.wait_for(
                self._plan_tasks(text, context, trace_id),
                timeout=self.config.planning_timeout
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"[SWELL] Task planning failed: {e}", extra={"trace_id": trace_id})
            return await self._fallback_direct_response(text, context, trace_id)

        # 3. Execute tasks (individual failures captured)
        results = await self._execute_parallel_safe(task_plan, trace_id)

        # 4. Synthesize (fallback to results summary on failure)
        try:
            response = await asyncio.wait_for(
                self._synthesize_response(text, context, results, trace_id),
                timeout=self.config.synthesis_timeout
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"[SWELL] Synthesis failed: {e}", extra={"trace_id": trace_id})
            return self._fallback_results_summary(results)

        return response

    except Exception as e:
        logger.error(f"[STORM] Workflow failed: {e}", extra={"trace_id": trace_id})
        return "I'm having trouble processing that right now. Please try again."

async def _build_context_safe(self, thread_uuid: str, trace_id: str) -> EnrichedContext:
    """Build context with partial failure tolerance."""
    results = await asyncio.gather(
        self.thread_manager.get_context_window(thread_uuid, limit=20),
        self._get_recent_summaries(hours=12),
        self._get_pending_tasks(),
        self._get_recent_entities(hours=24),
        self._get_relevant_islands(),
        return_exceptions=True,  # Don't fail if one query fails
    )

    # Extract successful results, use defaults for failures
    messages = results[0] if not isinstance(results[0], Exception) else {"messages": []}
    summaries = results[1] if not isinstance(results[1], Exception) else []
    # ... etc
```

## Development Notes

### Implementation
- **Files Modified**:
  - `src/klabautermann/agents/orchestrator.py` - Added error handling wrappers and helper methods
  - `tests/unit/test_orchestrator_v2_error_handling.py` - New comprehensive test suite
  - `tests/unit/test_orchestrator_v2_workflow.py` - Updated to use new _build_context_safe and _execute_parallel_safe methods

### Decisions Made
1. **Partial Failure Tolerance**: Used `asyncio.gather(..., return_exceptions=True)` for context building so individual memory layer failures don't crash the entire workflow
2. **Graceful Degradation**: Each phase has a fallback:
   - Context building → use empty defaults for failed queries
   - Task planning → fallback to direct Claude call without decomposition
   - Task execution → capture individual failures, continue with others
   - Synthesis → format raw results as simple summary
3. **Timeout Strategy**: Added configurable timeouts for planning (30s) and synthesis (30s) to prevent hanging
4. **Error Logging**: All errors logged with [SWELL] or [STORM] levels and trace_id for debugging

### Patterns Established
1. **Helper Methods Pattern**:
   - `_build_context_safe()` - Wraps context building with exception handling
   - `_fallback_direct_response()` - Simple LLM call when planning fails
   - `_fallback_results_summary()` - Format raw results when synthesis fails
   - `_execute_parallel_safe()` - Wrap execution with failure counting and logging

2. **Try-Except Nesting**: Inner try-except blocks for specific phases (planning, synthesis) allow recovery, outer try-except ensures user always gets a response

3. **Logging Strategy**:
   - [WHISPER] for successful fallbacks
   - [SWELL] for recoverable errors
   - [STORM] for complete workflow failures

### Testing
- Added 17 new test cases in `test_orchestrator_v2_error_handling.py`:
  - 4 tests for `_build_context_safe`
  - 3 tests for `_fallback_direct_response`
  - 4 tests for `_fallback_results_summary`
  - 3 tests for `_execute_parallel_safe`
  - 3 integration tests for workflow error handling
- All existing v2 workflow tests updated to use new safe methods
- All 37 tests pass

### Issues Encountered
1. **File Modification Conflicts**: Had to carefully insert helper methods using Python script rather than Edit tool due to concurrent modifications
2. **String Literal Escaping**: Had to fix escaped newlines (`\n`) that became literal newlines during string insertion
3. **Test Mocking**: Updated tests to mock new `_build_context_safe` and `_execute_parallel_safe` methods instead of old ones

### Deferred Items
- **Circuit Breaker**: Not implemented in this task. Would require tracking failure counts across requests and temporarily disabling failing subsystems. Deferred to future task for more complete design.

### Notes for Future Tasks
- Circuit breaker could be implemented as a decorator on helper methods
- Consider adding metrics tracking for failure rates
- May want to add user-visible degradation warnings ("Running in degraded mode")
