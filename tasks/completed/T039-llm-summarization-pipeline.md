# LLM Summarization Pipeline

## Metadata
- **ID**: T039
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: completed
- **Assignee**: alchemist

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.5 (Archivist system prompt)
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [x] T038 - Thread Summary Pydantic Models
- [x] T022 - Retry utility

## Context
The Archivist uses an LLM (Claude Haiku) to extract structured summaries from conversation threads. This pipeline takes raw messages, formats them for the LLM, and parses the response into validated Pydantic models. Quality of summarization directly impacts knowledge graph accuracy.

## Requirements
- [x] Create `src/klabautermann/agents/summarization.py`:

### Summarization Function
- [x] `summarize_thread(messages: list[dict], context: Optional[dict] = None) -> ThreadSummary`
- [x] Format messages into prompt
- [x] Call Claude Haiku with structured output
- [x] Validate and return ThreadSummary model
- [x] Use retry decorator for API calls

### Prompt Engineering
- [x] System prompt based on AGENTS.md Archivist section
- [x] Include extraction rules:
  - Extract the ESSENCE, not the transcript
  - What topics were discussed?
  - What decisions were made?
  - What action items emerged?
  - What new information was learned?
- [x] Include attribution preservation rules
- [x] Include conflict detection instructions

### Message Formatting
- [x] Format messages as conversation transcript
- [x] Include timestamps (relative: "2 hours ago")
- [x] Include role labels (User/Assistant)
- [x] Truncate very long messages (>1000 chars) with ellipsis

