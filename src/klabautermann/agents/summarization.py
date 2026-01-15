"""
LLM Summarization Pipeline for Klabautermann.

Extracts structured summaries from conversation threads using Claude Haiku.
Used by the Archivist to convert raw message history into ThreadSummary models
for long-term storage in the knowledge graph.

Reference: specs/architecture/AGENTS.md Section 1.5
Task: T039 - LLM Summarization Pipeline
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from klabautermann.core.logger import logger
from klabautermann.core.models import (
    ThreadSummary,
)
from klabautermann.utils.retry import retry_on_llm_errors


# ===========================================================================
# Constants
# ===========================================================================

# Model to use for summarization (Haiku for cost-effectiveness)
SUMMARIZATION_MODEL = "claude-3-5-haiku-20241022"

# Maximum tokens for summarization response
MAX_TOKENS = 2000

# Maximum message content length before truncation
MAX_MESSAGE_LENGTH = 1000

# System prompt for the Archivist role
ARCHIVIST_SYSTEM_PROMPT = """You are the Klabautermann Archivist—keeper of The Locker's long-term memory.

Your task is to analyze conversation threads and extract structured information for long-term storage.

SUMMARIZATION RULES:
1. Extract the ESSENCE, not the transcript
   - What topics were discussed?
   - What decisions were made?
   - What action items emerged?
   - What new information was learned?

2. Preserve ATTRIBUTION
   - Who said what (if relevant)
   - When did this conversation happen?

3. Detect CONFLICTS
   - Does this contradict existing data in The Locker?
   - If so, flag for temporal update (expire old, create new)

4. Be CONSERVATIVE
   - Only extract information explicitly stated or strongly implied
   - Mark low-confidence extractions accordingly
   - It's better to extract nothing than to hallucinate

