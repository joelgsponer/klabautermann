# Response Synthesis with Claude Opus

## Metadata
- **ID**: T056
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.5
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T051 - Orchestrator v2 Pydantic Models
- [x] T055 - Parallel Task Execution

## Context
Implement the `_synthesize_response()` method that combines results from all subagents into a coherent response. This is the "Synthesize" phase of Think-Dispatch-Synthesize.

## Requirements
- [ ] Create `SYNTHESIS_PROMPT` constant with system prompt from spec
- [ ] Implement `async def _synthesize_response(text, context, results, trace_id) -> str`
- [ ] Implement `_format_context(context)` helper for readable context
- [ ] Implement `_format_results(results)` helper for readable results
- [ ] Call Claude Opus with formatted prompt
- [ ] Handle empty results (all tasks failed)
- [ ] Enable proactive suggestions based on config

## Acceptance Criteria
- [ ] Generates coherent response from multiple task results
- [ ] Acknowledges ingested information when relevant
- [ ] Offers proactive follow-ups (calendar, email) when appropriate
- [ ] Handles missing information honestly ("I don't have that")
- [ ] Response maintains Klabautermann personality
- [ ] Works when some tasks failed (uses available results)

## Implementation Notes
Synthesis prompt from spec:
```
You are synthesizing a response for the user based on gathered information.

Original message: {original_text}

Context:
{formatted_context}

Results from subagents:
{formatted_results}

Instructions:
1. Answer the user's questions using the gathered information
2. If information is missing or uncertain, say so honestly
3. Be proactive - suggest follow-up actions if appropriate
4. If you ingested new information, briefly acknowledge it
5. Keep the response concise but complete
```

Helpers should format context/results in readable XML or markdown.
