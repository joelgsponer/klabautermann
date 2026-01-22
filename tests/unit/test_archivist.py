"""
Unit tests for Archivist Agent.

Reference: specs/architecture/AGENTS.md Section 1.5 (The Archivist)
Task: T040 - Archivist Agent Skeleton

The Archivist's job is to:
1. Scan for inactive threads (60+ minutes cooldown)
2. Summarize threads into Note nodes
3. Prune original messages after archival
4. Handle archival failures gracefully (reactivate thread)

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from klabautermann.agents.archivist import Archivist
from klabautermann.core.models import (
    AgentMessage,
    ChannelType,
    ThreadContext,
    ThreadSummary,
)


class TestScanForInactiveThreads:
    """Test suite for scanning inactive threads."""

    @pytest.fixture
    def mock_thread_manager(self) -> Mock:
        """Create a mock ThreadManager."""
        mock = Mock()
        mock.get_inactive_threads = AsyncMock()
        mock.mark_archiving = AsyncMock()
        mock.get_context_window = AsyncMock()
        mock.mark_archived = AsyncMock()
        mock.reactivate_thread = AsyncMock()
        mock.prune_thread_messages = AsyncMock(return_value=5)  # Return count of pruned messages
        return mock

    @pytest.fixture
    def archivist(self, mock_thread_manager: Mock) -> Archivist:
        """Create an Archivist instance with mocked dependencies."""
        return Archivist(
            name="archivist",
            config={"cooldown_minutes": 60, "max_threads_per_scan": 10},
            thread_manager=mock_thread_manager,
            neo4j_client=None,
        )

    @pytest.mark.asyncio
    async def test_scan_returns_inactive_threads(
        self, archivist: Archivist, mock_thread_manager: Mock
    ) -> None:
        """Should return list of inactive thread UUIDs."""
        mock_thread_manager.get_inactive_threads.return_value = [
            "thread-uuid-001",
            "thread-uuid-002",
        ]

        result = await archivist.scan_for_inactive_threads(trace_id="test-trace-001")

        assert result == ["thread-uuid-001", "thread-uuid-002"]
        mock_thread_manager.get_inactive_threads.assert_called_once_with(
            cooldown_minutes=60,
            limit=10,
            trace_id="test-trace-001",
        )

    @pytest.mark.asyncio
    async def test_scan_uses_configured_cooldown(self, mock_thread_manager: Mock) -> None:
        """Should use configured cooldown minutes."""
        archivist = Archivist(
            name="archivist",
            config={"cooldown_minutes": 120},
            thread_manager=mock_thread_manager,
        )

        await archivist.scan_for_inactive_threads(trace_id="test-trace-002")

        call_kwargs = mock_thread_manager.get_inactive_threads.call_args.kwargs
        assert call_kwargs["cooldown_minutes"] == 120

    @pytest.mark.asyncio
    async def test_scan_uses_configured_limit(self, mock_thread_manager: Mock) -> None:
        """Should use configured max_threads_per_scan limit."""
        archivist = Archivist(
            name="archivist",
            config={"max_threads_per_scan": 5},
            thread_manager=mock_thread_manager,
        )

        await archivist.scan_for_inactive_threads(trace_id="test-trace-003")

        call_kwargs = mock_thread_manager.get_inactive_threads.call_args.kwargs
        assert call_kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_scan_returns_empty_when_no_threads(
        self, archivist: Archivist, mock_thread_manager: Mock
    ) -> None:
        """Should return empty list when no inactive threads found."""
        mock_thread_manager.get_inactive_threads.return_value = []

        result = await archivist.scan_for_inactive_threads(trace_id="test-trace-004")

        assert result == []

    @pytest.mark.asyncio
    async def test_scan_without_thread_manager(self) -> None:
        """Should return empty list when ThreadManager not configured."""
        archivist = Archivist(
            name="archivist",
            config={},
            thread_manager=None,
        )

        result = await archivist.scan_for_inactive_threads(trace_id="test-trace-005")

        assert result == []


class TestArchiveThread:
    """Test suite for archiving a single thread."""

    @pytest.fixture
    def mock_thread_manager(self) -> Mock:
        """Create a mock ThreadManager."""
        mock = Mock()
        mock.mark_archiving = AsyncMock(return_value=True)
        mock.get_context_window = AsyncMock()
        mock.mark_archived = AsyncMock(return_value=True)
        mock.reactivate_thread = AsyncMock(return_value=True)
        mock.prune_thread_messages = AsyncMock(return_value=5)  # Return count of pruned messages
        return mock

    @pytest.fixture
    def mock_summarize(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        """Mock the summarize_thread function."""
        mock = AsyncMock()
        mock.return_value = ThreadSummary(
            summary="Test summary",
            topics=["test", "topic"],
            action_items=[],
            new_facts=[],
            conflicts=[],
            participants=["user", "assistant"],
            sentiment="neutral",
        )
        monkeypatch.setattr(
            "klabautermann.agents.archivist.summarize_thread",
            mock,
        )
        return mock

    @pytest.fixture
    def archivist(self, mock_thread_manager: Mock) -> Archivist:
        """Create an Archivist instance with mocked dependencies."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=mock_thread_manager,
            neo4j_client=None,
        )

    @pytest.mark.asyncio
    async def test_archive_success_returns_note_uuid(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should return Note UUID on successful archival."""
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-001",
            channel_type=ChannelType.CLI,
            messages=[
                {"role": "user", "content": "Hello", "timestamp": 1704067200.0},
                {"role": "assistant", "content": "Hi!", "timestamp": 1704067205.0},
            ],
        )

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-001",
            trace_id="test-trace-001",
        )

        assert result is not None
        assert isinstance(result, str)
        # Should have called mark_archiving first
        mock_thread_manager.mark_archiving.assert_called_once_with(
            "thread-uuid-001", "test-trace-001"
        )
        # Should have fetched messages
        mock_thread_manager.get_context_window.assert_called_once()
        # Should have summarized
        mock_summarize.assert_called_once()
        # Should have marked as archived
        mock_thread_manager.mark_archived.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_marks_archiving_atomically(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should call mark_archiving with thread UUID and trace ID."""
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-002",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )

        await archivist.archive_thread(
            thread_uuid="thread-uuid-002",
            trace_id="test-trace-002",
        )

        mock_thread_manager.mark_archiving.assert_called_once_with(
            "thread-uuid-002", "test-trace-002"
        )

    @pytest.mark.asyncio
    async def test_archive_returns_none_when_not_available(
        self, archivist: Archivist, mock_thread_manager: Mock
    ) -> None:
        """Should return None when thread not available for archival."""
        mock_thread_manager.mark_archiving.return_value = False

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-003",
            trace_id="test-trace-003",
        )

        assert result is None
        # Should not fetch messages or summarize
        mock_thread_manager.get_context_window.assert_not_called()

    @pytest.mark.asyncio
    async def test_archive_reactivates_on_empty_thread(
        self, archivist: Archivist, mock_thread_manager: Mock
    ) -> None:
        """Should reactivate thread when it has no messages."""
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-004",
            channel_type=ChannelType.CLI,
            messages=[],  # Empty messages
        )

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-004",
            trace_id="test-trace-004",
        )

        assert result is None
        mock_thread_manager.reactivate_thread.assert_called_once_with(
            "thread-uuid-004", "test-trace-004"
        )

    @pytest.mark.asyncio
    async def test_archive_reactivates_on_mark_archived_failure(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should reactivate thread when mark_archived fails."""
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-005",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )
        mock_thread_manager.mark_archived.return_value = False

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-005",
            trace_id="test-trace-005",
        )

        assert result is None
        mock_thread_manager.reactivate_thread.assert_called_once_with(
            "thread-uuid-005", "test-trace-005"
        )

    @pytest.mark.asyncio
    async def test_archive_reactivates_on_exception(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should reactivate thread when any exception occurs."""
        mock_thread_manager.get_context_window.side_effect = Exception("Database error")

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-006",
            trace_id="test-trace-006",
        )

        assert result is None
        mock_thread_manager.reactivate_thread.assert_called_once_with(
            "thread-uuid-006", "test-trace-006"
        )

    @pytest.mark.asyncio
    async def test_archive_without_thread_manager(self) -> None:
        """Should return None when ThreadManager not configured."""
        archivist = Archivist(
            name="archivist",
            config={},
            thread_manager=None,
        )

        result = await archivist.archive_thread(
            thread_uuid="thread-uuid-007",
            trace_id="test-trace-007",
        )

        assert result is None


