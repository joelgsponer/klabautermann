"""
Unit tests for zoom level search module.

Tests macro, meso, and micro level searches plus automatic zoom selection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.zoom_search import (
    MacroSearchResult,
    MesoSearchResult,
    MicroSearchResult,
    ZoomLevelSelector,
    ZoomSearchResponse,
    auto_zoom_search,
    get_entity_timeline,
    get_project_context,
    macro_search,
    meso_search,
    micro_search,
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


class TestMacroSearchResult:
    """Tests for MacroSearchResult dataclass."""

    def test_creation(self) -> None:
        """Test creating MacroSearchResult."""
        result = MacroSearchResult(
            island_uuid="island-001",
            island_name="Work Island",
            theme="professional",
            summary="Career and work activities",
            member_count=150,
            pending_tasks=5,
            last_activity=1705320000.0,
        )
        assert result.island_uuid == "island-001"
        assert result.island_name == "Work Island"
        assert result.theme == "professional"
        assert result.member_count == 150
        assert result.pending_tasks == 5


class TestMesoSearchResult:
    """Tests for MesoSearchResult dataclass."""

    def test_creation(self) -> None:
        """Test creating MesoSearchResult."""
        result = MesoSearchResult(
            uuid="note-001",
            item_type="Note",
            title="Q1 Budget Discussion",
            summary="Discussed budget allocations for Q1",
            created_at=1705320000.0,
            score=0.95,
            related_projects=["Project A"],
            mentioned_persons=["John", "Sarah"],
            aligned_goals=["Improve efficiency"],
        )
        assert result.uuid == "note-001"
        assert result.item_type == "Note"
        assert result.score == 0.95
        assert len(result.mentioned_persons) == 2


class TestMicroSearchResult:
    """Tests for MicroSearchResult dataclass."""

    def test_creation(self) -> None:
        """Test creating MicroSearchResult."""
        result = MicroSearchResult(
            entity_uuid="person-001",
            entity_type="Person",
            entity_properties={"name": "John", "email": "john@example.com"},
            score=0.88,
            relationships=[{"relationship": "WORKS_AT", "target": {"name": "Acme Corp"}}],
        )
        assert result.entity_uuid == "person-001"
        assert result.entity_type == "Person"
        assert result.entity_properties["name"] == "John"
        assert len(result.relationships) == 1


class TestZoomSearchResponse:
    """Tests for ZoomSearchResponse dataclass."""

    def test_creation(self) -> None:
        """Test creating ZoomSearchResponse."""
        macro_result = MacroSearchResult(
            island_uuid="i1",
            island_name="Test",
            theme="test",
            summary=None,
            member_count=10,
            pending_tasks=0,
            last_activity=None,
        )
        response = ZoomSearchResponse(
            zoom_level="macro",
            results=[macro_result],
            result_count=1,
        )
        assert response.zoom_level == "macro"
        assert response.result_count == 1


# =============================================================================
# Test Macro Search
# =============================================================================


class TestMacroSearch:
    """Tests for macro_search function."""

    @pytest.mark.asyncio
    async def test_returns_communities(self, mock_neo4j: MagicMock) -> None:
        """Test macro search returns community results."""
        mock_neo4j.execute_query.return_value = [
            {
                "island_uuid": "comm-001",
                "island_name": "Work Island",
                "theme": "professional",
                "summary": "Work-related entities",
                "member_count": 100,
                "pending_tasks": 5,
                "last_activity": 1705320000.0,
            },
            {
                "island_uuid": "comm-002",
                "island_name": "Family Island",
                "theme": "family",
                "summary": "Family members and events",
                "member_count": 30,
                "pending_tasks": 2,
                "last_activity": 1705310000.0,
            },
        ]

        results = await macro_search(mock_neo4j)

        assert len(results) == 2
        assert results[0].island_name == "Work Island"
        assert results[0].member_count == 100
        assert results[1].island_name == "Family Island"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test macro search with no communities."""
        mock_neo4j.execute_query.return_value = []

        results = await macro_search(mock_neo4j)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, mock_neo4j: MagicMock) -> None:
        """Test that limit parameter is passed."""
        mock_neo4j.execute_query.return_value = []

        await macro_search(mock_neo4j, limit=5)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["limit"] == 5


# =============================================================================
# Test Meso Search
# =============================================================================


