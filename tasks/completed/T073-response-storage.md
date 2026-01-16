# Response Storage in Thread

## Metadata
- **ID**: T073
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.1

## Dependencies
- [x] T056 - Response Synthesis

## Context
After generating a response, store it in the thread for conversation continuity. This uses the existing ThreadManager but needs proper integration with v2 workflow.

## Requirements
- [x] Implement `_store_response(thread_uuid, user_text, response, trace_id)`
- [x] Store both user message and assistant response
- [x] Update thread's last_message_at timestamp (via ThreadManager)
- [x] Handle storage failures gracefully (don't fail the response)
- [x] Trigger fire-and-forget ingestion of the exchange

## Acceptance Criteria
- [x] Response appears in thread history
- [x] Context window includes v2 responses
- [x] Storage failure doesn't crash workflow
- [x] Ingestion of conversation triggered (when ingestor available)
- [x] Thread timestamp updated (handled by ThreadManager.add_message)

## Implementation Notes
```python
async def _store_response(
    self,
    thread_uuid: str,
    user_text: str,
    response: str,
    trace_id: str
) -> None:
    """Store the exchange in thread history."""
    try:
        # Store user message
        await self.thread_manager.add_message(
            thread_uuid=thread_uuid,
            role="user",
            content=user_text,
            metadata={"trace_id": trace_id}
        )

        # Store assistant response
        await self.thread_manager.add_message(
            thread_uuid=thread_uuid,
            role="assistant",
            content=response,
            metadata={"trace_id": trace_id}
        )

        # Fire-and-forget ingestion of the exchange
        asyncio.create_task(
            self._ingest_conversation(user_text, response, trace_id)
        )

    except Exception as e:
        logger.warning(
            f"[SWELL] Failed to store response: {e}",
            extra={"trace_id": trace_id}
        )
        # Don't fail - user already has the response
```

## Development Notes

### Implementation Complete (2026-01-16)

Implemented comprehensive response storage for v2 workflow with the following enhancements:

1. **Dual Message Storage**: Modified `_store_response()` to store both user message and assistant response, ensuring complete conversation history

2. **Signature Change**: Updated method signature from:
   ```python
   async def _store_response(thread_uuid, response, trace_id)
   ```
   to:
   ```python
   async def _store_response(thread_uuid, user_text, response, trace_id)
   ```

3. **Fire-and-Forget Ingestion**: Added optional `_ingest_conversation_exchange()` helper that:
   - Combines user and assistant messages for context-aware extraction
   - Only triggers if ingestor is available (`hasattr` check)
   - Runs as fire-and-forget (doesn't block response delivery)
   - Silently ignores errors (logs at debug level)

4. **Error Handling**:
   - Storage failures logged but don't crash workflow
   - Early return if thread_manager unavailable
   - Try/except wrapper around entire storage operation

5. **Call Sites Updated**:
   - Direct response path (line 2133)
   - Standard synthesis path (line 2216)
   - Both now pass `text` parameter for user message

6. **Test Updates**:
   - All 20 tests in `test_orchestrator_v2_workflow.py` passing
   - Updated assertions to verify both messages stored
   - Verified storage failure handling
   - Confirmed no thread_manager scenario

### Key Decisions

- **Why store user message?**: Context window needs complete conversation history for next interaction
- **Why fire-and-forget ingestion?**: Storage is critical, ingestion is not; don't risk blocking user response
- **Why hasattr check?**: Orchestrator doesn't always have ingestor initialized (test scenarios, minimal configurations)
- **Thread timestamp**: Handled automatically by ThreadManager.add_message(), no additional code needed

### Files Modified

- `/home/klabautermann/klabautermann3/src/klabautermann/agents/orchestrator.py`
  - Updated `_store_response()` method (lines 2643-2706)
  - Added `_ingest_conversation_exchange()` helper (lines 2708-2740)
  - Updated call sites at lines 2133 and 2216

- `/home/klabautermann/klabautermann3/tests/unit/test_orchestrator_v2_workflow.py`
  - Updated TestHandleUserInputV2.test_full_workflow_executes_successfully (line 145)
  - Updated TestHandleUserInputV2.test_response_stored_in_thread (lines 282-300)
  - Updated TestStoreResponse.test_stores_response_successfully (lines 539-566)
  - Updated TestStoreResponse.test_handles_storage_failure_gracefully (lines 569-579)
  - Updated TestStoreResponse.test_does_nothing_if_no_thread_manager (lines 582-592)
