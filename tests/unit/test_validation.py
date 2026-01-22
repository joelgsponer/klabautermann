"""
Tests for ontology validation module.

Tests the OntologyValidator which validates extracted entities and relationships
against the Klabautermann ontology schema.

Issues: #11, #13
"""

import pytest

from klabautermann.core.validation import (
    RELATIONSHIP_CONSTRAINTS,
    VALID_ENTITY_TYPES,
    VALID_RELATIONSHIP_TYPES,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    OntologyValidator,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    is_valid_entity_type,
    is_valid_relationship_type,
    validate_extraction,
)


# ===========================================================================
# Test ValidationSeverity
# ===========================================================================


class TestValidationSeverity:
    """Tests for ValidationSeverity enum."""

    def test_severity_values(self) -> None:
        """Test that severity levels have expected values."""
        assert ValidationSeverity.ERROR.value == "error"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.INFO.value == "info"


# ===========================================================================
# Test ValidationIssue
# ===========================================================================


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            code="TEST_CODE",
            message="Test message",
            entity_name="John",
            entity_type="Person",
            property_name="email",
            expected="str",
            actual="int",
        )
        result = issue.to_dict()

        assert result["severity"] == "error"
        assert result["code"] == "TEST_CODE"
        assert result["message"] == "Test message"
        assert result["entity_name"] == "John"
        assert result["entity_type"] == "Person"
        assert result["property_name"] == "email"
        assert result["expected"] == "str"
        assert result["actual"] == "int"

    def test_to_dict_with_none_values(self) -> None:
        """Test conversion with None optional values."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code="SIMPLE",
            message="Simple issue",
        )
        result = issue.to_dict()

        assert result["entity_name"] is None
        assert result["property_name"] is None


# ===========================================================================
# Test ValidationResult
# ===========================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_error_count(self) -> None:
        """Test error count calculation."""
        result = ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(ValidationSeverity.ERROR, "E1", "Error 1"),
                ValidationIssue(ValidationSeverity.ERROR, "E2", "Error 2"),
                ValidationIssue(ValidationSeverity.WARNING, "W1", "Warning 1"),
            ],
        )
        assert result.error_count == 2

    def test_warning_count(self) -> None:
        """Test warning count calculation."""
        result = ValidationResult(
            is_valid=True,
            issues=[
                ValidationIssue(ValidationSeverity.WARNING, "W1", "Warning 1"),
                ValidationIssue(ValidationSeverity.WARNING, "W2", "Warning 2"),
                ValidationIssue(ValidationSeverity.INFO, "I1", "Info 1"),
            ],
        )
        assert result.warning_count == 2

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = ValidationResult(
            is_valid=True,
            issues=[],
            entities_validated=5,
            relationships_validated=3,
        )
        data = result.to_dict()

        assert data["is_valid"] is True
        assert data["error_count"] == 0
        assert data["warning_count"] == 0
        assert data["entities_validated"] == 5
        assert data["relationships_validated"] == 3
        assert data["issues"] == []


# ===========================================================================
# Test ExtractedEntity
# ===========================================================================


class TestExtractedEntity:
    """Tests for ExtractedEntity model."""

    def test_basic_entity(self) -> None:
        """Test creating a basic entity."""
        entity = ExtractedEntity(
            name="John Smith",
            entity_type="Person",
            properties={"email": "john@example.com"},
            confidence=0.95,
        )
        assert entity.name == "John Smith"
        assert entity.entity_type == "Person"
        assert entity.properties["email"] == "john@example.com"
        assert entity.confidence == 0.95

    def test_entity_type_normalization(self) -> None:
        """Test that lowercase entity types are normalized."""
        entity = ExtractedEntity(
            name="Test",
            entity_type="person",  # lowercase
        )
        assert entity.entity_type == "Person"  # Should be title-cased

    def test_default_confidence(self) -> None:
        """Test default confidence is 1.0."""
        entity = ExtractedEntity(name="Test", entity_type="Person")
        assert entity.confidence == 1.0

    def test_empty_properties(self) -> None:
        """Test default empty properties."""
        entity = ExtractedEntity(name="Test", entity_type="Person")
        assert entity.properties == {}


# ===========================================================================
# Test ExtractedRelationship
# ===========================================================================


class TestExtractedRelationship:
    """Tests for ExtractedRelationship model."""

    def test_basic_relationship(self) -> None:
        """Test creating a basic relationship."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="WORKS_AT",
            target_name="Acme Corp",
            target_type="Organization",
            confidence=0.9,
        )
        assert rel.source_name == "John"
        assert rel.relationship_type == "WORKS_AT"
        assert rel.target_name == "Acme Corp"

    def test_relationship_type_normalization(self) -> None:
        """Test that relationship types are uppercased."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="works_at",  # lowercase
            target_name="Acme",
            target_type="Organization",
        )
        assert rel.relationship_type == "WORKS_AT"  # Should be uppercased


# ===========================================================================
# Test ExtractionResult
# ===========================================================================


class TestExtractionResult:
    """Tests for ExtractionResult model."""

    def test_empty_result(self) -> None:
        """Test empty extraction result."""
        result = ExtractionResult()
        assert result.entities == []
        assert result.relationships == []
        assert result.source_text == ""

    def test_result_with_data(self) -> None:
        """Test extraction result with entities and relationships."""
        result = ExtractionResult(
            entities=[
                ExtractedEntity(name="John", entity_type="Person"),
            ],
            relationships=[
                ExtractedRelationship(
                    source_name="John",
                    source_type="Person",
                    relationship_type="WORKS_AT",
                    target_name="Acme",
                    target_type="Organization",
                ),
            ],
            source_text="John works at Acme",
        )
        assert len(result.entities) == 1
        assert len(result.relationships) == 1


# ===========================================================================
# Test Constants
# ===========================================================================


class TestValidationConstants:
    """Tests for validation constants."""

    def test_valid_entity_types_includes_core_types(self) -> None:
        """Test that core entity types are defined."""
        assert "Person" in VALID_ENTITY_TYPES
        assert "Organization" in VALID_ENTITY_TYPES
        assert "Project" in VALID_ENTITY_TYPES
        assert "Task" in VALID_ENTITY_TYPES
        assert "Event" in VALID_ENTITY_TYPES
        assert "Location" in VALID_ENTITY_TYPES

    def test_valid_entity_types_includes_personal_types(self) -> None:
        """Test that personal life entity types are defined."""
        assert "Hobby" in VALID_ENTITY_TYPES
        assert "Pet" in VALID_ENTITY_TYPES
        assert "Milestone" in VALID_ENTITY_TYPES
        assert "Routine" in VALID_ENTITY_TYPES
        assert "Preference" in VALID_ENTITY_TYPES

    def test_valid_relationship_types_includes_core_types(self) -> None:
        """Test that core relationship types are defined."""
        assert "WORKS_AT" in VALID_RELATIONSHIP_TYPES
        assert "REPORTS_TO" in VALID_RELATIONSHIP_TYPES
        assert "KNOWS" in VALID_RELATIONSHIP_TYPES
        assert "BLOCKS" in VALID_RELATIONSHIP_TYPES
        assert "ASSIGNED_TO" in VALID_RELATIONSHIP_TYPES

    def test_relationship_constraints_defined(self) -> None:
        """Test that relationship constraints are defined."""
        assert "WORKS_AT" in RELATIONSHIP_CONSTRAINTS
        assert "REPORTS_TO" in RELATIONSHIP_CONSTRAINTS

        # Check WORKS_AT constraints
        sources, targets = RELATIONSHIP_CONSTRAINTS["WORKS_AT"]
        assert "Person" in sources
        assert "Organization" in targets


# ===========================================================================
# Test OntologyValidator
# ===========================================================================


class TestOntologyValidator:
    """Tests for OntologyValidator."""

    @pytest.fixture
    def validator(self) -> OntologyValidator:
        """Create a validator instance."""
        return OntologyValidator(strict=False)

    @pytest.fixture
    def strict_validator(self) -> OntologyValidator:
        """Create a strict validator instance."""
        return OntologyValidator(strict=True)

    # --- Entity Type Validation ---

    def test_valid_entity_type(self, validator: OntologyValidator) -> None:
        """Test validation of valid entity type."""
        entity = ExtractedEntity(name="John", entity_type="Person")
        result = validator.validate_entity(entity)
        assert result.is_valid
        assert result.error_count == 0

    def test_invalid_entity_type(self, validator: OntologyValidator) -> None:
        """Test validation fails for invalid entity type."""
        entity = ExtractedEntity(name="Test", entity_type="InvalidType")
        result = validator.validate_entity(entity)
        assert not result.is_valid
        assert result.error_count == 1
        assert result.issues[0].code == "INVALID_ENTITY_TYPE"

    # --- Relationship Type Validation ---

    def test_valid_relationship_type(self, validator: OntologyValidator) -> None:
        """Test validation of valid relationship type."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="WORKS_AT",
            target_name="Acme",
            target_type="Organization",
        )
        result = validator.validate_relationship(rel)
        assert result.is_valid

    def test_invalid_relationship_type(self, validator: OntologyValidator) -> None:
        """Test validation fails for invalid relationship type."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="INVALID_REL",
            target_name="Acme",
            target_type="Organization",
        )
        result = validator.validate_relationship(rel)
        assert not result.is_valid
        assert result.issues[0].code == "INVALID_RELATIONSHIP_TYPE"

    # --- Relationship Constraint Validation ---

    def test_valid_relationship_constraints(self, validator: OntologyValidator) -> None:
        """Test validation passes for valid source/target types."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="REPORTS_TO",
            target_name="Jane",
            target_type="Person",
        )
        result = validator.validate_relationship(rel)
        assert result.is_valid

    def test_invalid_source_for_relationship(self, validator: OntologyValidator) -> None:
        """Test validation fails when source type is invalid for relationship."""
        rel = ExtractedRelationship(
            source_name="Acme",
            source_type="Organization",  # Organization can't WORKS_AT
            relationship_type="WORKS_AT",
            target_name="Corp",
            target_type="Organization",
        )
        result = validator.validate_relationship(rel)
        assert not result.is_valid
        assert any(i.code == "INVALID_SOURCE_FOR_RELATIONSHIP" for i in result.issues)

    def test_invalid_target_for_relationship(self, validator: OntologyValidator) -> None:
        """Test validation fails when target type is invalid for relationship."""
        rel = ExtractedRelationship(
            source_name="John",
            source_type="Person",
            relationship_type="WORKS_AT",
            target_name="John",
            target_type="Person",  # Person can't be target of WORKS_AT
        )
        result = validator.validate_relationship(rel)
        assert not result.is_valid
        assert any(i.code == "INVALID_TARGET_FOR_RELATIONSHIP" for i in result.issues)

    # --- Property Validation ---

    def test_valid_property_type(self, validator: OntologyValidator) -> None:
        """Test validation passes for correct property types."""
        entity = ExtractedEntity(
            name="John",
            entity_type="Person",
            properties={"email": "john@example.com"},  # String as expected
        )
        result = validator.validate_entity(entity)
        assert result.is_valid

    def test_invalid_property_type(self, validator: OntologyValidator) -> None:
        """Test validation warns for incorrect property types."""
        entity = ExtractedEntity(
            name="John",
            entity_type="Person",
            properties={"email": 12345},  # Should be string
        )
        result = validator.validate_entity(entity)
        # Should be valid (warning only) but have warnings
        assert result.is_valid
        assert any(i.code == "INVALID_PROPERTY_TYPE" for i in result.issues)

    # --- Enum Validation ---

    def test_valid_enum_value(self, validator: OntologyValidator) -> None:
        """Test validation passes for valid enum values."""
        entity = ExtractedEntity(
            name="My Task",
            entity_type="Task",
            properties={"status": "todo"},
        )
        result = validator.validate_entity(entity)
        assert result.is_valid

    def test_invalid_enum_value(self, validator: OntologyValidator) -> None:
        """Test validation warns for invalid enum values."""
        entity = ExtractedEntity(
            name="My Task",
            entity_type="Task",
            properties={"status": "invalid_status"},
        )
        result = validator.validate_entity(entity)
        assert result.is_valid  # Warning only
        assert any(i.code == "INVALID_ENUM_VALUE" for i in result.issues)

    # --- Confidence Validation ---

    def test_low_confidence_info(self, validator: OntologyValidator) -> None:
        """Test low confidence generates INFO issue."""
        entity = ExtractedEntity(
            name="Maybe John",
            entity_type="Person",
            confidence=0.3,
        )
        result = validator.validate_entity(entity)
        assert result.is_valid
        assert any(
            i.code == "LOW_CONFIDENCE" and i.severity == ValidationSeverity.INFO
            for i in result.issues
        )

    # --- Complete Extraction Validation ---

    def test_validate_complete_extraction(self, validator: OntologyValidator) -> None:
        """Test validation of complete extraction result."""
        extraction = ExtractionResult(
            entities=[
                ExtractedEntity(name="John", entity_type="Person"),
                ExtractedEntity(name="Acme", entity_type="Organization"),
            ],
            relationships=[
                ExtractedRelationship(
                    source_name="John",
                    source_type="Person",
                    relationship_type="WORKS_AT",
                    target_name="Acme",
                    target_type="Organization",
                ),
            ],
        )
        result = validator.validate_extraction(extraction)
        assert result.is_valid
        assert result.entities_validated == 2
        assert result.relationships_validated == 1

    def test_validate_extraction_with_errors(self, validator: OntologyValidator) -> None:
        """Test validation fails with invalid entities."""
        extraction = ExtractionResult(
            entities=[
                ExtractedEntity(name="Test", entity_type="InvalidType"),
            ],
        )
        result = validator.validate_extraction(extraction)
        assert not result.is_valid
        assert result.error_count == 1

    # --- Strict Mode ---

    def test_strict_mode_fails_on_warnings(self, strict_validator: OntologyValidator) -> None:
        """Test strict mode treats warnings as errors."""
        entity = ExtractedEntity(
            name="My Task",
            entity_type="Task",
            properties={"status": "invalid_status"},  # Will generate warning
        )
        result = strict_validator.validate_entity(entity)
        assert not result.is_valid  # Strict mode fails on warnings

    # --- Helper Methods ---

    def test_is_valid_entity_type_method(self, validator: OntologyValidator) -> None:
        """Test is_valid_entity_type method."""
        assert validator.is_valid_entity_type("Person")
        assert validator.is_valid_entity_type("person")  # Case insensitive
        assert not validator.is_valid_entity_type("InvalidType")

    def test_is_valid_relationship_type_method(self, validator: OntologyValidator) -> None:
        """Test is_valid_relationship_type method."""
        assert validator.is_valid_relationship_type("WORKS_AT")
        assert validator.is_valid_relationship_type("works_at")  # Case insensitive
        assert not validator.is_valid_relationship_type("INVALID")

    def test_get_valid_entity_types(self, validator: OntologyValidator) -> None:
        """Test get_valid_entity_types returns sorted list."""
        types = validator.get_valid_entity_types()
        assert isinstance(types, list)
        assert "Person" in types
        assert types == sorted(types)  # Should be sorted

    def test_get_entity_type_model(self, validator: OntologyValidator) -> None:
        """Test get_entity_type_model returns Pydantic model."""
        model = validator.get_entity_type_model("Person")
        assert model is not None
        # Model should have email field
        assert "email" in model.model_fields


# ===========================================================================
# Test Convenience Functions
# ===========================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_validate_extraction_function(self) -> None:
        """Test the validate_extraction convenience function."""
        extraction = ExtractionResult(
            entities=[
                ExtractedEntity(name="John", entity_type="Person"),
            ],
        )
        result = validate_extraction(extraction)
        assert result.is_valid

    def test_is_valid_entity_type_function(self) -> None:
        """Test the is_valid_entity_type convenience function."""
        assert is_valid_entity_type("Person")
        assert is_valid_entity_type("person")  # Case insensitive
        assert not is_valid_entity_type("Invalid")

    def test_is_valid_relationship_type_function(self) -> None:
        """Test the is_valid_relationship_type convenience function."""
        assert is_valid_relationship_type("WORKS_AT")
        assert is_valid_relationship_type("works_at")
        assert not is_valid_relationship_type("INVALID")


# ===========================================================================
# Test Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_from_core_module(self) -> None:
        """Test that validation exports are available from core module."""
        from klabautermann.core import (
            ExtractionResult,
            OntologyValidator,
            is_valid_entity_type,
        )

        # Basic smoke test
        assert ExtractionResult is not None
        assert OntologyValidator is not None
        assert is_valid_entity_type("Person")
