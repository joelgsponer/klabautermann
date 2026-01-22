"""
Ontology validation for Klabautermann.

Validates extracted entities and relationships against the Klabautermann ontology
before ingestion. Ensures type safety and property constraints are met.

Reference: specs/architecture/ONTOLOGY.md Section 7
Issues: #11, #13
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from klabautermann.core.logger import logger
from klabautermann.core.ontology import (
    ENTITY_TYPES,
    NodeLabel,
    RelationType,
)


# ===========================================================================
# Validation Result Types
# ===========================================================================


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""

    ERROR = "error"  # Blocks ingestion
    WARNING = "warning"  # Logged but allows ingestion
    INFO = "info"  # Informational only


@dataclass
class ValidationIssue:
    """A single validation issue found during entity/relationship validation."""

    severity: ValidationSeverity
    code: str  # Machine-readable code (e.g., "INVALID_ENTITY_TYPE")
    message: str  # Human-readable description
    entity_name: str | None = None
    entity_type: str | None = None
    property_name: str | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "property_name": self.property_name,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class ValidationResult:
    """Result of validating an extraction against the ontology."""

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    entities_validated: int = 0
    relationships_validated: int = 0

    @property
    def error_count(self) -> int:
        """Count of ERROR severity issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of WARNING severity issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.WARNING)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "entities_validated": self.entities_validated,
            "relationships_validated": self.relationships_validated,
            "issues": [i.to_dict() for i in self.issues],
        }


# ===========================================================================
# Pre-Extraction Entity Models
# ===========================================================================


class ExtractedEntity(BaseModel):
    """An entity extracted by the LLM before Graphiti ingestion."""

    name: str = Field(..., min_length=1, description="Entity name")
    entity_type: str = Field(..., description="Entity type from ontology")
    properties: dict[str, Any] = Field(default_factory=dict, description="Entity properties")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        """Ensure entity type uses proper casing."""
        # Allow both "Person" and "person" - normalize to title case
        return v.title() if v.islower() else v


class ExtractedRelationship(BaseModel):
    """A relationship extracted by the LLM before Graphiti ingestion."""

    source_name: str = Field(..., min_length=1, description="Source entity name")
    source_type: str = Field(..., description="Source entity type")
    relationship_type: str = Field(..., description="Relationship type from ontology")
    target_name: str = Field(..., min_length=1, description="Target entity name")
    target_type: str = Field(..., description="Target entity type")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship properties")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence")

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v: str) -> str:
        """Ensure relationship type uses proper casing (UPPER_SNAKE)."""
        return v.upper()


