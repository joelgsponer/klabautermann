"""Unit tests for backup and restore functionality."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from klabautermann.memory.backup import (
    BackupMetadata,
    BackupSnapshot,
    RestoreResult,
    clear_database,
    create_backup,
    load_backup_from_file,
    restore_backup,
    save_backup_to_file,
    validate_backup,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_nodes() -> list[dict]:
    """Sample nodes for testing."""
    return [
        {
            "element_id": "4:abc:0",
            "labels": ["Person"],
            "properties": {
                "uuid": "person-1",
                "name": "John Doe",
                "email": "john@example.com",
            },
        },
        {
            "element_id": "4:abc:1",
            "labels": ["Organization"],
            "properties": {
                "uuid": "org-1",
                "name": "Acme Corp",
                "industry": "Technology",
            },
        },
        {
            "element_id": "4:abc:2",
            "labels": ["Person"],
            "properties": {
                "uuid": "person-2",
                "name": "Jane Smith",
                "email": "jane@example.com",
            },
        },
    ]


@pytest.fixture
def sample_relationships() -> list[dict]:
    """Sample relationships for testing."""
    return [
        {
            "type": "WORKS_AT",
            "properties": {"title": "Engineer"},
            "from_element_id": "4:abc:0",
            "to_element_id": "4:abc:1",
            "from_labels": ["Person"],
            "to_labels": ["Organization"],
            "from_uuid": "person-1",
            "to_uuid": "org-1",
        },
        {
            "type": "KNOWS",
            "properties": {},
            "from_element_id": "4:abc:0",
            "to_element_id": "4:abc:2",
            "from_labels": ["Person"],
            "to_labels": ["Person"],
            "from_uuid": "person-1",
            "to_uuid": "person-2",
        },
    ]


@pytest.fixture
def sample_metadata() -> BackupMetadata:
    """Sample metadata for testing."""
    return BackupMetadata(
        created_at=datetime.now(UTC).isoformat(),
        version="1.0",
        node_count=3,
        relationship_count=2,
        node_labels=["Organization", "Person"],
        relationship_types=["KNOWS", "WORKS_AT"],
    )


@pytest.fixture
def sample_snapshot(
    sample_metadata: BackupMetadata,
    sample_nodes: list[dict],
    sample_relationships: list[dict],
) -> BackupSnapshot:
    """Sample backup snapshot for testing."""
    return BackupSnapshot(
        metadata=sample_metadata,
        nodes=sample_nodes,
        relationships=sample_relationships,
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock Neo4j client."""
    client = AsyncMock()
    client.execute_query = AsyncMock()
    return client


# =============================================================================
# BackupMetadata Tests
# =============================================================================


class TestBackupMetadata:
    """Test BackupMetadata dataclass."""

    def test_to_dict(self, sample_metadata: BackupMetadata) -> None:
        """Test converting metadata to dictionary."""
        data = sample_metadata.to_dict()

        assert data["version"] == "1.0"
        assert data["node_count"] == 3
        assert data["relationship_count"] == 2
        assert "Person" in data["node_labels"]
        assert "WORKS_AT" in data["relationship_types"]

    def test_from_dict(self) -> None:
        """Test creating metadata from dictionary."""
        data = {
            "created_at": "2026-01-22T10:00:00+00:00",
            "version": "1.0",
            "node_count": 5,
            "relationship_count": 3,
            "node_labels": ["Person"],
            "relationship_types": ["KNOWS"],
        }

        metadata = BackupMetadata.from_dict(data)

        assert metadata.node_count == 5
        assert metadata.relationship_count == 3
        assert metadata.version == "1.0"

    def test_from_dict_with_defaults(self) -> None:
        """Test creating metadata with missing optional fields."""
        data = {"created_at": "2026-01-22T10:00:00+00:00"}

        metadata = BackupMetadata.from_dict(data)

        assert metadata.node_count == 0
        assert metadata.relationship_count == 0
        assert metadata.version == "1.0"


# =============================================================================
# BackupSnapshot Tests
# =============================================================================


class TestBackupSnapshot:
    """Test BackupSnapshot dataclass."""

    def test_to_dict(self, sample_snapshot: BackupSnapshot) -> None:
        """Test converting snapshot to dictionary."""
        data = sample_snapshot.to_dict()

        assert "metadata" in data
        assert "nodes" in data
        assert "relationships" in data
        assert len(data["nodes"]) == 3
        assert len(data["relationships"]) == 2

    def test_from_dict(self, sample_snapshot: BackupSnapshot) -> None:
        """Test creating snapshot from dictionary."""
        data = sample_snapshot.to_dict()

        restored = BackupSnapshot.from_dict(data)

        assert restored.metadata.node_count == 3
        assert len(restored.nodes) == 3
        assert len(restored.relationships) == 2

    def test_json_roundtrip(self, sample_snapshot: BackupSnapshot) -> None:
        """Test JSON serialization roundtrip."""
        json_str = json.dumps(sample_snapshot.to_dict())
        data = json.loads(json_str)

        restored = BackupSnapshot.from_dict(data)

        assert restored.metadata.node_count == sample_snapshot.metadata.node_count
        assert len(restored.nodes) == len(sample_snapshot.nodes)


