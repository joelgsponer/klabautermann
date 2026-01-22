"""Unit tests for agents/hull_cleaner.py - graph pruning and maintenance."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.hull_cleaner import (
    AuditEntry,
    DuplicateCandidate,
    HullCleaner,
    HullCleanerConfig,
    MergeResult,
    PruningAction,
    PruningResult,
    PruningRule,
)
from klabautermann.core.models import AgentMessage


# =============================================================================
# Configuration Tests
# =============================================================================


class TestHullCleanerConfig:
    """Tests for HullCleanerConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = HullCleanerConfig()
        assert config.prune_weak_relationships is True
        assert config.weak_relationship_threshold == 0.2
        assert config.weak_relationship_age_days == 90
        assert config.max_deletions_per_run == 1000
        assert config.dry_run_by_default is True
        assert config.schedule_cron == "0 2 * * 0"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = HullCleanerConfig(
            prune_weak_relationships=False,
            weak_relationship_threshold=0.3,
            weak_relationship_age_days=60,
            max_deletions_per_run=500,
            dry_run_by_default=False,
        )
        assert config.prune_weak_relationships is False
        assert config.weak_relationship_threshold == 0.3
        assert config.weak_relationship_age_days == 60
        assert config.max_deletions_per_run == 500
        assert config.dry_run_by_default is False


class TestPruningRule:
    """Tests for PruningRule dataclass."""

    def test_default_values(self):
        """Test default rule values."""
        rule = PruningRule(name="test_rule")
        assert rule.name == "test_rule"
        assert rule.enabled is True
        assert rule.weight_threshold == 0.2
        assert rule.age_days == 90
        assert rule.max_items_per_run == 1000

    def test_custom_values(self):
        """Test custom rule values."""
        rule = PruningRule(
            name="custom_rule",
            enabled=False,
            weight_threshold=0.5,
            age_days=30,
            max_items_per_run=100,
        )
        assert rule.name == "custom_rule"
        assert rule.enabled is False
        assert rule.weight_threshold == 0.5


# =============================================================================
# PruningAction Tests
# =============================================================================


class TestPruningAction:
    """Tests for PruningAction enum."""

    def test_action_values(self):
        """Test enum values."""
        assert PruningAction.DELETE_RELATIONSHIP == "DELETE_RELATIONSHIP"
        assert PruningAction.DELETE_NODE == "DELETE_NODE"
        assert PruningAction.MERGE_NODES == "MERGE_NODES"
        assert PruningAction.ARCHIVE_THREAD == "ARCHIVE_THREAD"
        assert PruningAction.PREVIEW == "PREVIEW"


# =============================================================================
# AuditEntry Tests
# =============================================================================


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        timestamp = datetime(2026, 1, 22, 10, 30, 0)
        entry = AuditEntry(
            timestamp=timestamp,
            action=PruningAction.DELETE_RELATIONSHIP,
            entity_type="relationship",
            entity_id=12345,
            reason="Weight below threshold",
            metadata={"weight": 0.15, "relationship_type": "KNOWS"},
        )
        result = entry.to_dict()

        assert result["timestamp"] == "2026-01-22T10:30:00"
        assert result["action"] == "DELETE_RELATIONSHIP"
        assert result["entity_type"] == "relationship"
        assert result["entity_id"] == 12345
        assert result["reason"] == "Weight below threshold"
        assert result["metadata"]["weight"] == 0.15

    def test_to_dict_with_default_metadata(self):
        """Test to_dict with empty metadata."""
        entry = AuditEntry(
            timestamp=datetime.now(),
            action=PruningAction.PREVIEW,
            entity_type="node",
            entity_id="uuid-123",
            reason="Orphan node",
        )
        result = entry.to_dict()
        assert result["metadata"] == {}


# =============================================================================
# PruningResult Tests
# =============================================================================


