"""
Journal Generation Pipeline for Klabautermann.

Transforms daily analytics into narrative journal entries with Klabautermann
personality. Uses Claude Haiku for cost-efficient creative text generation.

Reference: specs/architecture/AGENTS.md Section 1.6 (The Scribe)
Reference: specs/branding/PERSONALITY.md
Task: T045 - Journal Generation Pipeline
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from klabautermann.core.logger import logger
from klabautermann.core.models import DailyAnalytics, JournalEntry
from klabautermann.utils.retry import retry_on_llm_errors


# System prompt captures Klabautermann personality
SCRIBE_SYSTEM_PROMPT = """You are the Klabautermann Scribe—chronicler of the daily voyage.

Your role is to transform dry statistics into a narrative journal entry that captures
the day's essence with wit, wisdom, and nautical flair.

PERSONALITY:
- Write as Klabautermann—the salty sage who has seen it all
- Use nautical metaphors naturally, not forced
- Be insightful but concise
- End with a forward-looking thought
- Never be annoying or try too hard

JOURNAL STRUCTURE:
Your journal entry must follow this five-part structure:

1. VOYAGE SUMMARY
   - One-paragraph overview of the day
   - Highlight the overall theme or nature of the day
   - Set the tone (productive, challenging, calm, busy, etc.)

2. KEY INTERACTIONS
   - Notable conversations or events
   - Mention specific people or projects if significant
   - Skip this section if the day was quiet

3. PROGRESS REPORT
   - Tasks completed, projects advanced
   - Concrete accomplishments
   - Acknowledge what's still pending without dwelling

4. WORKFLOW OBSERVATIONS
   - Patterns noticed in how the Captain works
   - Suggestions for improvement (gentle, not preachy)
   - Observations about timing, focus, or habits

5. SAILOR'S THINKING
   - A brief, witty reflection in your distinctive voice
   - Forward-looking thought about tomorrow or the week
   - End on a hopeful or motivating note

EXAMPLE TONE:
"Today the Captain navigated choppy waters with 23 messages across The Bridge.
Sarah from Acme signaled progress on the Q1 budget—a fair wind at last.
Three tasks walked the plank (completed), but The Manifest still holds 7 pending items.
I notice the Captain tends to schedule back-to-back meetings on Tuesdays;
perhaps we chart a calmer course next week.
The horizon looks promising. Tomorrow brings a meeting with the board—
I've prepared the budget notes in The Locker."