### Output Validation
- [x] Parse LLM response into ThreadSummary
- [x] Validate all fields against Pydantic constraints
- [x] Log warnings for low-confidence extractions (<0.5)
- [x] Return default/empty values if parsing fails (don't crash)

### Error Handling
- [x] Wrap API calls with retry decorator
- [x] Handle rate limits gracefully
- [x] Handle malformed LLM responses
- [x] Log all errors with trace_id

## Acceptance Criteria
- [x] Summarization extracts main topics from conversation
- [x] Action items extracted with assignees when mentioned
- [x] New facts extracted with entity types
- [x] Conflicts detected when contradicting existing knowledge
- [x] All output conforms to ThreadSummary model
- [x] API errors handled with retry
- [x] Unit tests with mocked LLM responses

## Implementation Notes

### Prompt Template
```python
SUMMARIZATION_PROMPT = '''
You are the Klabautermann Archivist - keeper of The Locker's long-term memory.

Analyze this conversation thread and extract structured information.

CONVERSATION:
{formatted_messages}

EXTRACTION RULES:
1. Extract the ESSENCE, not the transcript
   - What topics were discussed?
   - What decisions were made?
   - What action items emerged?
   - What new information was learned?

2. Preserve ATTRIBUTION
   - Who said what (if relevant)
   - When did this conversation happen?

3. Detect CONFLICTS
   - Does this contradict existing data?
   - If so, flag for temporal update

Return a structured summary following the exact schema provided.
'''
```

### Using Anthropic with Pydantic
```python
import anthropic
from pydantic import BaseModel

async def summarize_thread(
    messages: list[dict],
    context: Optional[dict] = None
) -> ThreadSummary:
    client = anthropic.Anthropic()

    formatted = format_messages(messages)
    prompt = SUMMARIZATION_PROMPT.format(formatted_messages=formatted)

    # Use tool_use for structured output
    response = await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=2000,
        tools=[{
            "name": "extract_summary",
            "description": "Extract structured summary from conversation",
            "input_schema": ThreadSummary.model_json_schema()
        }],
        tool_choice={"type": "tool", "name": "extract_summary"},
        messages=[{"role": "user", "content": prompt}]
    )

    # Parse tool response
    tool_use = next(
        block for block in response.content
        if block.type == "tool_use"
    )
    return ThreadSummary.model_validate(tool_use.input)
```

### Testing Strategy
- Mock the Anthropic client
- Test with sample conversation transcripts
- Verify all ThreadSummary fields populated
- Test error handling with malformed responses

---

## Development Notes

### Implementation Summary

Successfully implemented the LLM Summarization Pipeline for Sprint 3. This pipeline enables the Archivist agent to convert conversation threads into structured ThreadSummary objects using Claude Haiku with tool_use for reliable JSON extraction.

### Files Created

1. **`src/klabautermann/agents/summarization.py`** (330 lines)
   - Main summarization module with complete implementation
   - `summarize_thread()` - Core function using Anthropic tool_use API
   - `format_messages()` - Formats message list into readable transcript
   - `_format_timestamp()` - Converts timestamps to relative time strings
   - `_create_summarization_prompt()` - Builds full prompt with context
   - `_create_minimal_summary()` - Fallback for LLM failures
   - Integrated `@retry_on_llm_errors` decorator for resilience

2. **`tests/unit/test_summarization.py`** (560 lines)
   - Comprehensive test suite with 21 test cases
   - Tests for message formatting utilities
   - Tests for timestamp formatting (just now, minutes ago, hours ago, days ago)
   - Tests for summarization with mocked Anthropic API
   - Tests for error handling (API errors, validation errors, missing tool_use)
   - Tests for low confidence warnings and context inclusion
   - Real conversation example test

### Key Decisions

1. **Model Selection**: Used `claude-3-5-haiku-20241022` for cost-effectiveness
   - Summarization is pattern-based and doesn't require Sonnet's reasoning
   - Consistent with AGENTS.md specification for Archivist

2. **Structured Output via tool_use**: Used Anthropic's tool_use feature instead of JSON parsing
   - More reliable than parsing JSON from text responses
   - Leverages ThreadSummary.model_json_schema() for schema definition
   - Anthropic validates structure server-side before returning

3. **Message Truncation**: Set MAX_MESSAGE_LENGTH to 1000 chars
   - Prevents token limit issues with very long messages
   - Preserves meaningful context while reducing noise

4. **Graceful Degradation**: Return minimal summary on failures
   - Better to store basic info than lose conversation entirely
   - `_create_minimal_summary()` ensures we always return valid ThreadSummary

5. **Relative Timestamps**: Format as "2 hours ago" instead of absolute times
   - More human-readable for LLM context understanding
   - Helps with temporal reasoning in summaries

### Patterns Established

1. **Retry Integration**: Used `@retry_on_llm_errors` decorator consistently
   - Max 2 retries for LLM calls (standard for Haiku operations)
   - Handles RateLimitError and APIStatusError automatically

2. **Logging Strategy**: Nautical log levels throughout
   - `[CHART]` for major operations (summarization start)
   - `[BEACON]` for successful completions with metrics
   - `[SWELL]` for warnings (low confidence, missing tool_use)
   - `[STORM]` for errors with exc_info=True

3. **Test Mocking**: Used `monkeypatch` for environment variables
   - Cleaner than patching os.getenv directly
   - Properly isolated from actual API keys

4. **Error Context**: All errors logged with trace_id
   - Enables debugging across distributed operations
   - Consistent with existing agent patterns

### Testing Results

All 21 tests passing:
- 13 tests for message formatting and timestamp utilities
- 7 tests for summarization pipeline with various scenarios
- 1 test for realistic multi-turn conversation

Coverage includes:
- Message formatting with timestamps, truncation, roleplay cleaning
- Successful summarization with mocked API responses
- Error handling (API errors, validation errors, missing blocks)
- Low confidence warning detection
- Context inclusion in prompts
- Fallback to minimal summary on failures

### Integration Points

This module will be used by:
- **Archivist agent** (T040 - next task) for thread archival
- **Thread Manager** for summarizing inactive conversations
- **Daily Journal** generation (Scribe agent)

### Potential Improvements (Future)

1. **Confidence Calibration**: Track actual hallucination rate vs confidence scores
2. **Few-Shot Examples**: Add conversation examples to prompt for better extraction
3. **Iterative Refinement**: If confidence < threshold, ask clarifying questions
4. **Conflict Resolution**: More sophisticated logic for temporal updates
5. **Batch Summarization**: Optimize for multiple threads at once

### Notes

- Follows Alchemist principles: "The model lies - Never trust without verification"
- Conservative extraction with low confidence flags for uncertain data
- All Pydantic validation ensures type safety throughout pipeline
- Ready for integration with Archivist agent in T040