class TestMesoSearch:
    """Tests for meso_search function."""

    @pytest.mark.asyncio
    async def test_returns_projects_and_notes(self, mock_neo4j: MagicMock) -> None:
        """Test meso search returns projects and notes."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "proj-001",
                "item_type": "Project",
                "title": "Q1 Budget",
                "summary": "Budget planning project",
                "created_at": 1705320000.0,
                "score": 1.0,
                "related_projects": [],
                "mentioned_persons": ["John"],
                "aligned_goals": ["Save money"],
            },
            {
                "uuid": "note-001",
                "item_type": "Note",
                "title": "Budget Meeting",
                "summary": "Notes from budget meeting",
                "created_at": 1705310000.0,
                "score": 1.0,
                "related_projects": ["Q1 Budget"],
                "mentioned_persons": [],
                "aligned_goals": [],
            },
        ]

        results = await meso_search(mock_neo4j)

        assert len(results) == 2
        assert results[0].item_type == "Project"
        assert results[1].item_type == "Note"

    @pytest.mark.asyncio
    async def test_with_island_filter(self, mock_neo4j: MagicMock) -> None:
        """Test meso search with island filter."""
        mock_neo4j.execute_query.return_value = []

        await meso_search(mock_neo4j, island_filter="Work Island")

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["island_filter"] == "Work Island"

    @pytest.mark.asyncio
    async def test_filters_none_values(self, mock_neo4j: MagicMock) -> None:
        """Test that None values are filtered from lists."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "note-001",
                "item_type": "Note",
                "title": "Test",
                "summary": None,
                "created_at": None,
                "score": 1.0,
                "related_projects": [None, "Project A", None],
                "mentioned_persons": [None],
                "aligned_goals": [],
            }
        ]

        results = await meso_search(mock_neo4j)

        assert len(results) == 1
        assert results[0].related_projects == ["Project A"]
        assert results[0].mentioned_persons == []


class TestGetProjectContext:
    """Tests for get_project_context function."""

    @pytest.mark.asyncio
    async def test_returns_context(self, mock_neo4j: MagicMock) -> None:
        """Test getting project context."""
        mock_neo4j.execute_query.return_value = [
            {
                "project_name": "Q1 Budget",
                "status": "active",
                "deadline": 1705320000.0,
                "goal": "Save 10%",
                "island": "Work Island",
                "recent_notes": [],
                "tasks": [],
                "key_persons": ["John"],
            }
        ]

        result = await get_project_context(mock_neo4j, "proj-001")

        assert result is not None
        assert result["project_name"] == "Q1 Budget"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, mock_neo4j: MagicMock) -> None:
        """Test returns None for missing project."""
        mock_neo4j.execute_query.return_value = []

        result = await get_project_context(mock_neo4j, "nonexistent")

        assert result is None


# =============================================================================
# Test Micro Search
# =============================================================================


class TestMicroSearch:
    """Tests for micro_search function."""

    @pytest.mark.asyncio
    async def test_returns_entities(self, mock_neo4j: MagicMock) -> None:
        """Test micro search returns entity results."""
        mock_neo4j.execute_query.return_value = [
            {
                "entity_uuid": "person-001",
                "entity_type": "Person",
                "entity_properties": {"name": "John", "email": "john@example.com"},
                "score": 1.0,
                "relationships": [
                    {
                        "relationship": "WORKS_AT",
                        "target": {"name": "Acme"},
                        "target_type": "Organization",
                        "created_at": 1705320000.0,
                        "expired_at": None,
                    }
                ],
            }
        ]

        results = await micro_search(mock_neo4j)

        assert len(results) == 1
        assert results[0].entity_type == "Person"
        assert results[0].entity_properties["name"] == "John"

    @pytest.mark.asyncio
    async def test_with_entity_type_filter(self, mock_neo4j: MagicMock) -> None:
        """Test micro search with entity type filter."""
        mock_neo4j.execute_query.return_value = []

        await micro_search(mock_neo4j, entity_type="Person")

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        assert "n:Person" in query

    @pytest.mark.asyncio
    async def test_with_query_text(self, mock_neo4j: MagicMock) -> None:
        """Test micro search with query text."""
        mock_neo4j.execute_query.return_value = []

        await micro_search(mock_neo4j, query_text="john")

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["query_text"] == "john"

    @pytest.mark.asyncio
    async def test_filters_empty_relationships(self, mock_neo4j: MagicMock) -> None:
        """Test that relationships without targets are filtered."""
        mock_neo4j.execute_query.return_value = [
            {
                "entity_uuid": "person-001",
                "entity_type": "Person",
                "entity_properties": {"name": "John"},
                "score": 1.0,
                "relationships": [
                    {"relationship": "WORKS_AT", "target": None},
                    {"relationship": "KNOWS", "target": {"name": "Sarah"}},
                ],
            }
        ]

        results = await micro_search(mock_neo4j)

        assert len(results[0].relationships) == 1
        assert results[0].relationships[0]["relationship"] == "KNOWS"