class TestPruningResult:
    """Tests for PruningResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = PruningResult(
            operation="prune_weak_relationships",
            dry_run=True,
            relationships_found=10,
            relationships_pruned=5,
            nodes_found=0,
            nodes_removed=0,
            errors=["Error 1"],
            duration_ms=123.456,
        )
        d = result.to_dict()

        assert d["operation"] == "prune_weak_relationships"
        assert d["dry_run"] is True
        assert d["relationships_found"] == 10
        assert d["relationships_pruned"] == 5
        assert d["nodes_found"] == 0
        assert d["nodes_removed"] == 0
        assert d["errors"] == ["Error 1"]
        assert d["duration_ms"] == 123.46
        assert d["audit_entry_count"] == 0


# =============================================================================
# HullCleaner Tests
# =============================================================================


class TestHullCleanerInit:
    """Tests for HullCleaner initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default config."""
        mock_neo4j = MagicMock()
        cleaner = HullCleaner(neo4j_client=mock_neo4j)

        assert cleaner.name == "hull_cleaner"
        assert cleaner.neo4j == mock_neo4j
        assert cleaner.hull_config.prune_weak_relationships is True

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        mock_neo4j = MagicMock()
        config = HullCleanerConfig(
            weak_relationship_threshold=0.3,
            dry_run_by_default=False,
        )
        cleaner = HullCleaner(neo4j_client=mock_neo4j, config=config)

        assert cleaner.hull_config.weak_relationship_threshold == 0.3
        assert cleaner.hull_config.dry_run_by_default is False


class TestHullCleanerProcessMessage:
    """Tests for HullCleaner.process_message."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_process_scrape_barnacles(self, cleaner, mock_neo4j):
        """Test processing scrape_barnacles operation."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "scrape_barnacles", "dry_run": True},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)

        assert response is not None
        assert response.source_agent == "hull_cleaner"
        assert response.target_agent == "orchestrator"
        assert response.payload["operation"] == "scrape_barnacles"

    @pytest.mark.asyncio
    async def test_process_find_weak_relationships(self, cleaner, mock_neo4j):
        """Test processing find_weak_relationships operation."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "find_weak_relationships"},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)
        assert response is not None

    @pytest.mark.asyncio
    async def test_process_unknown_operation(self, cleaner):
        """Test processing unknown operation."""
        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "unknown_op"},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)
        assert response is not None
        assert "error" in response.payload


class TestFindWeakRelationships:
    """Tests for find_weak_relationships method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_find_weak_relationships_empty(self, cleaner, mock_neo4j):
        """Test finding weak relationships when none exist."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        result = await cleaner.find_weak_relationships()

        assert result == []

    @pytest.mark.asyncio
    async def test_find_weak_relationships_filters_by_age(self, cleaner, mock_neo4j):
        """Test that relationships are filtered by age."""
        # Simulate 2 relationships: one old, one recent
        now = time.time()
        old_time = now - (100 * 24 * 60 * 60)  # 100 days ago
        recent_time = now - (30 * 24 * 60 * 60)  # 30 days ago (too recent)

        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "rel_id": 1,
                    "rel_type": "KNOWS",
                    "source_name": "John",
                    "target_name": "Jane",
                    "weight": 0.15,
                    "last_accessed": old_time,
                },
                {
                    "rel_id": 2,
                    "rel_type": "KNOWS",
                    "source_name": "John",
                    "target_name": "Bob",
                    "weight": 0.18,
                    "last_accessed": recent_time,
                },
            ]
        )

        result = await cleaner.find_weak_relationships(age_days=90)

        # Only the old relationship should be returned
        assert len(result) == 1
        assert result[0].relationship_id == 1

    @pytest.mark.asyncio
    async def test_find_weak_relationships_includes_never_accessed(self, cleaner, mock_neo4j):
        """Test that relationships with no last_accessed are included."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "rel_id": 1,
                    "rel_type": "KNOWS",
                    "source_name": "John",
                    "target_name": "Jane",
                    "weight": 0.15,
                    "last_accessed": None,  # Never accessed
                },
            ]
        )

        result = await cleaner.find_weak_relationships()

        assert len(result) == 1


class TestPruneWeakRelationships:
    """Tests for prune_weak_relationships method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_prune_dry_run(self, cleaner, mock_neo4j):
        """Test pruning in dry run mode."""
        now = time.time()
        old_time = now - (100 * 24 * 60 * 60)

        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "rel_id": 1,
                    "rel_type": "KNOWS",
                    "source_name": "John",
                    "target_name": "Jane",
                    "weight": 0.15,
                    "last_accessed": old_time,
                },
            ]
        )

        result = await cleaner.prune_weak_relationships(dry_run=True)

        assert result.dry_run is True
        assert result.relationships_found == 1
        assert result.relationships_pruned == 1
        assert len(result.audit_entries) == 1
        assert result.audit_entries[0].action == PruningAction.PREVIEW

    @pytest.mark.asyncio
    async def test_prune_actual_delete(self, cleaner, mock_neo4j):
        """Test actual pruning (not dry run)."""
        now = time.time()
        old_time = now - (100 * 24 * 60 * 60)

        # First call returns weak relationships, second call deletes
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "rel_id": 1,
                        "rel_type": "KNOWS",
                        "source_name": "John",
                        "target_name": "Jane",
                        "weight": 0.15,
                        "last_accessed": old_time,
                    },
                ],
                [{"deleted": 1}],  # Delete result
            ]
        )

        result = await cleaner.prune_weak_relationships(dry_run=False)

        assert result.dry_run is False
        assert result.relationships_pruned == 1
        assert result.audit_entries[0].action == PruningAction.DELETE_RELATIONSHIP


