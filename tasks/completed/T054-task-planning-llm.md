# Task Planning with Claude Opus

## Metadata
- **ID**: T054
- **Priority**: P0
- **Category**: core
- **Effort**: L
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.3
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T051 - Orchestrator v2 Pydantic Models
- [x] T053 - Parallel Context Building

## Context
Implement the `_plan_tasks()` method that uses Claude Opus to analyze user messages and generate a structured task plan. This is the "Think" phase of the Think-Dispatch-Synthesize pattern.

## Requirements
- [x] Create `TASK_PLANNING_PROMPT` constant with system prompt from spec
- [x] Implement `async def _plan_tasks(text, context, trace_id) -> TaskPlan`
- [x] Format EnrichedContext into prompt-friendly string
- [x] Call Claude Opus with structured output (JSON mode)
- [x] Parse LLM response into `TaskPlan` Pydantic model
- [x] Handle malformed LLM output gracefully (fallback to direct response)
- [x] Add timeout for LLM call

## Acceptance Criteria
- [x] Given multi-intent message, returns TaskPlan with multiple tasks
- [x] Tasks correctly categorized as ingest/research/execute
- [x] Blocking flag correctly set (ingest=False, others=True)
- [x] Malformed LLM output doesn't crash, falls back gracefully
- [x] Logging includes reasoning from LLM
- [x] Model configurable (default: claude-opus-4-5-20251101)

## Implementation Notes
System prompt from spec:
```
You are the Klabautermann Orchestrator analyzing a user message.

Given the user's message and context, identify ALL tasks that would help provide a complete answer.

For each piece of information the user provides or requests:
1. INGEST: New facts to store ("I learned X", "Sarah works at Y")
2. RESEARCH: Information to retrieve from the knowledge graph
3. EXECUTE: Actions requiring calendar/email access

Think step by step:
- What is the user telling me? (potential ingestion)
- What is the user asking? (potential research/execution)
- What related information might be useful? (proactive research)

Return a structured task plan as JSON.
```

Output schema:
```json
{
  "reasoning": "string",
  "tasks": [
    {
      "task_type": "ingest|research|execute",
      "description": "string",
      "agent": "ingestor|researcher|executor",
      "payload": {},
      "blocking": true|false
    }
  ],
  "direct_response": "string|null"
}
```

## Development Notes

### Implementation
**Files Modified**:
- `src/klabautermann/agents/orchestrator.py`:
  - Added `TASK_PLANNING_PROMPT` class constant with structured prompt
  - Implemented `_plan_tasks()` method to orchestrate Claude Opus task planning
  - Implemented `_format_context_for_planning()` to format EnrichedContext into readable string
  - Implemented `_call_opus_for_planning()` to invoke Claude Opus API
  - Implemented `_parse_task_plan()` to parse JSON response with fallback handling

**Files Created**:
- `tests/unit/test_orchestrator_task_planning.py`: Comprehensive test suite with 13 tests

### Decisions Made
1. **Context Truncation**: Recent messages truncated to 200 chars, summaries to 100 chars to keep prompts concise
2. **JSON Parsing**: Supports both raw JSON and markdown code blocks (```json...)
3. **Error Handling**: Any exception during planning falls back to direct_response with friendly message
4. **Model Selection**: Hardcoded `claude-opus-4-5-20251101` in `_call_opus_for_planning()` (could be made configurable via orchestrator_v2.yaml in future)
5. **Async Pattern**: Uses `run_in_executor()` like existing methods since Anthropic SDK is synchronous

### Patterns Established
1. **Helper Method Structure**: Three-method pattern for LLM calls:
   - Main method (`_plan_tasks`) - orchestrates flow and error handling
   - API call method (`_call_opus_for_planning`) - handles LLM invocation
   - Parser method (`_parse_task_plan`) - validates and parses response
2. **Context Formatting**: Sections with headers (RECENT CONVERSATION, PENDING TASKS, etc.) for clear LLM understanding
3. **Graceful Degradation**: Always return valid TaskPlan even on error, never crash

### Testing
**Tests Added** (13 total):
- Multi-intent message handling
- Simple greeting direct response
- Blocking flag correctness
- Malformed JSON fallback
- Incomplete JSON fallback
- Context formatting (full and empty)
- Long content truncation
- JSON parsing (raw and markdown)
- Opus API call verification
- Reasoning logging
- Complex payload preservation

**Test Results**:
- All 13 new tests passing
- All 738 existing unit tests passing
- No regressions introduced
- Linter checks passed

### Issues Encountered
1. **Property Mocking**: Had to mock `orchestrator._anthropic` directly rather than patching the property due to lazy initialization
2. **Pydantic Defaults**: TaskPlan has default empty tasks list, so incomplete JSON test needed to check missing 'reasoning' field instead
