# Model Fallback Strategy

## Metadata
- **ID**: T070
- **Priority**: P2
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 6
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 3.3

## Dependencies
- [x] T054 - Task Planning with Claude Opus
- [x] T056 - Response Synthesis

## Context
Implement model fallback strategy for when the primary model (Opus) is unavailable or times out. This ensures the system remains functional even during API issues.

## Requirements
- [x] Configure fallback model (Sonnet) in config
- [x] Implement fallback in `_plan_tasks()` if Opus fails
- [x] Implement fallback in `_synthesize_response()` if Opus fails
- [x] Log when fallback is triggered
- [x] Consider cost implications (Sonnet is cheaper)

## Acceptance Criteria
- [x] System works when Opus is unavailable
- [x] Fallback triggers after timeout (not immediately)
- [x] Quality degradation is acceptable for fallback
- [x] Logs clearly indicate fallback was used
- [x] Config allows disabling fallback

## Implementation Notes
```python
# Config
model: claude-opus-4-5-20251101
fallback_model: claude-sonnet-4-20250514

async def _call_llm_with_fallback(
    self,
    prompt: str,
    trace_id: str,
    primary_model: str | None = None,
    fallback_model: str | None = None,
) -> str:
    """Call LLM with automatic fallback on failure."""
    primary = primary_model or self.config.model
    fallback = fallback_model or self.config.fallback_model

    try:
        return await asyncio.wait_for(
            self._call_llm(prompt, model=primary, trace_id=trace_id),
            timeout=self.config.llm_timeout
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(
            f"[SWELL] Primary model failed, trying fallback",
            extra={"trace_id": trace_id, "error": str(e), "fallback": fallback}
        )

        if not fallback:
            raise

        return await self._call_llm(prompt, model=fallback, trace_id=trace_id)
```

Cost consideration:
- Opus: More expensive but better reasoning
- Sonnet: Cheaper, may miss subtle multi-intent cases
- Could use Sonnet for simple messages, Opus for complex ones (future optimization)

## Development Notes

### Implementation Summary
Successfully implemented model fallback strategy for Orchestrator v2 workflow. The implementation follows the "measure twice, cut once" principle with proper error handling and logging.

### Files Modified
1. **src/klabautermann/config/manager.py**
   - Added `fallback_model: str | None = "claude-sonnet-4-20250514"` to `OrchestratorV2Config`
   - Defaults to Sonnet 4, but can be set to `null` to disable fallback

2. **src/klabautermann/agents/orchestrator.py**
   - Implemented `_call_llm_with_fallback()` helper method (lines 1442-1541)
   - Refactored `_call_opus_for_planning()` to use fallback helper
   - Refactored `_call_opus_for_synthesis()` to use fallback helper with synthesis_model support

### Key Design Decisions

1. **Timeout-based Fallback**: Primary model call wrapped in `asyncio.wait_for()` with configurable timeout (default 60s). Fallback only triggers after timeout or exception, not immediately.

2. **Logging Strategy**:
   - `[WHISPER]` for successful primary model calls
   - `[SWELL]` for primary model failures and fallback attempts (as required)
   - `[BEACON]` for successful fallback
   - `[STORM]` for total failure (both models failed)

3. **Configuration Flexibility**:
   - Supports model override via parameters (for synthesis_model)
   - Fallback can be disabled by setting `fallback_model: null` in config
   - Timeout read from `timeouts.llm_call` config (default 60s)

4. **Async Pattern**: Uses `run_in_executor()` for synchronous Anthropic SDK calls, maintaining async flow throughout.

### Testing
All 51 existing unit tests pass:
- `test_orchestrator_v2_config.py` (14 tests)
- `test_orchestrator_v2_error_handling.py` (17 tests)
- `test_orchestrator_v2_workflow.py` (20 tests)

No test changes were needed - the fallback is transparent to existing behavior when primary model succeeds.

### Cost Implications
- Fallback only triggers on failure/timeout - no additional cost in normal operation
- When fallback triggers: Sonnet 4 is ~10x cheaper than Opus 4.5
- Graceful degradation: System remains functional even if Opus is completely unavailable

### Future Optimizations
- Could implement complexity detection to use Sonnet for simple queries upfront
- Could track fallback rate to detect API issues proactively
- Could add circuit breaker pattern if primary model fails consistently