class TestScrapeBarnacles:
    """Tests for scrape_barnacles method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_scrape_barnacles_dry_run(self, cleaner):
        """Test full scrape in dry run mode."""
        result = await cleaner.scrape_barnacles(dry_run=True)

        assert result.operation == "scrape_barnacles"
        assert result.dry_run is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_scrape_barnacles_with_disabled_rules(self, mock_neo4j):
        """Test scrape with disabled rules."""
        config = HullCleanerConfig(prune_weak_relationships=False)
        cleaner = HullCleaner(neo4j_client=mock_neo4j, config=config)

        result = await cleaner.scrape_barnacles(dry_run=True)

        # No weak relationships should be processed
        assert result.relationships_found == 0


class TestGetPruningStatistics:
    """Tests for get_pruning_statistics method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_get_statistics(self, cleaner, mock_neo4j):
        """Test getting pruning statistics."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "total_relationships": 100,
                    "avg_weight": 0.75,
                    "min_weight": 0.1,
                    "max_weight": 1.0,
                    "weak_count": 15,
                }
            ]
        )

        stats = await cleaner.get_pruning_statistics()

        assert stats["total_relationships"] == 100
        assert stats["avg_weight"] == 0.75
        assert stats["weak_count"] == 15
        assert stats["weak_percentage"] == 15.0

    @pytest.mark.asyncio
    async def test_get_statistics_empty_graph(self, cleaner, mock_neo4j):
        """Test statistics for empty graph."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        stats = await cleaner.get_pruning_statistics()

        assert stats["total_relationships"] == 0
        assert stats["weak_percentage"] == 0


class TestAuditLog:
    """Tests for audit log functionality."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    def test_get_audit_log_empty(self, cleaner):
        """Test getting empty audit log."""
        log = cleaner.get_audit_log()
        assert log == []

    def test_clear_audit_log(self, cleaner):
        """Test clearing audit log."""
        # Add an entry manually
        cleaner._audit_log.append(
            AuditEntry(
                timestamp=datetime.now(),
                action=PruningAction.PREVIEW,
                entity_type="test",
                entity_id=1,
                reason="test",
            )
        )

        cleaner.clear_audit_log()
        assert cleaner.get_audit_log() == []


# =============================================================================
# Orphan Message Tests
# =============================================================================


class TestFindOrphanMessages:
    """Tests for find_orphan_messages method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_find_orphans_empty(self, cleaner, mock_neo4j):
        """Test finding orphans when none exist."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        result = await cleaner.find_orphan_messages()

        assert result == []

    @pytest.mark.asyncio
    async def test_find_orphans_with_results(self, cleaner, mock_neo4j):
        """Test finding orphan messages."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "uuid": "orphan-1",
                    "content": "Orphaned message content",
                    "timestamp": 1234567890.0,
                    "role": "user",
                },
                {
                    "uuid": "orphan-2",
                    "content": "Another orphan",
                    "timestamp": 1234567891.0,
                    "role": "assistant",
                },
            ]
        )

        result = await cleaner.find_orphan_messages()

        assert len(result) == 2
        assert result[0].uuid == "orphan-1"
        assert result[1].role == "assistant"


