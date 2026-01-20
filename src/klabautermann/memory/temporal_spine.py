"""
Temporal spine queries for Klabautermann.

Day nodes form the "temporal spine" of the graph - a chronological
backbone that anchors all time-bound entities via OCCURRED_ON relationships.

Reference: specs/architecture/MEMORY.md Section 5
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DayNode:
    """A Day node from the temporal spine."""

    date: str  # YYYY-MM-DD format
    day_of_week: str
    is_weekend: bool
    event_count: int
    note_count: int
    journal_count: int


@dataclass
class DayActivity:
    """An activity linked to a Day node."""

    uuid: str
    item_type: str  # Event, Note, JournalEntry, etc.
    title: str | None
    start_time: float | None
    properties: dict[str, Any]


@dataclass
class WeeklySummary:
    """Summary of activities for a week."""

    start_date: str
    end_date: str
    days: list[DaySummary]
    total_events: int
    total_notes: int


@dataclass
class DaySummary:
    """Summary of a single day."""

    date: str
    day_of_week: str
    is_weekend: bool
    activities: list[str]  # List of activity titles


# =============================================================================
# Day Node Management
# =============================================================================


async def get_or_create_day(
    neo4j: Neo4jClient,
    target_date: date | datetime | str,
    trace_id: str | None = None,
) -> str:
    """
    Get or create Day node for a specific date.

    Args:
        neo4j: Connected Neo4jClient instance
        target_date: Date to get/create (date, datetime, or YYYY-MM-DD string)
        trace_id: Optional trace ID for logging

    Returns:
        The date string (YYYY-MM-DD) of the Day node
    """
    # Normalize date input
    if isinstance(target_date, str):
        date_str = target_date
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
    elif isinstance(target_date, datetime):
        date_str = target_date.strftime("%Y-%m-%d")
        parsed_date = target_date
    else:  # date
        date_str = target_date.strftime("%Y-%m-%d")
        parsed_date = datetime.combine(target_date, datetime.min.time())

    day_of_week = parsed_date.strftime("%A")
    is_weekend = day_of_week in ["Saturday", "Sunday"]

    query = """
    MERGE (d:Day {date: $date})
    ON CREATE SET
        d.day_of_week = $day_of_week,
        d.is_weekend = $is_weekend,
        d.created_at = timestamp()
    RETURN d.date as date
    """

    result = await neo4j.execute_query(
        query,
        {"date": date_str, "day_of_week": day_of_week, "is_weekend": is_weekend},
        trace_id=trace_id,
    )

    return str(result[0]["date"]) if result else date_str


async def link_to_day(
    neo4j: Neo4jClient,
    node_uuid: str,
    node_label: str,
    target_date: date | datetime | str,
    trace_id: str | None = None,
) -> bool:
    """
    Link an entity to its Day node via OCCURRED_ON relationship.

    Args:
        neo4j: Connected Neo4jClient instance
        node_uuid: UUID of the node to link
        node_label: Label of the node (Event, Note, etc.)
        target_date: Date to link to
        trace_id: Optional trace ID for logging

    Returns:
        True if link created, False otherwise
    """
    # Normalize date
    if isinstance(target_date, str):
        date_str = target_date
    elif isinstance(target_date, datetime):
        date_str = target_date.strftime("%Y-%m-%d")
    else:  # date
        date_str = target_date.strftime("%Y-%m-%d")

    # First ensure day exists
    await get_or_create_day(neo4j, date_str, trace_id)

    # Link node to day
    query = f"""
    MATCH (n:{node_label} {{uuid: $node_uuid}})
    MATCH (d:Day {{date: $date}})
    MERGE (n)-[:OCCURRED_ON]->(d)
    RETURN n.uuid as uuid
    """

    result = await neo4j.execute_query(
        query, {"node_uuid": node_uuid, "date": date_str}, trace_id=trace_id
    )

    return bool(result)


# =============================================================================
# Day-Based Queries (#194)
# =============================================================================


async def get_day_activities(
    neo4j: Neo4jClient,
    target_date: date | datetime | str,
    trace_id: str | None = None,
) -> list[DayActivity]:
    """
    Get all activities that occurred on a specific day.

    Args:
        neo4j: Connected Neo4jClient instance
        target_date: Date to query
        trace_id: Optional trace ID for logging

    Returns:
        List of DayActivity items
    """
    # Normalize date
    if isinstance(target_date, str):
        date_str = target_date
    elif isinstance(target_date, datetime):
        date_str = target_date.strftime("%Y-%m-%d")
    else:  # date
        date_str = target_date.strftime("%Y-%m-%d")

    logger.debug(
        f"[WHISPER] Getting activities for {date_str}",
        extra={"trace_id": trace_id, "agent_name": "temporal_spine"},
    )

    query = """
    MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(item)
    RETURN item.uuid as uuid,
           labels(item)[0] as item_type,
           COALESCE(item.title, item.name, item.action) as title,
           item.start_time as start_time,
           properties(item) as properties
    ORDER BY item.start_time, item.timestamp, item.created_at
    """

    result = await neo4j.execute_query(query, {"date": date_str}, trace_id=trace_id)

    activities = [
        DayActivity(
            uuid=row["uuid"],
            item_type=row["item_type"],
            title=row.get("title"),
            start_time=row.get("start_time"),
            properties=row.get("properties", {}),
        )
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Found {len(activities)} activities for {date_str}",
        extra={"trace_id": trace_id, "agent_name": "temporal_spine"},
    )

    return activities


async def get_date_range_activities(
    neo4j: Neo4jClient,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    trace_id: str | None = None,
) -> dict[str, list[DayActivity]]:
    """
    Get activities for a date range.

    Args:
        neo4j: Connected Neo4jClient instance
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary mapping date strings to lists of activities
    """
    # Normalize dates
    if isinstance(start_date, str):
        start_str = start_date
    elif isinstance(start_date, datetime):
        start_str = start_date.strftime("%Y-%m-%d")
    else:
        start_str = start_date.strftime("%Y-%m-%d")

    if isinstance(end_date, str):
        end_str = end_date
    elif isinstance(end_date, datetime):
        end_str = end_date.strftime("%Y-%m-%d")
    else:
        end_str = end_date.strftime("%Y-%m-%d")

    logger.debug(
        f"[WHISPER] Getting activities from {start_str} to {end_str}",
        extra={"trace_id": trace_id, "agent_name": "temporal_spine"},
    )

    query = """
    MATCH (d:Day)
    WHERE d.date >= $start_date AND d.date <= $end_date
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(item)
    RETURN d.date as date,
           collect({
             uuid: item.uuid,
             item_type: labels(item)[0],
             title: COALESCE(item.title, item.name, item.action),
             start_time: item.start_time,
             properties: properties(item)
           }) as activities
    ORDER BY d.date
    """

    result = await neo4j.execute_query(
        query, {"start_date": start_str, "end_date": end_str}, trace_id=trace_id
    )

    activities_by_date: dict[str, list[DayActivity]] = {}

    for row in result:
        date_key = row["date"]
        activities_by_date[date_key] = [
            DayActivity(
                uuid=a["uuid"],
                item_type=a["item_type"],
                title=a.get("title"),
                start_time=a.get("start_time"),
                properties=a.get("properties", {}),
            )
            for a in row.get("activities", [])
            if a.get("uuid")  # Filter out empty entries
        ]

    return activities_by_date


async def get_weekly_summary(
    neo4j: Neo4jClient,
    week_start: date | datetime | str,
    trace_id: str | None = None,
) -> WeeklySummary:
    """
    Get a summary of activities for a week.

    Args:
        neo4j: Connected Neo4jClient instance
        week_start: First day of the week (typically Monday)
        trace_id: Optional trace ID for logging

    Returns:
        WeeklySummary with day-by-day breakdown
    """
    # Normalize date
    if isinstance(week_start, str):
        start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
    elif isinstance(week_start, datetime):
        start_date = week_start.date()
    else:
        start_date = week_start

    end_date = start_date + timedelta(days=6)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    query = """
    MATCH (d:Day)
    WHERE d.date >= $start_date AND d.date <= $end_date
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(item)
    WITH d, collect(COALESCE(item.title, item.name, item.action)) as activity_titles,
         sum(CASE WHEN labels(item)[0] = 'Event' THEN 1 ELSE 0 END) as event_count,
         sum(CASE WHEN labels(item)[0] = 'Note' THEN 1 ELSE 0 END) as note_count
    RETURN d.date as date,
           d.day_of_week as day_of_week,
           d.is_weekend as is_weekend,
           activity_titles,
           event_count,
           note_count
    ORDER BY d.date
    """

    result = await neo4j.execute_query(
        query, {"start_date": start_str, "end_date": end_str}, trace_id=trace_id
    )

    days = []
    total_events = 0
    total_notes = 0

    for row in result:
        day_summary = DaySummary(
            date=row["date"],
            day_of_week=row.get("day_of_week", ""),
            is_weekend=row.get("is_weekend", False),
            activities=[a for a in row.get("activity_titles", []) if a],
        )
        days.append(day_summary)
        total_events += row.get("event_count", 0)
        total_notes += row.get("note_count", 0)

    return WeeklySummary(
        start_date=start_str,
        end_date=end_str,
        days=days,
        total_events=total_events,
        total_notes=total_notes,
    )


# =============================================================================
# Entity Lookup by Date
# =============================================================================


async def find_entities_by_date(
    neo4j: Neo4jClient,
    target_date: date | datetime | str,
    entity_type: str | None = None,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find entities linked to a specific day.

    Args:
        neo4j: Connected Neo4jClient instance
        target_date: Date to search
        entity_type: Optional entity type filter (Event, Note, etc.)
        trace_id: Optional trace ID for logging

    Returns:
        List of entity dictionaries
    """
    # Normalize date
    if isinstance(target_date, str):
        date_str = target_date
    elif isinstance(target_date, datetime):
        date_str = target_date.strftime("%Y-%m-%d")
    else:
        date_str = target_date.strftime("%Y-%m-%d")

    type_clause = f"AND item:{entity_type}" if entity_type else ""

    query = f"""
    MATCH (d:Day {{date: $date}})<-[:OCCURRED_ON]-(item)
    WHERE true {type_clause}
    RETURN item.uuid as uuid,
           labels(item)[0] as entity_type,
           properties(item) as properties
    ORDER BY item.start_time, item.timestamp, item.created_at
    """

    return await neo4j.execute_query(query, {"date": date_str}, trace_id=trace_id)