class TestProcessArchivalQueue:
    """Test suite for processing the archival queue."""

    @pytest.fixture
    def mock_thread_manager(self) -> Mock:
        """Create a mock ThreadManager."""
        mock = Mock()
        mock.get_inactive_threads = AsyncMock()
        mock.mark_archiving = AsyncMock(return_value=True)
        mock.get_context_window = AsyncMock()
        mock.mark_archived = AsyncMock(return_value=True)
        mock.reactivate_thread = AsyncMock()
        mock.prune_thread_messages = AsyncMock(return_value=5)  # Return count of pruned messages
        return mock

    @pytest.fixture
    def mock_summarize(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        """Mock the summarize_thread function."""
        mock = AsyncMock()
        mock.return_value = ThreadSummary(
            summary="Test summary",
            topics=[],
            action_items=[],
            new_facts=[],
            conflicts=[],
            participants=[],
            sentiment="neutral",
        )
        monkeypatch.setattr(
            "klabautermann.agents.archivist.summarize_thread",
            mock,
        )
        return mock

    @pytest.fixture
    def archivist(self, mock_thread_manager: Mock) -> Archivist:
        """Create an Archivist instance with mocked dependencies."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=mock_thread_manager,
            neo4j_client=None,
        )

    @pytest.mark.asyncio
    async def test_process_queue_archives_all_threads(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should archive all inactive threads and return count."""
        mock_thread_manager.get_inactive_threads.return_value = [
            "thread-uuid-001",
            "thread-uuid-002",
            "thread-uuid-003",
        ]
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="test",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )

        result = await archivist.process_archival_queue(trace_id="test-trace-001")

        assert result == 3
        # Should have called mark_archiving for each thread
        assert mock_thread_manager.mark_archiving.call_count == 3

    @pytest.mark.asyncio
    async def test_process_queue_returns_zero_when_empty(
        self, archivist: Archivist, mock_thread_manager: Mock
    ) -> None:
        """Should return 0 when no inactive threads found."""
        mock_thread_manager.get_inactive_threads.return_value = []

        result = await archivist.process_archival_queue(trace_id="test-trace-002")

        assert result == 0

    @pytest.mark.asyncio
    async def test_process_queue_continues_on_failure(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should continue processing other threads when one fails."""
        mock_thread_manager.get_inactive_threads.return_value = [
            "thread-uuid-001",
            "thread-uuid-002",
            "thread-uuid-003",
        ]

        # First thread succeeds
        # Second thread fails (mark_archiving returns False)
        # Third thread succeeds
        mock_thread_manager.mark_archiving.side_effect = [True, False, True]
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="test",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )

        result = await archivist.process_archival_queue(trace_id="test-trace-003")

        # Should have archived 2 out of 3 threads
        assert result == 2


class TestProcessMessage:
    """Test suite for agent message processing."""

    @pytest.fixture
    def mock_thread_manager(self) -> Mock:
        """Create a mock ThreadManager."""
        mock = Mock()
        mock.mark_archiving = AsyncMock(return_value=True)
        mock.get_context_window = AsyncMock()
        mock.mark_archived = AsyncMock(return_value=True)
        mock.reactivate_thread = AsyncMock()
        mock.prune_thread_messages = AsyncMock(return_value=5)  # Return count of pruned messages
        return mock

    @pytest.fixture
    def mock_summarize(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        """Mock the summarize_thread function."""
        mock = AsyncMock()
        mock.return_value = ThreadSummary(
            summary="Test summary",
            topics=[],
            action_items=[],
            new_facts=[],
            conflicts=[],
            participants=[],
            sentiment="neutral",
        )
        monkeypatch.setattr(
            "klabautermann.agents.archivist.summarize_thread",
            mock,
        )
        return mock

    @pytest.fixture
    def archivist(self, mock_thread_manager: Mock) -> Archivist:
        """Create an Archivist instance with mocked dependencies."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=mock_thread_manager,
            neo4j_client=None,
        )

    @pytest.mark.asyncio
    async def test_handles_archive_thread_intent(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
    ) -> None:
        """Should handle ARCHIVE_THREAD intent and return result."""
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-001",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )

        msg = AgentMessage(
            trace_id="test-trace-001",
            source_agent="orchestrator",
            target_agent="archivist",
            intent="ARCHIVE_THREAD",
            payload={"thread_uuid": "thread-uuid-001"},
        )

        response = await archivist.process_message(msg)

        assert response is not None
        assert response.intent == "ARCHIVE_RESULT"
        assert response.target_agent == "orchestrator"
        assert response.payload["thread_uuid"] == "thread-uuid-001"
        assert response.payload["success"] is True
        assert "note_uuid" in response.payload

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_intent(self, archivist: Archivist) -> None:
        """Should return None for unknown intent."""
        msg = AgentMessage(
            trace_id="test-trace-002",
            source_agent="orchestrator",
            target_agent="archivist",
            intent="UNKNOWN_INTENT",
            payload={},
        )

        response = await archivist.process_message(msg)

        assert response is None

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_thread_uuid(self, archivist: Archivist) -> None:
        """Should return None when thread_uuid missing from payload."""
        msg = AgentMessage(
            trace_id="test-trace-003",
            source_agent="orchestrator",
            target_agent="archivist",
            intent="ARCHIVE_THREAD",
            payload={},  # Missing thread_uuid
        )

        response = await archivist.process_message(msg)

        assert response is None


