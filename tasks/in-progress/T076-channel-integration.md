# Channel Integration for V2

## Metadata
- **ID**: T076
- **Priority**: P1
- **Category**: channel
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md)
- Related: [CHANNELS.md](../../specs/architecture/CHANNELS.md)

## Dependencies
- [x] T059 - Orchestrator v2 Main Workflow
- [x] T060 - Migrate to v2

## Context
Ensure the v2 orchestrator works correctly with all communication channels (CLI, Telegram). The channel drivers call the orchestrator, so they need to work with the new workflow.

## Requirements
- [ ] Verify CLI driver works with v2
- [ ] Verify Telegram driver works with v2
- [ ] Ensure thread_uuid is passed correctly from channels
- [ ] Ensure trace_id propagation works
- [ ] Test multi-turn conversations across channels

## Acceptance Criteria
- [ ] CLI responds to multi-intent messages correctly
- [ ] Telegram responds to multi-intent messages correctly
- [ ] Thread context maintained across turns
- [ ] No regression in single-intent handling
- [ ] Error responses displayed correctly in both channels

## Implementation Notes
CLI driver location: `src/klabautermann/channels/cli.py`
Telegram driver location: `src/klabautermann/channels/telegram.py`

Both drivers should call:
```python
response = await orchestrator.handle_user_input(
    text=user_message,
    thread_uuid=thread_uuid,
    trace_id=trace_id,
)
```

With v2 migration (T060), this will route to `handle_user_input_v2()`.

Test scenarios:
1. CLI: "I met John at Acme. What's his email?"
2. Telegram: Same multi-intent message
3. CLI → Telegram: Continue conversation across channels