RULES:
- Be honest about quiet days (don't embellish nothing into something)
- Refer to tasks as "The Manifest", memory as "The Locker", calendar as "The Charts"
- Acknowledge challenges without being negative
- Celebrate wins without being effusive
- Keep total length under 300 words"""


def format_analytics_for_prompt(analytics: DailyAnalytics) -> str:
    """
    Format DailyAnalytics into readable context for the journal prompt.

    Args:
        analytics: Daily statistics to format.

    Returns:
        Formatted string with analytics data.
    """
    # Format new entities summary
    if analytics.new_entities:
        entity_parts = [
            f"{count} {entity_type}{'s' if count > 1 else ''}"
            for entity_type, count in analytics.new_entities.items()
            if count > 0
        ]
        new_entities_summary = ", ".join(entity_parts) if entity_parts else "no new entries"
    else:
        new_entities_summary = "no new entries"

    # Format top projects
    if analytics.top_projects:
        top_projects = ", ".join(p.get("name", "Unknown") for p in analytics.top_projects[:3])
    else:
        top_projects = "no specific projects"

    # Build formatted context
    context = f"""Today's voyage statistics for {analytics.date}:
- {analytics.interaction_count} messages exchanged across The Bridge
- {analytics.tasks_completed} tasks walked the plank (completed)
- {analytics.tasks_created} new tasks added to The Manifest
- {new_entities_summary} recorded in The Locker
- {analytics.notes_created} notes captured
- {analytics.events_count} events on The Charts
- Most discussed: {top_projects}"""

    return context


@retry_on_llm_errors(max_retries=2)
async def generate_journal(
    analytics: DailyAnalytics,
    context: dict[str, Any] | None = None,
    anthropic_api_key: str | None = None,
) -> JournalEntry:
    """
    Generate daily journal entry from analytics using Claude Haiku.

    Transforms raw statistics into a narrative journal entry with
    Klabautermann personality. Uses Anthropic's tool_use for structured output.

    Args:
        analytics: Daily statistics aggregated from the knowledge graph.
        context: Optional additional context (reserved for future use).
        anthropic_api_key: Anthropic API key (if not using env var).

    Returns:
        Validated JournalEntry with all required fields.

    Raises:
        anthropic.APIError: If LLM call fails after retries.
        ValueError: If response doesn't match expected schema.

    Example:
        >>> analytics = DailyAnalytics(
        ...     date="2026-01-15",
        ...     interaction_count=23,
        ...     tasks_completed=3,
        ...     tasks_created=2,
        ...     new_entities={"Person": 1, "Organization": 1},
        ...     notes_created=1,
        ...     events_count=4,
        ...     top_projects=[{"name": "Q1 Budget"}]
        ... )
        >>> entry = await generate_journal(analytics)
        >>> assert entry.content
        >>> assert entry.summary
        >>> assert entry.mood in ["productive", "challenging", "calm", "busy"]
    """
    trace_id = f"journal_{analytics.date}"

    logger.info(
        "[CHART] Generating journal entry",
        extra={"trace_id": trace_id, "date": analytics.date, "agent_name": "scribe"},
    )

    # Initialize Anthropic client
    client = AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else AsyncAnthropic()

    # Format analytics into prompt context
    analytics_context = format_analytics_for_prompt(analytics)

    # Build user prompt
    user_prompt = f"""{analytics_context}

Generate a daily journal entry following the five-part structure:
1. VOYAGE SUMMARY
2. KEY INTERACTIONS
3. PROGRESS REPORT
4. WORKFLOW OBSERVATIONS
5. SAILOR'S THINKING

Be honest, insightful, and capture Klabautermann's voice."""

    # Define tool schema for structured output
    journal_tool = {
        "name": "write_journal",
        "description": "Write the daily journal entry with structured fields",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full journal text with all five sections clearly delineated",
                },
                "summary": {
                    "type": "string",
                    "description": "One-line summary of the day (10-15 words max)",
                },
                "highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-5 key moments or achievements from the day",
                },
                "mood": {
                    "type": "string",
                    "enum": ["productive", "challenging", "calm", "busy", "mixed", "quiet"],
                    "description": "Overall sentiment of the day",
                },
                "forward_look": {
                    "type": "string",
                    "description": "Forward-looking closing thought (1-2 sentences)",
                },
            },
            "required": ["content", "summary", "highlights", "mood", "forward_look"],
        },
    }

    # Call Claude Haiku with tool_use
    logger.debug(
        "[WHISPER] Calling Claude Haiku for journal generation",
        extra={"trace_id": trace_id, "agent_name": "scribe"},
    )

    response = await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1500,
        temperature=0.7,
        system=SCRIBE_SYSTEM_PROMPT,
        tools=[journal_tool],
        tool_choice={"type": "tool", "name": "write_journal"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract tool_use block
    tool_use_block = next((block for block in response.content if block.type == "tool_use"), None)

    if not tool_use_block:
        logger.error(
            "[STORM] No tool_use block in response",
            extra={"trace_id": trace_id, "agent_name": "scribe"},
        )
        raise ValueError("LLM response missing tool_use block")

    # Validate and parse into JournalEntry
    try:
        journal_entry = JournalEntry.model_validate(tool_use_block.input)
    except Exception as e:
        logger.error(
            "[STORM] Failed to validate journal entry",
            extra={
                "trace_id": trace_id,
                "agent_name": "scribe",
                "error": str(e),
                "raw_input": tool_use_block.input,
            },
        )
        raise ValueError(f"Invalid journal entry schema: {e}") from e

    logger.info(
        "[BEACON] Journal entry generated successfully",
        extra={
            "trace_id": trace_id,
            "agent_name": "scribe",
            "date": analytics.date,
            "mood": journal_entry.mood,
            "highlights_count": len(journal_entry.highlights),
        },
    )

    return journal_entry


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "SCRIBE_SYSTEM_PROMPT",
    "format_analytics_for_prompt",
    "generate_journal",
]
