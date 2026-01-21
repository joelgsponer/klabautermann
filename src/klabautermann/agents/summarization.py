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
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger
from klabautermann.core.models import (
    ThreadSummary,
)
from klabautermann.utils.retry import retry_on_llm_errors


if TYPE_CHECKING:
    from klabautermann.core.models import ExtractedFact, FactConflict
    from klabautermann.memory.neo4j_client import Neo4jClient


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
# Conflict Detection
# ===========================================================================


async def detect_conflicts(
    facts: list[ExtractedFact],
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> list[FactConflict]:
    """
    Compare extracted facts against current graph state to detect contradictions.

    This function checks each extracted fact against the current state of the
    knowledge graph to identify temporal changes (like job changes) or status
    updates (like project completion).

    Args:
        facts: List of facts extracted from conversation summary.
        neo4j_client: Connected Neo4jClient instance for querying.
        trace_id: Trace ID for logging.

    Returns:
        List of detected conflicts with resolution strategies.

    Example:
        >>> facts = [ExtractedFact(
        ...     entity="Sarah",
        ...     entity_type="Person",
        ...     fact="Sarah now works at TechCorp",
        ...     confidence=0.9
        ... )]
        >>> conflicts = await detect_conflicts(facts, neo4j_client)
        >>> conflicts[0].resolution
        <ConflictResolution.EXPIRE_OLD: 'expire_old'>
    """

    trace_id = trace_id or f"conflict-{os.urandom(4).hex()}"
    conflicts: list[FactConflict] = []

    logger.info(
        f"[CHART] Checking {len(facts)} facts for conflicts",
        extra={"trace_id": trace_id, "fact_count": len(facts)},
    )

    for fact in facts:
        # Route to appropriate checker based on entity type
        conflict = None

        if fact.entity_type.lower() in ["person", "contact"]:
            conflict = await _check_person_conflicts(fact, neo4j_client, trace_id)
        elif fact.entity_type.lower() in ["project", "initiative"]:
            conflict = await _check_project_conflicts(fact, neo4j_client, trace_id)
        elif fact.entity_type.lower() in ["task", "action", "todo"]:
            conflict = await _check_task_conflicts(fact, neo4j_client, trace_id)

        if conflict:
            conflicts.append(conflict)
            logger.info(
                f"[BEACON] Conflict detected: {fact.entity} - {conflict.resolution.value}",
                extra={"trace_id": trace_id, "entity": fact.entity},
            )

    logger.info(
        f"[CHART] Conflict detection complete: {len(conflicts)} conflicts found",
        extra={"trace_id": trace_id, "conflict_count": len(conflicts)},
    )

    return conflicts


async def _check_person_conflicts(
    fact: ExtractedFact,
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> FactConflict | None:
    """
    Check for conflicts with Person entity facts.

    Detects:
    - Employment changes (WORKS_AT relationship updates)
    - Relationship changes (KNOWS, REPORTS_TO updates)

    Args:
        fact: Extracted fact about a person.
        neo4j_client: Connected Neo4jClient instance.
        trace_id: Trace ID for logging.

    Returns:
        FactConflict if contradiction detected, None otherwise.
    """
    from klabautermann.core.models import ConflictResolution, FactConflict

    # Check for employment changes
    if any(
        keyword in fact.fact.lower()
        for keyword in ["works at", "joined", "now at", "employed by", "working at"]
    ):
        query = """
        MATCH (p:Person)
        WHERE toLower(p.name) = toLower($name)
        OPTIONAL MATCH (p)-[r:WORKS_AT WHERE r.expired_at IS NULL]->(o:Organization)
        RETURN p.uuid as person_uuid, o.name as current_employer, r
        """

        records = await neo4j_client.execute_read(query, {"name": fact.entity}, trace_id=trace_id)

        if records and records[0].get("current_employer"):
            current_employer = records[0]["current_employer"]
            new_employer = _extract_employer_from_fact(fact.fact)

            if new_employer and new_employer.lower() != current_employer.lower():
                logger.info(
                    f"[BEACON] Employment change detected: {fact.entity} "
                    f"from {current_employer} to {new_employer}",
                    extra={"trace_id": trace_id},
                )
                return FactConflict(
                    existing_fact=f"{fact.entity} works at {current_employer}",
                    new_fact=fact.fact,
                    entity=fact.entity,
                    resolution=ConflictResolution.EXPIRE_OLD,
                )

    # Check for relationship changes (KNOWS, REPORTS_TO)
    if any(
        keyword in fact.fact.lower()
        for keyword in [
            "reports to",
            "manager is",
            "now reports to",
            "team lead is",
        ]
    ):
        query = """
        MATCH (p:Person)
        WHERE toLower(p.name) = toLower($name)
        OPTIONAL MATCH (p)-[r:REPORTS_TO WHERE r.expired_at IS NULL]->(m:Person)
        RETURN p.uuid as person_uuid, m.name as current_manager
        """

        records = await neo4j_client.execute_read(query, {"name": fact.entity}, trace_id=trace_id)

        if records and records[0].get("current_manager"):
            current_manager = records[0]["current_manager"]
            new_manager = _extract_manager_from_fact(fact.fact)

            if new_manager and new_manager.lower() != current_manager.lower():
                logger.info(
                    f"[BEACON] Manager change detected: {fact.entity} "
                    f"from {current_manager} to {new_manager}",
                    extra={"trace_id": trace_id},
                )
                return FactConflict(
                    existing_fact=f"{fact.entity} reports to {current_manager}",
                    new_fact=fact.fact,
                    entity=fact.entity,
                    resolution=ConflictResolution.EXPIRE_OLD,
                )

    return None


async def _check_project_conflicts(
    fact: ExtractedFact,
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> FactConflict | None:
    """
    Check for conflicts with Project entity facts.

    Detects:
    - Status changes (active -> completed, on_hold, cancelled)
    - Deadline changes

    Args:
        fact: Extracted fact about a project.
        neo4j_client: Connected Neo4jClient instance.
        trace_id: Trace ID for logging.

    Returns:
        FactConflict if contradiction detected, None otherwise.
    """
    from klabautermann.core.models import ConflictResolution, FactConflict

    # Check for status changes
    if any(
        keyword in fact.fact.lower()
        for keyword in [
            "completed",
            "finished",
            "cancelled",
            "on hold",
            "paused",
            "resumed",
        ]
    ):
        query = """
        MATCH (proj:Project)
        WHERE toLower(proj.name) = toLower($name)
        RETURN proj.uuid as project_uuid, proj.status as current_status
        """

        records = await neo4j_client.execute_read(query, {"name": fact.entity}, trace_id=trace_id)

        if records and records[0].get("current_status"):
            current_status = records[0]["current_status"]
            new_status = _extract_project_status_from_fact(fact.fact)

            if new_status and new_status.lower() != current_status.lower():
                logger.info(
                    f"[BEACON] Project status change detected: {fact.entity} "
                    f"from {current_status} to {new_status}",
                    extra={"trace_id": trace_id},
                )
                return FactConflict(
                    existing_fact=f"{fact.entity} status is {current_status}",
                    new_fact=fact.fact,
                    entity=fact.entity,
                    resolution=ConflictResolution.EXPIRE_OLD,
                )

    return None


async def _check_task_conflicts(
    fact: ExtractedFact,
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> FactConflict | None:
    """
    Check for conflicts with Task entity facts.

    Detects:
    - Task completion status changes (todo -> done)
    - Task cancellation

    Args:
        fact: Extracted fact about a task.
        neo4j_client: Connected Neo4jClient instance.
        trace_id: Trace ID for logging.

    Returns:
        FactConflict if contradiction detected, None otherwise.
    """
    from klabautermann.core.models import ConflictResolution, FactConflict

    # Check for task completion
    if any(
        keyword in fact.fact.lower() for keyword in ["completed", "done", "finished", "cancelled"]
    ):
        query = """
        MATCH (task:Task)
        WHERE toLower(task.action) CONTAINS toLower($action_fragment)
        RETURN task.uuid as task_uuid, task.status as current_status, task.action as action
        """

        # Extract a fragment of the task description for matching
        action_fragment = _extract_task_action_fragment(fact.fact)

        records = await neo4j_client.execute_read(
            query, {"action_fragment": action_fragment}, trace_id=trace_id
        )

        if records and records[0].get("current_status"):
            current_status = records[0]["current_status"]
            task_action = records[0]["action"]

            # Only flag if status changed from non-terminal to terminal
            if current_status in ["todo", "in_progress"] and any(
                keyword in fact.fact.lower() for keyword in ["completed", "done", "finished"]
            ):
                logger.info(
                    f"[BEACON] Task completion detected: {task_action}",
                    extra={"trace_id": trace_id},
                )
                return FactConflict(
                    existing_fact=f"Task '{task_action}' status is {current_status}",
                    new_fact=fact.fact,
                    entity=task_action,
                    resolution=ConflictResolution.EXPIRE_OLD,
                )

    return None


def _extract_employer_from_fact(fact_text: str) -> str | None:
    """
    Extract organization name from employment fact.

    Uses regex patterns to identify employer mentions in natural language.

    Args:
        fact_text: Natural language fact about employment.

    Returns:
        Employer name if found, None otherwise.

    Example:
        >>> _extract_employer_from_fact("Sarah now works at TechCorp")
        'TechCorp'
    """
    import re

    patterns = [
        r"works at ([\w\s]+?)(?:\s+as|\s+in|\.|$)",
        r"joined ([\w\s]+?)(?:\s+as|\s+in|\.|$)",
        r"now at ([\w\s]+?)(?:\s+as|\s+in|\.|$)",
        r"employed by ([\w\s]+?)(?:\s+as|\s+in|\.|$)",
        r"working at ([\w\s]+?)(?:\s+as|\s+in|\.|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, fact_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def _extract_manager_from_fact(fact_text: str) -> str | None:
    """
    Extract manager name from reporting relationship fact.

    Args:
        fact_text: Natural language fact about reporting relationship.

    Returns:
        Manager name if found, None otherwise.

    Example:
        >>> _extract_manager_from_fact("Sarah now reports to John")
        'John'
    """
    import re

    patterns = [
        r"reports to ([\w\s]+?)(?:\.|$)",
        r"manager is ([\w\s]+?)(?:\.|$)",
        r"team lead is ([\w\s]+?)(?:\.|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, fact_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def _extract_project_status_from_fact(fact_text: str) -> str | None:
    """
    Extract project status from fact text.

    Args:
        fact_text: Natural language fact about project status.

    Returns:
        Status string if found, None otherwise.

    Example:
        >>> _extract_project_status_from_fact("Project Alpha was completed")
        'completed'
    """
    status_map = {
        "completed": ["completed", "finished", "done"],
        "cancelled": ["cancelled", "canceled", "scrapped"],
        "on_hold": ["on hold", "paused", "suspended"],
        "active": ["resumed", "restarted", "active"],
    }

    fact_lower = fact_text.lower()

    for status, keywords in status_map.items():
        if any(keyword in fact_lower for keyword in keywords):
            return status

    return None


def _extract_task_action_fragment(fact_text: str) -> str:
    """
    Extract a fragment of task action for fuzzy matching.

    Takes the first few meaningful words from the fact to use for
    matching against existing task actions in the graph.

    Args:
        fact_text: Natural language fact about a task.

    Returns:
        Action fragment suitable for CONTAINS query.

    Example:
        >>> _extract_task_action_fragment("Completed sending the budget proposal")
        'sending budget'
    """
    import re

    # Remove status words
    cleaned = re.sub(r"\b(completed|done|finished|cancelled)\b", "", fact_text, flags=re.IGNORECASE)

    # Extract meaningful words (skip articles, prepositions)
    words = [
        w
        for w in cleaned.split()
        if len(w) > 2 and w.lower() not in ["the", "and", "for", "with", "from"]
    ]

    # Return first 2-3 words for fuzzy matching
    return " ".join(words[:3]) if words else fact_text[:20]


async def apply_conflict_resolutions(
    conflicts: list[FactConflict],
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> int:
    """
    Apply automatic conflict resolutions to the knowledge graph.

    Only applies resolutions marked as EXPIRE_OLD (safe temporal updates).
    Other resolution types (USER_REVIEW, KEEP_BOTH) are left for manual handling.

    Args:
        conflicts: List of detected conflicts.
        neo4j_client: Connected Neo4jClient instance for updates.
        trace_id: Trace ID for logging.

    Returns:
        Count of resolutions successfully applied.

    Example:
        >>> conflicts = [FactConflict(
        ...     existing_fact="Sarah works at Acme",
        ...     new_fact="Sarah works at TechCorp",
        ...     entity="Sarah",
        ...     resolution=ConflictResolution.EXPIRE_OLD
        ... )]
        >>> applied = await apply_conflict_resolutions(conflicts, neo4j_client)
        >>> applied
        1
    """
    from klabautermann.core.models import ConflictResolution

    trace_id = trace_id or f"resolve-{os.urandom(4).hex()}"
    applied = 0

    logger.info(
        f"[CHART] Applying automatic conflict resolutions for {len(conflicts)} conflicts",
        extra={"trace_id": trace_id, "conflict_count": len(conflicts)},
    )

    for conflict in conflicts:
        if conflict.resolution == ConflictResolution.EXPIRE_OLD:
            success = await _expire_old_relationship(conflict, neo4j_client, trace_id)
            if success:
                applied += 1
                logger.info(
                    f"[BEACON] Expired old relationship for {conflict.entity}",
                    extra={"trace_id": trace_id, "entity": conflict.entity},
                )
        else:
            logger.info(
                f"[CHART] Skipping resolution {conflict.resolution.value} for {conflict.entity} "
                "(requires user review)",
                extra={"trace_id": trace_id, "entity": conflict.entity},
            )

    logger.info(
        f"[CHART] Applied {applied} automatic resolutions",
        extra={"trace_id": trace_id, "applied_count": applied},
    )

    return applied


async def _expire_old_relationship(
    conflict: FactConflict,
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> bool:
    """
    Expire old relationship for temporal update.

    Sets expired_at timestamp on relationships that have been superseded
    by new information (e.g., job changes, status updates).

    Args:
        conflict: Conflict with EXPIRE_OLD resolution.
        neo4j_client: Connected Neo4jClient instance.
        trace_id: Trace ID for logging.

    Returns:
        True if relationship was successfully expired, False otherwise.
    """
    # Determine relationship type from conflict facts
    rel_type = None
    if "works at" in conflict.existing_fact.lower():
        rel_type = "WORKS_AT"
    elif "reports to" in conflict.existing_fact.lower():
        rel_type = "REPORTS_TO"
    elif "status is" in conflict.existing_fact.lower():
        # This is a property update, not a relationship
        # Update the node property instead
        return await _update_node_property(conflict, neo4j_client, trace_id)

    if not rel_type:
        logger.warning(
            f"[SWELL] Could not determine relationship type from conflict: {conflict.existing_fact}",
            extra={"trace_id": trace_id},
        )
        return False

    # Expire the relationship
    query = f"""
    MATCH (n)-[r:{rel_type} WHERE r.expired_at IS NULL]->(target)
    WHERE toLower(n.name) = toLower($entity_name)
    SET r.expired_at = timestamp()
    RETURN count(r) as expired_count
    """

    try:
        records = await neo4j_client.execute_write(
            query, {"entity_name": conflict.entity}, trace_id=trace_id
        )

        expired_count = int(records[0]["expired_count"]) if records else 0
        return bool(expired_count > 0)

    except Exception as e:
        logger.error(
            f"[STORM] Failed to expire relationship for {conflict.entity}: {e}",
            extra={"trace_id": trace_id},
            exc_info=True,
        )
        return False


async def _update_node_property(
    conflict: FactConflict,
    neo4j_client: Neo4jClient,
    trace_id: str | None = None,
) -> bool:
    """
    Update node property for status changes.

    Used when conflict involves a node property (like Project.status)
    rather than a relationship.

    Args:
        conflict: Conflict involving node property.
        neo4j_client: Connected Neo4jClient instance.
        trace_id: Trace ID for logging.

    Returns:
        True if property was successfully updated, False otherwise.
    """
    # Determine node type and property from conflict
    if "status is" in conflict.existing_fact.lower():
        new_status = _extract_project_status_from_fact(conflict.new_fact)

        if not new_status:
            logger.warning(
                f"[SWELL] Could not extract new status from fact: {conflict.new_fact}",
                extra={"trace_id": trace_id},
            )
            return False

        # Try Project first, then Task
        for label in ["Project", "Task"]:
            query = f"""
            MATCH (n:{label})
            WHERE toLower(n.name) = toLower($entity_name)
               OR (n.action IS NOT NULL AND toLower(n.action) = toLower($entity_name))
            SET n.status = $new_status, n.updated_at = timestamp()
            RETURN count(n) as updated_count
            """

            try:
                records = await neo4j_client.execute_write(
                    query,
                    {"entity_name": conflict.entity, "new_status": new_status},
                    trace_id=trace_id,
                )

                updated_count = records[0]["updated_count"] if records else 0
                if updated_count > 0:
                    return True

            except Exception as e:
                logger.error(
                    f"[STORM] Failed to update {label} property for {conflict.entity}: {e}",
                    extra={"trace_id": trace_id},
                    exc_info=True,
                )

    return False


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "apply_conflict_resolutions",
    "detect_conflicts",
    "format_messages",
    "summarize_thread",
]
