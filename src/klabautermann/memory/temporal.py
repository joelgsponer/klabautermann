"""
Temporal utilities for Klabautermann.

Provides time expression parsing and temporal filtering for queries like:
- "last week", "yesterday", "in 2025"
- "Who did Sarah work for last year?"
- "What meetings do I have this week?"

Reference: specs/RESEARCHER.md Section 2.5
Issue: #21 - [AGT-P-014] Implement time-filtered temporal queries
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Time Expression Types
# =============================================================================


class TimeExpressionType(str, Enum):
    """Type of temporal expression parsed from query."""

    RELATIVE_PAST = "relative_past"  # "last week", "yesterday"
    RELATIVE_FUTURE = "relative_future"  # "next week", "tomorrow"
    ABSOLUTE = "absolute"  # "in 2025", "January 15th"
    RANGE = "range"  # "between X and Y"
    AS_OF = "as_of"  # "as of last year", point-in-time snapshot
    NONE = "none"  # No temporal expression found


@dataclass
class TimeRange:
    """A parsed time range from a temporal expression."""

    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None  # For point-in-time queries
    expression_type: TimeExpressionType = TimeExpressionType.NONE
    original_expression: str | None = None

    @property
    def start_ms(self) -> int | None:
        """Get start time as milliseconds since epoch (for Neo4j)."""
        return int(self.start.timestamp() * 1000) if self.start else None

    @property
    def end_ms(self) -> int | None:
        """Get end time as milliseconds since epoch (for Neo4j)."""
        return int(self.end.timestamp() * 1000) if self.end else None

    @property
    def as_of_ms(self) -> int | None:
        """Get as_of time as milliseconds since epoch (for Neo4j)."""
        return int(self.as_of.timestamp() * 1000) if self.as_of else None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "as_of_ms": self.as_of_ms,
            "expression_type": self.expression_type.value,
            "original_expression": self.original_expression,
        }


# =============================================================================
# Time Expression Patterns
# =============================================================================

# Relative expressions with their offsets
RELATIVE_EXPRESSIONS: dict[str, tuple[timedelta, timedelta | None]] = {
    # Days
    "today": (timedelta(days=0), timedelta(days=1)),
    "yesterday": (timedelta(days=-1), timedelta(days=0)),
    "tomorrow": (timedelta(days=1), timedelta(days=2)),
    "day before yesterday": (timedelta(days=-2), timedelta(days=-1)),
    # Weeks
    "this week": (timedelta(days=0), timedelta(days=7)),
    "last week": (timedelta(days=-7), timedelta(days=0)),
    "next week": (timedelta(days=7), timedelta(days=14)),
    "past week": (timedelta(days=-7), timedelta(days=0)),
    # Months
    "this month": (timedelta(days=0), timedelta(days=30)),
    "last month": (timedelta(days=-30), timedelta(days=0)),
    "next month": (timedelta(days=30), timedelta(days=60)),
    "past month": (timedelta(days=-30), timedelta(days=0)),
    # Years
    "this year": (timedelta(days=0), timedelta(days=365)),
    "last year": (timedelta(days=-365), timedelta(days=0)),
    "next year": (timedelta(days=365), timedelta(days=730)),
    "past year": (timedelta(days=-365), timedelta(days=0)),
    # Informal
    "recently": (timedelta(days=-14), timedelta(days=0)),
    "soon": (timedelta(days=0), timedelta(days=7)),
}

# Patterns for "N days/weeks/months ago"
# Note: Longer forms (days, weeks, etc.) come first to match before shorter forms
AGO_PATTERN = re.compile(
    r"(\d+)\s*(days?|weeks?|months?|years?)\s*ago",
    re.IGNORECASE,
)

# Patterns for "in N days/weeks/months"
IN_PATTERN = re.compile(
    r"in\s*(\d+)\s*(days?|weeks?|months?|years?)",
    re.IGNORECASE,
)

# Pattern for year references like "in 2025" or "2024"
YEAR_PATTERN = re.compile(r"(?:in\s+)?(\d{4})\b")

# Pattern for "as of" expressions
AS_OF_PATTERN = re.compile(
    r"as\s+of\s+(last\s+year|last\s+month|last\s+week|\d{4})",
    re.IGNORECASE,
)


# =============================================================================
# Time Expression Parsing
# =============================================================================


def parse_time_expression(
    query: str,
    reference_time: datetime | None = None,
    timezone: str = "UTC",
) -> TimeRange:
    """
    Parse temporal expressions from a query string.

    Args:
        query: The user's query that may contain time expressions.
        reference_time: Reference point for relative expressions (default: now).
        timezone: Timezone for the reference time.

    Returns:
        TimeRange with parsed start/end times, or empty range if none found.

    Examples:
        >>> parse_time_expression("meetings last week")
        TimeRange(start=..., end=..., expression_type=RELATIVE_PAST)

        >>> parse_time_expression("who did Sarah work for in 2024")
        TimeRange(start=2024-01-01, end=2024-12-31, expression_type=ABSOLUTE)
    """
    tz = ZoneInfo(timezone)
    now = reference_time or datetime.now(tz)

    # Normalize query for matching
    query_lower = query.lower()

    # 1. Check for "as of" expressions (point-in-time snapshot)
    as_of_match = AS_OF_PATTERN.search(query_lower)
    if as_of_match:
        as_of_expr = as_of_match.group(1)
        as_of_time = _parse_as_of(as_of_expr, now)
        if as_of_time:
            return TimeRange(
                as_of=as_of_time,
                expression_type=TimeExpressionType.AS_OF,
                original_expression=as_of_match.group(0),
            )

    # 2. Check for relative expressions
    for expr, (start_delta, end_delta) in RELATIVE_EXPRESSIONS.items():
        if expr in query_lower:
            start = _start_of_day(now + start_delta, tz)
            end = _start_of_day(now + end_delta, tz) if end_delta else None
            return TimeRange(
                start=start,
                end=end,
                expression_type=(
                    TimeExpressionType.RELATIVE_PAST
                    if start_delta.days <= 0
                    else TimeExpressionType.RELATIVE_FUTURE
                ),
                original_expression=expr,
            )

    # 3. Check for "N days/weeks ago" pattern
    ago_match = AGO_PATTERN.search(query_lower)
    if ago_match:
        amount = int(ago_match.group(1))
        unit = ago_match.group(2).lower().rstrip("s")  # Normalize plural
        delta = _get_time_delta(amount, unit)
        start = _start_of_day(now - delta, tz)
        end = _start_of_day(now, tz)
        return TimeRange(
            start=start,
            end=end,
            expression_type=TimeExpressionType.RELATIVE_PAST,
            original_expression=ago_match.group(0),
        )

    # 4. Check for "in N days/weeks" pattern
    in_match = IN_PATTERN.search(query_lower)
    if in_match:
        amount = int(in_match.group(1))
        unit = in_match.group(2).lower().rstrip("s")
        delta = _get_time_delta(amount, unit)
        start = _start_of_day(now, tz)
        end = _start_of_day(now + delta, tz)
        return TimeRange(
            start=start,
            end=end,
            expression_type=TimeExpressionType.RELATIVE_FUTURE,
            original_expression=in_match.group(0),
        )

    # 5. Check for year patterns like "in 2025" or "2024"
    year_match = YEAR_PATTERN.search(query)
    if year_match:
        year = int(year_match.group(1))
        # Only match reasonable years (not random 4-digit numbers)
        if 1990 <= year <= 2100:
            start = datetime(year, 1, 1, tzinfo=tz)
            end = datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)
            return TimeRange(
                start=start,
                end=end,
                expression_type=TimeExpressionType.ABSOLUTE,
                original_expression=year_match.group(0),
            )

    # No temporal expression found
    return TimeRange(expression_type=TimeExpressionType.NONE)


def _parse_as_of(expr: str, now: datetime) -> datetime | None:
    """Parse an 'as of' expression to a point in time."""
    expr_lower = expr.lower()

    if "last year" in expr_lower:
        # End of last year
        return datetime(now.year - 1, 12, 31, 23, 59, 59, tzinfo=now.tzinfo)
    elif "last month" in expr_lower:
        # End of last month
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_of_month - timedelta(seconds=1)
    elif "last week" in expr_lower:
        # End of last week (last Sunday)
        days_since_sunday = (now.weekday() + 1) % 7
        end_of_last_week = now - timedelta(days=days_since_sunday)
        return end_of_last_week.replace(hour=23, minute=59, second=59, microsecond=0)
    elif expr_lower.isdigit() and len(expr_lower) == 4:
        year = int(expr_lower)
        return datetime(year, 12, 31, 23, 59, 59, tzinfo=now.tzinfo)

    return None


def _get_time_delta(amount: int, unit: str) -> timedelta:
    """Convert amount and unit to timedelta."""
    if unit == "day":
        return timedelta(days=amount)
    elif unit == "week":
        return timedelta(weeks=amount)
    elif unit == "month":
        return timedelta(days=amount * 30)  # Approximate
    elif unit == "year":
        return timedelta(days=amount * 365)  # Approximate
    return timedelta()


def _start_of_day(dt: datetime, tz: ZoneInfo) -> datetime:
    """Get start of day for a datetime."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# =============================================================================