class TestConfiguration:
    """Test suite for configuration handling."""

    def test_uses_default_cooldown(self) -> None:
        """Should use default cooldown when not configured."""
        archivist = Archivist(name="archivist", config={})

        assert archivist.cooldown_minutes == 60

    def test_uses_configured_cooldown(self) -> None:
        """Should use configured cooldown minutes."""
        archivist = Archivist(
            name="archivist",
            config={"cooldown_minutes": 120},
        )

        assert archivist.cooldown_minutes == 120

    def test_uses_default_max_threads(self) -> None:
        """Should use default max_threads_per_scan when not configured."""
        archivist = Archivist(name="archivist", config={})

        assert archivist.max_threads_per_scan == 10

    def test_uses_configured_max_threads(self) -> None:
        """Should use configured max_threads_per_scan."""
        archivist = Archivist(
            name="archivist",
            config={"max_threads_per_scan": 5},
        )

        assert archivist.max_threads_per_scan == 5


class TestDetectAndMergeDuplicates:
    """Test suite for duplicate detection and merging (#35, #191)."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_query = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def archivist(self, mock_neo4j: Mock) -> Archivist:
        """Create an Archivist instance with mocked Neo4j client."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_detect_duplicates_uses_process_duplicates(
        self, archivist: Archivist, mock_neo4j: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should use process_duplicates pipeline for comprehensive detection."""
        mock_process = AsyncMock(
            return_value={
                "auto_merged": 2,
                "flagged_for_review": 1,
                "ignored": 3,
            }
        )
        monkeypatch.setattr("klabautermann.agents.archivist.process_duplicates", mock_process)

        result = await archivist.detect_and_merge_duplicates(trace_id="test-trace-001")

        assert result == {"auto_merged": 2, "flagged_for_review": 1, "ignored": 3}
        mock_process.assert_called_once_with(
            mock_neo4j,
            auto_merge_threshold=0.9,
            review_threshold=0.7,
            trace_id="test-trace-001",
        )

    @pytest.mark.asyncio
    async def test_detect_duplicates_custom_thresholds(
        self, archivist: Archivist, mock_neo4j: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should pass custom thresholds to process_duplicates."""
        mock_process = AsyncMock(
            return_value={"auto_merged": 0, "flagged_for_review": 0, "ignored": 0}
        )
        monkeypatch.setattr("klabautermann.agents.archivist.process_duplicates", mock_process)

        await archivist.detect_and_merge_duplicates(
            trace_id="test-trace-002",
            auto_merge_threshold=0.95,
            review_threshold=0.8,
        )

        mock_process.assert_called_once_with(
            mock_neo4j,
            auto_merge_threshold=0.95,
            review_threshold=0.8,
            trace_id="test-trace-002",
        )

    @pytest.mark.asyncio
    async def test_detect_duplicates_returns_empty_stats_without_neo4j(self) -> None:
        """Should return empty stats when Neo4j client not configured."""
        archivist = Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=None,
        )

        result = await archivist.detect_and_merge_duplicates(trace_id="test-trace-003")

        assert result == {"auto_merged": 0, "flagged_for_review": 0, "ignored": 0}