QUALITY GUIDELINES:
- Summary should be 2-3 sentences capturing the essence
- Topics should be specific (not just "work" but "Q1 budget planning")
- Action items must have clear actions, not vague goals
- New facts should be verifiable from the conversation
- Conflicts should only be flagged when there's a clear contradiction
"""


# ===========================================================================
# Main Functions
# ===========================================================================


def format_messages(messages: list[dict]) -> str:
    """
    Format messages into a readable conversation transcript.

    Args:
        messages: List of message dicts with 'role', 'content', 'timestamp' keys.
                  'timestamp' can be float (Unix timestamp) or ISO string.

    Returns:
        Formatted string suitable for LLM consumption.

    Example:
        >>> messages = [
        ...     {"role": "user", "content": "Hello!", "timestamp": 1704067200.0},
        ...     {"role": "assistant", "content": "Hi there!", "timestamp": 1704067205.0}
        ... ]
        >>> formatted = format_messages(messages)
        >>> print(formatted)
        [2 minutes ago] User: Hello!
        [2 minutes ago] Assistant: Hi there!
    """
    formatted_lines = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp")

        # Format timestamp as relative time
        time_str = _format_timestamp(timestamp)

        # Truncate long messages
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH] + "..."

        # Clean roleplay markers and formatting (basic cleaning)
        content = content.replace("*", "").replace("**", "")

        # Capitalize role for readability
        role_str = role.capitalize()

        formatted_lines.append(f"[{time_str}] {role_str}: {content}")

    return "\n".join(formatted_lines)


def _format_timestamp(timestamp: float | str | None) -> str:
    """
    Format timestamp as relative time string.

    Args:
        timestamp: Unix timestamp (float) or ISO string or None.

    Returns:
        Relative time string like "2 hours ago" or "just now".
    """
    if timestamp is None:
        return "unknown time"

    try:
        # Convert to float if string
        if isinstance(timestamp, str):
            # Try parsing as ISO format first
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp_float = dt.timestamp()
            except ValueError:
                # Fall back to float conversion
                timestamp_float = float(timestamp)
        else:
            timestamp_float = float(timestamp)

        # Calculate time difference
        now = datetime.now(UTC).timestamp()
        delta_seconds = now - timestamp_float

        if delta_seconds < 60:
            return "just now"
        elif delta_seconds < 3600:
            minutes = int(delta_seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif delta_seconds < 86400:
            hours = int(delta_seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(delta_seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"

    except (ValueError, TypeError):
        return "unknown time"


def _create_summarization_prompt(formatted_messages: str, context: dict | None) -> str:
    """
    Create the full summarization prompt with messages and context.

    Args:
        formatted_messages: Formatted conversation transcript.
        context: Optional context dict (e.g., user info, thread metadata).

    Returns:
        Complete prompt string for the LLM.
    """
    prompt_parts = ["CONVERSATION TRANSCRIPT:\n", formatted_messages]

    if context:
        prompt_parts.append("\n\nADDITIONAL CONTEXT:")
        for key, value in context.items():
            prompt_parts.append(f"- {key}: {value}")

    prompt_parts.append(
        "\n\nPlease analyze this conversation and extract structured information "
        "using the extract_summary tool. Focus on essence, not verbatim transcription."
    )

    return "\n".join(prompt_parts)


@retry_on_llm_errors(max_retries=2)
async def summarize_thread(
    messages: list[dict],
    context: dict | None = None,
    trace_id: str | None = None,
) -> ThreadSummary:
    """
    Summarize a conversation thread using Claude Haiku.

    This function uses Anthropic's tool_use feature to get reliable structured
    JSON output matching the ThreadSummary schema. The LLM is instructed to
    extract topics, action items, new facts, and conflicts from the conversation.

    Args:
        messages: List of message dicts with 'role', 'content', 'timestamp' keys.
        context: Optional context about thread/user (e.g., {"user_name": "John"}).
        trace_id: Trace ID for logging (generated if not provided).

    Returns:
        ThreadSummary with extracted information.

    Raises:
        Exception: If API call fails after retries or response is malformed.

    Example:
        >>> messages = [
        ...     {"role": "user", "content": "I met Sarah today", "timestamp": 1704067200.0},
        ...     {"role": "assistant", "content": "Great! Tell me more", "timestamp": 1704067205.0},
        ...     {"role": "user", "content": "She's a PM at Acme", "timestamp": 1704067210.0}
        ... ]
        >>> summary = await summarize_thread(messages)
        >>> summary.topics
        ['Sarah', 'Acme', 'new contact']
    """
    import anthropic

    trace_id = trace_id or f"summ-{os.urandom(4).hex()}"

    logger.info(
        f"[CHART] Summarizing thread with {len(messages)} messages",
        extra={"trace_id": trace_id, "message_count": len(messages)},
    )

    # Format messages into readable transcript
    formatted = format_messages(messages)

    # Create full prompt with context
    prompt = _create_summarization_prompt(formatted, context)

    # Initialize Anthropic client
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    try:
        # Call LLM with tool_use for structured output
        response = client.messages.create(
            model=SUMMARIZATION_MODEL,
            max_tokens=MAX_TOKENS,
            system=ARCHIVIST_SYSTEM_PROMPT,
            tools=[
                {
                    "name": "extract_summary",
                    "description": "Extract structured summary from conversation thread",
                    "input_schema": ThreadSummary.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "extract_summary"},
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract tool use block from response
        tool_use_block = None
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_use_block = block
                break

        if not tool_use_block:
            logger.warning(
                "[SWELL] No tool_use block in LLM response, returning minimal summary",
                extra={"trace_id": trace_id},
            )
            return _create_minimal_summary(messages)

        # Parse and validate using Pydantic
        summary = ThreadSummary.model_validate(tool_use_block.input)

        # Log low-confidence extractions
        for fact in summary.new_facts:
            if fact.confidence < 0.5:
                logger.warning(
                    f"[SWELL] Low-confidence fact extraction: {fact.fact} (confidence: {fact.confidence})",
                    extra={"trace_id": trace_id},
                )

        logger.info(
            f"[BEACON] Summarization complete: {len(summary.topics)} topics, "
            f"{len(summary.action_items)} actions, {len(summary.new_facts)} facts",
            extra={
                "trace_id": trace_id,
                "topic_count": len(summary.topics),
                "action_count": len(summary.action_items),
                "fact_count": len(summary.new_facts),
                "conflict_count": len(summary.conflicts),
            },
        )

        return summary

    except anthropic.APIError as e:
        logger.error(
            f"[STORM] Anthropic API error during summarization: {e}",
            extra={"trace_id": trace_id},
            exc_info=True,
        )
        raise

    except Exception as e:
        logger.error(
            f"[STORM] Unexpected error during summarization: {e}",
            extra={"trace_id": trace_id},
            exc_info=True,
        )
        # Return minimal summary instead of crashing
        return _create_minimal_summary(messages)


def _create_minimal_summary(messages: list[dict]) -> ThreadSummary:
    """
    Create a minimal ThreadSummary when LLM extraction fails.

    This ensures graceful degradation - we still store something rather than
    losing the conversation entirely.

    Args:
        messages: Original messages from the conversation.

    Returns:
        ThreadSummary with basic information only.
    """
    # Extract participants from roles
    participants = list({msg.get("role", "unknown") for msg in messages})

    return ThreadSummary(
        summary=f"Conversation with {len(messages)} messages (summarization failed)",
        topics=[],
        action_items=[],
        new_facts=[],
        conflicts=[],
        participants=participants,
        sentiment="neutral",
    )


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "format_messages",
    "summarize_thread",
]