async def find_entities_in_range(
    neo4j: Neo4jClient,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    entity_type: str | None = None,
    limit: int = 100,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find entities within a date range.

    Args:
        neo4j: Connected Neo4jClient instance
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        entity_type: Optional entity type filter
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        List of entity dictionaries with their dates
    """
    # Normalize dates
    if isinstance(start_date, str):
        start_str = start_date
    elif isinstance(start_date, datetime):
        start_str = start_date.strftime("%Y-%m-%d")
    else:
        start_str = start_date.strftime("%Y-%m-%d")

    if isinstance(end_date, str):
        end_str = end_date
    elif isinstance(end_date, datetime):
        end_str = end_date.strftime("%Y-%m-%d")
    else:
        end_str = end_date.strftime("%Y-%m-%d")

    type_clause = f"AND item:{entity_type}" if entity_type else ""

    query = f"""
    MATCH (d:Day)<-[:OCCURRED_ON]-(item)
    WHERE d.date >= $start_date AND d.date <= $end_date
    {type_clause}
    RETURN item.uuid as uuid,
           labels(item)[0] as entity_type,
           d.date as occurred_on,
           properties(item) as properties
    ORDER BY d.date, item.start_time, item.timestamp
    LIMIT $limit
    """

    return await neo4j.execute_query(
        query,
        {"start_date": start_str, "end_date": end_str, "limit": limit},
        trace_id=trace_id,
    )


# =============================================================================
# Day Statistics
# =============================================================================


async def get_day_statistics(
    neo4j: Neo4jClient,
    target_date: date | datetime | str,
    trace_id: str | None = None,
) -> DayNode | None:
    """
    Get statistics for a specific day.

    Args:
        neo4j: Connected Neo4jClient instance
        target_date: Date to get statistics for
        trace_id: Optional trace ID for logging

    Returns:
        DayNode with counts, or None if day doesn't exist
    """
    # Normalize date
    if isinstance(target_date, str):
        date_str = target_date
    elif isinstance(target_date, datetime):
        date_str = target_date.strftime("%Y-%m-%d")
    else:
        date_str = target_date.strftime("%Y-%m-%d")

    query = """
    MATCH (d:Day {date: $date})
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(event:Event)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(note:Note)
    OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(journal:JournalEntry)
    RETURN d.date as date,
           d.day_of_week as day_of_week,
           d.is_weekend as is_weekend,
           count(DISTINCT event) as event_count,
           count(DISTINCT note) as note_count,
           count(DISTINCT journal) as journal_count
    """

    result = await neo4j.execute_query(query, {"date": date_str}, trace_id=trace_id)

    if not result:
        return None

    row = result[0]
    return DayNode(
        date=row["date"],
        day_of_week=row.get("day_of_week", ""),
        is_weekend=row.get("is_weekend", False),
        event_count=row.get("event_count", 0),
        note_count=row.get("note_count", 0),
        journal_count=row.get("journal_count", 0),
    )


async def get_active_days_in_range(
    neo4j: Neo4jClient,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    trace_id: str | None = None,
) -> list[str]:
    """
    Get dates that have at least one activity in a range.

    Args:
        neo4j: Connected Neo4jClient instance
        start_date: Start of date range
        end_date: End of date range
        trace_id: Optional trace ID for logging

    Returns:
        List of date strings (YYYY-MM-DD) with activities
    """
    # Normalize dates
    if isinstance(start_date, str):
        start_str = start_date
    elif isinstance(start_date, datetime):
        start_str = start_date.strftime("%Y-%m-%d")
    else:
        start_str = start_date.strftime("%Y-%m-%d")

    if isinstance(end_date, str):
        end_str = end_date
    elif isinstance(end_date, datetime):
        end_str = end_date.strftime("%Y-%m-%d")
    else:
        end_str = end_date.strftime("%Y-%m-%d")

    query = """
    MATCH (d:Day)<-[:OCCURRED_ON]-(item)
    WHERE d.date >= $start_date AND d.date <= $end_date
    RETURN DISTINCT d.date as date
    ORDER BY d.date
    """

    result = await neo4j.execute_query(
        query, {"start_date": start_str, "end_date": end_str}, trace_id=trace_id
    )

    return [row["date"] for row in result]


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # Data Classes
    "DayActivity",
    "DayNode",
    "DaySummary",
    "WeeklySummary",
    # Day Management
    "get_or_create_day",
    "link_to_day",
    # Day Queries
    "find_entities_by_date",
    "find_entities_in_range",
    "get_active_days_in_range",
    "get_date_range_activities",
    "get_day_activities",
    "get_day_statistics",
    "get_weekly_summary",
]