class TestRemoveOrphanMessages:
    """Tests for remove_orphan_messages method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_remove_orphans_dry_run(self, cleaner, mock_neo4j):
        """Test removing orphans in dry run mode."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "uuid": "orphan-1",
                    "content": "Test content",
                    "timestamp": 1234567890.0,
                    "role": "user",
                },
            ]
        )

        result = await cleaner.remove_orphan_messages(dry_run=True)

        assert result.dry_run is True
        assert result.nodes_found == 1
        assert result.nodes_removed == 1  # Would be removed
        assert len(result.audit_entries) == 1
        assert result.audit_entries[0].action == PruningAction.PREVIEW

    @pytest.mark.asyncio
    async def test_remove_orphans_actual(self, cleaner, mock_neo4j):
        """Test actual orphan removal."""
        # First call returns orphans, second call is the count, third is delete
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_orphan_messages
                [
                    {
                        "uuid": "orphan-1",
                        "content": "Test",
                        "timestamp": 1234567890.0,
                        "role": "user",
                    },
                ],
                # count_orphan_messages (inside delete_orphan_messages)
                [{"count": 1}],
                # actual delete batch
                [{"deleted": 1}],
                # next delete batch (returns 0 to stop)
                [{"deleted": 0}],
            ]
        )

        result = await cleaner.remove_orphan_messages(dry_run=False)

        assert result.dry_run is False
        assert result.nodes_found == 1
        assert result.nodes_removed == 1
        assert result.audit_entries[0].action == PruningAction.DELETE_NODE


class TestScrapeBarnaclesWithOrphans:
    """Tests for scrape_barnacles with orphan cleanup enabled."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_scrape_includes_orphans(self, cleaner):
        """Test that scrape_barnacles includes orphan cleanup."""
        result = await cleaner.scrape_barnacles(dry_run=True)

        # Should have processed both weak rels and orphans
        assert result.operation == "scrape_barnacles"
        # Both operations should complete without errors
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_scrape_with_orphans_disabled(self, mock_neo4j):
        """Test scrape with orphan cleanup disabled."""
        config = HullCleanerConfig(
            prune_weak_relationships=False,
            remove_orphan_messages=False,
        )
        cleaner = HullCleaner(neo4j_client=mock_neo4j, config=config)

        result = await cleaner.scrape_barnacles(dry_run=True)

        # No operations should be processed
        assert result.relationships_found == 0
        assert result.nodes_found == 0


class TestProcessMessageOrphanOperations:
    """Tests for process_message with orphan operations."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_process_find_orphan_messages(self, cleaner, mock_neo4j):
        """Test processing find_orphan_messages operation."""
        mock_neo4j.execute_query = AsyncMock(
            return_value=[
                {
                    "uuid": "orphan-1",
                    "content": "Test content",
                    "timestamp": 1234567890.0,
                    "role": "user",
                },
            ]
        )

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "find_orphan_messages"},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["orphan_messages"]) == 1

    @pytest.mark.asyncio
    async def test_process_remove_orphan_messages(self, cleaner, mock_neo4j):
        """Test processing remove_orphan_messages operation."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "remove_orphan_messages", "dry_run": True},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)

        assert response is not None
        assert response.payload["operation"] == "remove_orphan_messages"


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that module exports are accessible."""

    def test_exports_from_agents_module(self):
        """Test that HullCleaner exports are available from agents module."""
        from klabautermann.agents import (
            AuditEntry,
            HullCleaner,
            HullCleanerConfig,
            PruningAction,
            PruningResult,
            PruningRule,
        )

        # Verify imports succeeded
        assert HullCleaner is not None
        assert HullCleanerConfig is not None
        assert PruningAction is not None
        assert PruningResult is not None
        assert PruningRule is not None
        assert AuditEntry is not None

    def test_new_exports_from_agents_module(self):
        """Test that new duplicate detection exports are available."""
        from klabautermann.agents import (
            DuplicateCandidate,
            MergeResult,
        )

        # Verify imports succeeded
        assert DuplicateCandidate is not None
        assert MergeResult is not None


# =============================================================================
# Duplicate Detection Tests (#84)
# =============================================================================