class ExtractionResult(BaseModel):
    """Complete extraction result from LLM pre-extraction."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    source_text: str = Field(default="", description="Original text that was analyzed")


# ===========================================================================
# Ontology Validator
# ===========================================================================


# Valid entity types from the ontology (NodeLabel enum values)
VALID_ENTITY_TYPES: set[str] = {label.value for label in NodeLabel}

# Valid relationship types from the ontology (RelationType enum values)
VALID_RELATIONSHIP_TYPES: set[str] = {rel.value for rel in RelationType}

# Relationship source/target constraints
# Maps relationship type to allowed (source_types, target_types)
RELATIONSHIP_CONSTRAINTS: dict[str, tuple[set[str], set[str]]] = {
    # Professional Context
    "WORKS_AT": ({"Person"}, {"Organization"}),
    "REPORTS_TO": ({"Person"}, {"Person"}),
    "AFFILIATED_WITH": ({"Person"}, {"Organization"}),
    # Action Hierarchy
    "CONTRIBUTES_TO": ({"Project"}, {"Goal"}),
    "PART_OF": ({"Task", "Project"}, {"Project"}),
    "SUBTASK_OF": ({"Task"}, {"Task"}),
    "BLOCKS": ({"Task"}, {"Task"}),
    "DEPENDS_ON": ({"Task"}, {"Task"}),
    "ASSIGNED_TO": ({"Task"}, {"Person"}),
    # Spatial Context
    "HELD_AT": ({"Event"}, {"Location"}),
    "LOCATED_IN": ({"Person", "Organization"}, {"Location"}),
    "CREATED_AT_LOCATION": ({"Note"}, {"Location"}),
    # Knowledge Linking
    "REFERENCES": ({"Note", "Resource"}, {"Resource"}),
    "SUMMARIZES": ({"Note"}, {"Event", "Thread"}),
    "SUMMARY_OF": ({"Note"}, {"Thread"}),
    "MENTIONED_IN": (
        {"Person", "Organization", "Project", "Task"},
        {"Note", "Event", "Message"},
    ),
    "DISCUSSED": ({"Event"}, {"Project", "Task", "Goal"}),
    # Event Context
    "ATTENDED": ({"Person"}, {"Event"}),
    "ORGANIZED_BY": ({"Event"}, {"Person", "Organization"}),
    # Email Context
    "SENT_BY": ({"Email"}, {"Person"}),
    "SENT_TO": ({"Email"}, {"Person"}),
    "PART_OF_EMAIL_THREAD": ({"Email"}, {"Thread"}),
    # Calendar Context
    "ATTENDED_BY": ({"CalendarEvent"}, {"Person"}),
    "HELD_AT_LOCATION": ({"CalendarEvent"}, {"Location"}),
    # Information Lineage
    "VERSION_OF": ({"Resource"}, {"Resource"}),
    "REPLIES_TO": ({"Note", "Message"}, {"Note", "Message"}),
    "ATTACHED_TO": ({"Resource"}, {"Event", "Note", "Email"}),
    # Interpersonal Context
    "KNOWS": ({"Person"}, {"Person"}),
    "INTRODUCED_BY": ({"Person"}, {"Person"}),
    # Family & Personal Relationships
    "FAMILY_OF": ({"Person"}, {"Person"}),
    "SPOUSE_OF": ({"Person"}, {"Person"}),
    "PARENT_OF": ({"Person"}, {"Person"}),
    "CHILD_OF": ({"Person"}, {"Person"}),
    "SIBLING_OF": ({"Person"}, {"Person"}),
    "FRIEND_OF": ({"Person"}, {"Person"}),
    # Personal Life
    "PRACTICES": ({"Person"}, {"Hobby"}),
    "INTERESTED_IN": ({"Person"}, {"Hobby", "Note", "Project"}),
    "PREFERS": ({"Person"}, {"Preference"}),
    "OWNS": ({"Person"}, {"Pet"}),
    "CARES_FOR": ({"Person"}, {"Pet"}),
    "RECORDED": ({"Person"}, {"HealthMetric"}),
    "ACHIEVES": ({"Person"}, {"Milestone"}),
    "FOLLOWS_ROUTINE": ({"Person"}, {"Routine"}),
    # Community (Knowledge Islands)
    "PART_OF_ISLAND": (
        {"Person", "Project", "Note", "Hobby", "Organization", "Task"},
        {"Community"},
    ),
    # Lore System
    "EXPANDS_UPON": ({"LoreEpisode"}, {"LoreEpisode"}),
    "TOLD_TO": ({"LoreEpisode"}, {"Person"}),
    "SAGA_STARTED_BY": ({"LoreEpisode"}, {"Person"}),
    # Thread Management
    "CONTAINS": ({"Thread"}, {"Message"}),
    "PRECEDES": ({"Message"}, {"Message"}),
    # Temporal Spine
    "OCCURRED_ON": ({"Event", "JournalEntry", "Note"}, {"Day"}),
    # Categorization
    "TAGGED_WITH": ({"Note", "Project", "Resource"}, {"Tag"}),
}

# Property type constraints for entity types
# Maps entity_type -> property_name -> expected Python type
PROPERTY_TYPE_CONSTRAINTS: dict[str, dict[str, type]] = {
    "Person": {
        "email": str,
        "title": str,
        "phone": str,
    },
    "Organization": {
        "industry": str,
        "domain": str,
    },
    "Project": {
        "status": str,
        "deadline": str,
    },
    "Task": {
        "status": str,
        "priority": str,
        "due_date": str,
    },
    "Event": {
        "start_time": str,
        "event_location": str,
    },
    "Location": {
        "address": str,
        "location_type": str,
    },
    "Hobby": {
        "category": str,
        "skill_level": str,
        "frequency": str,
    },
    "HealthMetric": {
        "metric_type": str,
        "unit": str,
    },
    "Pet": {
        "species": str,
        "breed": str,
    },
    "Milestone": {
        "category": str,
        "significance": str,
    },
    "Routine": {
        "frequency": str,
        "time_of_day": str,
        "duration_minutes": int,
        "is_active": bool,
    },
    "Preference": {
        "category": str,
        "sentiment": str,
        "strength": float,
    },
}

# Valid enum values for status fields
STATUS_CONSTRAINTS: dict[str, dict[str, set[str]]] = {
    "Project": {
        "status": {"active", "on_hold", "completed", "cancelled"},
    },
    "Task": {
        "status": {"todo", "in_progress", "done", "cancelled"},
        "priority": {"urgent", "high", "medium", "low"},
    },
    "Goal": {
        "status": {"active", "achieved", "abandoned"},
    },
    "Thread": {
        "status": {"active", "archiving", "archived"},
    },
    "Routine": {
        "frequency": {"daily", "weekly", "monthly", "weekdays", "weekends"},
        "time_of_day": {"morning", "afternoon", "evening", "night"},
    },
    "Preference": {
        "sentiment": {"likes", "dislikes", "love", "hate", "neutral", "prefers", "avoids"},
    },
    "Milestone": {
        "significance": {"minor", "moderate", "major", "life_changing"},
    },
    "Hobby": {
        "skill_level": {"beginner", "intermediate", "advanced", "expert"},
        "frequency": {"daily", "weekly", "monthly", "occasional"},
    },
}


class OntologyValidator:
    """
    Validates extracted entities and relationships against the Klabautermann ontology.

    Performs the following validations:
    1. Entity type validation (must be in NodeLabel enum)
    2. Relationship type validation (must be in RelationType enum)
    3. Relationship constraint validation (source/target type compatibility)
    4. Property type validation
    5. Enum value validation (status fields, etc.)
    """

    def __init__(self, strict: bool = False) -> None:
        """
        Initialize the validator.

        Args:
            strict: If True, warnings are treated as errors.
        """
        self.strict = strict

    def validate_extraction(
        self, extraction: ExtractionResult, trace_id: str | None = None
    ) -> ValidationResult:
        """
        Validate a complete extraction result against the ontology.

        Args:
            extraction: The extraction result to validate.
            trace_id: Optional trace ID for logging.

        Returns:
            ValidationResult with any issues found.
        """
        issues: list[ValidationIssue] = []
        entities_validated = 0
        relationships_validated = 0

        # Validate each entity
        for entity in extraction.entities:
            entity_issues = self._validate_entity(entity)
            issues.extend(entity_issues)
            entities_validated += 1

        # Validate each relationship
        for relationship in extraction.relationships:
            rel_issues = self._validate_relationship(relationship)
            issues.extend(rel_issues)
            relationships_validated += 1

        # Determine overall validity
        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        has_warnings = any(i.severity == ValidationSeverity.WARNING for i in issues)
        is_valid = not has_errors and (not self.strict or not has_warnings)

        # Log validation result
        if issues:
            log_level = "warning" if is_valid else "error"
            getattr(logger, log_level)(
                f"[SWELL] Ontology validation completed with {len(issues)} issues",
                extra={
                    "trace_id": trace_id,
                    "is_valid": is_valid,
                    "error_count": sum(1 for i in issues if i.severity == ValidationSeverity.ERROR),
                    "warning_count": sum(
                        1 for i in issues if i.severity == ValidationSeverity.WARNING
                    ),
                    "entities_validated": entities_validated,
                    "relationships_validated": relationships_validated,
                },
            )

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            entities_validated=entities_validated,
            relationships_validated=relationships_validated,
        )

    def validate_entity(self, entity: ExtractedEntity) -> ValidationResult:
        """
        Validate a single entity against the ontology.

        Args:
            entity: The entity to validate.

        Returns:
            ValidationResult with any issues found.
        """
        issues = self._validate_entity(entity)
        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        has_warnings = any(i.severity == ValidationSeverity.WARNING for i in issues)
        is_valid = not has_errors and (not self.strict or not has_warnings)
        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            entities_validated=1,
        )

    def validate_relationship(self, relationship: ExtractedRelationship) -> ValidationResult:
        """
        Validate a single relationship against the ontology.

        Args:
            relationship: The relationship to validate.

        Returns:
            ValidationResult with any issues found.
        """
        issues = self._validate_relationship(relationship)
        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            is_valid=not has_errors,
            issues=issues,
            relationships_validated=1,
        )

    def _validate_entity(self, entity: ExtractedEntity) -> list[ValidationIssue]:
        """Validate a single entity and return any issues."""
        issues: list[ValidationIssue] = []

        # 1. Validate entity type
        if entity.entity_type not in VALID_ENTITY_TYPES:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_ENTITY_TYPE",
                    message=f"Unknown entity type: {entity.entity_type}",
                    entity_name=entity.name,
                    entity_type=entity.entity_type,
                    expected=", ".join(sorted(VALID_ENTITY_TYPES)[:10]) + "...",
                    actual=entity.entity_type,
                )
            )
            # Can't validate properties if type is invalid
            return issues

        # 2. Validate property types
        type_constraints = PROPERTY_TYPE_CONSTRAINTS.get(entity.entity_type, {})
        for prop_name, prop_value in entity.properties.items():
            if prop_name in type_constraints:
                expected_type = type_constraints[prop_name]
                if isinstance(expected_type, tuple):
                    if not isinstance(prop_value, expected_type):
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.WARNING,
                                code="INVALID_PROPERTY_TYPE",
                                message=f"Property '{prop_name}' has wrong type",
                                entity_name=entity.name,
                                entity_type=entity.entity_type,
                                property_name=prop_name,
                                expected=str(expected_type),
                                actual=type(prop_value).__name__,
                            )
                        )
                elif not isinstance(prop_value, expected_type):
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            code="INVALID_PROPERTY_TYPE",
                            message=f"Property '{prop_name}' has wrong type",
                            entity_name=entity.name,
                            entity_type=entity.entity_type,
                            property_name=prop_name,
                            expected=expected_type.__name__,
                            actual=type(prop_value).__name__,
                        )
                    )

        # 3. Validate enum values (status, priority, etc.)
        enum_constraints = STATUS_CONSTRAINTS.get(entity.entity_type, {})
        for prop_name, valid_values in enum_constraints.items():
            if prop_name in entity.properties:
                prop_value = entity.properties[prop_name]
                if isinstance(prop_value, str):
                    # Normalize to lowercase for comparison
                    normalized = prop_value.lower()
                    if normalized not in valid_values:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.WARNING,
                                code="INVALID_ENUM_VALUE",
                                message=f"Property '{prop_name}' has invalid value",
                                entity_name=entity.name,
                                entity_type=entity.entity_type,
                                property_name=prop_name,
                                expected=", ".join(sorted(valid_values)),
                                actual=prop_value,
                            )
                        )

        # 4. Validate low confidence extractions
        if entity.confidence < 0.5:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    code="LOW_CONFIDENCE",
                    message=f"Entity extraction has low confidence: {entity.confidence:.0%}",
                    entity_name=entity.name,
                    entity_type=entity.entity_type,
                )
            )

        return issues

    def _validate_relationship(self, relationship: ExtractedRelationship) -> list[ValidationIssue]:
        """Validate a single relationship and return any issues."""
        issues: list[ValidationIssue] = []
        rel_type = relationship.relationship_type

        # 1. Validate relationship type
        if rel_type not in VALID_RELATIONSHIP_TYPES:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_RELATIONSHIP_TYPE",
                    message=f"Unknown relationship type: {rel_type}",
                    entity_name=f"{relationship.source_name} -> {relationship.target_name}",
                    expected=", ".join(sorted(VALID_RELATIONSHIP_TYPES)[:10]) + "...",
                    actual=rel_type,
                )
            )
            return issues

        # 2. Validate source/target entity types
        source_type = relationship.source_type.title()
        target_type = relationship.target_type.title()

        if source_type not in VALID_ENTITY_TYPES:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_SOURCE_TYPE",
                    message=f"Unknown source entity type for {rel_type}",
                    entity_name=relationship.source_name,
                    entity_type=source_type,
                )
            )

        if target_type not in VALID_ENTITY_TYPES:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_TARGET_TYPE",
                    message=f"Unknown target entity type for {rel_type}",
                    entity_name=relationship.target_name,
                    entity_type=target_type,
                )
            )

        # 3. Validate relationship constraints (source/target compatibility)
        if rel_type in RELATIONSHIP_CONSTRAINTS:
            allowed_sources, allowed_targets = RELATIONSHIP_CONSTRAINTS[rel_type]

            if source_type not in allowed_sources:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="INVALID_SOURCE_FOR_RELATIONSHIP",
                        message=f"{rel_type} cannot have {source_type} as source",
                        entity_name=relationship.source_name,
                        entity_type=source_type,
                        expected=", ".join(sorted(allowed_sources)),
                        actual=source_type,
                    )
                )

            if target_type not in allowed_targets:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="INVALID_TARGET_FOR_RELATIONSHIP",
                        message=f"{rel_type} cannot have {target_type} as target",
                        entity_name=relationship.target_name,
                        entity_type=target_type,
                        expected=", ".join(sorted(allowed_targets)),
                        actual=target_type,
                    )
                )

        # 4. Validate low confidence extractions
        if relationship.confidence < 0.5:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    code="LOW_CONFIDENCE",
                    message=f"Relationship extraction has low confidence: {relationship.confidence:.0%}",
                    entity_name=f"{relationship.source_name} -{rel_type}-> {relationship.target_name}",
                )
            )

        return issues

    def is_valid_entity_type(self, entity_type: str) -> bool:
        """Check if an entity type is valid according to the ontology."""
        return entity_type in VALID_ENTITY_TYPES or entity_type.title() in VALID_ENTITY_TYPES

    def is_valid_relationship_type(self, relationship_type: str) -> bool:
        """Check if a relationship type is valid according to the ontology."""
        return relationship_type.upper() in VALID_RELATIONSHIP_TYPES

    def get_valid_entity_types(self) -> list[str]:
        """Return list of valid entity types."""
        return sorted(VALID_ENTITY_TYPES)

    def get_valid_relationship_types(self) -> list[str]:
        """Return list of valid relationship types."""
        return sorted(VALID_RELATIONSHIP_TYPES)

    def get_entity_type_model(self, entity_type: str) -> type[BaseModel] | None:
        """Get the Pydantic model for an entity type, if available."""
        return ENTITY_TYPES.get(entity_type)


# ===========================================================================
# Convenience Functions
# ===========================================================================


def validate_extraction(
    extraction: ExtractionResult, strict: bool = False, trace_id: str | None = None
) -> ValidationResult:
    """
    Validate an extraction result against the ontology.

    Args:
        extraction: The extraction to validate.
        strict: If True, treat warnings as errors.
        trace_id: Optional trace ID for logging.

    Returns:
        ValidationResult with validation outcome and any issues.
    """
    validator = OntologyValidator(strict=strict)
    return validator.validate_extraction(extraction, trace_id=trace_id)


def is_valid_entity_type(entity_type: str) -> bool:
    """Check if an entity type is valid according to the ontology."""
    return entity_type in VALID_ENTITY_TYPES or entity_type.title() in VALID_ENTITY_TYPES


def is_valid_relationship_type(relationship_type: str) -> bool:
    """Check if a relationship type is valid according to the ontology."""
    return relationship_type.upper() in VALID_RELATIONSHIP_TYPES


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "PROPERTY_TYPE_CONSTRAINTS",
    "RELATIONSHIP_CONSTRAINTS",
    "STATUS_CONSTRAINTS",
    "VALID_ENTITY_TYPES",
    "VALID_RELATIONSHIP_TYPES",
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractionResult",
    "OntologyValidator",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "is_valid_entity_type",
    "is_valid_relationship_type",
    "validate_extraction",
]