# Temporal Query Execution
# =============================================================================


@dataclass
class TemporalQueryResult:
    """Result of a temporal query."""

    records: list[dict[str, Any]]
    time_range: TimeRange
    query_time_ms: float
    records_found: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "records": self.records,
            "time_range": self.time_range.to_dict(),
            "query_time_ms": round(self.query_time_ms, 2),
            "records_found": self.records_found,
        }


async def execute_temporal_query(
    client: Neo4jClient,
    query: str,
    time_range: TimeRange,
    node_labels: list[str] | None = None,
    limit: int = 50,
    trace_id: str | None = None,
) -> TemporalQueryResult:
    """
    Execute a temporal query with parsed time range.

    Filters nodes and relationships based on created_at/expired_at timestamps.

    Args:
        client: Connected Neo4j client.
        query: Search query for filtering results (name/content matching).
        time_range: Parsed time range from parse_time_expression().
        node_labels: Optional list of node labels to search (default: common types).
        limit: Maximum results to return.
        trace_id: Optional trace ID for logging.

    Returns:
        TemporalQueryResult with matching records.
    """
    import time

    start_time = time.time()

    # Default to common node types
    if not node_labels:
        node_labels = ["Person", "Organization", "Event", "Task", "Note"]

    # Build label filter
    label_filter = " OR ".join(f"n:{label}" for label in node_labels)

    # Build temporal filter based on type
    if time_range.expression_type == TimeExpressionType.AS_OF:
        # Point-in-time snapshot
        temporal_filter = """
        AND n.created_at <= $as_of_ms
        AND (n.expired_at IS NULL OR n.expired_at > $as_of_ms)
        """
        params: dict[str, Any] = {"as_of_ms": time_range.as_of_ms}
    elif time_range.start_ms and time_range.end_ms:
        # Range query
        temporal_filter = """
        AND n.created_at >= $start_ms
        AND n.created_at < $end_ms
        """
        params = {"start_ms": time_range.start_ms, "end_ms": time_range.end_ms}
    elif time_range.start_ms:
        # From start onwards
        temporal_filter = "AND n.created_at >= $start_ms"
        params = {"start_ms": time_range.start_ms}
    else:
        # No temporal filter
        temporal_filter = ""
        params = {}

    # Build the query
    cypher = f"""
    MATCH (n)
    WHERE ({label_filter})
      AND (n.name IS NOT NULL AND toLower(n.name) CONTAINS toLower($query))
      {temporal_filter}
    RETURN labels(n)[0] as type,
           n.uuid as uuid,
           n.name as name,
           n.created_at as created_at,
           n.expired_at as expired_at
    ORDER BY n.created_at DESC
    LIMIT $limit
    """

    params["query"] = query
    params["limit"] = limit

    logger.debug(
        f"[WHISPER] Executing temporal query with range: {time_range.expression_type.value}",
        extra={"trace_id": trace_id},
    )

    records = await client.execute_query(cypher, params, trace_id=trace_id)

    query_time = (time.time() - start_time) * 1000

    result_records = [
        {
            "type": r["type"],
            "uuid": r["uuid"],
            "name": r["name"],
            "created_at": r.get("created_at"),
            "expired_at": r.get("expired_at"),
        }
        for r in records
    ]

    logger.debug(
        f"[WHISPER] Temporal query found {len(result_records)} records",
        extra={"trace_id": trace_id},
    )

    return TemporalQueryResult(
        records=result_records,
        time_range=time_range,
        query_time_ms=query_time,
        records_found=len(result_records),
    )