# =============================================================================
# Create Backup Tests
# =============================================================================


class TestCreateBackup:
    """Test create_backup function."""

    @pytest.mark.asyncio
    async def test_create_backup_success(self, mock_client: AsyncMock) -> None:
        """Test creating a backup snapshot."""
        # Mock node query response
        mock_client.execute_query.side_effect = [
            # First call: nodes
            [
                {
                    "labels": ["Person"],
                    "props": {"uuid": "p1", "name": "Test"},
                    "id": "4:abc:0",
                },
            ],
            # Second call: relationships
            [
                {
                    "type": "KNOWS",
                    "props": {},
                    "from_id": "4:abc:0",
                    "to_id": "4:abc:1",
                    "from_labels": ["Person"],
                    "to_labels": ["Person"],
                    "from_uuid": "p1",
                    "to_uuid": "p2",
                },
            ],
        ]

        snapshot = await create_backup(mock_client)

        assert snapshot.metadata.node_count == 1
        assert snapshot.metadata.relationship_count == 1
        assert "Person" in snapshot.metadata.node_labels
        assert "KNOWS" in snapshot.metadata.relationship_types

    @pytest.mark.asyncio
    async def test_create_backup_empty_database(self, mock_client: AsyncMock) -> None:
        """Test creating backup of empty database."""
        mock_client.execute_query.side_effect = [[], []]

        snapshot = await create_backup(mock_client)

        assert snapshot.metadata.node_count == 0
        assert snapshot.metadata.relationship_count == 0
        assert len(snapshot.nodes) == 0
        assert len(snapshot.relationships) == 0


# =============================================================================
# File Operations Tests
# =============================================================================


