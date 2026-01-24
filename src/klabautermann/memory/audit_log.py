"""
Audit Log Persistence for Klabautermann.

Provides persistent storage and querying of audit entries in Neo4j.
The HullCleaner generates AuditEntry objects during maintenance operations;
this module stores them as AuditLog nodes for historical review.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 5
Issue: #87
"""

from __future__ import annotations

import json
import time
import uuid as uuid_lib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.ontology import NodeLabel


if TYPE_CHECKING:
    from klabautermann.agents.hull_cleaner import AuditEntry
    from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Audit Query Filters
# ===========================================================================


@dataclass
class AuditQueryFilter:
    """Filter parameters for querying audit log entries."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    action_types: list[str] | None = None
    entity_types: list[str] | None = None
    agent_name: str | None = None
    limit: int = 100
    offset: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert filter to dictionary."""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "action_types": self.action_types,
            "entity_types": self.entity_types,
            "agent_name": self.agent_name,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass
class StoredAuditEntry:
    """An audit entry retrieved from Neo4j."""

    uuid: str
    timestamp: datetime
    action: str
    entity_type: str
    entity_id: str
    reason: str
    agent_name: str
    metadata: dict[str, Any]
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "uuid": self.uuid,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "reason": self.reason,
            "agent_name": self.agent_name,
            "metadata": self.metadata,
            "trace_id": self.trace_id,
        }


@dataclass
class AuditLogStats:
    """Statistics about audit log entries."""

    total_entries: int
    entries_by_action: dict[str, int]
    entries_by_entity_type: dict[str, int]
    date_range_start: datetime | None
    date_range_end: datetime | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_entries": self.total_entries,
            "entries_by_action": self.entries_by_action,
            "entries_by_entity_type": self.entries_by_entity_type,
            "date_range_start": (
                self.date_range_start.isoformat() if self.date_range_start else None
            ),
            "date_range_end": (self.date_range_end.isoformat() if self.date_range_end else None),
        }


# ===========================================================================
# Persistence Functions
# ===========================================================================


async def save_audit_entry(
    neo4j: Neo4jClient,
    entry: AuditEntry,
    agent_name: str = "hull_cleaner",
    trace_id: str | None = None,
) -> str:
    """
    Save a single audit entry to Neo4j.

    Creates an AuditLog node with the entry's properties.

    Args:
        neo4j: Connected Neo4j client.
        entry: The AuditEntry to persist.
        agent_name: Name of the agent that generated this entry.
        trace_id: Optional trace ID for logging.

    Returns:
        UUID of the created AuditLog node.
    """
    audit_uuid = str(uuid_lib.uuid4())
    created_at = time.time()

    # Serialize metadata to JSON string for Neo4j storage
    metadata_json = json.dumps(entry.metadata) if entry.metadata else "{}"

    query = f"""
    CREATE (al:{NodeLabel.AUDIT_LOG.value} {{
        uuid: $uuid,
        timestamp: $timestamp,
        action: $action,
        entity_type: $entity_type,
        entity_id: $entity_id,
        reason: $reason,
        agent_name: $agent_name,
        metadata: $metadata,
        trace_id: $trace_id,
        created_at: $created_at
    }})
    RETURN al.uuid as uuid
    """

    result = await neo4j.execute_write(
        query,
        {
            "uuid": audit_uuid,
            "timestamp": entry.timestamp.isoformat(),
            "action": entry.action.value,
            "entity_type": entry.entity_type,
            "entity_id": str(entry.entity_id),
            "reason": entry.reason,
            "agent_name": agent_name,
            "metadata": metadata_json,
            "trace_id": trace_id or "",
            "created_at": created_at,
        },
        trace_id=trace_id,
    )

    logger.debug(
        f"[WHISPER] Saved audit entry: {entry.action.value}",
        extra={"trace_id": trace_id, "agent_name": "audit_log", "uuid": audit_uuid},
    )

    return str(result[0]["uuid"]) if result else audit_uuid