async def get_historical_relationships(
    client: Neo4jClient,
    person_name: str,
    relationship_type: str,
    as_of: datetime,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get relationships as they existed at a point in time.

    Useful for queries like "Who did Sarah work for last year?"

    Args:
        client: Connected Neo4j client.
        person_name: Name of the person to query.
        relationship_type: Type of relationship (e.g., "WORKS_AT", "REPORTS_TO").
        as_of: Point in time to query.
        trace_id: Optional trace ID for logging.

    Returns:
        List of relationships that were active at the specified time.
    """
    as_of_ms = int(as_of.timestamp() * 1000)

    cypher = """
    MATCH (p:Person)-[r]->(target)
    WHERE toLower(p.name) CONTAINS toLower($person_name)
      AND type(r) = $rel_type
      AND r.created_at <= $as_of_ms
      AND (r.expired_at IS NULL OR r.expired_at > $as_of_ms)
    RETURN p.name as person,
           type(r) as relationship,
           labels(target)[0] as target_type,
           target.name as target_name,
           r.created_at as since,
           r.expired_at as until,
           properties(r) as properties
    ORDER BY r.created_at DESC
    """

    params = {
        "person_name": person_name,
        "rel_type": relationship_type,
        "as_of_ms": as_of_ms,
    }

    logger.debug(
        f"[WHISPER] Getting historical {relationship_type} for {person_name} as of {as_of.isoformat()}",
        extra={"trace_id": trace_id},
    )

    records = await client.execute_query(cypher, params, trace_id=trace_id)

    return [
        {
            "person": r["person"],
            "relationship": r["relationship"],
            "target_type": r["target_type"],
            "target_name": r["target_name"],
            "since": r.get("since"),
            "until": r.get("until"),
            "properties": r.get("properties", {}),
        }
        for r in records
    ]


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "TemporalQueryResult",
    "TimeExpressionType",
    "TimeRange",
    "execute_temporal_query",
    "get_historical_relationships",
    "parse_time_expression",
]
