"""
Unit tests for the GraphitiClient memory layer.

Tests search, ingestion, and entity retrieval operations
using mocked Graphiti library.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.core.exceptions import ExternalServiceError, GraphConnectionError


class TestGraphitiClientConnection:
    """Tests for GraphitiClient connection management."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values from env vars."""
        with patch.dict("os.environ", {
            "NEO4J_URI": "bolt://test:7687",
            "NEO4J_USERNAME": "testuser",
            "NEO4J_PASSWORD": "testpass",
            "OPENAI_API_KEY": "test-key",
        }):
            from klabautermann.memory.graphiti_client import GraphitiClient
            client = GraphitiClient()

            assert client.neo4j_uri == "bolt://test:7687"
            assert client.neo4j_user == "testuser"
            assert client.neo4j_password == "testpass"
            assert client.openai_api_key == "test-key"
            assert not client.is_connected

    def test_init_with_explicit_values(self) -> None:
        """Test initialization with explicit parameter values."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient(
            neo4j_uri="bolt://explicit:7687",
            neo4j_user="explicituser",
            neo4j_password="explicitpass",
            openai_api_key="explicit-key",
        )

        assert client.neo4j_uri == "bolt://explicit:7687"
        assert client.neo4j_user == "explicituser"
        assert client.neo4j_password == "explicitpass"
        assert client.openai_api_key == "explicit-key"

    @pytest.mark.asyncio
    async def test_connect_success(self) -> None:
        """Verify connection initializes Graphiti client."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        mock_graphiti_instance = MagicMock()
        mock_graphiti_instance.build_indices_and_constraints = AsyncMock()
        mock_graphiti_class = MagicMock(return_value=mock_graphiti_instance)

        # Patch at the point of import inside connect()
        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(Graphiti=mock_graphiti_class),
        }):
            client = GraphitiClient(
                neo4j_uri="bolt://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
            )
            await client.connect()

            assert client.is_connected
            assert client._client is not None

    @pytest.mark.asyncio
    async def test_connect_handles_connection_failure(self) -> None:
        """Raises GraphConnectionError on connection failure."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        mock_graphiti_class = MagicMock(side_effect=Exception("Connection refused"))

        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(Graphiti=mock_graphiti_class),
        }):
            client = GraphitiClient(
                neo4j_uri="bolt://invalid:7687",
                neo4j_user="neo4j",
                neo4j_password="wrong",
            )

            with pytest.raises(GraphConnectionError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self) -> None:
        """Verify disconnect cleans up resources."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        # Create connected client
        client = GraphitiClient()
        client._client = MagicMock()
        client._client.close = AsyncMock()
        client._connected = True

        await client.disconnect()

        assert client._client is None
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_handles_error_gracefully(self) -> None:
        """Disconnect handles errors without crashing."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._client.close = AsyncMock(side_effect=Exception("Close failed"))
        client._connected = True

        # Should not raise
        await client.disconnect()

        assert client._client is None
        assert not client.is_connected

    def test_is_connected_property(self) -> None:
        """Verify is_connected reflects actual state."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()

        # Initially not connected
        assert not client.is_connected

        # Connected state requires both flag and client
        client._connected = True
        assert not client.is_connected  # Still false because _client is None

        client._client = MagicMock()
        assert client.is_connected  # Now true

        client._connected = False
        assert not client.is_connected  # Flag is false


class TestGraphitiClientSearch:
    """Tests for GraphitiClient search operations."""

    @pytest.fixture
    def connected_client(self) -> Any:
        """Create a connected GraphitiClient with mocked internals."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True
        return client

    def _create_mock_result(
        self, fact: str, score: float = 0.9, uuid: str = "uuid-1", label: str = "Fact"
    ) -> MagicMock:
        """Create a properly configured mock search result."""
        mock = MagicMock()
        mock.fact = fact
        mock.content = fact
        mock.score = score
        mock.uuid = uuid
        mock.label = label
        mock.name = None  # Explicitly set name to None instead of MagicMock
        return mock

    @pytest.mark.asyncio
    async def test_search_returns_results(self, connected_client: Any) -> None:
        """Search returns list of SearchResult objects."""
        mock_result_1 = self._create_mock_result(
            "John works at Acme Corp", 0.95, "uuid-1", "Fact"
        )
        mock_result_2 = self._create_mock_result(
            "Sarah is a developer", 0.85, "uuid-2", "Fact"
        )

        connected_client._client.search = AsyncMock(return_value=[mock_result_1, mock_result_2])

        results = await connected_client.search("Who works at Acme?", trace_id="test-123")

        assert len(results) == 2
        assert results[0].content == "John works at Acme Corp"
        assert results[0].score == 0.95
        assert results[1].content == "Sarah is a developer"

    @pytest.mark.asyncio
    async def test_search_with_limit(self, connected_client: Any) -> None:
        """Respects limit parameter."""
        connected_client._client.search = AsyncMock(return_value=[])

        await connected_client.search("test query", limit=5, trace_id="test-123")

        connected_client._client.search.assert_called_once_with("test query", num_results=5)

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(self, connected_client: Any) -> None:
        """Returns empty list when no matches."""
        connected_client._client.search = AsyncMock(return_value=[])

        results = await connected_client.search("no matches", trace_id="test-123")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_raises_when_disconnected(self) -> None:
        """Raises GraphConnectionError if not connected."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()

        with pytest.raises(GraphConnectionError):
            await client.search("test query")

    @pytest.mark.asyncio
    async def test_search_handles_graphiti_error(self, connected_client: Any) -> None:
        """Raises ExternalServiceError on failure."""
        connected_client._client.search = AsyncMock(side_effect=Exception("Search error"))

        with pytest.raises(ExternalServiceError):
            await connected_client.search("test query", trace_id="test-123")


