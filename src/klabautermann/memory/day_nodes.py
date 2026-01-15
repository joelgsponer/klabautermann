"""
Day Node management for the temporal spine of the knowledge graph.

Day nodes form the chronological backbone that anchors all time-bound entities
(Events, Notes, JournalEntries) via [:OCCURRED_ON] relationships.

Reference: specs/architecture/MEMORY.md Section 5, ONTOLOGY.md Section 1.3
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


async def get_or_create_day(
    neo4j: Neo4jClient,
    date: datetime,
    trace_id: str | None = None,
) -> str:
    """
    Get or create Day node for a specific date.

    Uses MERGE for idempotency - safe to call multiple times for same date.

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date to create/retrieve Day node for
        trace_id: Optional trace ID for logging

    Returns:
        Date string in YYYY-MM-DD format (Day node's primary key)

    Example:
        >>> date_str = await get_or_create_day(neo4j, datetime(2025, 1, 15))
        >>> print(date_str)  # "2025-01-15"
    """
    date_str = date.strftime("%Y-%m-%d")
    day_of_week = date.strftime("%A")
    is_weekend = day_of_week in ["Saturday", "Sunday"]

    logger.debug(
        f"[WHISPER] Getting/creating Day node for {date_str}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    query = """
    MERGE (d:Day {date: $date})
    ON CREATE SET
        d.day_of_week = $day_of_week,
        d.is_weekend = $is_weekend
    RETURN d.date as date
    """

    result = await neo4j.execute_write(
        query,
        {
            "date": date_str,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
        },
        trace_id=trace_id,
    )

    if not result:
        logger.error(
            f"[STORM] Failed to create Day node for {date_str}",
            extra={"trace_id": trace_id, "agent_name": "day_nodes"},
        )
        return date_str

    logger.debug(
        f"[WHISPER] Day node ready: {date_str} ({day_of_week})",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    return str(result[0]["date"])


async def link_to_day(
    neo4j: Neo4jClient,
    node_uuid: str,
    label: str,
    date: datetime,
    trace_id: str | None = None,
) -> None:
    """
    Link an entity to its Day node via [:OCCURRED_ON].

    Creates both the Day node (if needed) and the relationship.
    Safe to call multiple times - uses MERGE for idempotency.

    Args:
        neo4j: Connected Neo4jClient instance
        node_uuid: UUID of the entity to link
        label: Node label (Note, Event, JournalEntry)
        date: Date the entity occurred on
        trace_id: Optional trace ID for logging

    Example:
        >>> await link_to_day(neo4j, note_uuid, "Note", datetime(2025, 1, 15))
    """
    date_str = date.strftime("%Y-%m-%d")

    logger.debug(
        f"[WHISPER] Linking {label}:{node_uuid} to Day:{date_str}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    # Use string interpolation for label (safe - not user input)
    # Use parameters for date and UUID (user-controlled data)
    query = f"""
    MATCH (n:{label} {{uuid: $node_uuid}})
    MERGE (d:Day {{date: $date}})
    MERGE (n)-[:OCCURRED_ON]->(d)
    """

    await neo4j.execute_write(
        query,
        {"node_uuid": node_uuid, "date": date_str},
        trace_id=trace_id,
    )

    logger.debug(
        f"[WHISPER] Linked {label} to Day {date_str}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )


async def link_note_to_day(
    neo4j: Neo4jClient,
    note_uuid: str,
    date: datetime | None = None,
    trace_id: str | None = None,
) -> None:
    """
    Convenience method: Link a Note to its Day node.

    Uses current date if not specified. Commonly used after note creation.

    Args:
        neo4j: Connected Neo4jClient instance
        note_uuid: UUID of the Note to link
        date: Date note was created (defaults to now)
        trace_id: Optional trace ID for logging

    Example:
        >>> await link_note_to_day(neo4j, note_uuid)  # Uses today
        >>> await link_note_to_day(neo4j, note_uuid, datetime(2025, 1, 10))
    """
    if date is None:
        date = datetime.now(UTC)

    await link_to_day(neo4j, note_uuid, "Note", date, trace_id=trace_id)


async def get_day_contents(
    neo4j: Neo4jClient,
    date_str: str,
    trace_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Get all entities linked to a specific Day.

    Returns entities grouped by type (Notes, Events, JournalEntries).

    Args:
        neo4j: Connected Neo4jClient instance
        date_str: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with entity types as keys, lists of entities as values.
        Each entity includes: uuid, title, content_summarized

    Example:
        >>> contents = await get_day_contents(neo4j, "2025-01-15")
        >>> print(contents)
        {
            "Note": [{"uuid": "...", "title": "Meeting notes", ...}],
            "Event": [{"uuid": "...", "title": "Team sync", ...}],
            "JournalEntry": []
        }
    """
    logger.debug(
        f"[WHISPER] Fetching contents for Day {date_str}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    query = """
    MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(item)
    RETURN labels(item)[0] as type,
           item.uuid as uuid,
           item.title as title,
           item.content_summarized as summary,
           item.created_at as created_at
    ORDER BY item.created_at
    """

    records = await neo4j.execute_read(
        query,
        {"date": date_str},
        trace_id=trace_id,
    )

    # Group by type
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        item_type = record["type"]
        if item_type not in grouped:
            grouped[item_type] = []

        grouped[item_type].append(
            {
                "uuid": record["uuid"],
                "title": record.get("title"),
                "summary": record.get("summary"),
                "created_at": record.get("created_at"),
            }
        )

    logger.debug(
        f"[WHISPER] Day {date_str} contains {len(records)} items across {len(grouped)} types",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    return grouped


async def get_days_in_range(
    neo4j: Neo4jClient,
    start_date: str,
    end_date: str,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get all Day nodes in a date range with entity counts.

    Useful for calendar views and weekly/monthly summaries.

    Args:
        neo4j: Connected Neo4jClient instance
        start_date: Start date in YYYY-MM-DD format (inclusive)
        end_date: End date in YYYY-MM-DD format (inclusive)
        trace_id: Optional trace ID for logging

    Returns:
        List of Day records with counts of linked entities.
        Each record includes: date, day_of_week, is_weekend, note_count,
        event_count, journal_count

    Example:
        >>> days = await get_days_in_range(neo4j, "2025-01-13", "2025-01-19")
        >>> for day in days:
        ...     print(f"{day['date']} ({day['day_of_week']}): {day['note_count']} notes")
    """
    logger.debug(
        f"[WHISPER] Fetching days from {start_date} to {end_date}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    query = """
    MATCH (d:Day)
    WHERE d.date >= $start_date AND d.date <= $end_date
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(note:Note)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(event:Event)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(journal:JournalEntry)
    RETURN d.date as date,
           d.day_of_week as day_of_week,
           d.is_weekend as is_weekend,
           count(DISTINCT note) as note_count,
           count(DISTINCT event) as event_count,
           count(DISTINCT journal) as journal_count
    ORDER BY d.date
    """

    records = await neo4j.execute_read(
        query,
        {"start_date": start_date, "end_date": end_date},
        trace_id=trace_id,
    )

    logger.debug(
        f"[WHISPER] Found {len(records)} days in range",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    return records


async def get_daily_summary(
    neo4j: Neo4jClient,
    date_str: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Get summary statistics for a specific day.

    Used by the Scribe agent for daily journal generation.

    Args:
        neo4j: Connected Neo4jClient instance
        date_str: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with counts and metadata:
        - note_count: Number of notes created
        - event_count: Number of events
        - journal_count: Number of journal entries
        - day_of_week: Day name (Monday, Tuesday, etc.)
        - is_weekend: Boolean

    Example:
        >>> summary = await get_daily_summary(neo4j, "2025-01-15")
        >>> print(f"{summary['day_of_week']}: {summary['note_count']} notes")
    """
    logger.debug(
        f"[WHISPER] Generating summary for Day {date_str}",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    query = """
    MATCH (d:Day {date: $date})
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(note:Note)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(event:Event)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(journal:JournalEntry)
    RETURN d.date as date,
           d.day_of_week as day_of_week,
           d.is_weekend as is_weekend,
           count(DISTINCT note) as note_count,
           count(DISTINCT event) as event_count,
           count(DISTINCT journal) as journal_count
    """

    records = await neo4j.execute_read(
        query,
        {"date": date_str},
        trace_id=trace_id,
    )

    if not records:
        logger.warning(
            f"[STORM] No Day node found for {date_str}",
            extra={"trace_id": trace_id, "agent_name": "day_nodes"},
        )
        return {
            "date": date_str,
            "day_of_week": None,
            "is_weekend": False,
            "note_count": 0,
            "event_count": 0,
            "journal_count": 0,
        }

    summary = records[0]

    logger.debug(
        f"[WHISPER] Day {date_str} summary: {summary['note_count']} notes, "
        f"{summary['event_count']} events, {summary['journal_count']} journals",
        extra={"trace_id": trace_id, "agent_name": "day_nodes"},
    )

    return summary


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "get_or_create_day",
    "link_to_day",
    "link_note_to_day",
    "get_day_contents",
    "get_days_in_range",
    "get_daily_summary",
]