class TestFileOperations:
    """Test file save/load operations."""

    @pytest.mark.asyncio
    async def test_save_and_load_backup(self, sample_snapshot: BackupSnapshot) -> None:
        """Test saving and loading a backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "backup.json"

            await save_backup_to_file(sample_snapshot, filepath)

            assert filepath.exists()

            loaded = await load_backup_from_file(filepath)

            assert loaded.metadata.node_count == sample_snapshot.metadata.node_count
            assert len(loaded.nodes) == len(sample_snapshot.nodes)
            assert len(loaded.relationships) == len(sample_snapshot.relationships)

    @pytest.mark.asyncio
    async def test_save_creates_parent_directories(self, sample_snapshot: BackupSnapshot) -> None:
        """Test that save creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "nested" / "path" / "backup.json"

            await save_backup_to_file(sample_snapshot, filepath)

            assert filepath.exists()

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self) -> None:
        """Test loading a file that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            await load_backup_from_file("/nonexistent/path/backup.json")


# =============================================================================
# Clear Database Tests
# =============================================================================


class TestClearDatabase:
    """Test clear_database function."""

    @pytest.mark.asyncio
    async def test_clear_database(self, mock_client: AsyncMock) -> None:
        """Test clearing all data from database."""
        # First batch deletes 1000, second batch deletes 500 (under batch size)
        mock_client.execute_query.side_effect = [
            [{"deleted": 1000}],
            [{"deleted": 500}],
        ]

        deleted = await clear_database(mock_client)

        assert deleted == 1500
        assert mock_client.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_empty_database(self, mock_client: AsyncMock) -> None:
        """Test clearing an already empty database."""
        mock_client.execute_query.return_value = [{"deleted": 0}]

        deleted = await clear_database(mock_client)

        assert deleted == 0


# =============================================================================
# Restore Backup Tests
# =============================================================================


class TestRestoreBackup:
    """Test restore_backup function."""

    @pytest.mark.asyncio
    async def test_restore_backup_success(
        self, mock_client: AsyncMock, sample_snapshot: BackupSnapshot
    ) -> None:
        """Test restoring a backup successfully."""
        # Mock node creation
        mock_client.execute_query.return_value = [{"uuid": "test-uuid", "new_id": "4:new:0"}]

        result = await restore_backup(mock_client, sample_snapshot)

        assert result.success
        assert result.nodes_restored == 3
        assert result.relationships_restored == 2
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_restore_with_clear(
        self, mock_client: AsyncMock, sample_snapshot: BackupSnapshot
    ) -> None:
        """Test restoring with clear_existing=True."""
        # First call is clear_database batch delete
        # Then node creations, then relationship creations
        mock_client.execute_query.side_effect = [
            [{"deleted": 0}],  # clear_database
            *[[{"uuid": "test", "new_id": "4:new:0"}]] * 3,  # 3 nodes
            *[[{"r": {}}]] * 2,  # 2 relationships
        ]

        result = await restore_backup(mock_client, sample_snapshot, clear_existing=True)

        assert result.success
        # First call is the clear operation
        assert mock_client.execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_restore_with_missing_uuids(self, mock_client: AsyncMock) -> None:
        """Test restoring relationships with missing UUIDs."""
        snapshot = BackupSnapshot(
            metadata=BackupMetadata(
                created_at=datetime.now(UTC).isoformat(),
                node_count=0,
                relationship_count=1,
            ),
            nodes=[],
            relationships=[
                {
                    "type": "KNOWS",
                    "properties": {},
                    "from_uuid": None,
                    "to_uuid": None,
                }
            ],
        )

        mock_client.execute_query.return_value = []

        result = await restore_backup(mock_client, snapshot)

        assert result.success  # Should succeed but with warnings
        assert result.relationships_restored == 0
        assert len(result.warnings) > 0


# =============================================================================
# Validate Backup Tests
# =============================================================================


class TestValidateBackup:
    """Test validate_backup function."""

    @pytest.mark.asyncio
    async def test_validate_valid_backup(self, sample_snapshot: BackupSnapshot) -> None:
        """Test validating a valid backup."""
        errors = await validate_backup(sample_snapshot)

        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_validate_count_mismatch(self) -> None:
        """Test detecting node count mismatch."""
        snapshot = BackupSnapshot(
            metadata=BackupMetadata(
                created_at=datetime.now(UTC).isoformat(),
                node_count=5,  # Says 5 but only 1 node
                relationship_count=0,
            ),
            nodes=[{"element_id": "1", "labels": ["Person"], "properties": {}}],
            relationships=[],
        )

        errors = await validate_backup(snapshot)

        assert len(errors) > 0
        assert any("count mismatch" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_validate_relationship_mismatch(self) -> None:
        """Test detecting relationship count mismatch."""
        snapshot = BackupSnapshot(
            metadata=BackupMetadata(
                created_at=datetime.now(UTC).isoformat(),
                node_count=0,
                relationship_count=10,  # Says 10 but empty
            ),
            nodes=[],
            relationships=[],
        )

        errors = await validate_backup(snapshot)

        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_validate_orphan_relationship(self) -> None:
        """Test detecting relationships referencing non-existent nodes."""
        snapshot = BackupSnapshot(
            metadata=BackupMetadata(
                created_at=datetime.now(UTC).isoformat(),
                node_count=1,
                relationship_count=1,
            ),
            nodes=[{"element_id": "4:abc:0", "labels": ["Person"], "properties": {}}],
            relationships=[
                {
                    "type": "KNOWS",
                    "from_element_id": "4:abc:0",
                    "to_element_id": "4:abc:999",  # Does not exist
                }
            ],
        )

        errors = await validate_backup(snapshot)

        assert len(errors) > 0
        assert any("non-existent" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_validate_duplicate_uuids(self) -> None:
        """Test detecting duplicate UUIDs within same label."""
        snapshot = BackupSnapshot(
            metadata=BackupMetadata(
                created_at=datetime.now(UTC).isoformat(),
                node_count=2,
                relationship_count=0,
            ),
            nodes=[
                {
                    "element_id": "4:abc:0",
                    "labels": ["Person"],
                    "properties": {"uuid": "duplicate-uuid"},
                },
                {
                    "element_id": "4:abc:1",
                    "labels": ["Person"],
                    "properties": {"uuid": "duplicate-uuid"},  # Same UUID
                },
            ],
            relationships=[],
        )

        errors = await validate_backup(snapshot)

        assert len(errors) > 0
        assert any("duplicate" in e.lower() for e in errors)


# =============================================================================
# RestoreResult Tests
# =============================================================================


class TestRestoreResult:
    """Test RestoreResult dataclass."""

    def test_successful_result(self) -> None:
        """Test creating a successful result."""
        result = RestoreResult(
            success=True,
            nodes_restored=10,
            relationships_restored=5,
        )

        assert result.success
        assert result.nodes_restored == 10
        assert result.relationships_restored == 5
        assert len(result.errors) == 0

    def test_failed_result(self) -> None:
        """Test creating a failed result."""
        result = RestoreResult(
            success=False,
            nodes_restored=5,
            relationships_restored=2,
            errors=["Failed to create node X", "Failed to create relationship Y"],
        )

        assert not result.success
        assert len(result.errors) == 2

    def test_result_with_warnings(self) -> None:
        """Test result with warnings but no errors."""
        result = RestoreResult(
            success=True,
            nodes_restored=10,
            warnings=["Skipped node without labels"],
        )

        assert result.success
        assert len(result.warnings) == 1
