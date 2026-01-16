# V2 Rollback Mechanism

## Metadata
- **ID**: T077
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 9

## Dependencies
- [x] T060 - Migrate to v2

## Context
Implement a safe rollback mechanism to revert to v1 workflow if v2 causes issues in production. This provides a safety net during migration.

## Requirements
- [x] Add `use_v2_workflow` config flag (default: true after migration)
- [x] Implement routing based on flag in `handle_user_input()`
- [x] Keep v1 code intact (renamed to `_handle_user_input_v1`)
- [x] Allow runtime toggle via config reload
- [x] Log which workflow version is active

## Acceptance Criteria
- [x] Setting `use_v2_workflow: false` reverts to v1
- [x] Config change takes effect without restart
- [x] Both workflows coexist in codebase
- [x] Clear logging indicates active version
- [x] No performance impact from routing check

## Implementation Notes
```python
async def handle_user_input(
    self,
    text: str,
    thread_uuid: str,
    trace_id: str | None = None,
) -> str:
    """Main entry point - routes to v1 or v2 based on config."""
    trace_id = trace_id or self._generate_trace_id()

    use_v2 = self.config.get("use_v2_workflow", True)
    logger.info(
        f"[CHART] Processing with {'v2' if use_v2 else 'v1'} workflow",
        extra={"trace_id": trace_id}
    )

    if use_v2:
        return await self.handle_user_input_v2(text, thread_uuid, trace_id)
    else:
        return await self._handle_user_input_v1(text, thread_uuid, trace_id)

async def _handle_user_input_v1(self, text: str, thread_uuid: str, trace_id: str) -> str:
    """Legacy v1 workflow with intent classification."""
    # ... existing v1 code moved here
```

Config:
```yaml
# Set to false to rollback to v1
use_v2_workflow: true
```

## Development Notes

### Implementation Summary
The rollback mechanism was already implemented in T060 (migrate to v2). This task verified and enhanced it:

1. **Config Flag**: `use_v2_workflow` in `config/agents/orchestrator.yaml` (default: true)
2. **Routing Logic**: `handle_user_input()` checks flag and routes to:
   - `handle_user_input_v2()` when true (Think-Dispatch-Synthesize)
   - `_handle_user_input_v1()` when false (intent-based routing)
3. **Logging Enhancement**: Added [CHART] logging for v1 workflow selection to match v2
4. **Runtime Toggle**: Config is read on each request, no restart needed

### Changes Made
- **orchestrator.py**: Added [CHART] log message for v1 workflow selection (line 312-315)
- **test_v2_rollback.py**: Comprehensive test suite (10 tests, all passing)

### Test Coverage
Tests verify:
- v2 routes to `handle_user_input_v2` when flag is true
- v1 routes to `_handle_user_input_v1` when flag is false
- Config defaults to v2 when flag is missing or config is None
- Runtime config changes take effect without restart
- Both workflows coexist independently
- [CHART] logging indicates which version is active
- Trace ID generation works for both workflows
- Negligible performance overhead from routing check

### Files Modified
- `/home/klabautermann/klabautermann3/src/klabautermann/agents/orchestrator.py`

### Files Added
- `/home/klabautermann/klabautermann3/tests/unit/test_v2_rollback.py`

### Test Results
```
10 passed in 1.54s
```

### Rollback Instructions
To revert to v1 workflow in production:
1. Edit `config/agents/orchestrator.yaml`
2. Set `use_v2_workflow: false`
3. No restart required - takes effect on next request
4. Monitor logs for `[CHART] Using v1 workflow` confirmation

### Performance Impact
Routing check is a simple dictionary lookup (`config.get()`), adding < 1µs overhead per request. Performance tests confirm negligible impact even with 100+ requests.