class TestGetEntityTimeline:
    """Tests for get_entity_timeline function."""

    @pytest.mark.asyncio
    async def test_returns_timeline(self, mock_neo4j: MagicMock) -> None:
        """Test getting entity timeline."""
        mock_neo4j.execute_query.return_value = [
            {
                "relationship": "WORKS_AT",
                "related_type": "Organization",
                "related_name": "Acme Corp",
                "started": 1705320000.0,
                "ended": None,
            },
            {
                "relationship": "WORKS_AT",
                "related_type": "Organization",
                "related_name": "Old Co",
                "started": 1700000000.0,
                "ended": 1705319999.0,
            },
        ]

        result = await get_entity_timeline(mock_neo4j, "person-001")

        assert len(result) == 2
        assert result[0]["relationship"] == "WORKS_AT"
        assert result[0]["related_name"] == "Acme Corp"


# =============================================================================
# Test Zoom Level Selector
# =============================================================================


class TestZoomLevelSelector:
    """Tests for ZoomLevelSelector class."""

    def test_macro_indicators(self) -> None:
        """Test macro level detection."""
        selector = ZoomLevelSelector()

        assert selector.select_zoom_level("Give me an overview of my life") == "macro"
        assert selector.select_zoom_level("Show me a summary of all themes") == "macro"
        assert selector.select_zoom_level("Summary of everything in my life") == "macro"

    def test_meso_indicators(self) -> None:
        """Test meso level detection."""
        selector = ZoomLevelSelector()

        assert selector.select_zoom_level("Show project status and progress") == "meso"
        assert selector.select_zoom_level("Tell me discussed topics") == "meso"
        assert selector.select_zoom_level("Show me recent notes") == "meso"

    def test_micro_indicators(self) -> None:
        """Test micro level detection."""
        selector = ZoomLevelSelector()

        assert selector.select_zoom_level("Who is John?") == "micro"
        assert selector.select_zoom_level("When did Sarah join?") == "micro"
        assert selector.select_zoom_level("What is John's email?") == "micro"

    def test_question_words_favor_micro(self) -> None:
        """Test that question words boost micro score."""
        selector = ZoomLevelSelector()

        # "Who" should strongly favor micro
        assert selector.select_zoom_level("Who works at Acme?") == "micro"
        assert selector.select_zoom_level("Where is the meeting?") == "micro"

    def test_default_to_micro(self) -> None:
        """Test that ambiguous queries default to micro."""
        selector = ZoomLevelSelector()

        # No strong indicators
        assert selector.select_zoom_level("Find information") == "micro"


# =============================================================================
# Test Auto Zoom Search
# =============================================================================


class TestAutoZoomSearch:
    """Tests for auto_zoom_search function."""

    @pytest.mark.asyncio
    async def test_selects_macro(self, mock_neo4j: MagicMock) -> None:
        """Test auto search selects macro level."""
        mock_neo4j.execute_query.return_value = []

        response = await auto_zoom_search(mock_neo4j, "Give me an overview")

        assert response.zoom_level == "macro"

    @pytest.mark.asyncio
    async def test_selects_meso(self, mock_neo4j: MagicMock) -> None:
        """Test auto search selects meso level."""
        mock_neo4j.execute_query.return_value = []

        response = await auto_zoom_search(mock_neo4j, "Show project status and progress")

        assert response.zoom_level == "meso"

    @pytest.mark.asyncio
    async def test_selects_micro(self, mock_neo4j: MagicMock) -> None:
        """Test auto search selects micro level."""
        mock_neo4j.execute_query.return_value = []

        response = await auto_zoom_search(mock_neo4j, "Who is John?")

        assert response.zoom_level == "micro"

    @pytest.mark.asyncio
    async def test_returns_correct_result_count(self, mock_neo4j: MagicMock) -> None:
        """Test result count is accurate."""
        mock_neo4j.execute_query.return_value = [
            {
                "entity_uuid": "1",
                "entity_type": "Person",
                "entity_properties": {},
                "score": 1.0,
                "relationships": [],
            },
            {
                "entity_uuid": "2",
                "entity_type": "Person",
                "entity_properties": {},
                "score": 0.9,
                "relationships": [],
            },
        ]

        response = await auto_zoom_search(mock_neo4j, "Find people")

        assert response.result_count == 2
