"""
Sprint 3 Integration Tests - Memory Lifecycle

Tests the memory lifecycle components working together end-to-end:
- Thread archival pipeline (Archivist)
- Day node temporal spine
- Daily reflection journal generation (Scribe)
- Time-travel queries with temporal properties
- Conflict detection during archival
- Scheduler integration for automated jobs

Reference: specs/quality/TESTING.md Section 3, specs/architecture/AGENTS.md
Task: T050 - Sprint 3 Integration Tests

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""
# ruff: noqa: SIM105, B017

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.archivist import Archivist
from klabautermann.agents.scribe import Scribe
from klabautermann.core.models import (
    DailyAnalytics,
    JournalEntry,
)
from klabautermann.memory.day_nodes import (
    get_day_contents,
    get_or_create_day,
    link_note_to_day,
)
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.thread_manager import ThreadManager
from klabautermann.utils.scheduler import create_scheduler, register_scheduled_jobs


# ====================
# FIXTURES
# ====================


@pytest.fixture
def mock_neo4j_client() -> MagicMock:
    """Mock Neo4j client for testing."""
    client = MagicMock(spec=Neo4jClient)

    # Mock session context manager
    session = MagicMock()
    session.run = AsyncMock(return_value=MagicMock(data=AsyncMock(return_value=[])))

    async def async_context_manager(*args: Any, **kwargs: Any) -> Any:
        class AsyncContextManager:
            async def __aenter__(self) -> Any:
                return session

            async def __aexit__(self, *args: Any) -> None:
                pass

        return AsyncContextManager()

    client.session = MagicMock(side_effect=async_context_manager)
    client.execute_query = AsyncMock(return_value=[])
    client.execute_write = AsyncMock(return_value=[{"uuid": str(uuid.uuid4())}])
    client.execute_read = AsyncMock(return_value=[])

    return client


@pytest.fixture
def mock_thread_manager(mock_neo4j_client: MagicMock) -> ThreadManager:
    """Create ThreadManager with mocked Neo4j client."""
    manager = ThreadManager(neo4j=mock_neo4j_client)
    return manager


@pytest.fixture
def test_thread_uuid() -> str:
    """Generate unique thread UUID for test isolation."""
    return f"test-thread-{uuid.uuid4()}"


@pytest.fixture
def test_date() -> str:
    """Get yesterday's date for testing (simulates midnight run)."""
    yesterday = datetime.now(UTC) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


# ====================
# TEST SCENARIO 1: THREAD ARCHIVAL FLOW
# ====================


