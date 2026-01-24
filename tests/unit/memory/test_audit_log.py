"""
Tests for audit log persistence module.

Tests the AuditLog node storage and querying functionality
for HullCleaner maintenance operations.

Issue: #87
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.hull_cleaner import AuditEntry, PruningAction
from klabautermann.memory.audit_log import (
    AuditLogStats,
    AuditQueryFilter,
    StoredAuditEntry,
    delete_old_audit_entries,
    get_audit_stats,
    query_audit_log,
    save_audit_entries,
    save_audit_entry,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock(return_value=[])
    client.execute_write = AsyncMock(return_value=[])
    return client


@pytest.fixture
def sample_audit_entry() -> AuditEntry:
    """Create a sample AuditEntry for testing."""
    return AuditEntry(
        timestamp=datetime(2026, 1, 22, 10, 30, 0),
        action=PruningAction.DELETE_RELATIONSHIP,
        entity_type="relationship",
        entity_id=12345,
        reason="Weight below threshold (0.15)",
        metadata={"weight": 0.15, "relationship_type": "KNOWS"},
    )


@pytest.fixture
def sample_entries() -> list[AuditEntry]:
    """Create multiple sample entries for batch testing."""
    return [
        AuditEntry(
            timestamp=datetime(2026, 1, 22, 10, 30, 0),
            action=PruningAction.DELETE_RELATIONSHIP,
            entity_type="relationship",
            entity_id=12345,
            reason="Weak relationship",
            metadata={"weight": 0.15},
        ),
        AuditEntry(
            timestamp=datetime(2026, 1, 22, 10, 31, 0),
            action=PruningAction.DELETE_NODE,
            entity_type="message",
            entity_id="msg-uuid-123",
            reason="Orphan message",
            metadata={"role": "user"},
        ),
        AuditEntry(
            timestamp=datetime(2026, 1, 22, 10, 32, 0),
            action=PruningAction.MERGE_NODES,
            entity_type="person",
            entity_id="person-uuid-456",
            reason="Duplicate entity",
            metadata={"similarity": 0.95},
        ),
    ]


# ===========================================================================
# AuditQueryFilter Tests
# ===========================================================================


class TestAuditQueryFilter:
    """Tests for AuditQueryFilter dataclass."""

    def test_default_values(self) -> None:
        """Test default filter values."""
        filter_obj = AuditQueryFilter()

        assert filter_obj.start_time is None
        assert filter_obj.end_time is None
        assert filter_obj.action_types is None
        assert filter_obj.entity_types is None
        assert filter_obj.agent_name is None
        assert filter_obj.limit == 100
        assert filter_obj.offset == 0

    def test_custom_values(self) -> None:
        """Test filter with custom values."""
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)

        filter_obj = AuditQueryFilter(
            start_time=start,
            end_time=end,
            action_types=["DELETE_RELATIONSHIP", "DELETE_NODE"],
            entity_types=["relationship", "message"],
            agent_name="hull_cleaner",
            limit=50,
            offset=10,
        )

        assert filter_obj.start_time == start
        assert filter_obj.end_time == end
        assert len(filter_obj.action_types) == 2
        assert filter_obj.limit == 50

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        start = datetime(2026, 1, 15, 10, 0, 0)

        filter_obj = AuditQueryFilter(
            start_time=start,
            action_types=["DELETE_NODE"],
            limit=25,
        )

        result = filter_obj.to_dict()

        assert result["start_time"] == "2026-01-15T10:00:00"
        assert result["end_time"] is None
        assert result["action_types"] == ["DELETE_NODE"]
        assert result["limit"] == 25


# ===========================================================================
# StoredAuditEntry Tests
# ===========================================================================


class TestStoredAuditEntry:
    """Tests for StoredAuditEntry dataclass."""

    def test_creation(self) -> None:
        """Test creating a StoredAuditEntry."""
        entry = StoredAuditEntry(
            uuid="audit-uuid-123",
            timestamp=datetime(2026, 1, 22, 10, 30, 0),
            action="DELETE_RELATIONSHIP",
            entity_type="relationship",
            entity_id="12345",
            reason="Weight below threshold",
            agent_name="hull_cleaner",
            metadata={"weight": 0.15},
            trace_id="trace-123",
        )

        assert entry.uuid == "audit-uuid-123"
        assert entry.action == "DELETE_RELATIONSHIP"
        assert entry.metadata["weight"] == 0.15

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        entry = StoredAuditEntry(
            uuid="audit-uuid-123",
            timestamp=datetime(2026, 1, 22, 10, 30, 0),
            action="DELETE_NODE",
            entity_type="message",
            entity_id="msg-uuid-456",
            reason="Orphan",
            agent_name="hull_cleaner",
            metadata={},
        )

        result = entry.to_dict()

        assert result["uuid"] == "audit-uuid-123"
        assert result["timestamp"] == "2026-01-22T10:30:00"
        assert result["action"] == "DELETE_NODE"
        assert result["trace_id"] is None


# ===========================================================================
# AuditLogStats Tests
# ===========================================================================


class TestAuditLogStats:
    """Tests for AuditLogStats dataclass."""

    def test_creation(self) -> None:
        """Test creating AuditLogStats."""
        stats = AuditLogStats(
            total_entries=100,
            entries_by_action={"DELETE_RELATIONSHIP": 60, "DELETE_NODE": 40},
            entries_by_entity_type={"relationship": 60, "message": 40},
            date_range_start=datetime(2026, 1, 1),
            date_range_end=datetime(2026, 1, 22),
        )

        assert stats.total_entries == 100
        assert stats.entries_by_action["DELETE_RELATIONSHIP"] == 60
        assert stats.date_range_start.year == 2026

    def test_empty_stats(self) -> None:
        """Test empty stats."""
        stats = AuditLogStats(
            total_entries=0,
            entries_by_action={},
            entries_by_entity_type={},
            date_range_start=None,
            date_range_end=None,
        )

        assert stats.total_entries == 0
        assert stats.date_range_start is None

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = AuditLogStats(
            total_entries=50,
            entries_by_action={"MERGE_NODES": 50},
            entries_by_entity_type={"person": 50},
            date_range_start=datetime(2026, 1, 15),
            date_range_end=datetime(2026, 1, 20),
        )

        result = stats.to_dict()

        assert result["total_entries"] == 50
        assert result["date_range_start"] == "2026-01-15T00:00:00"


# ===========================================================================
# save_audit_entry Tests
# ===========================================================================


class TestSaveAuditEntry:
    """Tests for save_audit_entry function."""

    @pytest.mark.asyncio
    async def test_save_single_entry(
        self,
        mock_neo4j: MagicMock,
        sample_audit_entry: AuditEntry,
    ) -> None:
        """Test saving a single audit entry."""
        mock_neo4j.execute_write = AsyncMock(return_value=[{"uuid": "created-uuid"}])

        result = await save_audit_entry(
            neo4j=mock_neo4j,
            entry=sample_audit_entry,
            agent_name="hull_cleaner",
            trace_id="trace-123",
        )

        assert result == "created-uuid"
        mock_neo4j.execute_write.assert_called_once()

        # Check query parameters
        call_args = mock_neo4j.execute_write.call_args
        params = call_args[0][1]

        assert params["action"] == "DELETE_RELATIONSHIP"
        assert params["entity_type"] == "relationship"
        assert params["entity_id"] == "12345"
        assert params["agent_name"] == "hull_cleaner"
        assert "weight" in json.loads(params["metadata"])

    @pytest.mark.asyncio
    async def test_save_entry_empty_metadata(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test saving entry with empty metadata."""
        entry = AuditEntry(
            timestamp=datetime.now(),
            action=PruningAction.DELETE_NODE,
            entity_type="message",
            entity_id="test-uuid",
            reason="Test reason",
            metadata={},
        )

        mock_neo4j.execute_write = AsyncMock(return_value=[{"uuid": "uuid-123"}])

        result = await save_audit_entry(
            neo4j=mock_neo4j,
            entry=entry,
        )

        assert result == "uuid-123"

        call_args = mock_neo4j.execute_write.call_args
        params = call_args[0][1]
        assert params["metadata"] == "{}"


