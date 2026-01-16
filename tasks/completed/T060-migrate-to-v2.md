# Migrate to Orchestrator v2

## Metadata
- **ID**: T060
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 9
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T059 - Orchestrator v2 Main Workflow
- [x] T061 - Smoke Test: Full Workflow (tests pass first)

## Context
Replace the current intent classification workflow with the new Think-Dispatch-Synthesize pattern. This is a high-impact change that should be done after v2 is tested.

## Requirements
- [ ] Update `handle_user_input()` to call `handle_user_input_v2()`
- [ ] Deprecate `_classify_intent()` method (keep for rollback)
- [ ] Deprecate `IntentClassification` usage in orchestrator
- [ ] Remove intent-based routing (`_handle_search`, `_handle_action`, etc.)
- [ ] Update CLI and Telegram drivers if needed
- [ ] Add feature flag for gradual rollout (optional)
- [ ] Update logging to reflect new workflow

## Acceptance Criteria
- [ ] All existing tests pass with v2 workflow
- [ ] CLI works with v2 orchestrator
- [ ] Telegram channel works with v2 orchestrator
- [ ] Multi-intent messages handled correctly
- [ ] Single-intent messages still work
- [ ] Rollback possible by reverting to v1 workflow

## Implementation Notes
Migration approach:
1. First, keep both v1 and v2 workflows
2. Add config flag: `use_v2_workflow: true`
3. Route based on flag
4. Once stable, remove v1 code

```python
async def handle_user_input(self, text: str, thread_uuid: str, trace_id: str) -> str:
    if self.config.get("use_v2_workflow", False):
        return await self.handle_user_input_v2(text, thread_uuid, trace_id)
    else:
        # Legacy v1 workflow
        return await self._handle_user_input_v1(text, thread_uuid, trace_id)
```

Cleanup after stable:
- Remove `_classify_intent()`
- Remove `_handle_search()`, `_handle_action()`, `_handle_conversation()`
- Remove `IntentClassification` model (or mark deprecated)