async def save_audit_entries(
    neo4j: Neo4jClient,
    entries: list[AuditEntry],
    agent_name: str = "hull_cleaner",
    trace_id: str | None = None,
) -> list[str]:
    """
    Save multiple audit entries to Neo4j in a batch.

    Uses UNWIND for efficient batch insertion.

    Args:
        neo4j: Connected Neo4j client.
        entries: List of AuditEntry objects to persist.
        agent_name: Name of the agent that generated these entries.
        trace_id: Optional trace ID for logging.

    Returns:
        List of UUIDs of the created AuditLog nodes.
    """
    if not entries:
        return []

    created_at = time.time()

    # Prepare entry data with UUIDs
    entries_data = []
    for entry in entries:
        audit_uuid = str(uuid_lib.uuid4())
        metadata_json = json.dumps(entry.metadata) if entry.metadata else "{}"
        entries_data.append(
            {
                "uuid": audit_uuid,
                "timestamp": entry.timestamp.isoformat(),
                "action": entry.action.value,
                "entity_type": entry.entity_type,
                "entity_id": str(entry.entity_id),
                "reason": entry.reason,
                "agent_name": agent_name,
                "metadata": metadata_json,
                "trace_id": trace_id or "",
                "created_at": created_at,
            }
        )

    query = f"""
    UNWIND $entries as entry
    CREATE (al:{NodeLabel.AUDIT_LOG.value} {{
        uuid: entry.uuid,
        timestamp: entry.timestamp,
        action: entry.action,
        entity_type: entry.entity_type,
        entity_id: entry.entity_id,
        reason: entry.reason,
        agent_name: entry.agent_name,
        metadata: entry.metadata,
        trace_id: entry.trace_id,
        created_at: entry.created_at
    }})
    RETURN al.uuid as uuid
    """

    result = await neo4j.execute_write(
        query,
        {"entries": entries_data},
        trace_id=trace_id,
    )

    uuids = [str(r["uuid"]) for r in result]

    logger.info(
        f"[BEACON] Saved {len(uuids)} audit entries",
        extra={"trace_id": trace_id, "agent_name": "audit_log", "count": len(uuids)},
    )

    return uuids


# ===========================================================================
# Query Functions
# ===========================================================================


