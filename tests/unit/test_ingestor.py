"""
Unit tests for Ingestor Agent.

Reference: specs/architecture/AGENTS.md Section 1.2
Task: T023 - Ingestor Agent

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from klabautermann.agents.ingestor import Ingestor
from klabautermann.core.models import (
    AgentMessage,
    EntityExtraction,
    EntityLabel,
    ExtractionResult,
    RelationshipExtraction,
)


class TestIngestorAgent:
    """Test suite for Ingestor agent functionality."""

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock Graphiti client."""
        mock = Mock()
        mock.is_connected = True
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_llm(self) -> Mock:
        """Create a mock Anthropic LLM client."""
        mock = Mock()
        mock.messages = Mock()
        mock.messages.create = AsyncMock()
        return mock

    @pytest.fixture
    def ingestor(self, mock_graphiti: Mock, mock_llm: Mock) -> Ingestor:
        """Create an Ingestor instance with mocked dependencies."""
        config = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 2048,
            "temperature": 0.3,
        }
        return Ingestor(
            name="ingestor",
            config=config,
            graphiti_client=mock_graphiti,
            llm_client=mock_llm,
        )

    # =========================================================================
    # Entity Extraction Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_extract_person_with_email(self, ingestor: Ingestor, mock_llm: Mock) -> None:
        """Extraction should capture Person with email from 'I met Sarah (sarah@acme.com)'."""
        # Setup mock LLM response
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Sarah",
                                "label": "Person",
                                "properties": {"email": "sarah@acme.com"},
                                "confidence": 1.0,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("I met Sarah (sarah@acme.com)", "test-trace-001")

        # Verify
        assert len(result.entities) == 1
        entity = result.entities[0]
        assert entity.name == "Sarah"
        assert entity.label == EntityLabel.PERSON
        assert entity.properties.get("email") == "sarah@acme.com"

    @pytest.mark.asyncio
    async def test_extract_person_organization_works_at(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """Extraction should create Person, Organization, and WORKS_AT relationship."""
        # Setup mock LLM response
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Sarah Johnson",
                                "label": "Person",
                                "properties": {"email": "sarah@acme.com", "title": "PM"},
                                "confidence": 1.0,
                            },
                            {
                                "name": "Acme Corp",
                                "label": "Organization",
                                "properties": {"domain": "acme.com"},
                                "confidence": 1.0,
                            },
                        ],
                        "relationships": [
                            {
                                "source_name": "Sarah Johnson",
                                "source_label": "Person",
                                "relationship_type": "WORKS_AT",
                                "target_name": "Acme Corp",
                                "target_label": "Organization",
                                "properties": {"title": "PM"},
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract(
            "I met Sarah Johnson from Acme Corp. She's a PM there.", "test-trace-002"
        )

        # Verify entities
        assert len(result.entities) == 2
        person = next(e for e in result.entities if e.label == EntityLabel.PERSON)
        org = next(e for e in result.entities if e.label == EntityLabel.ORGANIZATION)

        assert person.name == "Sarah Johnson"
        assert person.properties.get("email") == "sarah@acme.com"
        assert person.properties.get("title") == "PM"

        assert org.name == "Acme Corp"
        assert org.properties.get("domain") == "acme.com"

        # Verify relationship
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.source_name == "Sarah Johnson"
        assert rel.relationship_type == "WORKS_AT"
        assert rel.target_name == "Acme Corp"
        assert rel.properties.get("title") == "PM"

    @pytest.mark.asyncio
    async def test_extract_task_with_priority(self, ingestor: Ingestor, mock_llm: Mock) -> None:
        """Extraction should capture Task with priority and status."""
        # Setup mock LLM response
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Send Q1 report",
                                "label": "Task",
                                "properties": {"status": "todo", "priority": "high"},
                                "confidence": 1.0,
                            }
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("I need to send the Q1 report ASAP", "test-trace-003")

        # Verify
        assert len(result.entities) == 1
        task = result.entities[0]
        assert task.label == EntityLabel.TASK
        assert task.properties.get("priority") == "high"
        assert task.properties.get("status") == "todo"

    @pytest.mark.asyncio
    async def test_extract_event_with_location(self, ingestor: Ingestor, mock_llm: Mock) -> None:
        """Extraction should capture Event and Location with HELD_AT relationship."""
        # Setup mock LLM response
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Team Standup",
                                "label": "Event",
                                "properties": {"start_time": 1705320000.0},
                                "confidence": 1.0,
                            },
                            {
                                "name": "Conference Room A",
                                "label": "Location",
                                "properties": {"type": "office"},
                                "confidence": 1.0,
                            },
                        ],
                        "relationships": [
                            {
                                "source_name": "Team Standup",
                                "source_label": "Event",
                                "relationship_type": "HELD_AT",
                                "target_name": "Conference Room A",
                                "target_label": "Location",
                                "properties": {},
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("Team standup in Conference Room A", "test-trace-004")

        # Verify
        assert len(result.entities) == 2
        event = next(e for e in result.entities if e.label == EntityLabel.EVENT)
        location = next(e for e in result.entities if e.label == EntityLabel.LOCATION)

        assert event.name == "Team Standup"
        assert location.name == "Conference Room A"
        assert location.properties.get("type") == "office"

        # Verify relationship
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.relationship_type == "HELD_AT"

    # =========================================================================
    # Temporal Awareness Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_historical_relationship_detection(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """Extraction should detect 'used to work at' as historical context."""
        # Setup mock LLM response with historical indicator in properties
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {"name": "John", "label": "Person", "properties": {}, "confidence": 1.0},
                            {
                                "name": "Google",
                                "label": "Organization",
                                "properties": {},
                                "confidence": 1.0,
                            },
                        ],
                        "relationships": [
                            {
                                "source_name": "John",
                                "source_label": "Person",
                                "relationship_type": "WORKS_AT",
                                "target_name": "Google",
                                "target_label": "Organization",
                                "properties": {"historical": True, "note": "past employment"},
                                "confidence": 1.0,
                            }
                        ],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("John used to work at Google", "test-trace-005")

        # Verify that historical context is captured in properties
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.relationship_type == "WORKS_AT"
        # The LLM should indicate historical context in properties
        assert rel.properties.get("historical") is True or "past" in str(rel.properties).lower()

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(
        self, ingestor: Ingestor, mock_graphiti: Mock
    ) -> None:
        """Empty text should return None without calling LLM."""
        msg = AgentMessage(
            trace_id="test-trace-006",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={"text": "", "thread_id": "thread-123"},
        )

        result = await ingestor.process_message(msg)

        # Should return None (fire-and-forget)
        assert result is None
        # Should not call Graphiti
        mock_graphiti.add_episode.assert_not_called()

    @pytest.mark.asyncio
    async def test_json_parsing_error_returns_empty_result(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """Invalid JSON from LLM should return empty ExtractionResult."""
        # Setup mock LLM response with invalid JSON
        mock_response = Mock()
        mock_response.content = [Mock(text="This is not valid JSON at all!")]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("Some text", "test-trace-007")

        # Should return empty result, not crash
        assert len(result.entities) == 0
        assert len(result.relationships) == 0

    @pytest.mark.asyncio
    async def test_markdown_code_block_parsing(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """LLM response with markdown code blocks should be parsed correctly."""
        # Setup mock LLM response with markdown
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text='```json\n{"entities": [{"name": "Test", "label": "Person", "properties": {}, "confidence": 1.0}], "relationships": []}\n```'
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("Test text", "test-trace-008")

        # Should parse successfully
        assert len(result.entities) == 1
        assert result.entities[0].name == "Test"

    @pytest.mark.asyncio
    async def test_invalid_entity_label_skipped(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """Entities with invalid labels should be skipped, not crash."""
        # Setup mock LLM response with invalid label
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Valid",
                                "label": "Person",
                                "properties": {},
                                "confidence": 1.0,
                            },
                            {
                                "name": "Invalid",
                                "label": "InvalidLabel",
                                "properties": {},
                                "confidence": 1.0,
                            },
                        ],
                        "relationships": [],
                    }
                )
            )
        ]
        mock_llm.messages.create.return_value = mock_response

        # Execute extraction
        result = await ingestor._extract("Test text", "test-trace-009")

        # Should only have valid entity
        assert len(result.entities) == 1
        assert result.entities[0].name == "Valid"

    # =========================================================================
    # Graphiti Integration Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_write_to_graph_formats_episode_correctly(
        self, ingestor: Ingestor, mock_graphiti: Mock
    ) -> None:
        """Writing to graph should format extraction as episode content."""
        extraction = ExtractionResult(
            trace_id="test-trace-010",
            entities=[
                EntityExtraction(
                    name="Sarah",
                    label=EntityLabel.PERSON,
                    properties={"email": "sarah@acme.com"},
                    confidence=1.0,
                )
            ],
            relationships=[
                RelationshipExtraction(
                    source_name="Sarah",
                    source_label=EntityLabel.PERSON,
                    relationship_type="WORKS_AT",
                    target_name="Acme",
                    target_label=EntityLabel.ORGANIZATION,
                    properties={"title": "PM"},
                    confidence=1.0,
                )
            ],
        )

        await ingestor._write_to_graph(
            extraction=extraction,
            thread_id="thread-123",
            captain_uuid="user-456",
            trace_id="test-trace-010",
        )

        # Verify Graphiti was called
        mock_graphiti.add_episode.assert_called_once()
        call_args = mock_graphiti.add_episode.call_args

        # Check episode content format
        content = call_args.kwargs["content"]
        assert "Person: Sarah" in content
        assert "email=sarah@acme.com" in content
        assert "Sarah WORKS_AT Acme" in content
        assert "title=PM" in content

    @pytest.mark.asyncio
    async def test_graphiti_not_connected_skips_write(
        self, ingestor: Ingestor, mock_graphiti: Mock
    ) -> None:
        """If Graphiti not connected, should skip write without crashing."""
        mock_graphiti.is_connected = False

        extraction = ExtractionResult(
            trace_id="test-trace-011",
            entities=[
                EntityExtraction(
                    name="Test", label=EntityLabel.PERSON, properties={}, confidence=1.0
                )
            ],
            relationships=[],
        )

        # Should not raise exception
        await ingestor._write_to_graph(
            extraction=extraction,
            thread_id="thread-123",
            captain_uuid="user-456",
            trace_id="test-trace-011",
        )

        # Should not call add_episode
        mock_graphiti.add_episode.assert_not_called()

    # =========================================================================
    # Fire-and-Forget Pattern Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_process_message_returns_none(
        self, ingestor: Ingestor, mock_llm: Mock, mock_graphiti: Mock
    ) -> None:
        """process_message should always return None (fire-and-forget)."""
        # Setup mock LLM response
        mock_response = Mock()
        mock_response.content = [
            Mock(text=json.dumps({"entities": [], "relationships": []}))
        ]
        mock_llm.messages.create.return_value = mock_response

        msg = AgentMessage(
            trace_id="test-trace-012",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={"text": "Some text", "thread_id": "thread-123"},
        )

        result = await ingestor.process_message(msg)

        # Should always return None
        assert result is None

    @pytest.mark.asyncio
    async def test_extraction_failure_does_not_crash_agent(
        self, ingestor: Ingestor, mock_llm: Mock
    ) -> None:
        """LLM failures should be logged but not crash the agent."""
        # Setup mock LLM to raise exception
        mock_llm.messages.create.side_effect = Exception("LLM service down")

        msg = AgentMessage(
            trace_id="test-trace-013",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={"text": "Some text", "thread_id": "thread-123"},
        )

        # Should not raise exception
        result = await ingestor.process_message(msg)

        # Should return None
        assert result is None

    # =========================================================================
    # No LLM Client Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_no_llm_client_returns_empty_result(self) -> None:
        """Ingestor without LLM client should return empty result."""
        ingestor = Ingestor(
            name="ingestor",
            config={},
            graphiti_client=None,
            llm_client=None,
        )

        result = await ingestor._extract("Some text", "test-trace-014")

        # Should return empty result
        assert len(result.entities) == 0
        assert len(result.relationships) == 0


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIngestorIntegration:
    """Integration tests for Ingestor with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_complex_conversation_extraction(self) -> None:
        """Test extraction from complex multi-entity conversation."""
        # Setup
        mock_graphiti = Mock()
        mock_graphiti.is_connected = True
        mock_graphiti.add_episode = AsyncMock()

        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = [
            Mock(
                text=json.dumps(
                    {
                        "entities": [
                            {
                                "name": "Alice Johnson",
                                "label": "Person",
                                "properties": {"email": "alice@techcorp.com", "title": "Engineer"},
                                "confidence": 1.0,
                            },
                            {
                                "name": "Bob Smith",
                                "label": "Person",
                                "properties": {"email": "bob@techcorp.com", "title": "Manager"},
                                "confidence": 1.0,
                            },
                            {
                                "name": "TechCorp",
                                "label": "Organization",
                                "properties": {"domain": "techcorp.com"},
                                "confidence": 1.0,
                            },
                            {
                                "name": "Project Phoenix",
                                "label": "Project",
                                "properties": {"status": "active"},
                                "confidence": 1.0,
                            },
                        ],
                        "relationships": [
                            {
                                "source_name": "Alice Johnson",
                                "source_label": "Person",
                                "relationship_type": "WORKS_AT",
                                "target_name": "TechCorp",
                                "target_label": "Organization",
                                "properties": {"title": "Engineer"},
                                "confidence": 1.0,
                            },
                            {
                                "source_name": "Bob Smith",
                                "source_label": "Person",
                                "relationship_type": "WORKS_AT",
                                "target_name": "TechCorp",
                                "target_label": "Organization",
                                "properties": {"title": "Manager"},
                                "confidence": 1.0,
                            },
                            {
                                "source_name": "Alice Johnson",
                                "source_label": "Person",
                                "relationship_type": "REPORTS_TO",
                                "target_name": "Bob Smith",
                                "target_label": "Person",
                                "properties": {},
                                "confidence": 1.0,
                            },
                        ],
                    }
                )
            )
        ]
        mock_llm.messages.create = AsyncMock(return_value=mock_response)

        ingestor = Ingestor(
            name="ingestor",
            config={},
            graphiti_client=mock_graphiti,
            llm_client=mock_llm,
        )

        # Execute
        msg = AgentMessage(
            trace_id="test-integration-001",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={
                "text": "I met Alice Johnson (alice@techcorp.com) and her manager Bob Smith (bob@techcorp.com). They both work at TechCorp on Project Phoenix.",
                "thread_id": "thread-789",
                "captain_uuid": "user-123",
            },
        )

        result = await ingestor.process_message(msg)

        # Verify
        assert result is None  # Fire-and-forget
        mock_graphiti.add_episode.assert_called_once()

        # Check that all entities and relationships made it to the episode
        call_args = mock_graphiti.add_episode.call_args
        content = call_args.kwargs["content"]
        assert "Alice Johnson" in content
        assert "Bob Smith" in content
        assert "TechCorp" in content
        assert "Project Phoenix" in content
        assert "WORKS_AT" in content
        assert "REPORTS_TO" in content