# ===========================================================================
# save_audit_entries Tests
# ===========================================================================


class TestSaveAuditEntries:
    """Tests for save_audit_entries function."""

    @pytest.mark.asyncio
    async def test_save_empty_list(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test saving empty list returns empty list."""
        result = await save_audit_entries(
            neo4j=mock_neo4j,
            entries=[],
        )

        assert result == []
        mock_neo4j.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_multiple_entries(
        self,
        mock_neo4j: MagicMock,
        sample_entries: list[AuditEntry],
    ) -> None:
        """Test batch saving multiple entries."""
        mock_neo4j.execute_write = AsyncMock(
            return_value=[
                {"uuid": "uuid-1"},
                {"uuid": "uuid-2"},
                {"uuid": "uuid-3"},
            ]
        )

        result = await save_audit_entries(
            neo4j=mock_neo4j,
            entries=sample_entries,
            agent_name="hull_cleaner",
            trace_id="batch-trace",
        )

        assert len(result) == 3
        assert "uuid-1" in result

        # Check UNWIND was used in query
        call_args = mock_neo4j.execute_write.call_args
        query = call_args[0][0]
        assert "UNWIND" in query


# ===========================================================================
# query_audit_log Tests
# ===========================================================================


class TestQueryAuditLog:
    """Tests for query_audit_log function."""

    @pytest.mark.asyncio
    async def test_query_no_filters(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test query with no filters."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "al": {
                        "uuid": "uuid-1",
                        "timestamp": "2026-01-22T10:30:00",
                        "action": "DELETE_NODE",
                        "entity_type": "message",
                        "entity_id": "msg-123",
                        "reason": "Orphan",
                        "agent_name": "hull_cleaner",
                        "metadata": "{}",
                        "trace_id": None,
                    }
                }
            ]
        )

        result = await query_audit_log(neo4j=mock_neo4j)

        assert len(result) == 1
        assert result[0].uuid == "uuid-1"
        assert result[0].action == "DELETE_NODE"

    @pytest.mark.asyncio
    async def test_query_with_time_filter(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test query with time range filter."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        filters = AuditQueryFilter(
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 31),
        )

        await query_audit_log(neo4j=mock_neo4j, filters=filters)

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "al.timestamp >=" in query
        assert "al.timestamp <=" in query
        assert params["start_time"] == "2026-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_query_with_action_filter(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test query filtered by action types."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        filters = AuditQueryFilter(
            action_types=["DELETE_RELATIONSHIP", "MERGE_NODES"],
        )

        await query_audit_log(neo4j=mock_neo4j, filters=filters)

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "al.action IN" in query
        assert params["action_types"] == ["DELETE_RELATIONSHIP", "MERGE_NODES"]

    @pytest.mark.asyncio
    async def test_query_parses_metadata(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test that metadata JSON is parsed correctly."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "al": {
                        "uuid": "uuid-1",
                        "timestamp": "2026-01-22T10:30:00",
                        "action": "DELETE_RELATIONSHIP",
                        "entity_type": "relationship",
                        "entity_id": "12345",
                        "reason": "Weak",
                        "agent_name": "hull_cleaner",
                        "metadata": '{"weight": 0.15, "type": "KNOWS"}',
                        "trace_id": "trace-123",
                    }
                }
            ]
        )

        result = await query_audit_log(neo4j=mock_neo4j)

        assert result[0].metadata["weight"] == 0.15
        assert result[0].metadata["type"] == "KNOWS"


# ===========================================================================
# get_audit_stats Tests
# ===========================================================================


class TestGetAuditStats:
    """Tests for get_audit_stats function."""

    @pytest.mark.asyncio
    async def test_get_stats(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test getting audit statistics."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "total": 100,
                    "actions": [
                        "DELETE_RELATIONSHIP",
                        "DELETE_RELATIONSHIP",
                        "DELETE_NODE",
                    ],
                    "entity_types": ["relationship", "relationship", "message"],
                    "min_ts": "2026-01-01T00:00:00",
                    "max_ts": "2026-01-22T23:59:59",
                }
            ]
        )

        stats = await get_audit_stats(neo4j=mock_neo4j)

        assert stats.total_entries == 100
        assert stats.entries_by_action["DELETE_RELATIONSHIP"] == 2
        assert stats.entries_by_action["DELETE_NODE"] == 1
        assert stats.date_range_start.month == 1

    @pytest.mark.asyncio
    async def test_get_stats_empty(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test getting stats with no entries."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        stats = await get_audit_stats(neo4j=mock_neo4j)

        assert stats.total_entries == 0
        assert stats.entries_by_action == {}
        assert stats.date_range_start is None


# ===========================================================================
# delete_old_audit_entries Tests
# ===========================================================================


class TestDeleteOldAuditEntries:
    """Tests for delete_old_audit_entries function."""

    @pytest.mark.asyncio
    async def test_delete_old_entries(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test deleting entries older than cutoff."""
        mock_neo4j.execute_write = AsyncMock(return_value=[{"deleted": 50}])

        cutoff = datetime.now() - timedelta(days=90)
        deleted = await delete_old_audit_entries(
            neo4j=mock_neo4j,
            older_than=cutoff,
        )

        assert deleted == 50
        mock_neo4j.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_none(
        self,
        mock_neo4j: MagicMock,
    ) -> None:
        """Test delete when no matching entries."""
        mock_neo4j.execute_write = AsyncMock(return_value=[{"deleted": 0}])

        cutoff = datetime.now() - timedelta(days=365)
        deleted = await delete_old_audit_entries(
            neo4j=mock_neo4j,
            older_than=cutoff,
        )

        assert deleted == 0