async def query_audit_log(
    neo4j: Neo4jClient,
    filters: AuditQueryFilter | None = None,
    trace_id: str | None = None,
) -> list[StoredAuditEntry]:
    """
    Query audit log entries with optional filters.

    Args:
        neo4j: Connected Neo4j client.
        filters: Optional filters to apply.
        trace_id: Optional trace ID for logging.

    Returns:
        List of StoredAuditEntry objects matching the filters.
    """
    filters = filters or AuditQueryFilter()

    # Build WHERE clauses
    where_clauses: list[str] = []
    params: dict[str, Any] = {
        "limit": filters.limit,
        "offset": filters.offset,
    }

    if filters.start_time:
        where_clauses.append("al.timestamp >= $start_time")
        params["start_time"] = filters.start_time.isoformat()

    if filters.end_time:
        where_clauses.append("al.timestamp <= $end_time")
        params["end_time"] = filters.end_time.isoformat()

    if filters.action_types:
        where_clauses.append("al.action IN $action_types")
        params["action_types"] = filters.action_types

    if filters.entity_types:
        where_clauses.append("al.entity_type IN $entity_types")
        params["entity_types"] = filters.entity_types

    if filters.agent_name:
        where_clauses.append("al.agent_name = $agent_name")
        params["agent_name"] = filters.agent_name

    where_str = " AND ".join(where_clauses) if where_clauses else "TRUE"

    query = f"""
    MATCH (al:{NodeLabel.AUDIT_LOG.value})
    WHERE {where_str}
    RETURN al
    ORDER BY al.timestamp DESC
    SKIP $offset
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, params, trace_id=trace_id)

    entries = []
    for record in result:
        node = record["al"]
        # Parse metadata JSON back to dict
        metadata = {}
        if node.get("metadata"):
            try:
                metadata = json.loads(node["metadata"])
            except json.JSONDecodeError:
                metadata = {"raw": node["metadata"]}

        entries.append(
            StoredAuditEntry(
                uuid=node["uuid"],
                timestamp=datetime.fromisoformat(node["timestamp"]),
                action=node["action"],
                entity_type=node["entity_type"],
                entity_id=node["entity_id"],
                reason=node["reason"],
                agent_name=node["agent_name"],
                metadata=metadata,
                trace_id=node.get("trace_id"),
            )
        )

    logger.debug(
        f"[WHISPER] Retrieved {len(entries)} audit entries",
        extra={"trace_id": trace_id, "agent_name": "audit_log"},
    )

    return entries


async def get_audit_stats(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> AuditLogStats:
    """
    Get statistics about the audit log.

    Args:
        neo4j: Connected Neo4j client.
        trace_id: Optional trace ID for logging.

    Returns:
        AuditLogStats with counts and date ranges.
    """
    query = f"""
    MATCH (al:{NodeLabel.AUDIT_LOG.value})
    WITH count(al) as total,
         collect(al.action) as actions,
         collect(al.entity_type) as entity_types,
         min(al.timestamp) as min_ts,
         max(al.timestamp) as max_ts
    RETURN total, actions, entity_types, min_ts, max_ts
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    if not result:
        return AuditLogStats(
            total_entries=0,
            entries_by_action={},
            entries_by_entity_type={},
            date_range_start=None,
            date_range_end=None,
        )

    record = result[0]

    # Count actions
    action_counts: dict[str, int] = {}
    for action in record.get("actions", []):
        action_counts[action] = action_counts.get(action, 0) + 1

    # Count entity types
    entity_counts: dict[str, int] = {}
    for entity_type in record.get("entity_types", []):
        entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

    # Parse date range
    min_ts = record.get("min_ts")
    max_ts = record.get("max_ts")

    return AuditLogStats(
        total_entries=record.get("total", 0),
        entries_by_action=action_counts,
        entries_by_entity_type=entity_counts,
        date_range_start=datetime.fromisoformat(min_ts) if min_ts else None,
        date_range_end=datetime.fromisoformat(max_ts) if max_ts else None,
    )


async def delete_old_audit_entries(
    neo4j: Neo4jClient,
    older_than: datetime,
    trace_id: str | None = None,
) -> int:
    """
    Delete audit entries older than the specified date.

    Useful for pruning very old audit records.

    Args:
        neo4j: Connected Neo4j client.
        older_than: Delete entries with timestamp before this date.
        trace_id: Optional trace ID for logging.

    Returns:
        Number of deleted entries.
    """
    query = f"""
    MATCH (al:{NodeLabel.AUDIT_LOG.value})
    WHERE al.timestamp < $cutoff
    WITH al LIMIT 1000
    DETACH DELETE al
    RETURN count(*) as deleted
    """

    result = await neo4j.execute_write(
        query,
        {"cutoff": older_than.isoformat()},
        trace_id=trace_id,
    )

    deleted: int = int(result[0]["deleted"]) if result else 0

    logger.info(
        f"[BEACON] Deleted {deleted} old audit entries",
        extra={"trace_id": trace_id, "agent_name": "audit_log", "cutoff": older_than.isoformat()},
    )

    return deleted


# ===========================================================================
# Export
# ===========================================================================


__all__ = [
    "AuditLogStats",
    "AuditQueryFilter",
    "StoredAuditEntry",
    "delete_old_audit_entries",
    "get_audit_stats",
    "query_audit_log",
    "save_audit_entries",
    "save_audit_entry",
]