class TestGraphitiClientEntitySearch:
    """Tests for GraphitiClient entity search operations."""

    @pytest.fixture
    def connected_client(self) -> Any:
        """Create a connected GraphitiClient with mocked internals."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True
        return client

    @pytest.mark.asyncio
    async def test_search_entities_returns_results(self, connected_client: Any) -> None:
        """Entity search returns SearchResult list."""
        # Mock Neo4j session and results
        mock_result = MagicMock()
        mock_result.data = AsyncMock(return_value=[
            {"uuid": "uuid-1", "name": "John Doe", "summary": "Software engineer", "labels": ["Person"], "score": 0.9},
            {"uuid": "uuid-2", "name": "Acme Corp", "summary": "Tech company", "labels": ["Organization"], "score": 0.8},
        ])

        mock_session = MagicMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        connected_client._client.driver = MagicMock()
        connected_client._client.driver.session = MagicMock(return_value=mock_session)

        results = await connected_client.search_entities("John", trace_id="test-123")

        assert len(results) == 2
        assert results[0].name == "John Doe"
        assert results[0].label == "Person"
        assert results[1].name == "Acme Corp"
        assert results[1].label == "Organization"

    @pytest.mark.asyncio
    async def test_search_entities_returns_empty_on_error(self, connected_client: Any) -> None:
        """Returns empty list instead of raising on error."""
        mock_session = MagicMock()
        mock_session.run = AsyncMock(side_effect=Exception("Query failed"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        connected_client._client.driver = MagicMock()
        connected_client._client.driver.session = MagicMock(return_value=mock_session)

        # Should not raise, just return empty list
        results = await connected_client.search_entities("test", trace_id="test-123")

        assert results == []


class TestGraphitiClientIngestion:
    """Tests for GraphitiClient episode ingestion."""

    @pytest.fixture
    def connected_client(self) -> Any:
        """Create a connected GraphitiClient with mocked internals."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True
        return client

    @pytest.mark.asyncio
    async def test_add_episode_success(self, connected_client: Any) -> None:
        """Episode ingested successfully."""
        connected_client._client.add_episode = AsyncMock()

        # Mock the EpisodeType import inside add_episode
        mock_episode_type = MagicMock()
        mock_episode_type.message = "message"
        mock_episode_type.text = "text"

        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(),
            "graphiti_core.nodes": MagicMock(EpisodeType=mock_episode_type),
        }):
            await connected_client.add_episode(
                content="John met Sarah at the conference",
                source="conversation",
                trace_id="test-123",
            )

        connected_client._client.add_episode.assert_called_once()
        call_kwargs = connected_client._client.add_episode.call_args.kwargs
        assert call_kwargs["episode_body"] == "John met Sarah at the conference"

    @pytest.mark.asyncio
    async def test_add_episode_with_group_id(self, connected_client: Any) -> None:
        """Group ID passed correctly."""
        connected_client._client.add_episode = AsyncMock()

        mock_episode_type = MagicMock()
        mock_episode_type.message = "message"

        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(),
            "graphiti_core.nodes": MagicMock(EpisodeType=mock_episode_type),
        }):
            await connected_client.add_episode(
                content="Test content",
                source="conversation",
                group_id="thread-123",
                trace_id="test-123",
            )

        call_kwargs = connected_client._client.add_episode.call_args.kwargs
        assert call_kwargs["group_id"] == "thread-123"

    @pytest.mark.asyncio
    async def test_add_episode_uses_reference_time(self, connected_client: Any) -> None:
        """Reference time passed correctly."""
        connected_client._client.add_episode = AsyncMock()

        ref_time = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)

        mock_episode_type = MagicMock()
        mock_episode_type.message = "message"

        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(),
            "graphiti_core.nodes": MagicMock(EpisodeType=mock_episode_type),
        }):
            await connected_client.add_episode(
                content="Historical event",
                reference_time=ref_time,
                trace_id="test-123",
            )

        call_kwargs = connected_client._client.add_episode.call_args.kwargs
        assert call_kwargs["reference_time"] == ref_time

    @pytest.mark.asyncio
    async def test_add_episode_raises_when_disconnected(self) -> None:
        """Raises GraphConnectionError if not connected."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()

        with pytest.raises(GraphConnectionError):
            await client.add_episode(content="test", trace_id="test-123")

    @pytest.mark.asyncio
    async def test_add_episode_handles_graphiti_error(self, connected_client: Any) -> None:
        """Raises ExternalServiceError on failure."""
        connected_client._client.add_episode = AsyncMock(
            side_effect=Exception("Ingestion failed")
        )

        mock_episode_type = MagicMock()
        mock_episode_type.message = "message"

        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(),
            "graphiti_core.nodes": MagicMock(EpisodeType=mock_episode_type),
        }):
            with pytest.raises(ExternalServiceError):
                await connected_client.add_episode(
                    content="test",
                    trace_id="test-123",
                )


class TestGraphitiClientEntityRetrieval:
    """Tests for GraphitiClient entity retrieval."""

    @pytest.fixture
    def connected_client(self) -> Any:
        """Create a connected GraphitiClient with mocked internals."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True
        return client

    @pytest.mark.asyncio
    async def test_get_entity_returns_data(self, connected_client: Any) -> None:
        """Returns entity dict when found."""
        mock_node = {"uuid": "uuid-1", "name": "John", "type": "Person"}
        connected_client._client.get_node = AsyncMock(return_value=mock_node)

        result = await connected_client.get_entity("uuid-1", trace_id="test-123")

        assert result is not None
        assert result["name"] == "John"
        assert result["type"] == "Person"

    @pytest.mark.asyncio
    async def test_get_entity_returns_none_when_not_found(self, connected_client: Any) -> None:
        """Returns None for missing entity."""
        connected_client._client.get_node = AsyncMock(return_value=None)

        result = await connected_client.get_entity("nonexistent-uuid", trace_id="test-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_fallback_when_no_method(self, connected_client: Any) -> None:
        """Falls back gracefully when get_node not available."""
        # Remove get_node method to simulate older Graphiti version
        del connected_client._client.get_node

        result = await connected_client.get_entity("uuid-1", trace_id="test-123")

        # Should return None as fallback
        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_handles_error(self, connected_client: Any) -> None:
        """Returns None on error instead of raising."""
        connected_client._client.get_node = AsyncMock(side_effect=Exception("Error"))

        result = await connected_client.get_entity("uuid-1", trace_id="test-123")

        assert result is None


class TestGraphitiClientEnsureConnected:
    """Tests for connection validation."""

    def test_ensure_connected_raises_when_not_connected(self) -> None:
        """Raises GraphConnectionError when not connected."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()

        with pytest.raises(GraphConnectionError):
            client._ensure_connected()

    def test_ensure_connected_passes_when_connected(self) -> None:
        """No error when properly connected."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True

        # Should not raise
        client._ensure_connected()


class TestGraphitiClientSearchResultMapping:
    """Tests for search result mapping from Graphiti to SearchResult."""

    @pytest.fixture
    def connected_client(self) -> Any:
        """Create a connected GraphitiClient."""
        from klabautermann.memory.graphiti_client import GraphitiClient

        client = GraphitiClient()
        client._client = MagicMock()
        client._connected = True
        return client

    @pytest.mark.asyncio
    async def test_maps_fact_attribute(self, connected_client: Any) -> None:
        """Maps 'fact' attribute to content."""
        mock_result = MagicMock()
        mock_result.fact = "This is a fact"
        mock_result.content = None
        mock_result.score = 0.9
        mock_result.uuid = "uuid-1"
        mock_result.label = "Fact"
        mock_result.name = None

        connected_client._client.search = AsyncMock(return_value=[mock_result])

        results = await connected_client.search("test", trace_id="test-123")

        assert results[0].content == "This is a fact"

    @pytest.mark.asyncio
    async def test_maps_content_when_no_fact(self, connected_client: Any) -> None:
        """Falls back to 'content' attribute when 'fact' is None."""
        mock_result = MagicMock()
        mock_result.fact = None
        mock_result.content = "This is content"
        mock_result.score = 0.8
        mock_result.uuid = "uuid-1"
        mock_result.label = "Note"
        mock_result.name = None

        connected_client._client.search = AsyncMock(return_value=[mock_result])

        results = await connected_client.search("test", trace_id="test-123")

        assert results[0].content == "This is content"

    @pytest.mark.asyncio
    async def test_extracts_metadata(self, connected_client: Any) -> None:
        """Extracts metadata attributes from results."""
        mock_result = MagicMock()
        mock_result.fact = "A fact"
        mock_result.score = 0.9
        mock_result.uuid = "uuid-1"
        mock_result.label = "Fact"
        mock_result.name = None
        mock_result.source = "conversation"
        mock_result.created_at = "2026-01-20T10:00:00Z"
        mock_result.episode_uuid = "episode-123"

        connected_client._client.search = AsyncMock(return_value=[mock_result])

        results = await connected_client.search("test", trace_id="test-123")

        assert results[0].metadata.get("source") == "conversation"
        assert results[0].metadata.get("created_at") == "2026-01-20T10:00:00Z"
        assert results[0].metadata.get("episode_uuid") == "episode-123"
