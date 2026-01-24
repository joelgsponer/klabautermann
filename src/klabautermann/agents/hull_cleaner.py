"""
HullCleaner agent for Klabautermann.

Graph pruning and maintenance agent that removes "barnacles" - weak relationships,
redundant paths, and stale data that accumulate over time. This keeps the graph
performant and reduces noise in search results.

Also handles duplicate entity detection using Levenshtein similarity and
entity merging using APOC refactor operations.

Audit entries are generated for all pruning operations and can be persisted
to Neo4j as AuditLog nodes for historical review and compliance.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 5
Issues: #79, #80, #81, #84, #85, #86, #87, #88
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
from klabautermann.memory.orphan_cleanup import (
    OrphanMessage,
    delete_orphan_messages,
    find_orphan_messages,
)
from klabautermann.memory.weight_decay import (
    RelationshipWeight,
    get_low_weight_relationships,
)


if TYPE_CHECKING:
    from klabautermann.memory.audit_log import AuditLogStats, StoredAuditEntry
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
    MERGE_PREVIEW = "MERGE_PREVIEW"
    TRANSITIVE_REDUCTION = "TRANSITIVE_REDUCTION"
    TRANSITIVE_PREVIEW = "TRANSITIVE_PREVIEW"


@dataclass
class TransitivePath:
    """A redundant transitive path A->B->C where A->C also exists."""

    source_uuid: str
    intermediate_uuid: str
    target_uuid: str
    source_name: str
    intermediate_name: str
    target_name: str
    relationship_type: str
    direct_weight: float  # Weight of A->C
    indirect_weight: float  # Combined weight of A->B + B->C
    redundant_rel_id: int  # ID of the relationship to remove

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_uuid": self.source_uuid,
            "intermediate_uuid": self.intermediate_uuid,
            "target_uuid": self.target_uuid,
            "source_name": self.source_name,
            "intermediate_name": self.intermediate_name,
            "target_name": self.target_name,
            "relationship_type": self.relationship_type,
            "direct_weight": round(self.direct_weight, 3),
            "indirect_weight": round(self.indirect_weight, 3),
            "redundant_rel_id": self.redundant_rel_id,
        }


@dataclass
class TransitiveResult:
    """Result of a transitive reduction operation."""

    operation: str
    dry_run: bool
    paths_found: int
    paths_reduced: int
    errors: list[str]
    duration_ms: float
    audit_entries: list[AuditEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "dry_run": self.dry_run,
            "paths_found": self.paths_found,
            "paths_reduced": self.paths_reduced,
            "errors": self.errors,
            "duration_ms": round(self.duration_ms, 2),
            "audit_entry_count": len(self.audit_entries),
        }


@dataclass
class DuplicateCandidate:
    """A candidate pair of potentially duplicate entities."""

    uuid1: str
    uuid2: str
    name1: str
    name2: str
    entity_type: str  # "Person" or "Organization"
    similarity: float
    email_match: bool = False

    @property
    def confidence(self) -> str:
        """Get confidence level for this duplicate pair."""
        if self.email_match or self.similarity >= 0.95:
            return "HIGH"
        elif self.similarity >= 0.85:
            return "MEDIUM"
        else:
            return "LOW"


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

    # Orphan cleanup settings
    remove_orphan_messages: bool = True
    orphan_batch_size: int = 50

    # Duplicate detection settings
    detect_duplicates: bool = True
    duplicate_similarity_threshold: float = 0.85
    duplicate_auto_merge_threshold: float = 0.95  # Auto-merge above this threshold
    max_duplicates_per_run: int = 100

    # Transitive redundancy detection settings (#86)
    detect_transitive_redundancy: bool = True
    transitive_weight_threshold: float = 0.5  # Remove if direct > indirect combined
    max_transitive_per_run: int = 100

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


@dataclass
class MergeResult:
    """Result of a duplicate merge operation."""

    operation: str
    dry_run: bool
    duplicates_found: int
    duplicates_merged: int
    high_confidence: int
    medium_confidence: int
    errors: list[str]
    duration_ms: float
    audit_entries: list[AuditEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "dry_run": self.dry_run,
            "duplicates_found": self.duplicates_found,
            "duplicates_merged": self.duplicates_merged,
            "high_confidence": self.high_confidence,
            "medium_confidence": self.medium_confidence,
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
        persist_audit = payload.get("persist_audit", False)

        logger.info(
            f"[CHART] HullCleaner processing {operation} (dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if operation == "scrape_barnacles":
            result = await self.scrape_barnacles(
                dry_run=dry_run, persist_audit=persist_audit, trace_id=trace_id
            )
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
        elif operation == "find_orphan_messages":
            orphans = await self.find_orphan_messages(trace_id=trace_id)
            result_payload = {
                "orphan_messages": [
                    {
                        "uuid": o.uuid,
                        "content": o.content[:100] if o.content else None,
                        "role": o.role,
                    }
                    for o in orphans
                ],
                "count": len(orphans),
            }
        elif operation == "remove_orphan_messages":
            result = await self.remove_orphan_messages(dry_run=dry_run, trace_id=trace_id)
            result_payload = result.to_dict()
        elif operation == "find_duplicates":
            duplicates = await self.find_duplicate_entities(trace_id=trace_id)
            result_payload = {
                "duplicates": [
                    {
                        "uuid1": d.uuid1,
                        "uuid2": d.uuid2,
                        "name1": d.name1,
                        "name2": d.name2,
                        "entity_type": d.entity_type,
                        "similarity": round(d.similarity, 3),
                        "confidence": d.confidence,
                        "email_match": d.email_match,
                    }
                    for d in duplicates
                ],
                "count": len(duplicates),
            }
        elif operation == "merge_duplicates":
            merge_result = await self.merge_duplicates(dry_run=dry_run, trace_id=trace_id)
            result_payload = merge_result.to_dict()
        elif operation == "find_transitive_paths":
            paths = await self.find_transitive_paths(trace_id=trace_id)
            result_payload = {
                "transitive_paths": [p.to_dict() for p in paths],
                "count": len(paths),
            }
        elif operation == "reduce_transitive_paths":
            transitive_result = await self.reduce_transitive_paths(
                dry_run=dry_run, trace_id=trace_id
            )
            result_payload = transitive_result.to_dict()
        elif operation == "query_stored_audit":
            # Query persisted audit entries from Neo4j
            filters = payload.get("filters", {})
            stored_entries = await self.query_stored_audit(filters=filters, trace_id=trace_id)
            result_payload = {
                "entries": [e.to_dict() for e in stored_entries],
                "count": len(stored_entries),
            }
        elif operation == "get_audit_stats":
            # Get audit log statistics
            stats = await self.get_audit_stats(trace_id=trace_id)
            result_payload = stats.to_dict() if stats else {}
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
        persist_audit: bool = False,
        trace_id: str | None = None,
    ) -> PruningResult:
        """
        Main pruning routine - remove all types of graph barnacles.

        This is the primary entry point that runs all enabled pruning rules.

        Args:
            dry_run: If True, only preview changes without deleting.
            persist_audit: If True, save audit entries to Neo4j AuditLog nodes.
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

        # 2. Remove orphan messages
        if self.hull_config.remove_orphan_messages:
            try:
                orphan_result = await self.remove_orphan_messages(
                    dry_run=dry_run, trace_id=trace_id
                )
                total_nodes_found += orphan_result.nodes_found
                total_nodes_removed += orphan_result.nodes_removed
                self._audit_log.extend(orphan_result.audit_entries)
            except Exception as e:
                error_msg = f"Orphan message removal failed: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

        # 3. Detect and merge duplicate entities
        if self.hull_config.detect_duplicates:
            try:
                merge_result = await self.merge_duplicates(dry_run=dry_run, trace_id=trace_id)
                # Merged nodes count as "removed" (uuid2 merged into uuid1)
                total_nodes_found += merge_result.duplicates_found
                total_nodes_removed += merge_result.duplicates_merged
                self._audit_log.extend(merge_result.audit_entries)
            except Exception as e:
                error_msg = f"Duplicate entity merge failed: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

        # 4. Detect and reduce transitive redundancy
        if self.hull_config.detect_transitive_redundancy:
            try:
                transitive_result = await self.reduce_transitive_paths(
                    dry_run=dry_run, trace_id=trace_id
                )
                total_rels_found += transitive_result.paths_found
                total_rels_pruned += transitive_result.paths_reduced
                self._audit_log.extend(transitive_result.audit_entries)
            except Exception as e:
                error_msg = f"Transitive reduction failed: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

        # Persist audit entries to Neo4j if requested
        if persist_audit and self._audit_log:
            try:
                await self._persist_audit_log(trace_id=trace_id)
            except Exception as e:
                error_msg = f"Audit log persistence failed: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

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
            f"found {total_rels_found} weak relationships (pruned {total_rels_pruned}), "
            f"found {total_nodes_found} orphan messages (removed {total_nodes_removed}) "
            f"({'preview' if dry_run else 'actual'})"
            f"{' (audit persisted)' if persist_audit else ''}",
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
    # Orphan Message Operations
    # =========================================================================

    async def find_orphan_messages(
        self,
        limit: int | None = None,
        trace_id: str | None = None,
    ) -> list[OrphanMessage]:
        """
        Find messages not linked to any thread.

        These are candidates for cleanup - messages that were created but
        never properly linked due to failed transactions or bugs.

        Args:
            limit: Maximum orphans to return (default from config).
            trace_id: Optional trace ID for logging.

        Returns:
            List of OrphanMessage objects representing orphan messages.
        """
        limit = limit or self.hull_config.max_deletions_per_run

        logger.debug(
            f"[WHISPER] Finding orphan messages (limit={limit})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Use existing orphan_cleanup infrastructure
        orphans = await find_orphan_messages(
            neo4j=self.neo4j,
            limit=limit,
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Found {len(orphans)} orphan messages",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return orphans

    async def remove_orphan_messages(
        self,
        dry_run: bool = True,
        trace_id: str | None = None,
    ) -> PruningResult:
        """
        Delete orphan messages from the graph.

        Args:
            dry_run: If True, only preview changes without deleting.
            trace_id: Optional trace ID for logging.

        Returns:
            PruningResult with operation statistics.
        """
        start_time = time.time()

        logger.info(
            f"[CHART] Removing orphan messages (dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Find orphans first
        orphans = await self.find_orphan_messages(trace_id=trace_id)

        audit_entries: list[AuditEntry] = []
        removed_count = 0
        errors: list[str] = []

        for orphan in orphans:
            # Create audit entry
            entry = AuditEntry(
                timestamp=datetime.now(),
                action=PruningAction.PREVIEW if dry_run else PruningAction.DELETE_NODE,
                entity_type="message",
                entity_id=orphan.uuid,
                reason="Message not linked to any thread",
                metadata={
                    "role": orphan.role,
                    "content_preview": orphan.content[:50] if orphan.content else None,
                },
            )
            audit_entries.append(entry)

        if not dry_run:
            # Use existing delete_orphan_messages for actual deletion
            cleanup_result = await delete_orphan_messages(
                neo4j=self.neo4j,
                batch_size=self.hull_config.orphan_batch_size,
                dry_run=False,
                trace_id=trace_id,
            )
            removed_count = cleanup_result.deleted_count
            if cleanup_result.failed_count > 0:
                errors.append(f"Failed to delete {cleanup_result.failed_count} orphan batches")
        else:
            removed_count = len(orphans)  # Count as "would be removed" in dry run

        duration_ms = (time.time() - start_time) * 1000

        result = PruningResult(
            operation="remove_orphan_messages",
            dry_run=dry_run,
            relationships_found=0,
            relationships_pruned=0,
            nodes_found=len(orphans),
            nodes_removed=removed_count,
            errors=errors,
            duration_ms=duration_ms,
            audit_entries=audit_entries,
        )

        logger.info(
            f"[BEACON] Orphan message removal complete: "
            f"found {len(orphans)}, removed {removed_count} "
            f"({'preview' if dry_run else 'actual'})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return result

    # =========================================================================
    # Duplicate Entity Operations
    # =========================================================================

    async def find_duplicate_entities(
        self,
        threshold: float | None = None,
        limit: int | None = None,
        trace_id: str | None = None,
    ) -> list[DuplicateCandidate]:
        """
        Find potential duplicate Person/Organization nodes using Levenshtein similarity.

        Uses APOC text similarity functions to compare entity names.

        Args:
            threshold: Similarity threshold (default from config, typically 0.85).
            limit: Maximum duplicates to return (default from config).
            trace_id: Optional trace ID for logging.

        Returns:
            List of DuplicateCandidate objects representing potential duplicates.
        """
        threshold = threshold or self.hull_config.duplicate_similarity_threshold
        limit = limit or self.hull_config.max_duplicates_per_run

        logger.debug(
            f"[WHISPER] Finding duplicate entities (threshold={threshold})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        duplicates: list[DuplicateCandidate] = []

        # Find duplicate Persons
        person_query = """
        MATCH (p1:Person), (p2:Person)
        WHERE p1.uuid < p2.uuid
          AND p1.name IS NOT NULL
          AND p2.name IS NOT NULL
          AND apoc.text.levenshteinSimilarity(
              toLower(p1.name),
              toLower(p2.name)
          ) > $threshold
        WITH p1, p2,
             apoc.text.levenshteinSimilarity(toLower(p1.name), toLower(p2.name)) as similarity,
             CASE WHEN p1.email IS NOT NULL AND p1.email = p2.email THEN true ELSE false END as email_match
        RETURN p1.uuid as uuid1, p2.uuid as uuid2,
               p1.name as name1, p2.name as name2,
               similarity, email_match
        ORDER BY similarity DESC
        LIMIT $limit
        """

        person_results = await self.neo4j.execute_query(
            person_query,
            {"threshold": threshold, "limit": limit},
            trace_id=trace_id,
        )

        for row in person_results:
            duplicates.append(
                DuplicateCandidate(
                    uuid1=row["uuid1"],
                    uuid2=row["uuid2"],
                    name1=row["name1"],
                    name2=row["name2"],
                    entity_type="Person",
                    similarity=row["similarity"],
                    email_match=row["email_match"],
                )
            )

        # Find duplicate Organizations
        org_query = """
        MATCH (o1:Organization), (o2:Organization)
        WHERE o1.uuid < o2.uuid
          AND o1.name IS NOT NULL
          AND o2.name IS NOT NULL
          AND apoc.text.levenshteinSimilarity(
              toLower(o1.name),
              toLower(o2.name)
          ) > $threshold
        WITH o1, o2,
             apoc.text.levenshteinSimilarity(toLower(o1.name), toLower(o2.name)) as similarity
        RETURN o1.uuid as uuid1, o2.uuid as uuid2,
               o1.name as name1, o2.name as name2,
               similarity
        ORDER BY similarity DESC
        LIMIT $limit
        """

        org_results = await self.neo4j.execute_query(
            org_query,
            {"threshold": threshold, "limit": limit},
            trace_id=trace_id,
        )

        for row in org_results:
            duplicates.append(
                DuplicateCandidate(
                    uuid1=row["uuid1"],
                    uuid2=row["uuid2"],
                    name1=row["name1"],
                    name2=row["name2"],
                    entity_type="Organization",
                    similarity=row["similarity"],
                    email_match=False,
                )
            )

        # Sort by similarity descending (highest confidence first)
        duplicates.sort(key=lambda d: d.similarity, reverse=True)

        logger.debug(
            f"[WHISPER] Found {len(duplicates)} potential duplicates "
            f"({sum(1 for d in duplicates if d.entity_type == 'Person')} persons, "
            f"{sum(1 for d in duplicates if d.entity_type == 'Organization')} orgs)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return duplicates

    async def merge_duplicates(
        self,
        dry_run: bool = True,
        auto_merge_only: bool = True,
        trace_id: str | None = None,
    ) -> MergeResult:
        """
        Merge duplicate entities, preserving all relationships.

        Uses APOC refactor to merge nodes. By default, only auto-merges
        HIGH confidence duplicates (similarity >= 0.95 or email match).

        Args:
            dry_run: If True, only preview changes without merging.
            auto_merge_only: If True, only merge HIGH confidence duplicates.
            trace_id: Optional trace ID for logging.

        Returns:
            MergeResult with operation statistics.
        """
        start_time = time.time()

        logger.info(
            f"[CHART] Merging duplicate entities "
            f"(dry_run={dry_run}, auto_merge_only={auto_merge_only})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Find all duplicates
        duplicates = await self.find_duplicate_entities(trace_id=trace_id)

        audit_entries: list[AuditEntry] = []
        merged_count = 0
        high_confidence_count = 0
        medium_confidence_count = 0
        errors: list[str] = []

        for dup in duplicates:
            if dup.confidence == "HIGH":
                high_confidence_count += 1
            elif dup.confidence == "MEDIUM":
                medium_confidence_count += 1

            # Skip low confidence duplicates
            if dup.confidence == "LOW":
                continue

            # In auto_merge_only mode, skip MEDIUM confidence
            if auto_merge_only and dup.confidence == "MEDIUM":
                # Still create a preview entry for review
                entry = AuditEntry(
                    timestamp=datetime.now(),
                    action=PruningAction.MERGE_PREVIEW,
                    entity_type=dup.entity_type.lower(),
                    entity_id=f"{dup.uuid1}:{dup.uuid2}",
                    reason=f"Medium confidence duplicate: '{dup.name1}' ≈ '{dup.name2}' "
                    f"(similarity: {dup.similarity:.2%})",
                    metadata={
                        "uuid1": dup.uuid1,
                        "uuid2": dup.uuid2,
                        "name1": dup.name1,
                        "name2": dup.name2,
                        "similarity": dup.similarity,
                        "confidence": dup.confidence,
                        "requires_review": True,
                    },
                )
                audit_entries.append(entry)
                continue

            # Create audit entry for HIGH confidence merge
            entry = AuditEntry(
                timestamp=datetime.now(),
                action=PruningAction.MERGE_PREVIEW if dry_run else PruningAction.MERGE_NODES,
                entity_type=dup.entity_type.lower(),
                entity_id=f"{dup.uuid1}:{dup.uuid2}",
                reason=f"High confidence duplicate: '{dup.name1}' ≈ '{dup.name2}' "
                f"(similarity: {dup.similarity:.2%}"
                f"{', email match' if dup.email_match else ''})",
                metadata={
                    "uuid1": dup.uuid1,
                    "uuid2": dup.uuid2,
                    "name1": dup.name1,
                    "name2": dup.name2,
                    "similarity": dup.similarity,
                    "confidence": dup.confidence,
                    "email_match": dup.email_match,
                },
            )
            audit_entries.append(entry)

            if not dry_run:
                try:
                    await self._merge_nodes(dup.uuid1, dup.uuid2, trace_id)
                    merged_count += 1
                except Exception as e:
                    error_msg = f"Failed to merge {dup.name1} with {dup.name2}: {e}"
                    logger.error(
                        f"[STORM] {error_msg}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    errors.append(error_msg)
            else:
                merged_count += 1  # Count as "would be merged" in dry run

        duration_ms = (time.time() - start_time) * 1000

        result = MergeResult(
            operation="merge_duplicates",
            dry_run=dry_run,
            duplicates_found=len(duplicates),
            duplicates_merged=merged_count,
            high_confidence=high_confidence_count,
            medium_confidence=medium_confidence_count,
            errors=errors,
            duration_ms=duration_ms,
            audit_entries=audit_entries,
        )

        logger.info(
            f"[BEACON] Duplicate merge complete: "
            f"found {len(duplicates)} duplicates, "
            f"merged {merged_count} HIGH confidence "
            f"({medium_confidence_count} MEDIUM require review) "
            f"({'preview' if dry_run else 'actual'})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return result

    async def _merge_nodes(
        self,
        keep_uuid: str,
        remove_uuid: str,
        trace_id: str | None = None,
    ) -> bool:
        """
        Merge two nodes using APOC, preserving all relationships.

        The node with keep_uuid is preserved, and all relationships from
        remove_uuid are transferred to it.

        Args:
            keep_uuid: UUID of the node to keep.
            remove_uuid: UUID of the node to merge into keep_uuid.
            trace_id: Optional trace ID for logging.

        Returns:
            True if merge was successful, False otherwise.
        """
        # Use APOC refactor to merge nodes
        # properties: 'combine' keeps all properties from both nodes
        # mergeRels: true transfers all relationships
        query = """
        MATCH (keep {uuid: $keep_uuid}), (remove {uuid: $remove_uuid})
        CALL apoc.refactor.mergeNodes([keep, remove], {
            properties: 'combine',
            mergeRels: true
        })
        YIELD node
        RETURN node.uuid as merged_uuid
        """

        result = await self.neo4j.execute_query(
            query,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid},
            trace_id=trace_id,
        )

        if result:
            logger.debug(
                f"[WHISPER] Merged {remove_uuid} into {keep_uuid}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return True

        return False

    # =========================================================================
    # Transitive Redundancy Detection (#86)
    # =========================================================================

    async def find_transitive_paths(
        self,
        limit: int | None = None,
        trace_id: str | None = None,
    ) -> list[TransitivePath]:
        """
        Find redundant transitive paths in the graph.

        A transitive path A->B->C is redundant when:
        1. A direct relationship A->C exists
        2. The direct relationship has equal or greater weight

        Args:
            limit: Maximum paths to return.
            trace_id: Optional trace ID for logging.

        Returns:
            List of TransitivePath objects describing redundant paths.
        """
        limit = limit or self.hull_config.max_transitive_per_run

        logger.info(
            "[CHART] Searching for transitive redundancy",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Find triangles where direct relationship is stronger than indirect path
        # Only consider weighted relationship types used by Graphiti
        query = """
        MATCH (a)-[r1]->(b)-[r2]->(c)
        WHERE (a)-[direct]->(c)
        AND type(r1) = type(r2)
        AND type(r1) = type(direct)
        AND r1.weight IS NOT NULL
        AND r2.weight IS NOT NULL
        AND direct.weight IS NOT NULL
        AND direct.weight >= (r1.weight + r2.weight) / 2
        AND a <> c
        AND a <> b
        AND b <> c
        RETURN DISTINCT
            a.uuid as source_uuid,
            b.uuid as intermediate_uuid,
            c.uuid as target_uuid,
            COALESCE(a.name, a.uuid) as source_name,
            COALESCE(b.name, b.uuid) as intermediate_name,
            COALESCE(c.name, c.uuid) as target_name,
            type(r2) as relationship_type,
            direct.weight as direct_weight,
            (r1.weight + r2.weight) / 2 as indirect_weight,
            id(r2) as redundant_rel_id
        ORDER BY direct_weight - indirect_weight DESC
        LIMIT $limit
        """

        result = await self.neo4j.execute_query(
            query,
            {"limit": limit},
            trace_id=trace_id,
        )

        paths = [
            TransitivePath(
                source_uuid=row["source_uuid"],
                intermediate_uuid=row["intermediate_uuid"],
                target_uuid=row["target_uuid"],
                source_name=row["source_name"],
                intermediate_name=row["intermediate_name"],
                target_name=row["target_name"],
                relationship_type=row["relationship_type"],
                direct_weight=float(row["direct_weight"]),
                indirect_weight=float(row["indirect_weight"]),
                redundant_rel_id=int(row["redundant_rel_id"]),
            )
            for row in result
        ]

        logger.info(
            f"[BEACON] Found {len(paths)} transitive redundant paths",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return paths

    async def reduce_transitive_paths(
        self,
        dry_run: bool = True,
        trace_id: str | None = None,
    ) -> TransitiveResult:
        """
        Find and remove redundant transitive relationships.

        When A->B->C exists and A->C also exists with sufficient weight,
        the B->C relationship is redundant and can be removed.

        Args:
            dry_run: If True, only preview without deleting.
            trace_id: Optional trace ID for logging.

        Returns:
            TransitiveResult with operation statistics.
        """
        start_time = time.time()
        errors: list[str] = []

        logger.info(
            f"[CHART] Starting transitive reduction (dry_run={dry_run})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Find redundant paths
        paths = await self.find_transitive_paths(trace_id=trace_id)

        audit_entries: list[AuditEntry] = []
        paths_reduced = 0

        for path in paths:
            # Create audit entry
            action = (
                PruningAction.TRANSITIVE_PREVIEW if dry_run else PruningAction.TRANSITIVE_REDUCTION
            )
            entry = AuditEntry(
                timestamp=datetime.now(),
                action=action,
                entity_type="relationship",
                entity_id=path.redundant_rel_id,
                reason=(
                    f"Transitive redundancy: {path.source_name}->{path.intermediate_name}"
                    f"->{path.target_name} (direct weight {path.direct_weight:.2f} >= "
                    f"indirect {path.indirect_weight:.2f})"
                ),
                metadata={
                    "source_uuid": path.source_uuid,
                    "intermediate_uuid": path.intermediate_uuid,
                    "target_uuid": path.target_uuid,
                    "relationship_type": path.relationship_type,
                    "direct_weight": path.direct_weight,
                    "indirect_weight": path.indirect_weight,
                },
            )
            audit_entries.append(entry)

            if not dry_run:
                try:
                    # Delete the redundant relationship
                    delete_query = """
                    MATCH ()-[r]->()
                    WHERE id(r) = $rel_id
                    DELETE r
                    RETURN count(r) as deleted
                    """
                    query_result = await self.neo4j.execute_query(
                        delete_query,
                        {"rel_id": path.redundant_rel_id},
                        trace_id=trace_id,
                    )
                    if query_result and query_result[0].get("deleted", 0) > 0:
                        paths_reduced += 1
                except Exception as e:
                    errors.append(f"Failed to delete relationship {path.redundant_rel_id}: {e}")

        if dry_run:
            paths_reduced = len(paths)  # Preview counts all found as "would reduce"

        duration_ms = (time.time() - start_time) * 1000

        result = TransitiveResult(
            operation="reduce_transitive_paths",
            dry_run=dry_run,
            paths_found=len(paths),
            paths_reduced=paths_reduced,
            errors=errors,
            duration_ms=duration_ms,
            audit_entries=audit_entries,
        )

        logger.info(
            f"[BEACON] Transitive reduction complete: "
            f"found {len(paths)} paths, reduced {paths_reduced} "
            f"({'preview' if dry_run else 'actual'})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return result

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

    # =========================================================================
    # Persistent Audit Log Operations (#87)
    # =========================================================================

    async def _persist_audit_log(
        self,
        trace_id: str | None = None,
    ) -> list[str]:
        """
        Persist the current session's audit entries to Neo4j.

        Creates AuditLog nodes for each entry in the session log.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of created AuditLog node UUIDs.
        """
        if not self._audit_log:
            return []

        # Import here to avoid circular imports
        from klabautermann.memory.audit_log import save_audit_entries

        uuids = await save_audit_entries(
            neo4j=self.neo4j,
            entries=self._audit_log,
            agent_name=self.name,
            trace_id=trace_id,
        )

        logger.info(
            f"[BEACON] Persisted {len(uuids)} audit entries to graph",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return uuids

    async def query_stored_audit(
        self,
        filters: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> list[StoredAuditEntry]:
        """
        Query persisted audit entries from Neo4j.

        Args:
            filters: Dictionary with filter parameters:
                - start_time: ISO format datetime string
                - end_time: ISO format datetime string
                - action_types: List of action type strings
                - entity_types: List of entity type strings
                - agent_name: Agent name filter
                - limit: Max entries to return (default 100)
                - offset: Skip first N entries
            trace_id: Optional trace ID for logging.

        Returns:
            List of StoredAuditEntry objects.
        """
        from datetime import datetime as dt

        from klabautermann.memory.audit_log import AuditQueryFilter, query_audit_log

        # Build filter from dict
        filter_obj = AuditQueryFilter()

        if filters:
            if filters.get("start_time"):
                filter_obj.start_time = dt.fromisoformat(filters["start_time"])
            if filters.get("end_time"):
                filter_obj.end_time = dt.fromisoformat(filters["end_time"])
            if filters.get("action_types"):
                filter_obj.action_types = filters["action_types"]
            if filters.get("entity_types"):
                filter_obj.entity_types = filters["entity_types"]
            if filters.get("agent_name"):
                filter_obj.agent_name = filters["agent_name"]
            if filters.get("limit"):
                filter_obj.limit = filters["limit"]
            if filters.get("offset"):
                filter_obj.offset = filters["offset"]

        entries = await query_audit_log(
            neo4j=self.neo4j,
            filters=filter_obj,
            trace_id=trace_id,
        )

        return entries

    async def get_audit_stats(
        self,
        trace_id: str | None = None,
    ) -> AuditLogStats | None:
        """
        Get statistics about persisted audit entries.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            AuditLogStats with counts and date ranges, or None if error.
        """
        from klabautermann.memory.audit_log import get_audit_stats

        try:
            stats = await get_audit_stats(
                neo4j=self.neo4j,
                trace_id=trace_id,
            )
            return stats
        except Exception as e:
            logger.error(
                f"[STORM] Failed to get audit stats: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "AuditEntry",
    "DuplicateCandidate",
    "HullCleaner",
    "HullCleanerConfig",
    "MergeResult",
    "PruningAction",
    "PruningResult",
    "PruningRule",
    "TransitivePath",
    "TransitiveResult",
]
