"""
HullCleaner agent for Klabautermann.

Graph pruning and maintenance agent that removes "barnacles" - weak relationships,
redundant paths, and stale data that accumulate over time. This keeps the graph
performant and reduces noise in search results.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 5
Issues: #79, #80, #81, #88
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage
from klabautermann.memory.weight_decay import (
    RelationshipWeight,
    get_low_weight_relationships,
)


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Configuration
# =============================================================================


class PruningAction(str, Enum):
    """Types of pruning actions."""

    DELETE_RELATIONSHIP = "DELETE_RELATIONSHIP"
    DELETE_NODE = "DELETE_NODE"
    MERGE_NODES = "MERGE_NODES"
    ARCHIVE_THREAD = "ARCHIVE_THREAD"
    PREVIEW = "PREVIEW"


@dataclass
class PruningRule:
    """Configuration for a pruning rule."""

    name: str
    enabled: bool = True
    weight_threshold: float = 0.2
    age_days: int = 90
    max_items_per_run: int = 1000


@dataclass
class HullCleanerConfig:
    """Configuration for HullCleaner agent."""

    # Enable/disable specific pruning rules
    prune_weak_relationships: bool = True
    weak_relationship_threshold: float = 0.2
    weak_relationship_age_days: int = 90

    # Run limits
    max_deletions_per_run: int = 1000
    dry_run_by_default: bool = True

    # Scheduling (for future use)
    schedule_cron: str = "0 2 * * 0"  # Sunday 02:00


# =============================================================================
# Audit Trail
# =============================================================================


@dataclass
class AuditEntry:
    """A single audit log entry for a pruning action."""

    timestamp: datetime
    action: PruningAction
    entity_type: str  # "relationship" or "node"
    entity_id: int | str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass
class PruningResult:
    """Result of a pruning operation."""

    operation: str
    dry_run: bool
    relationships_found: int
    relationships_pruned: int
    nodes_found: int
    nodes_removed: int
    errors: list[str]
    duration_ms: float
    audit_entries: list[AuditEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "dry_run": self.dry_run,
            "relationships_found": self.relationships_found,
            "relationships_pruned": self.relationships_pruned,
            "nodes_found": self.nodes_found,
            "nodes_removed": self.nodes_removed,
            "errors": self.errors,
            "duration_ms": round(self.duration_ms, 2),
            "audit_entry_count": len(self.audit_entries),
        }


# =============================================================================
# HullCleaner Agent
# =============================================================================


class HullCleaner(BaseAgent):
    """
    Graph pruning and maintenance agent.

    The Hull Cleaner removes "barnacles" - weak relationships, redundant paths,
    and stale data that accumulate over time. This keeps the graph performant
    and reduces noise in search results.
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        config: HullCleanerConfig | None = None,
    ) -> None:
        """
        Initialize HullCleaner.

        Args:
            neo4j_client: Connected Neo4j client for graph operations.
            config: Optional configuration for pruning behavior.
        """
        super().__init__(name="hull_cleaner")
        self.neo4j = neo4j_client
        self.hull_config = config or HullCleanerConfig()

        # Audit log for the current session
        self._audit_log: list[AuditEntry] = []

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process an incoming message.

        HullCleaner responds to maintenance commands.

        Args:
            msg: The incoming agent message.

        Returns:
            Response message with pruning results.
        """
        trace_id = msg.trace_id
        payload = msg.payload or {}

        operation = payload.get("operation", "scrape_barnacles")
        dry_run = payload.get("dry_run", self.hull_config.dry_run_by_default)

        logger.info(
            f"[CHART] HullCleaner processing {operation} (dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if operation == "scrape_barnacles":
            result = await self.scrape_barnacles(dry_run=dry_run, trace_id=trace_id)
            result_payload = result.to_dict()
        elif operation == "find_weak_relationships":
            weak_rels = await self.find_weak_relationships(trace_id=trace_id)
            result_payload = {
                "weak_relationships": [
                    {
                        "relationship_id": r.relationship_id,
                        "relationship_type": r.relationship_type,
                        "source_name": r.source_name,
                        "target_name": r.target_name,
                        "current_weight": r.current_weight,
                        "days_since_access": r.days_since_access,
                    }
                    for r in weak_rels
                ],
                "count": len(weak_rels),
            }
        elif operation == "prune_weak_relationships":
            result = await self.prune_weak_relationships(dry_run=dry_run, trace_id=trace_id)
            result_payload = result.to_dict()
        else:
            result_payload = {"error": f"Unknown operation: {operation}"}

        return AgentMessage(
            source_agent=self.name,
            target_agent=msg.source_agent,
            intent="hull_cleaner_result",
            payload=result_payload,
            trace_id=trace_id,
        )

    # =========================================================================
    # Main Operations
    # =========================================================================

    async def scrape_barnacles(
        self,
        dry_run: bool = True,
        trace_id: str | None = None,
    ) -> PruningResult:
        """
        Main pruning routine - remove all types of graph barnacles.

        This is the primary entry point that runs all enabled pruning rules.

        Args:
            dry_run: If True, only preview changes without deleting.
            trace_id: Optional trace ID for logging.

        Returns:
            PruningResult with operation statistics.
        """
        start_time = time.time()
        self._audit_log = []  # Reset audit log for this run
        errors: list[str] = []

        total_rels_found = 0
        total_rels_pruned = 0
        total_nodes_found = 0
        total_nodes_removed = 0

        logger.info(
            f"[CHART] Starting barnacle scraping (dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # 1. Prune weak relationships
        if self.hull_config.prune_weak_relationships:
            try:
                weak_result = await self.prune_weak_relationships(
                    dry_run=dry_run, trace_id=trace_id
                )
                total_rels_found += weak_result.relationships_found
                total_rels_pruned += weak_result.relationships_pruned
                self._audit_log.extend(weak_result.audit_entries)
            except Exception as e:
                error_msg = f"Weak relationship pruning failed: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

        # Future: Add more pruning operations here
        # - Orphan message removal
        # - Duplicate entity detection
        # - Transitive path reduction

        duration_ms = (time.time() - start_time) * 1000

        result = PruningResult(
            operation="scrape_barnacles",
            dry_run=dry_run,
            relationships_found=total_rels_found,
            relationships_pruned=total_rels_pruned,
            nodes_found=total_nodes_found,
            nodes_removed=total_nodes_removed,
            errors=errors,
            duration_ms=duration_ms,
            audit_entries=self._audit_log,
        )

        logger.info(
            f"[BEACON] Barnacle scraping complete: "
            f"found {total_rels_found} weak relationships, "
            f"pruned {total_rels_pruned} "
            f"({'preview' if dry_run else 'actual'})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return result

    # =========================================================================
    # Weak Relationship Operations
    # =========================================================================

    async def find_weak_relationships(
        self,
        threshold: float | None = None,
        age_days: int | None = None,
        limit: int | None = None,
        trace_id: str | None = None,
    ) -> list[RelationshipWeight]:
        """
        Find relationships with low weight and old age.

        These are candidates for pruning - relationships that haven't been
        accessed recently and have decayed below the threshold.

        Args:
            threshold: Weight threshold (default from config).
            age_days: Minimum age in days (default from config).
            limit: Maximum relationships to return.
            trace_id: Optional trace ID for logging.

        Returns:
            List of RelationshipWeight objects representing weak relationships.
        """
        threshold = threshold or self.hull_config.weak_relationship_threshold
        age_days = age_days or self.hull_config.weak_relationship_age_days
        limit = limit or self.hull_config.max_deletions_per_run

        logger.debug(
            f"[WHISPER] Finding weak relationships (threshold={threshold}, age_days={age_days})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Use existing weight_decay infrastructure
        weak_rels = await get_low_weight_relationships(
            neo4j=self.neo4j,
            threshold=threshold,
            limit=limit,
            trace_id=trace_id,
        )

        # Filter by age
        now = time.time()
        age_threshold_seconds = age_days * 24 * 60 * 60
        filtered_rels = []

        for rel in weak_rels:
            if rel.last_accessed is not None:
                age_seconds = now - rel.last_accessed
                if age_seconds >= age_threshold_seconds:
                    filtered_rels.append(rel)
            else:
                # No last_accessed means never accessed - include it
                filtered_rels.append(rel)

        logger.debug(
            f"[WHISPER] Found {len(filtered_rels)} weak relationships "
            f"(filtered from {len(weak_rels)})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return filtered_rels

    async def prune_weak_relationships(
        self,
        dry_run: bool = True,
        threshold: float | None = None,
        age_days: int | None = None,
        trace_id: str | None = None,
    ) -> PruningResult:
        """
        Delete weak relationships from the graph.

        Args:
            dry_run: If True, only preview changes without deleting.
            threshold: Weight threshold (default from config).
            age_days: Minimum age in days (default from config).
            trace_id: Optional trace ID for logging.

        Returns:
            PruningResult with operation statistics.
        """
        start_time = time.time()
        threshold = threshold or self.hull_config.weak_relationship_threshold
        age_days = age_days or self.hull_config.weak_relationship_age_days

        logger.info(
            f"[CHART] Pruning weak relationships "
            f"(threshold={threshold}, age_days={age_days}, dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Find candidates
        weak_rels = await self.find_weak_relationships(
            threshold=threshold,
            age_days=age_days,
            trace_id=trace_id,
        )

        audit_entries: list[AuditEntry] = []
        pruned_count = 0
        errors: list[str] = []

        for rel in weak_rels:
            # Create audit entry
            entry = AuditEntry(
                timestamp=datetime.now(),
                action=PruningAction.PREVIEW if dry_run else PruningAction.DELETE_RELATIONSHIP,
                entity_type="relationship",
                entity_id=rel.relationship_id,
                reason=f"Weight {rel.current_weight:.3f} below threshold {threshold}, "
                f"not accessed for {rel.days_since_access:.0f} days",
                metadata={
                    "relationship_type": rel.relationship_type,
                    "source_name": rel.source_name,
                    "target_name": rel.target_name,
                    "weight": rel.current_weight,
                    "days_since_access": rel.days_since_access,
                },
            )
            audit_entries.append(entry)

            if not dry_run:
                try:
                    await self._delete_relationship(rel.relationship_id, trace_id)
                    pruned_count += 1
                except Exception as e:
                    error_msg = f"Failed to delete relationship {rel.relationship_id}: {e}"
                    logger.error(
                        f"[STORM] {error_msg}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    errors.append(error_msg)
            else:
                pruned_count += 1  # Count as "would be pruned" in dry run

        duration_ms = (time.time() - start_time) * 1000

        result = PruningResult(
            operation="prune_weak_relationships",
            dry_run=dry_run,
            relationships_found=len(weak_rels),
            relationships_pruned=pruned_count,
            nodes_found=0,
            nodes_removed=0,
            errors=errors,
            duration_ms=duration_ms,
            audit_entries=audit_entries,
        )

        logger.info(
            f"[BEACON] Weak relationship pruning complete: "
            f"found {len(weak_rels)}, pruned {pruned_count} "
            f"({'preview' if dry_run else 'actual'})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return result

    async def _delete_relationship(
        self,
        relationship_id: int,
        trace_id: str | None = None,
    ) -> bool:
        """
        Delete a relationship by its Neo4j internal ID.

        Args:
            relationship_id: Neo4j internal relationship ID.
            trace_id: Optional trace ID for logging.

        Returns:
            True if relationship was deleted, False otherwise.
        """
        query = """
        MATCH ()-[r]->()
        WHERE id(r) = $rel_id
        DELETE r
        RETURN count(r) as deleted
        """

        result = await self.neo4j.execute_query(
            query,
            {"rel_id": relationship_id},
            trace_id=trace_id,
        )

        deleted: int = result[0]["deleted"] if result else 0

        logger.debug(
            f"[WHISPER] Deleted relationship {relationship_id}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return deleted > 0

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_pruning_statistics(
        self,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Get statistics about graph health and pruning candidates.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Dictionary with graph health metrics.
        """
        threshold = self.hull_config.weak_relationship_threshold

        # Get relationship weight distribution
        query = """
        MATCH ()-[r]->()
        WHERE r.weight IS NOT NULL
        RETURN
            count(r) as total_relationships,
            avg(r.weight) as avg_weight,
            min(r.weight) as min_weight,
            max(r.weight) as max_weight,
            sum(CASE WHEN r.weight < $threshold THEN 1 ELSE 0 END) as weak_count
        """

        result = await self.neo4j.execute_query(
            query,
            {"threshold": threshold},
            trace_id=trace_id,
        )

        if not result:
            return {
                "total_relationships": 0,
                "avg_weight": 0,
                "min_weight": 0,
                "max_weight": 0,
                "weak_count": 0,
                "weak_percentage": 0,
            }

        row = result[0]
        total = row.get("total_relationships", 0)
        weak = row.get("weak_count", 0)

        return {
            "total_relationships": total,
            "avg_weight": round(row.get("avg_weight", 0), 3),
            "min_weight": round(row.get("min_weight", 0), 3),
            "max_weight": round(row.get("max_weight", 0), 3),
            "weak_count": weak,
            "weak_percentage": round((weak / total * 100) if total > 0 else 0, 1),
            "threshold": threshold,
        }

    def get_audit_log(self) -> list[dict[str, Any]]:
        """
        Get the current session's audit log.

        Returns:
            List of audit entry dictionaries.
        """
        return [entry.to_dict() for entry in self._audit_log]

    def clear_audit_log(self) -> None:
        """Clear the current session's audit log."""
        self._audit_log = []


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "AuditEntry",
    "HullCleaner",
    "HullCleanerConfig",
    "PruningAction",
    "PruningResult",
    "PruningRule",
]