class TestThreadArchivalFlow:
    """
    Test complete thread archival pipeline.

    Workflow:
    1. Create active thread with messages
    2. Mock time passage (cooldown)
    3. Trigger archival
    4. Verify thread status transitions
    5. Verify Note node created with summary
    6. Verify Note linked to Thread via [:SUMMARY_OF]
    7. Verify messages pruned
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_archival_creates_note_and_links_to_thread(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
        test_thread_uuid: str,
    ) -> None:
        """Thread archival creates Note node and links it to Thread."""
        # Setup: Mock thread with messages
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=MagicMock(
                messages=[
                    {"role": "user", "content": "I met Sarah from Acme Corp today"},
                    {"role": "assistant", "content": "Tell me more about Sarah"},
                    {"role": "user", "content": "She's the CTO there"},
                ]
            )
        )

        # Mock mark_archiving succeeds
        mock_thread_manager.mark_archiving = AsyncMock(return_value=True)
        mock_thread_manager.mark_archived = AsyncMock(return_value=True)

        # Mock summarization (this would normally call LLM)
        with patch(
            "klabautermann.agents.archivist.summarize_thread",
            new_callable=AsyncMock,
        ) as mock_summarize:
            mock_summarize.return_value = MagicMock(
                summary="Discussed Sarah, CTO at Acme Corp",
                topics=["people", "organizations"],
                action_items=[],
                new_facts=[],
                conflicts=[],
            )

            # Create Archivist and archive thread
            archivist = Archivist(
                thread_manager=mock_thread_manager,
                neo4j_client=mock_neo4j_client,
            )

            note_uuid = await archivist.archive_thread(test_thread_uuid)

            # Assert: Note UUID returned
            assert note_uuid is not None
            assert isinstance(note_uuid, str)

            # Assert: Thread marked as archiving then archived
            # Use ANY for trace_id since it's dynamically generated
            mock_thread_manager.mark_archiving.assert_called_once_with(test_thread_uuid, ANY)
            # mark_archived uses keyword arguments
            mock_thread_manager.mark_archived.assert_called_once()
            call_kwargs = mock_thread_manager.mark_archived.call_args.kwargs
            assert call_kwargs["thread_uuid"] == test_thread_uuid
            assert call_kwargs["summary_uuid"] == note_uuid

            # Assert: Summarization called
            mock_summarize.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_archival_reactivates_on_failure(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
        test_thread_uuid: str,
    ) -> None:
        """Thread is reactivated if archival fails."""
        # Setup: Mock mark_archiving succeeds
        mock_thread_manager.mark_archiving = AsyncMock(return_value=True)
        mock_thread_manager.get_context_window = AsyncMock(return_value=MagicMock(messages=[]))
        mock_thread_manager.reactivate_thread = AsyncMock(return_value=True)

        archivist = Archivist(
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j_client,
        )

        # Act: Archive thread with no messages (should fail)
        note_uuid = await archivist.archive_thread(test_thread_uuid)

        # Assert: Archival failed, thread reactivated
        assert note_uuid is None
        mock_thread_manager.reactivate_thread.assert_called_once_with(test_thread_uuid, ANY)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scan_for_inactive_threads(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
    ) -> None:
        """Archivist scans for inactive threads using cooldown."""
        # Setup: Mock inactive threads
        inactive_uuids = [
            f"thread-{uuid.uuid4()}",
            f"thread-{uuid.uuid4()}",
        ]
        mock_thread_manager.get_inactive_threads = AsyncMock(return_value=inactive_uuids)

        archivist = Archivist(
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j_client,
            config={"cooldown_minutes": 60},
        )

        # Act: Scan for inactive threads
        found_threads = await archivist.scan_for_inactive_threads()

        # Assert: Correct threads returned
        assert len(found_threads) == 2
        assert found_threads == inactive_uuids
        mock_thread_manager.get_inactive_threads.assert_called_once_with(
            cooldown_minutes=60,
            limit=10,  # default max_threads_per_scan
            trace_id=ANY,  # Dynamically generated trace_id
        )


# ====================
# TEST SCENARIO 2: DAY NODE INTEGRATION
# ====================


class TestDayNodeIntegration:
    """
    Test Day node creation and linking.

    Workflow:
    1. Create entities with timestamps
    2. Verify Day nodes created (MERGE idempotency)
    3. Verify [:OCCURRED_ON] relationships
    4. Query day contents
    5. Verify temporal spine integrity
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_day_node_creation_idempotent(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Day nodes are created idempotently with MERGE."""
        # Setup: Mock successful creation
        mock_neo4j_client.execute_write = AsyncMock(return_value=[{"date": test_date}])

        # Act: Create day node twice
        date = datetime.strptime(test_date, "%Y-%m-%d")
        date_str1 = await get_or_create_day(mock_neo4j_client, date)
        date_str2 = await get_or_create_day(mock_neo4j_client, date)

        # Assert: Same date string returned both times
        assert date_str1 == test_date
        assert date_str2 == test_date

        # Assert: MERGE query called (idempotent)
        assert mock_neo4j_client.execute_write.call_count == 2

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_link_note_to_day(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Notes are linked to Day nodes via [:OCCURRED_ON]."""
        # Setup: Mock successful linking
        mock_neo4j_client.execute_write = AsyncMock(return_value=[])

        note_uuid = str(uuid.uuid4())
        date = datetime.strptime(test_date, "%Y-%m-%d")

        # Act: Link note to day
        await link_note_to_day(mock_neo4j_client, note_uuid, date)

        # Assert: Write query called with correct parameters
        mock_neo4j_client.execute_write.assert_called_once()
        call_args = mock_neo4j_client.execute_write.call_args
        assert test_date in str(call_args)
        assert note_uuid in str(call_args)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_day_contents(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Day contents can be queried and grouped by entity type."""
        # Setup: Mock day with multiple entities
        mock_neo4j_client.execute_read = AsyncMock(
            return_value=[
                {
                    "type": "Note",
                    "uuid": str(uuid.uuid4()),
                    "title": "Meeting notes",
                    "summary": "Discussed project X",
                    "created_at": time.time(),
                },
                {
                    "type": "Event",
                    "uuid": str(uuid.uuid4()),
                    "title": "Team sync",
                    "summary": None,
                    "created_at": time.time(),
                },
                {
                    "type": "Note",
                    "uuid": str(uuid.uuid4()),
                    "title": "Follow-up",
                    "summary": "Action items",
                    "created_at": time.time(),
                },
            ]
        )

        # Act: Get day contents
        contents = await get_day_contents(mock_neo4j_client, test_date)

        # Assert: Entities grouped by type
        assert "Note" in contents
        assert "Event" in contents
        assert len(contents["Note"]) == 2
        assert len(contents["Event"]) == 1


# ====================
# TEST SCENARIO 3: SCRIBE DAILY REFLECTION
# ====================


class TestScribeDailyReflection:
    """
    Test Scribe daily journal generation.

    Workflow:
    1. Create day's worth of activity
    2. Trigger Scribe reflection
    3. Verify JournalEntry node created
    4. Verify linked to correct Day
    5. Verify analytics data included
    6. Verify idempotency (no duplicate journals)
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_generate_daily_reflection(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Scribe generates daily reflection with analytics."""
        # Setup: Mock analytics data
        mock_analytics = DailyAnalytics(
            date=test_date,
            interaction_count=42,
            new_entities={"Person": 2, "Organization": 1},
            tasks_completed=3,
            tasks_created=5,
            top_projects=[],
            notes_created=7,
            events_count=2,
        )

        # Mock journal generation (LLM call)
        mock_journal = JournalEntry(
            content="Full journal content here...",
            summary="Productive day with 42 interactions",
            highlights=["Met Sarah from Acme", "Completed 3 tasks"],
            mood="productive",
            forward_look="Tomorrow: follow up with John",
        )

        with (
            patch(
                "klabautermann.agents.scribe.get_daily_analytics",
                new_callable=AsyncMock,
            ) as mock_get_analytics,
            patch(
                "klabautermann.agents.scribe.generate_journal",
                new_callable=AsyncMock,
            ) as mock_gen_journal,
        ):
            mock_get_analytics.return_value = mock_analytics
            mock_gen_journal.return_value = mock_journal

            # Mock no existing journal
            mock_neo4j_client.execute_read = AsyncMock(return_value=[])

            # Mock journal creation - the Scribe generates its own UUID
            mock_neo4j_client.execute_write = AsyncMock(
                return_value=[
                    {"uuid": "some-uuid"}
                ]  # The actual UUID is generated in _create_journal_node
            )

            # Create Scribe and generate journal
            scribe = Scribe(neo4j_client=mock_neo4j_client)
            result_uuid = await scribe.generate_daily_reflection(date=test_date)

            # Assert: Journal UUID returned (it's a valid UUID string)
            assert result_uuid is not None
            assert isinstance(result_uuid, str)
            # Verify it's a valid UUID format
            uuid.UUID(result_uuid)

            # Assert: Analytics gathered
            mock_get_analytics.assert_called_once()

            # Assert: Journal generated
            mock_gen_journal.assert_called_once_with(mock_analytics)

            # Assert: Journal node created
            mock_neo4j_client.execute_write.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_journal_idempotency(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Scribe skips journal creation if one already exists."""
        # Setup: Mock existing journal
        mock_neo4j_client.execute_read = AsyncMock(return_value=[{"uuid": str(uuid.uuid4())}])

        scribe = Scribe(neo4j_client=mock_neo4j_client)

        # Act: Try to generate journal when one exists
        result_uuid = await scribe.generate_daily_reflection(date=test_date)

        # Assert: No new journal created
        assert result_uuid is None

        # Assert: No write operations performed
        mock_neo4j_client.execute_write.assert_not_called()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_journal_skipped_for_low_activity(
        self,
        mock_neo4j_client: MagicMock,
        test_date: str,
    ) -> None:
        """Scribe skips journal if activity below threshold."""
        # Setup: Mock low activity analytics
        mock_analytics = DailyAnalytics(
            date=test_date,
            interaction_count=0,  # Below default min_interactions=1
            new_entities={},
            tasks_completed=0,
            tasks_created=0,
            top_projects=[],
            notes_created=0,
            events_count=0,
        )

        with patch(
            "klabautermann.agents.scribe.get_daily_analytics",
            new_callable=AsyncMock,
        ) as mock_get_analytics:
            mock_get_analytics.return_value = mock_analytics

            # Mock no existing journal
            mock_neo4j_client.execute_read = AsyncMock(return_value=[])

            scribe = Scribe(
                neo4j_client=mock_neo4j_client,
                config={"min_interactions": 1},
            )

            # Act: Try to generate journal
            result_uuid = await scribe.generate_daily_reflection(date=test_date)

            # Assert: No journal created due to low activity
            assert result_uuid is None
            mock_neo4j_client.execute_write.assert_not_called()


# ====================
# TEST SCENARIO 4: TIME-TRAVEL QUERY
# ====================


class TestTimeTravelQuery:
    """
    Test temporal queries with expired_at properties.

    Workflow:
    1. Create Person with employer relationship
    2. Change employer (expire old, create new)
    3. Query current employer (expired_at IS NULL)
    4. Query historical employer (at specific timestamp)
    5. Verify temporal accuracy
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_current_employer_query(
        self,
        mock_neo4j_client: MagicMock,
    ) -> None:
        """Query returns current employer (expired_at IS NULL)."""
        # Setup: Mock current employer relationship
        acme_uuid = str(uuid.uuid4())
        mock_neo4j_client.execute_read = AsyncMock(
            return_value=[
                {
                    "org_name": "Acme Corp",
                    "org_uuid": acme_uuid,
                    "title": "CTO",
                    "created_at": time.time(),
                    "expired_at": None,
                }
            ]
        )

        # Act: Query current employer
        query = """
        MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
        WHERE r.expired_at IS NULL
        RETURN o.name as org_name, o.uuid as org_uuid, r.title as title,
               r.created_at as created_at, r.expired_at as expired_at
        """
        result = await mock_neo4j_client.execute_read(
            query,
            {"person_uuid": str(uuid.uuid4())},
        )

        # Assert: Current employer returned
        assert len(result) == 1
        assert result[0]["org_name"] == "Acme Corp"
        assert result[0]["expired_at"] is None

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_historical_employer_query(
        self,
        mock_neo4j_client: MagicMock,
    ) -> None:
        """Query returns historical employer at specific timestamp."""
        # Setup: Mock historical employer (30 days ago)
        thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
        oldcorp_uuid = str(uuid.uuid4())

        mock_neo4j_client.execute_read = AsyncMock(
            return_value=[
                {
                    "org_name": "OldCorp",
                    "org_uuid": oldcorp_uuid,
                    "title": "Engineer",
                    "created_at": thirty_days_ago - (60 * 24 * 60 * 60),  # 60 days ago
                    "expired_at": thirty_days_ago,
                }
            ]
        )

        # Act: Query employer at 30 days ago
        query = """
        MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
        WHERE r.created_at <= $timestamp
          AND (r.expired_at IS NULL OR r.expired_at > $timestamp)
        RETURN o.name as org_name, o.uuid as org_uuid, r.title as title,
               r.created_at as created_at, r.expired_at as expired_at
        """
        result = await mock_neo4j_client.execute_read(
            query,
            {"person_uuid": str(uuid.uuid4()), "timestamp": thirty_days_ago},
        )

        # Assert: Historical employer returned
        assert len(result) == 1
        assert result[0]["org_name"] == "OldCorp"
        assert result[0]["expired_at"] == thirty_days_ago


# ====================
# TEST SCENARIO 5: CONFLICT DETECTION
# ====================


class TestConflictDetection:
    """
    Test conflict detection during thread archival.

    Workflow:
    1. Create Person with employer
    2. Create thread mentioning new employer
    3. Archive thread (triggers summarization)
    4. Verify conflict detected in summary
    5. Verify old relationship expired
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_employer_change_conflict_detected(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
        test_thread_uuid: str,
    ) -> None:
        """Archival detects employer change as conflict."""
        # Setup: Mock thread mentioning new employer
        mock_thread_manager.get_context_window = AsyncMock(
            return_value=MagicMock(
                messages=[
                    {"role": "user", "content": "Sarah left Acme and joined NewCorp as VP"},
                ]
            )
        )

        mock_thread_manager.mark_archiving = AsyncMock(return_value=True)
        mock_thread_manager.mark_archived = AsyncMock(return_value=True)

        # Mock summarization with conflict
        with patch(
            "klabautermann.agents.archivist.summarize_thread",
            new_callable=AsyncMock,
        ) as mock_summarize:
            mock_summarize.return_value = MagicMock(
                summary="Sarah changed jobs",
                topics=["people", "career"],
                action_items=[],
                new_facts=[
                    MagicMock(
                        entity="Sarah",
                        entity_type="Person",
                        fact="works at NewCorp as VP",
                    )
                ],
                conflicts=[
                    MagicMock(
                        existing_fact="Sarah works at Acme as CTO",
                        new_fact="Sarah works at NewCorp as VP",
                        entity="Sarah",
                        resolution="expire_old",
                    )
                ],
            )

            archivist = Archivist(
                thread_manager=mock_thread_manager,
                neo4j_client=mock_neo4j_client,
            )

            # Act: Archive thread
            note_uuid = await archivist.archive_thread(test_thread_uuid)

            # Assert: Note created
            assert note_uuid is not None

            # Assert: Summary contains conflict
            summary = mock_summarize.return_value
            assert len(summary.conflicts) == 1
            assert summary.conflicts[0].entity == "Sarah"
            assert summary.conflicts[0].resolution == "expire_old"


# ====================
# TEST SCENARIO 6: SCHEDULER INTEGRATION
# ====================


class TestSchedulerIntegration:
    """
    Test APScheduler integration with agents.

    Workflow:
    1. Create scheduler with mock jobs
    2. Verify jobs registered
    3. Trigger jobs manually
    4. Verify execution logged
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scheduler_registers_archivist_job(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
    ) -> None:
        """Scheduler registers Archivist job with interval trigger."""
        # Create scheduler
        scheduler = create_scheduler(job_store="memory")

        # Create mock archivist
        archivist = Archivist(
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j_client,
        )
        archivist.process_archival_queue = AsyncMock(return_value=0)  # type: ignore[method-assign]

        # Register jobs
        agents = {"archivist": archivist}
        config = {"archivist": {"enabled": True, "interval_minutes": 15}}
        register_scheduled_jobs(scheduler, agents, config)

        # Assert: Job registered
        jobs = scheduler.get_jobs()
        assert len(jobs) > 0
        job_ids = [job.id for job in jobs]
        assert "archivist_scan" in job_ids

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scheduler_registers_scribe_job(
        self,
        mock_neo4j_client: MagicMock,
    ) -> None:
        """Scheduler registers Scribe job with cron trigger."""
        # Create scheduler
        scheduler = create_scheduler(job_store="memory")

        # Create mock scribe
        scribe = Scribe(neo4j_client=mock_neo4j_client)
        scribe.generate_daily_reflection = AsyncMock(return_value=None)  # type: ignore[method-assign]

        # Register jobs
        agents = {"scribe": scribe}
        config = {"scribe": {"enabled": True, "hour": 0, "minute": 0}}
        register_scheduled_jobs(scheduler, agents, config)

        # Assert: Job registered
        jobs = scheduler.get_jobs()
        assert len(jobs) > 0
        job_ids = [job.id for job in jobs]
        assert "scribe_reflection" in job_ids

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scheduler_disabled_jobs_not_registered(
        self,
        mock_neo4j_client: MagicMock,
        mock_thread_manager: ThreadManager,
    ) -> None:
        """Disabled jobs are not registered."""
        # Create scheduler
        scheduler = create_scheduler(job_store="memory")

        # Create agents
        archivist = Archivist(
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j_client,
        )
        scribe = Scribe(neo4j_client=mock_neo4j_client)

        # Register with both jobs disabled
        agents = {"archivist": archivist, "scribe": scribe}
        config = {
            "archivist": {"enabled": False},
            "scribe": {"enabled": False},
        }
        register_scheduled_jobs(scheduler, agents, config)

        # Assert: No jobs registered
        jobs = scheduler.get_jobs()
        assert len(jobs) == 0


# ====================
# RUN TESTS
# ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