class TestGetFlaggedDuplicates:
    """Test suite for retrieving flagged duplicates (#35)."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_query = AsyncMock()
        return mock

    @pytest.fixture
    def archivist(self, mock_neo4j: Mock) -> Archivist:
        """Create an Archivist instance with mocked Neo4j client."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_returns_flagged_duplicates(self, archivist: Archivist, mock_neo4j: Mock) -> None:
        """Should return DuplicateCandidate objects for flagged pairs."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid1": "person-001",
                "uuid2": "person-002",
                "name1": "John Doe",
                "name2": "John D.",
                "entity_type": "Person",
                "similarity_score": 0.85,
                "match_reasons": ["similar_name"],
            },
        ]

        result = await archivist.get_flagged_duplicates(trace_id="test-trace-001")

        assert len(result) == 1
        assert result[0].uuid1 == "person-001"
        assert result[0].uuid2 == "person-002"
        assert result[0].entity_type == "Person"
        assert result[0].similarity_score == 0.85
        assert result[0].match_reasons == ["similar_name"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_without_neo4j(self) -> None:
        """Should return empty list when Neo4j client not configured."""
        archivist = Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=None,
        )

        result = await archivist.get_flagged_duplicates(trace_id="test-trace-002")

        assert result == []


class TestResolveFlaggedDuplicate:
    """Test suite for resolving flagged duplicates (#35)."""

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_query = AsyncMock()
        return mock

    @pytest.fixture
    def archivist(self, mock_neo4j: Mock) -> Archivist:
        """Create an Archivist instance with mocked Neo4j client."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_merge_flagged_duplicate(
        self, archivist: Archivist, mock_neo4j: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should merge entities when merge=True."""
        mock_neo4j.execute_query.return_value = [{"entity_type": "Person"}]
        mock_merge = AsyncMock(return_value=True)
        monkeypatch.setattr("klabautermann.agents.archivist.merge_entities", mock_merge)

        result = await archivist.resolve_flagged_duplicate(
            uuid1="person-001",
            uuid2="person-002",
            merge=True,
            trace_id="test-trace-001",
        )

        assert result is True
        mock_merge.assert_called_once_with(
            mock_neo4j,
            keep_uuid="person-001",
            remove_uuid="person-002",
            entity_type="Person",
            trace_id="test-trace-001",
        )

    @pytest.mark.asyncio
    async def test_dismiss_flagged_duplicate(self, archivist: Archivist, mock_neo4j: Mock) -> None:
        """Should mark as reviewed when merge=False."""
        mock_neo4j.execute_query.return_value = [{"updated": 1}]

        result = await archivist.resolve_flagged_duplicate(
            uuid1="person-001",
            uuid2="person-002",
            merge=False,
            trace_id="test-trace-002",
        )

        assert result is True
        # Should have set reviewed=true
        call_args = mock_neo4j.execute_query.call_args
        assert "reviewed = true" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_false_without_neo4j(self) -> None:
        """Should return False when Neo4j client not configured."""
        archivist = Archivist(
            name="archivist",
            config={},
            thread_manager=None,
            neo4j_client=None,
        )

        result = await archivist.resolve_flagged_duplicate(
            uuid1="person-001",
            uuid2="person-002",
            merge=True,
            trace_id="test-trace-003",
        )

        assert result is False


class TestProcessArchivalQueueWithDeduplication:
    """Test suite for archival queue with deduplication integration (#35, #191)."""

    @pytest.fixture
    def mock_thread_manager(self) -> Mock:
        """Create a mock ThreadManager."""
        mock = Mock()
        mock.get_inactive_threads = AsyncMock()
        mock.mark_archiving = AsyncMock(return_value=True)
        mock.get_context_window = AsyncMock()
        mock.mark_archived = AsyncMock(return_value=True)
        mock.reactivate_thread = AsyncMock()
        mock.prune_thread_messages = AsyncMock(return_value=5)
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient with AsyncMock methods."""
        mock = Mock()
        mock.execute_write = AsyncMock(return_value=[{"uuid": "note-uuid-001", "title": "Summary"}])
        mock.execute_query = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def mock_summarize(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        """Mock the summarize_thread function."""
        mock = AsyncMock()
        mock.return_value = ThreadSummary(
            summary="Test summary",
            topics=[],
            action_items=[],
            new_facts=[],
            conflicts=[],
            participants=[],
            sentiment="neutral",
        )
        monkeypatch.setattr(
            "klabautermann.agents.archivist.summarize_thread",
            mock,
        )
        return mock

    @pytest.fixture
    def archivist(self, mock_thread_manager: Mock, mock_neo4j: Mock) -> Archivist:
        """Create an Archivist instance with mocked dependencies."""
        return Archivist(
            name="archivist",
            config={},
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_runs_deduplication_after_archival(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        mock_summarize: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should run deduplication after archiving threads."""
        mock_thread_manager.get_inactive_threads.return_value = ["thread-uuid-001"]
        mock_thread_manager.get_context_window.return_value = ThreadContext(
            thread_uuid="thread-uuid-001",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Test"}],
        )

        mock_dedup = AsyncMock(
            return_value={"auto_merged": 2, "flagged_for_review": 1, "ignored": 0}
        )
        monkeypatch.setattr(archivist, "detect_and_merge_duplicates", mock_dedup)

        await archivist.process_archival_queue(trace_id="test-trace-001")

        mock_dedup.assert_called_once_with("test-trace-001")

    @pytest.mark.asyncio
    async def test_skips_deduplication_when_no_threads_archived(
        self,
        archivist: Archivist,
        mock_thread_manager: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should skip deduplication when no threads were archived."""
        mock_thread_manager.get_inactive_threads.return_value = []

        mock_dedup = AsyncMock(
            return_value={"auto_merged": 0, "flagged_for_review": 0, "ignored": 0}
        )
        monkeypatch.setattr(archivist, "detect_and_merge_duplicates", mock_dedup)

        await archivist.process_archival_queue(trace_id="test-trace-002")

        mock_dedup.assert_not_called()
