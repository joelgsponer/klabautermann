"""
Graph backup and restore functionality for Klabautermann.

Provides JSON-based export/import of the Neo4j knowledge graph for
backup, migration, and disaster recovery purposes.

Features:
- Export all nodes and relationships to JSON
- Include all properties with timestamp metadata
- Validate consistency after restore
- Optionally clear existing data before restore

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.ontology import NodeLabel, RelationType


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class BackupMetadata:
    """Metadata about a backup snapshot."""

    created_at: str
    version: str = "1.0"
    node_count: int = 0
    relationship_count: int = 0
    node_labels: list[str] = field(default_factory=list)
    relationship_types: list[str] = field(default_factory=list)
    source_database: str = "neo4j"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "created_at": self.created_at,
            "version": self.version,
            "node_count": self.node_count,
            "relationship_count": self.relationship_count,
            "node_labels": self.node_labels,
            "relationship_types": self.relationship_types,
            "source_database": self.source_database,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupMetadata:
        """Create from dictionary."""
        return cls(
            created_at=data["created_at"],
            version=data.get("version", "1.0"),
            node_count=data.get("node_count", 0),
            relationship_count=data.get("relationship_count", 0),
            node_labels=data.get("node_labels", []),
            relationship_types=data.get("relationship_types", []),
            source_database=data.get("source_database", "neo4j"),
        )


@dataclass
class BackupSnapshot:
    """A complete snapshot of the graph database."""

    metadata: BackupMetadata
    nodes: list[dict[str, Any]]
    relationships: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "metadata": self.metadata.to_dict(),
            "nodes": self.nodes,
            "relationships": self.relationships,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupSnapshot:
        """Create from dictionary."""
        return cls(
            metadata=BackupMetadata.from_dict(data["metadata"]),
            nodes=data.get("nodes", []),
            relationships=data.get("relationships", []),
        )


@dataclass
class RestoreResult:
    """Result of a restore operation."""

    success: bool
    nodes_restored: int = 0
    relationships_restored: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# Backup Functions
# =============================================================================


async def create_backup(
    client: Neo4jClient,
    trace_id: str | None = None,
) -> BackupSnapshot:
    """
    Create a backup snapshot of the entire graph database.

    Exports all nodes and relationships with their properties to a
    BackupSnapshot object that can be serialized to JSON.

    Args:
        client: Connected Neo4j client.
        trace_id: Optional trace ID for logging.

    Returns:
        BackupSnapshot containing all graph data.
    """
    logger.info(
        "[CHART] Starting graph backup...",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Export all nodes with labels and properties
    node_query = """
    MATCH (n)
    RETURN labels(n) as labels, properties(n) as props, elementId(n) as id
    """
    nodes_result = await client.execute_query(node_query, trace_id=trace_id, timeout_ms=120000)

    nodes = []
    node_labels_set: set[str] = set()

    for record in nodes_result:
        labels = record["labels"]
        props = record["props"]
        element_id = record["id"]

        node_labels_set.update(labels)
        nodes.append(
            {
                "element_id": element_id,
                "labels": labels,
                "properties": props,
            }
        )

    logger.debug(
        f"[WHISPER] Exported {len(nodes)} nodes",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Export all relationships with types and properties
    rel_query = """
    MATCH (a)-[r]->(b)
    RETURN type(r) as type, properties(r) as props,
           elementId(a) as from_id, elementId(b) as to_id,
           labels(a) as from_labels, labels(b) as to_labels,
           properties(a).uuid as from_uuid, properties(b).uuid as to_uuid
    """
    rels_result = await client.execute_query(rel_query, trace_id=trace_id, timeout_ms=120000)

    relationships = []
    rel_types_set: set[str] = set()

    for record in rels_result:
        rel_type = record["type"]
        rel_types_set.add(rel_type)

        relationships.append(
            {
                "type": rel_type,
                "properties": record["props"],
                "from_element_id": record["from_id"],
                "to_element_id": record["to_id"],
                "from_labels": record["from_labels"],
                "to_labels": record["to_labels"],
                "from_uuid": record["from_uuid"],
                "to_uuid": record["to_uuid"],
            }
        )

    logger.debug(
        f"[WHISPER] Exported {len(relationships)} relationships",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Create metadata
    metadata = BackupMetadata(
        created_at=datetime.now(UTC).isoformat(),
        node_count=len(nodes),
        relationship_count=len(relationships),
        node_labels=sorted(node_labels_set),
        relationship_types=sorted(rel_types_set),
    )

    logger.info(
        f"[BEACON] Backup complete: {metadata.node_count} nodes, "
        f"{metadata.relationship_count} relationships",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    return BackupSnapshot(
        metadata=metadata,
        nodes=nodes,
        relationships=relationships,
    )


async def save_backup_to_file(
    snapshot: BackupSnapshot,
    filepath: Path | str,
    trace_id: str | None = None,
) -> None:
    """
    Save a backup snapshot to a JSON file.

    Args:
        snapshot: Backup snapshot to save.
        filepath: Path to the output JSON file.
        trace_id: Optional trace ID for logging.
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with filepath.open("w", encoding="utf-8") as f:
        json.dump(snapshot.to_dict(), f, indent=2, default=str)

    file_size = filepath.stat().st_size
    logger.info(
        f"[BEACON] Backup saved to {filepath} ({file_size / 1024:.1f} KB)",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )


