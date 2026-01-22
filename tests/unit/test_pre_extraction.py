"""
Tests for LLM-based pre-extraction module.

Tests the PreExtractionEngine which uses Claude Haiku to extract entities
and relationships before Graphiti ingestion.

Issues: #11, #13
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.pre_extraction import (
    PreExtractionConfig,
    PreExtractionEngine,
    pre_extract_entities,
)


# Disable workflow inspector logging during tests
@pytest.fixture(autouse=True)
def disable_workflow_inspector():
    """Disable workflow inspector logging for tests."""
    with patch("klabautermann.agents.pre_extraction.log_thinking", return_value=None):
        yield


# ===========================================================================
# Test PreExtractionConfig
# ===========================================================================


class TestPreExtractionConfig:
    """Tests for PreExtractionConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = PreExtractionConfig()
        assert config.enabled is True
        assert config.model == "claude-3-5-haiku-latest"
        assert config.min_confidence == 0.5
        assert config.max_tokens == 2048
        assert config.temperature == 0.0
        assert config.validate_ontology is True
        assert config.strict_validation is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = PreExtractionConfig(
            enabled=False,
            model="claude-3-sonnet",
            min_confidence=0.7,
            strict_validation=True,
        )
        assert config.enabled is False
        assert config.model == "claude-3-sonnet"
        assert config.min_confidence == 0.7
        assert config.strict_validation is True


# ===========================================================================
# Test PreExtractionEngine
# ===========================================================================


