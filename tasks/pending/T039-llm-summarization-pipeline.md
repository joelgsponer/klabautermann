# LLM Summarization Pipeline

## Metadata
- **ID**: T039
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
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
- [ ] Create `src/klabautermann/agents/summarization.py`:

### Summarization Function
- [ ] `summarize_thread(messages: list[dict], context: Optional[dict] = None) -> ThreadSummary`
- [ ] Format messages into prompt
- [ ] Call Claude Haiku with structured output
- [ ] Validate and return ThreadSummary model
- [ ] Use retry decorator for API calls

### Prompt Engineering
- [ ] System prompt based on AGENTS.md Archivist section
- [ ] Include extraction rules:
  - Extract the ESSENCE, not the transcript
  - What topics were discussed?
  - What decisions were made?
  - What action items emerged?
  - What new information was learned?
- [ ] Include attribution preservation rules
- [ ] Include conflict detection instructions

### Message Formatting
- [ ] Format messages as conversation transcript
- [ ] Include timestamps (relative: "2 hours ago")
- [ ] Include role labels (User/Assistant)
- [ ] Truncate very long messages (>1000 chars) with ellipsis

### Output Validation
- [ ] Parse LLM response into ThreadSummary
- [ ] Validate all fields against Pydantic constraints
- [ ] Log warnings for low-confidence extractions (<0.5)
- [ ] Return default/empty values if parsing fails (don't crash)

### Error Handling
- [ ] Wrap API calls with retry decorator
- [ ] Handle rate limits gracefully
- [ ] Handle malformed LLM responses
- [ ] Log all errors with trace_id

## Acceptance Criteria
- [ ] Summarization extracts main topics from conversation
- [ ] Action items extracted with assignees when mentioned
- [ ] New facts extracted with entity types
- [ ] Conflicts detected when contradicting existing knowledge
- [ ] All output conforms to ThreadSummary model
- [ ] API errors handled with retry
- [ ] Unit tests with mocked LLM responses

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
