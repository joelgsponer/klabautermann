# Journal Generation Pipeline

## Metadata
- **ID**: T045
- **Priority**: P1
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: alchemist

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.6 (Scribe System Prompt)
- Related: [PERSONALITY.md](../../specs/branding/PERSONALITY.md)

## Dependencies
- [x] T044 - Scribe Analytics Queries
- [x] T022 - Retry utility

## Context
The Scribe generates daily reflections in Klabautermann's voice - a salty, efficient helper with nautical metaphors. This pipeline takes the day's analytics and crafts a journal entry that captures what happened, what was accomplished, and looks ahead. The journal should feel personal and insightful, not robotic.

## Requirements
- [ ] Create `src/klabautermann/agents/journal_generation.py`:

### Journal Generation Function
- [ ] `generate_journal(analytics: DailyAnalytics, context: Optional[dict] = None) -> JournalEntry`
  - Format analytics into prompt
  - Call Claude Haiku for journal generation
  - Parse response into JournalEntry model
  - Return validated entry

### JournalEntry Model
- [ ] Add to `core/models.py`:
  ```python
  class JournalEntry(BaseModel):
      content: str  # Full journal text
      summary: str  # One-line summary
      highlights: list[str]  # Key moments
      mood: str  # overall sentiment (productive, challenging, calm, busy)
      forward_look: str  # What's ahead
  ```

### Prompt Engineering
- [ ] System prompt captures Klabautermann personality:
  - Salty sage voice
  - Nautical metaphors (natural, not forced)
  - Insightful but concise
  - Forward-looking
- [ ] Include journal structure from AGENTS.md:
  1. VOYAGE SUMMARY: One-paragraph overview
  2. KEY INTERACTIONS: Notable conversations
  3. PROGRESS REPORT: Tasks completed, projects advanced
  4. WORKFLOW OBSERVATIONS: Patterns noticed
  5. SAILOR'S THINKING: Witty reflection

### Input Formatting
- [ ] Format analytics into readable context
- [ ] Include specific names and projects mentioned
- [ ] Highlight notable achievements (tasks completed, new contacts)

## Acceptance Criteria
- [ ] Journal includes all five sections
- [ ] Klabautermann personality evident in voice
- [ ] Nautical metaphors used naturally
- [ ] Analytics data reflected in content
- [ ] Forward-looking element present
- [ ] Output validates against JournalEntry model
- [ ] Unit tests with mocked LLM

## Implementation Notes

### Prompt Template
```python
JOURNAL_PROMPT = '''
You are the Klabautermann Scribe - chronicler of the daily voyage.

Today's voyage statistics:
- {interaction_count} messages exchanged across The Bridge
- {tasks_completed} tasks walked the plank (completed)
- {tasks_created} new tasks added to The Manifest
- {new_entities_summary} new souls and ports recorded in The Locker
- Most discussed: {top_projects}

Generate a daily journal entry following this structure:

1. VOYAGE SUMMARY: One-paragraph overview of the day
2. KEY INTERACTIONS: Notable conversations or events (if any)
3. PROGRESS REPORT: Tasks completed, projects advanced
4. WORKFLOW OBSERVATIONS: Patterns noticed, suggestions for improvement
5. SAILOR'S THINKING: A brief, witty reflection in your voice

PERSONALITY RULES:
- Write as Klabautermann - the salty sage
- Reference nautical metaphors naturally
- Be insightful but concise
- End with a forward-looking thought
- Never be annoying or forced

EXAMPLE TONE:
"Today the Captain navigated choppy waters with 23 messages across The Bridge.
Sarah from Acme signaled progress on the Q1 budget - a fair wind at last.
Three tasks walked the plank, but The Manifest still holds 7 pending items.
I notice the Captain tends to schedule back-to-back meetings on Tuesdays;
perhaps we chart a calmer course next week.
The horizon looks promising. Tomorrow brings a meeting with the board -
I've prepared the budget notes in The Locker."
'''

async def generate_journal(
    analytics: DailyAnalytics,
    context: Optional[dict] = None
) -> JournalEntry:
    """Generate daily journal entry from analytics."""
    client = anthropic.Anthropic()

    # Format analytics
    new_entities_summary = ", ".join(
        f"{count} {entity_type}s"
        for entity_type, count in analytics.new_entities.items()
        if count > 0
    ) or "no new entries"

    top_projects = ", ".join(
        p["name"] for p in analytics.top_projects
    ) or "no specific projects"

    prompt = JOURNAL_PROMPT.format(
        interaction_count=analytics.interaction_count,
        tasks_completed=analytics.tasks_completed,
        tasks_created=analytics.tasks_created,
        new_entities_summary=new_entities_summary,
        top_projects=top_projects
    )

    response = await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1500,
        tools=[{
            "name": "write_journal",
            "description": "Write the daily journal entry",
            "input_schema": JournalEntry.model_json_schema()
        }],
        tool_choice={"type": "tool", "name": "write_journal"},
        messages=[{"role": "user", "content": prompt}]
    )

    tool_use = next(
        block for block in response.content
        if block.type == "tool_use"
    )
    return JournalEntry.model_validate(tool_use.input)
```

### Testing Strategy
- Mock Anthropic client
- Test with various analytics scenarios (busy day, quiet day, many tasks)
- Verify all JournalEntry fields populated
- Check mood classification is sensible