class TestPreExtractionEngine:
    """Tests for PreExtractionEngine."""

    @pytest.fixture
    def mock_anthropic(self) -> AsyncMock:
        """Create a mock Anthropic client."""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def engine(self, mock_anthropic: AsyncMock) -> PreExtractionEngine:
        """Create an extraction engine with mock client."""
        return PreExtractionEngine(anthropic_client=mock_anthropic)

    @pytest.fixture
    def disabled_engine(self, mock_anthropic: AsyncMock) -> PreExtractionEngine:
        """Create a disabled extraction engine."""
        config = PreExtractionConfig(enabled=False)
        return PreExtractionEngine(anthropic_client=mock_anthropic, config=config)

    # --- Basic Extraction Tests ---

    @pytest.mark.asyncio
    async def test_extract_returns_empty_when_disabled(
        self, disabled_engine: PreExtractionEngine
    ) -> None:
        """Test that disabled engine returns empty result."""
        result, validation = await disabled_engine.extract("Test text")
        assert result.entities == []
        assert result.relationships == []
        assert validation is None

    @pytest.mark.asyncio
    async def test_extract_returns_empty_for_short_text(self, engine: PreExtractionEngine) -> None:
        """Test that very short text returns empty result."""
        result, validation = await engine.extract("Hi")
        assert result.entities == []
        assert result.relationships == []

    @pytest.mark.asyncio
    async def test_extract_calls_llm(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test that extraction calls the LLM."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "John Smith",
                                "entity_type": "Person",
                                "properties": {"email": "john@example.com"},
                                "confidence": 0.95,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, validation = await engine.extract("I met John Smith (john@example.com) today.")

        # Verify LLM was called
        mock_anthropic.messages.create.assert_called_once()

        # Verify extraction result
        assert len(result.entities) == 1
        assert result.entities[0].name == "John Smith"
        assert result.entities[0].entity_type == "Person"
        assert result.entities[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_extract_with_relationships(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test extraction of entities and relationships."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "John Smith",
                                "entity_type": "Person",
                                "properties": {},
                                "confidence": 0.9,
                            },
                            {
                                "name": "Acme Corp",
                                "entity_type": "Organization",
                                "properties": {},
                                "confidence": 0.85,
                            },
                        ],
                        "relationships": [
                            {
                                "source_name": "John Smith",
                                "source_type": "Person",
                                "relationship_type": "WORKS_AT",
                                "target_name": "Acme Corp",
                                "target_type": "Organization",
                                "properties": {},
                                "confidence": 0.8,
                            }
                        ],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, validation = await engine.extract("John Smith works at Acme Corp as a PM.")

        assert len(result.entities) == 2
        assert len(result.relationships) == 1
        assert result.relationships[0].relationship_type == "WORKS_AT"

    # --- Confidence Filtering ---

    @pytest.mark.asyncio
    async def test_filters_low_confidence_entities(self, mock_anthropic: AsyncMock) -> None:
        """Test that low confidence entities are filtered out."""
        config = PreExtractionConfig(min_confidence=0.6)
        engine = PreExtractionEngine(anthropic_client=mock_anthropic, config=config)

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "High Confidence",
                                "entity_type": "Person",
                                "properties": {},
                                "confidence": 0.9,
                            },
                            {
                                "name": "Low Confidence",
                                "entity_type": "Person",
                                "properties": {},
                                "confidence": 0.4,  # Below threshold
                            },
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, _ = await engine.extract("Test text with entities")

        # Only high confidence entity should remain
        assert len(result.entities) == 1
        assert result.entities[0].name == "High Confidence"

    # --- Validation Integration ---

    @pytest.mark.asyncio
    async def test_validates_extraction(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test that extraction result is validated."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "John",
                                "entity_type": "Person",
                                "properties": {},
                                "confidence": 0.9,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, validation = await engine.extract("I met John today.")

        assert validation is not None
        assert validation.is_valid
        assert validation.entities_validated == 1

    @pytest.mark.asyncio
    async def test_validation_catches_invalid_types(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test that validation catches invalid entity types."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Test Entity",
                                "entity_type": "InvalidType",  # Invalid
                                "properties": {},
                                "confidence": 0.9,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        # Text must be >= 10 chars to trigger extraction
        result, validation = await engine.extract("This is test text for extraction validation")

        assert validation is not None
        assert not validation.is_valid
        assert validation.error_count > 0

    @pytest.mark.asyncio
    async def test_validation_disabled(self, mock_anthropic: AsyncMock) -> None:
        """Test extraction without validation."""
        config = PreExtractionConfig(validate_ontology=False)
        engine = PreExtractionEngine(anthropic_client=mock_anthropic, config=config)

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({"entities": [], "relationships": []}))]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, validation = await engine.extract("Test text")

        assert validation is None  # No validation performed

    # --- Error Handling ---

    @pytest.mark.asyncio
    async def test_handles_invalid_json_response(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test graceful handling of invalid JSON from LLM."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is not valid JSON")]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        result, validation = await engine.extract("Test text for extraction")

        # Should return empty result, not crash
        assert result.entities == []
        assert result.relationships == []

    @pytest.mark.asyncio
    async def test_handles_llm_exception(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test graceful handling of LLM exceptions."""
        mock_anthropic.messages.create = AsyncMock(side_effect=Exception("LLM API error"))

        # Text must be >= 10 chars to trigger extraction
        result, validation = await engine.extract("This is test text for extraction")

        # Should return empty result, not crash
        assert result.entities == []
        assert result.relationships == []

    @pytest.mark.asyncio
    async def test_handles_malformed_entity(
        self, engine: PreExtractionEngine, mock_anthropic: AsyncMock
    ) -> None:
        """Test handling of malformed entity data."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Valid Entity",
                                "entity_type": "Person",
                                "confidence": 0.9,
                            },
                            {
                                # Missing required fields
                                "name": "",
                                "entity_type": "",
                            },
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        # Text must be >= 10 chars to trigger extraction
        result, _ = await engine.extract("This is test text for entity extraction")

        # Valid entity should be extracted, malformed one skipped
        assert len(result.entities) == 1
        assert result.entities[0].name == "Valid Entity"


# ===========================================================================
# Test Convenience Function
# ===========================================================================


class TestPreExtractEntities:
    """Tests for the pre_extract_entities convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function(self) -> None:
        """Test the pre_extract_entities convenience function."""
        mock_anthropic = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Test Person",
                                "entity_type": "Person",
                                "properties": {},
                                "confidence": 0.9,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        # Text must be >= 10 chars to trigger extraction
        with patch("klabautermann.agents.pre_extraction.log_thinking", return_value=None):
            result, validation = await pre_extract_entities(
                text="This is a test text for entity extraction",
                anthropic_client=mock_anthropic,
            )

        assert len(result.entities) == 1
        assert validation is not None


# ===========================================================================
# Test Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_from_agents_module(self) -> None:
        """Test that pre-extraction exports are available from agents module."""
        from klabautermann.agents import (
            PreExtractionConfig,
            PreExtractionEngine,
            pre_extract_entities,
        )

        assert PreExtractionConfig is not None
        assert PreExtractionEngine is not None
        assert pre_extract_entities is not None

        # Test config defaults
        config = PreExtractionConfig()
        assert config.enabled is True