async def load_backup_from_file(
    filepath: Path | str,
    trace_id: str | None = None,
) -> BackupSnapshot:
    """
    Load a backup snapshot from a JSON file.

    Args:
        filepath: Path to the backup JSON file.
        trace_id: Optional trace ID for logging.

    Returns:
        BackupSnapshot loaded from the file.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file isn't valid JSON.
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Backup file not found: {filepath}")

    with filepath.open("r", encoding="utf-8") as f:
        data = json.load(f)

    snapshot = BackupSnapshot.from_dict(data)

    logger.info(
        f"[CHART] Loaded backup from {filepath}: "
        f"{snapshot.metadata.node_count} nodes, "
        f"{snapshot.metadata.relationship_count} relationships",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    return snapshot


# =============================================================================
# Restore Functions
# =============================================================================


async def clear_database(
    client: Neo4jClient,
    trace_id: str | None = None,
) -> int:
    """
    Clear all data from the database.

    WARNING: This permanently deletes all nodes and relationships!

    Args:
        client: Connected Neo4j client.
        trace_id: Optional trace ID for logging.

    Returns:
        Number of nodes deleted.
    """
    logger.warning(
        "[STORM] Clearing database - all data will be deleted!",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Delete in batches to avoid memory issues
    total_deleted = 0
    batch_size = 1000

    while True:
        # Delete batch of nodes (relationships deleted automatically)
        delete_query = """
        MATCH (n)
        WITH n LIMIT $batch_size
        DETACH DELETE n
        RETURN count(*) as deleted
        """
        result = await client.execute_query(
            delete_query,
            {"batch_size": batch_size},
            trace_id=trace_id,
            timeout_ms=60000,
        )

        deleted = result[0]["deleted"] if result else 0
        total_deleted += deleted

        if deleted < batch_size:
            break

    logger.info(
        f"[BEACON] Database cleared: {total_deleted} nodes deleted",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    return total_deleted


async def restore_backup(
    client: Neo4jClient,
    snapshot: BackupSnapshot,
    clear_existing: bool = False,
    trace_id: str | None = None,
) -> RestoreResult:
    """
    Restore a backup snapshot to the database.

    Args:
        client: Connected Neo4j client.
        snapshot: Backup snapshot to restore.
        clear_existing: If True, clear all existing data first.
        trace_id: Optional trace ID for logging.

    Returns:
        RestoreResult with restore statistics.
    """
    logger.info(
        f"[CHART] Starting restore: {snapshot.metadata.node_count} nodes, "
        f"{snapshot.metadata.relationship_count} relationships",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    errors: list[str] = []
    warnings: list[str] = []

    # Clear existing data if requested
    if clear_existing:
        await clear_database(client, trace_id)

    # Map old element IDs to new UUIDs for relationship restoration
    id_mapping: dict[str, str] = {}

    # Restore nodes
    nodes_restored = 0
    for node in snapshot.nodes:
        labels = node["labels"]
        props = node["properties"]
        old_id = node["element_id"]

        # Validate labels exist in our ontology
        valid_labels = []
        for label in labels:
            try:
                NodeLabel(label)
                valid_labels.append(label)
            except ValueError:
                # Allow labels not in enum (for Graphiti-managed nodes)
                valid_labels.append(label)

        if not valid_labels:
            warnings.append(f"Node with no valid labels: {old_id}")
            continue

        # Create node with original properties
        label_str = ":".join(valid_labels)
        create_query = (
            f"CREATE (n:{label_str} $props) RETURN n.uuid as uuid, elementId(n) as new_id"
        )

        try:
            result = await client.execute_query(
                create_query,
                {"props": props},
                trace_id=trace_id,
            )

            if result:
                # Map old ID to new UUID for relationship creation
                new_uuid = result[0].get("uuid") or props.get("uuid")
                if new_uuid:
                    id_mapping[old_id] = new_uuid
                nodes_restored += 1

        except Exception as e:
            errors.append(f"Failed to restore node {old_id}: {e}")

    logger.debug(
        f"[WHISPER] Restored {nodes_restored}/{len(snapshot.nodes)} nodes",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Restore relationships
    relationships_restored = 0
    for rel in snapshot.relationships:
        rel_type = rel["type"]
        props = rel["properties"]
        from_uuid = rel.get("from_uuid")
        to_uuid = rel.get("to_uuid")
        from_labels = rel.get("from_labels", [])
        to_labels = rel.get("to_labels", [])

        # Skip if we don't have UUIDs
        if not from_uuid or not to_uuid:
            warnings.append(f"Skipping relationship with missing UUIDs: {rel_type}")
            continue

        # Validate relationship type (allow types not in enum for Graphiti-managed)
        with contextlib.suppress(ValueError):
            RelationType(rel_type)

        # Build label matches
        from_label = from_labels[0] if from_labels else ""
        to_label = to_labels[0] if to_labels else ""

        # Create relationship using UUIDs
        if from_label and to_label:
            rel_query = f"""
            MATCH (a:{from_label} {{uuid: $from_uuid}})
            MATCH (b:{to_label} {{uuid: $to_uuid}})
            CREATE (a)-[r:{rel_type} $props]->(b)
            RETURN r
            """
        else:
            rel_query = f"""
            MATCH (a {{uuid: $from_uuid}})
            MATCH (b {{uuid: $to_uuid}})
            CREATE (a)-[r:{rel_type} $props]->(b)
            RETURN r
            """

        try:
            result = await client.execute_query(
                rel_query,
                {"from_uuid": from_uuid, "to_uuid": to_uuid, "props": props or {}},
                trace_id=trace_id,
            )

            if result:
                relationships_restored += 1

        except Exception as e:
            errors.append(f"Failed to restore relationship {rel_type}: {e}")

    logger.debug(
        f"[WHISPER] Restored {relationships_restored}/{len(snapshot.relationships)} relationships",
        extra={"trace_id": trace_id, "agent_name": "backup"},
    )

    # Determine success
    success = len(errors) == 0

    if success:
        logger.info(
            f"[BEACON] Restore complete: {nodes_restored} nodes, "
            f"{relationships_restored} relationships",
            extra={"trace_id": trace_id, "agent_name": "backup"},
        )
    else:
        logger.error(
            f"[STORM] Restore completed with {len(errors)} errors",
            extra={"trace_id": trace_id, "agent_name": "backup"},
        )

    return RestoreResult(
        success=success,
        nodes_restored=nodes_restored,
        relationships_restored=relationships_restored,
        errors=errors,
        warnings=warnings,
    )


# =============================================================================
# Validation
# =============================================================================


async def validate_backup(
    snapshot: BackupSnapshot,
    trace_id: str | None = None,
) -> list[str]:
    """
    Validate a backup snapshot for consistency.

    Checks:
    - Metadata matches actual counts
    - All relationships reference valid nodes
    - No duplicate UUIDs within same label

    Args:
        snapshot: Backup snapshot to validate.
        trace_id: Optional trace ID for logging.

    Returns:
        List of validation errors (empty if valid).
    """
    errors: list[str] = []

    # Check metadata counts
    if snapshot.metadata.node_count != len(snapshot.nodes):
        errors.append(
            f"Node count mismatch: metadata says {snapshot.metadata.node_count}, "
            f"actual is {len(snapshot.nodes)}"
        )

    if snapshot.metadata.relationship_count != len(snapshot.relationships):
        errors.append(
            f"Relationship count mismatch: metadata says {snapshot.metadata.relationship_count}, "
            f"actual is {len(snapshot.relationships)}"
        )

    # Build set of node element IDs
    node_ids = {node["element_id"] for node in snapshot.nodes}

    # Check relationships reference valid nodes
    for rel in snapshot.relationships:
        from_id = rel.get("from_element_id")
        to_id = rel.get("to_element_id")

        if from_id and from_id not in node_ids:
            errors.append(f"Relationship references non-existent from node: {from_id}")

        if to_id and to_id not in node_ids:
            errors.append(f"Relationship references non-existent to node: {to_id}")

    # Check for duplicate UUIDs within same label
    uuid_by_label: dict[str, set[str]] = {}
    for node in snapshot.nodes:
        props = node.get("properties", {})
        uuid = props.get("uuid")
        labels = node.get("labels", [])

        if uuid:
            for label in labels:
                if label not in uuid_by_label:
                    uuid_by_label[label] = set()

                if uuid in uuid_by_label[label]:
                    errors.append(f"Duplicate UUID in {label}: {uuid}")
                else:
                    uuid_by_label[label].add(uuid)

    return errors


# =============================================================================
# Export
# =============================================================================


__all__ = [
    "BackupMetadata",
    "BackupSnapshot",
    "RestoreResult",
    "clear_database",
    "create_backup",
    "load_backup_from_file",
    "restore_backup",
    "save_backup_to_file",
    "validate_backup",
]