class TestDuplicateCandidate:
    """Tests for DuplicateCandidate dataclass."""

    def test_confidence_high_with_email_match(self):
        """Test HIGH confidence when emails match."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John Doe",
            name2="John D.",
            entity_type="Person",
            similarity=0.86,
            email_match=True,
        )
        assert candidate.confidence == "HIGH"

    def test_confidence_high_with_high_similarity(self):
        """Test HIGH confidence with similarity >= 0.95."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John Doe",
            name2="John Doe",
            entity_type="Person",
            similarity=0.98,
            email_match=False,
        )
        assert candidate.confidence == "HIGH"

    def test_confidence_medium(self):
        """Test MEDIUM confidence with similarity 0.85-0.95."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John Doe",
            name2="Jon Doe",
            entity_type="Person",
            similarity=0.90,
            email_match=False,
        )
        assert candidate.confidence == "MEDIUM"

    def test_confidence_low(self):
        """Test LOW confidence with similarity < 0.85."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John Doe",
            name2="Jane Doe",
            entity_type="Person",
            similarity=0.80,
            email_match=False,
        )
        assert candidate.confidence == "LOW"


class TestMergeResult:
    """Tests for MergeResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = MergeResult(
            operation="merge_duplicates",
            dry_run=True,
            duplicates_found=10,
            duplicates_merged=3,
            high_confidence=3,
            medium_confidence=7,
            errors=["Error 1"],
            duration_ms=123.456,
        )
        d = result.to_dict()

        assert d["operation"] == "merge_duplicates"
        assert d["dry_run"] is True
        assert d["duplicates_found"] == 10
        assert d["duplicates_merged"] == 3
        assert d["high_confidence"] == 3
        assert d["medium_confidence"] == 7
        assert d["errors"] == ["Error 1"]
        assert d["duration_ms"] == 123.46
        assert d["audit_entry_count"] == 0


class TestHullCleanerConfigDuplicates:
    """Tests for HullCleanerConfig duplicate detection settings."""

    def test_default_duplicate_values(self):
        """Test default duplicate detection configuration values."""
        config = HullCleanerConfig()
        assert config.detect_duplicates is True
        assert config.duplicate_similarity_threshold == 0.85
        assert config.duplicate_auto_merge_threshold == 0.95
        assert config.max_duplicates_per_run == 100

    def test_custom_duplicate_values(self):
        """Test custom duplicate detection configuration values."""
        config = HullCleanerConfig(
            detect_duplicates=False,
            duplicate_similarity_threshold=0.90,
            duplicate_auto_merge_threshold=0.98,
            max_duplicates_per_run=50,
        )
        assert config.detect_duplicates is False
        assert config.duplicate_similarity_threshold == 0.90
        assert config.duplicate_auto_merge_threshold == 0.98
        assert config.max_duplicates_per_run == 50


class TestPruningActionMergePreview:
    """Tests for MERGE_PREVIEW pruning action."""

    def test_merge_preview_action(self):
        """Test MERGE_PREVIEW enum value."""
        assert PruningAction.MERGE_PREVIEW == "MERGE_PREVIEW"


class TestFindDuplicateEntities:
    """Tests for find_duplicate_entities method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_find_duplicates_empty(self, cleaner, mock_neo4j):
        """Test finding duplicates when none exist."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        result = await cleaner.find_duplicate_entities()

        assert result == []

    @pytest.mark.asyncio
    async def test_find_duplicate_persons(self, cleaner, mock_neo4j):
        """Test finding duplicate Person nodes."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # Person query results
                [
                    {
                        "uuid1": "person-1",
                        "uuid2": "person-2",
                        "name1": "John Doe",
                        "name2": "Jon Doe",
                        "similarity": 0.88,
                        "email_match": False,
                    },
                ],
                # Organization query results (empty)
                [],
            ]
        )

        result = await cleaner.find_duplicate_entities()

        assert len(result) == 1
        assert result[0].entity_type == "Person"
        assert result[0].name1 == "John Doe"
        assert result[0].similarity == 0.88

    @pytest.mark.asyncio
    async def test_find_duplicate_organizations(self, cleaner, mock_neo4j):
        """Test finding duplicate Organization nodes."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # Person query results (empty)
                [],
                # Organization query results
                [
                    {
                        "uuid1": "org-1",
                        "uuid2": "org-2",
                        "name1": "Acme Corp",
                        "name2": "Acme Corporation",
                        "similarity": 0.92,
                    },
                ],
            ]
        )

        result = await cleaner.find_duplicate_entities()

        assert len(result) == 1
        assert result[0].entity_type == "Organization"
        assert result[0].name1 == "Acme Corp"

    @pytest.mark.asyncio
    async def test_find_duplicates_sorted_by_similarity(self, cleaner, mock_neo4j):
        """Test that duplicates are sorted by similarity (highest first)."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # Person query results
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "A",
                        "name2": "B",
                        "similarity": 0.86,
                        "email_match": False,
                    },
                    {
                        "uuid1": "p3",
                        "uuid2": "p4",
                        "name1": "C",
                        "name2": "D",
                        "similarity": 0.95,
                        "email_match": False,
                    },
                ],
                # Organization query results
                [
                    {"uuid1": "o1", "uuid2": "o2", "name1": "E", "name2": "F", "similarity": 0.90},
                ],
            ]
        )

        result = await cleaner.find_duplicate_entities()

        assert len(result) == 3
        # Should be sorted: 0.95, 0.90, 0.86
        assert result[0].similarity == 0.95
        assert result[1].similarity == 0.90
        assert result[2].similarity == 0.86

    @pytest.mark.asyncio
    async def test_find_duplicates_with_email_match(self, cleaner, mock_neo4j):
        """Test finding duplicates with email match."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "uuid1": "person-1",
                        "uuid2": "person-2",
                        "name1": "John D",
                        "name2": "John Doe",
                        "similarity": 0.87,
                        "email_match": True,
                    },
                ],
                [],
            ]
        )

        result = await cleaner.find_duplicate_entities()

        assert len(result) == 1
        assert result[0].email_match is True
        assert result[0].confidence == "HIGH"  # Email match = HIGH confidence


# =============================================================================
# Entity Merge Tests (#85)
# =============================================================================


class TestMergeDuplicates:
    """Tests for merge_duplicates method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_merge_dry_run(self, cleaner, mock_neo4j):
        """Test merging in dry run mode."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_duplicate_entities - persons
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John Doe",
                        "name2": "John Doe",
                        "similarity": 0.98,
                        "email_match": True,
                    },
                ],
                # find_duplicate_entities - orgs
                [],
            ]
        )

        result = await cleaner.merge_duplicates(dry_run=True)

        assert result.dry_run is True
        assert result.duplicates_found == 1
        assert result.duplicates_merged == 1  # Would be merged
        assert result.high_confidence == 1
        assert len(result.audit_entries) == 1
        assert result.audit_entries[0].action == PruningAction.MERGE_PREVIEW

    @pytest.mark.asyncio
    async def test_merge_actual(self, cleaner, mock_neo4j):
        """Test actual merging (not dry run)."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_duplicate_entities - persons
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John Doe",
                        "name2": "John Doe",
                        "similarity": 0.98,
                        "email_match": False,
                    },
                ],
                # find_duplicate_entities - orgs
                [],
                # _merge_nodes
                [{"merged_uuid": "p1"}],
            ]
        )

        result = await cleaner.merge_duplicates(dry_run=False)

        assert result.dry_run is False
        assert result.duplicates_merged == 1
        assert result.audit_entries[0].action == PruningAction.MERGE_NODES

    @pytest.mark.asyncio
    async def test_merge_auto_only_skips_medium(self, cleaner, mock_neo4j):
        """Test that auto_merge_only skips MEDIUM confidence duplicates."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_duplicate_entities - persons
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John Doe",
                        "name2": "Jon Doe",
                        "similarity": 0.90,  # MEDIUM confidence
                        "email_match": False,
                    },
                ],
                # find_duplicate_entities - orgs
                [],
            ]
        )

        result = await cleaner.merge_duplicates(dry_run=False, auto_merge_only=True)

        # Should create a preview entry but not merge
        assert result.duplicates_merged == 0
        assert result.medium_confidence == 1
        assert len(result.audit_entries) == 1
        assert result.audit_entries[0].action == PruningAction.MERGE_PREVIEW
        assert result.audit_entries[0].metadata["requires_review"] is True

    @pytest.mark.asyncio
    async def test_merge_skips_low_confidence(self, cleaner, mock_neo4j):
        """Test that LOW confidence duplicates are skipped entirely."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_duplicate_entities - persons
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John",
                        "name2": "Jane",
                        "similarity": 0.82,  # LOW confidence (but still > threshold)
                        "email_match": False,
                    },
                ],
                # find_duplicate_entities - orgs
                [],
            ]
        )

        # Use a threshold that would still find this
        cleaner.hull_config.duplicate_similarity_threshold = 0.80

        result = await cleaner.merge_duplicates(dry_run=False)

        # Should skip LOW confidence entirely
        assert result.duplicates_merged == 0
        assert len(result.audit_entries) == 0

    @pytest.mark.asyncio
    async def test_merge_handles_errors(self, cleaner, mock_neo4j):
        """Test that merge errors are captured in result."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # find_duplicate_entities - persons
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John Doe",
                        "name2": "John Doe",
                        "similarity": 0.98,
                        "email_match": False,
                    },
                ],
                # find_duplicate_entities - orgs
                [],
                # _merge_nodes - throws error
                Exception("APOC merge failed"),
            ]
        )

        result = await cleaner.merge_duplicates(dry_run=False)

        assert result.duplicates_merged == 0
        assert len(result.errors) == 1
        assert "APOC merge failed" in result.errors[0]


class TestMergeNodes:
    """Tests for _merge_nodes method."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_merge_nodes_success(self, cleaner, mock_neo4j):
        """Test successful node merge."""
        mock_neo4j.execute_query = AsyncMock(return_value=[{"merged_uuid": "keep-uuid"}])

        result = await cleaner._merge_nodes("keep-uuid", "remove-uuid")

        assert result is True
        # Verify the query was called with correct parameters
        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["keep_uuid"] == "keep-uuid"
        assert call_args[0][1]["remove_uuid"] == "remove-uuid"

    @pytest.mark.asyncio
    async def test_merge_nodes_failure(self, cleaner, mock_neo4j):
        """Test failed node merge (no result)."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        result = await cleaner._merge_nodes("keep-uuid", "remove-uuid")

        assert result is False


class TestProcessMessageDuplicateOperations:
    """Tests for process_message with duplicate operations."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_process_find_duplicates(self, cleaner, mock_neo4j):
        """Test processing find_duplicates operation."""
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                # Person duplicates
                [
                    {
                        "uuid1": "p1",
                        "uuid2": "p2",
                        "name1": "John Doe",
                        "name2": "Jon Doe",
                        "similarity": 0.88,
                        "email_match": False,
                    },
                ],
                # Org duplicates
                [],
            ]
        )

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "find_duplicates"},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["duplicates"]) == 1
        assert response.payload["duplicates"][0]["name1"] == "John Doe"
        assert response.payload["duplicates"][0]["confidence"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_process_merge_duplicates(self, cleaner, mock_neo4j):
        """Test processing merge_duplicates operation."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="hull_cleaner",
            intent="maintenance",
            payload={"operation": "merge_duplicates", "dry_run": True},
            trace_id="test-trace",
        )

        response = await cleaner.process_message(msg)

        assert response is not None
        assert response.payload["operation"] == "merge_duplicates"


class TestScrapeBarnaclesWithDuplicates:
    """Tests for scrape_barnacles with duplicate detection enabled."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def cleaner(self, mock_neo4j):
        """Create HullCleaner with mock client."""
        return HullCleaner(neo4j_client=mock_neo4j)

    @pytest.mark.asyncio
    async def test_scrape_includes_duplicates(self, cleaner):
        """Test that scrape_barnacles includes duplicate detection."""
        result = await cleaner.scrape_barnacles(dry_run=True)

        # Should have processed weak rels, orphans, and duplicates
        assert result.operation == "scrape_barnacles"
        # All operations should complete without errors
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_scrape_with_duplicates_disabled(self, mock_neo4j):
        """Test scrape with duplicate detection disabled."""
        config = HullCleanerConfig(
            prune_weak_relationships=False,
            remove_orphan_messages=False,
            detect_duplicates=False,
        )
        cleaner = HullCleaner(neo4j_client=mock_neo4j, config=config)

        result = await cleaner.scrape_barnacles(dry_run=True)

        # No operations should be processed
        assert result.relationships_found == 0
        assert result.nodes_found == 0

    @pytest.mark.asyncio
    async def test_scrape_handles_duplicate_errors(self, cleaner, mock_neo4j):
        """Test that scrape_barnacles handles duplicate merge errors gracefully."""
        # First two calls succeed (weak rels, orphans), third fails
        mock_neo4j.execute_query = AsyncMock(
            side_effect=[
                [],  # weak rels
                [],  # orphans
                Exception("Duplicate detection failed"),  # duplicates - persons
            ]
        )

        result = await cleaner.scrape_barnacles(dry_run=True)

        # Should have captured the error but not crashed
        assert len(result.errors) == 1
        assert "Duplicate entity merge failed" in result.errors[0]
