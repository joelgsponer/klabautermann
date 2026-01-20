"""
Unit tests for orphan message cleanup module.

Tests orphan detection and deletion functionality.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.orphan_cleanup import (
    OrphanCleanupResult,
    OrphanMessage,
    cleanup_result_to_dict,
    count_orphan_messages,
    delete_orphan_messages,
    find_orphan_messages,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4jClient."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


# =============================================================================
# Test Data Classes
# =============================================================================


class TestOrphanMessage:
    """Tests for OrphanMessage dataclass."""

    def test_creation(self) -> None:
        """Test creating OrphanMessage."""
        orphan = OrphanMessage(
            uuid="test-uuid",
            content="Test content",
            timestamp=1705320000.0,
            role="user",
        )
        assert orphan.uuid == "test-uuid"
        assert orphan.content == "Test content"
        assert orphan.timestamp == 1705320000.0
        assert orphan.role == "user"

    def test_creation_with_none_values(self) -> None:
        """Test creating OrphanMessage with None values."""
        orphan = OrphanMessage(
            uuid="test-uuid",
            content=None,
            timestamp=None,
            role=None,
        )
        assert orphan.uuid == "test-uuid"
        assert orphan.content is None


class TestOrphanCleanupResult:
    """Tests for OrphanCleanupResult dataclass."""

    def test_creation(self) -> None:
        """Test creating OrphanCleanupResult."""
        result = OrphanCleanupResult(
            orphan_count=10,
            deleted_count=8,
            failed_count=2,
            execution_time_ms=150.5,
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )
        assert result.orphan_count == 10
        assert result.deleted_count == 8
        assert result.failed_count == 2
        assert result.execution_time_ms == 150.5


# =============================================================================
# Test Orphan Detection
# =============================================================================


class TestFindOrphanMessages:
    """Tests for find_orphan_messages function."""

    @pytest.mark.asyncio
    async def test_finds_orphans(self, mock_neo4j: MagicMock) -> None:
        """Test finding orphan messages."""
        mock_neo4j.execute_query.return_value = [
            {"uuid": "orphan-1", "content": "Content 1", "timestamp": 1705320000.0, "role": "user"},
            {
                "uuid": "orphan-2",
                "content": "Content 2",
                "timestamp": 1705319900.0,
                "role": "assistant",
            },
        ]

        result = await find_orphan_messages(mock_neo4j)

        assert len(result) == 2
        assert result[0].uuid == "orphan-1"
        assert result[1].uuid == "orphan-2"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test when no orphans found."""
        mock_neo4j.execute_query.return_value = []

        result = await find_orphan_messages(mock_neo4j)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, mock_neo4j: MagicMock) -> None:
        """Test that limit parameter is passed."""
        mock_neo4j.execute_query.return_value = []

        await find_orphan_messages(mock_neo4j, limit=50)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["limit"] == 50


class TestCountOrphanMessages:
    """Tests for count_orphan_messages function."""

    @pytest.mark.asyncio
    async def test_returns_count(self, mock_neo4j: MagicMock) -> None:
        """Test counting orphan messages."""
        mock_neo4j.execute_query.return_value = [{"count": 25}]

        result = await count_orphan_messages(mock_neo4j)

        assert result == 25

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test counting with empty result."""
        mock_neo4j.execute_query.return_value = []

        result = await count_orphan_messages(mock_neo4j)

        assert result == 0


# =============================================================================
# Test Orphan Deletion
# =============================================================================


class TestDeleteOrphanMessages:
    """Tests for delete_orphan_messages function."""

    @pytest.mark.asyncio
    async def test_deletes_orphans(self, mock_neo4j: MagicMock) -> None:
        """Test deleting orphan messages."""
        mock_neo4j.execute_query.side_effect = [
            [{"count": 10}],  # count_orphan_messages
            [{"deleted": 10}],  # delete batch
            [{"deleted": 0}],  # no more to delete
        ]

        result = await delete_orphan_messages(mock_neo4j)

        assert result.orphan_count == 10
        assert result.deleted_count == 10
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_no_orphans_to_delete(self, mock_neo4j: MagicMock) -> None:
        """Test when no orphans exist."""
        mock_neo4j.execute_query.return_value = [{"count": 0}]

        result = await delete_orphan_messages(mock_neo4j)

        assert result.orphan_count == 0
        assert result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_dry_run(self, mock_neo4j: MagicMock) -> None:
        """Test dry run mode."""
        mock_neo4j.execute_query.return_value = [{"count": 15}]

        result = await delete_orphan_messages(mock_neo4j, dry_run=True)

        assert result.orphan_count == 15
        assert result.deleted_count == 0
        # Should only call count, not delete
        assert mock_neo4j.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_handles_deletion_error(self, mock_neo4j: MagicMock) -> None:
        """Test handling deletion errors."""
        mock_neo4j.execute_query.side_effect = [
            [{"count": 10}],  # count
            Exception("Database error"),  # deletion fails
        ]

        result = await delete_orphan_messages(mock_neo4j)

        assert result.orphan_count == 10
        assert result.failed_count == 1


# =============================================================================
# Test Serialization
# =============================================================================


class TestCleanupResultToDict:
    """Tests for cleanup_result_to_dict function."""

    def test_converts_to_dict(self) -> None:
        """Test converting result to dictionary."""
        result = OrphanCleanupResult(
            orphan_count=20,
            deleted_count=18,
            failed_count=2,
            execution_time_ms=250.0,
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )

        d = cleanup_result_to_dict(result)

        assert d["orphan_count"] == 20
        assert d["deleted_count"] == 18
        assert d["failed_count"] == 2
        assert d["execution_time_ms"] == 250.0
        assert "timestamp" in d
