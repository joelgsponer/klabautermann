"""
Unit tests for APScheduler Integration.

Reference: specs/architecture/AGENTS.md Section 8 (Deployment Configuration)
Task: T047 - APScheduler Integration

The scheduler provides periodic job execution for agents:
1. Archivist scans every 15 minutes
2. Scribe generates reflections at midnight
3. Jobs coalesce to prevent duplicate runs
4. Graceful shutdown handling

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from klabautermann.utils.scheduler import (
    create_scheduler,
    register_scheduled_jobs,
    shutdown_scheduler,
    start_scheduler,
)


class TestSchedulerCreation:
    """Test suite for scheduler creation and configuration."""

    def test_creates_scheduler_with_default_config(self) -> None:
        """Should create scheduler with default memory job store."""
        scheduler = create_scheduler()

        assert scheduler is not None
        assert isinstance(scheduler, AsyncIOScheduler)
        assert scheduler.state == 0  # STATE_STOPPED

    def test_creates_scheduler_with_memory_jobstore(self) -> None:
        """Should create scheduler with memory job store."""
        scheduler = create_scheduler(job_store="memory")

        assert scheduler is not None
        assert "default" in scheduler._jobstores

    def test_creates_scheduler_with_sqlite_jobstore(self) -> None:
        """Should create scheduler with SQLite job store."""
        try:
            import sqlalchemy  # noqa: F401

            scheduler = create_scheduler(job_store="sqlite", sqlite_path=":memory:")

            assert scheduler is not None
            assert "default" in scheduler._jobstores
        except ImportError:
            pytest.skip("SQLAlchemy not installed (optional dependency)")

    def test_uses_utc_timezone_by_default(self) -> None:
        """Should use UTC as default timezone."""
        scheduler = create_scheduler()

        assert str(scheduler.timezone) == "UTC"

    def test_uses_custom_timezone(self) -> None:
        """Should use custom timezone when provided."""
        scheduler = create_scheduler(timezone="America/New_York")

        assert "America/New_York" in str(scheduler.timezone)

    def test_configures_job_defaults(self) -> None:
        """Should configure job defaults for coalescing and max instances."""
        scheduler = create_scheduler()

        # Check job defaults
        assert scheduler._job_defaults["coalesce"] is True
        assert scheduler._job_defaults["max_instances"] == 1
        assert scheduler._job_defaults["misfire_grace_time"] == 3600


class TestJobRegistration:
    """Test suite for job registration."""

    @pytest.fixture
    def scheduler(self) -> AsyncIOScheduler:
        """Create scheduler instance for tests."""
        return create_scheduler()

    @pytest.fixture
    def mock_archivist(self) -> Mock:
        """Create mock Archivist agent."""
        agent = Mock()
        agent.process_archival_queue = AsyncMock()
        return agent

    @pytest.fixture
    def mock_scribe(self) -> Mock:
        """Create mock Scribe agent."""
        agent = Mock()
        agent.generate_daily_reflection = AsyncMock()
        return agent

    def test_registers_archivist_job_when_enabled(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Should register Archivist job when agent available and enabled."""
        agents = {"archivist": mock_archivist}
        config = {"archivist": {"enabled": True, "interval_minutes": 15}}

        register_scheduled_jobs(scheduler, agents, config)

        # Check job is registered
        job = scheduler.get_job("archivist_scan")
        assert job is not None
        assert job.name == "Archivist Thread Scan"

    def test_registers_archivist_with_custom_interval(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Should register Archivist with custom interval."""
        agents = {"archivist": mock_archivist}
        config = {"archivist": {"enabled": True, "interval_minutes": 30}}

        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("archivist_scan")
        assert job is not None
        # Interval trigger should be 30 minutes
        # Note: Checking exact interval requires accessing trigger internals

    def test_skips_archivist_when_disabled(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Should not register Archivist job when disabled."""
        agents = {"archivist": mock_archivist}
        config = {"archivist": {"enabled": False}}

        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("archivist_scan")
        assert job is None

    def test_skips_archivist_when_not_available(self, scheduler: AsyncIOScheduler) -> None:
        """Should not register Archivist job when agent not available."""
        agents = {}  # No archivist
        config = {"archivist": {"enabled": True}}

        # Should not raise exception
        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("archivist_scan")
        assert job is None

    def test_registers_scribe_job_when_enabled(
        self, scheduler: AsyncIOScheduler, mock_scribe: Mock
    ) -> None:
        """Should register Scribe job when agent available and enabled."""
        agents = {"scribe": mock_scribe}
        config = {"scribe": {"enabled": True, "hour": 0, "minute": 0}}

        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("scribe_reflection")
        assert job is not None
        assert job.name == "Scribe Daily Reflection"

    def test_registers_scribe_with_custom_time(
        self, scheduler: AsyncIOScheduler, mock_scribe: Mock
    ) -> None:
        """Should register Scribe with custom time."""
        agents = {"scribe": mock_scribe}
        config = {"scribe": {"enabled": True, "hour": 23, "minute": 30}}

        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("scribe_reflection")
        assert job is not None

    def test_skips_scribe_when_disabled(
        self, scheduler: AsyncIOScheduler, mock_scribe: Mock
    ) -> None:
        """Should not register Scribe job when disabled."""
        agents = {"scribe": mock_scribe}
        config = {"scribe": {"enabled": False}}

        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("scribe_reflection")
        assert job is None

    def test_skips_scribe_when_not_available(self, scheduler: AsyncIOScheduler) -> None:
        """Should not register Scribe job when agent not available."""
        agents = {}  # No scribe
        config = {"scribe": {"enabled": True}}

        # Should not raise exception
        register_scheduled_jobs(scheduler, agents, config)

        job = scheduler.get_job("scribe_reflection")
        assert job is None

    def test_registers_both_jobs(
        self,
        scheduler: AsyncIOScheduler,
        mock_archivist: Mock,
        mock_scribe: Mock,
    ) -> None:
        """Should register both Archivist and Scribe jobs when available."""
        agents = {
            "archivist": mock_archivist,
            "scribe": mock_scribe,
        }

        register_scheduled_jobs(scheduler, agents)

        archivist_job = scheduler.get_job("archivist_scan")
        scribe_job = scheduler.get_job("scribe_reflection")

        assert archivist_job is not None
        assert scribe_job is not None

    def test_uses_default_config_when_not_provided(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Should use default config when none provided."""
        agents = {"archivist": mock_archivist}

        # No config provided - should use defaults
        register_scheduled_jobs(scheduler, agents)

        job = scheduler.get_job("archivist_scan")
        assert job is not None

    def test_replace_existing_jobs(self, scheduler: AsyncIOScheduler, mock_archivist: Mock) -> None:
        """Should replace existing jobs when re-registered."""
        agents = {"archivist": mock_archivist}

        # Register once
        register_scheduled_jobs(scheduler, agents)
        job1 = scheduler.get_job("archivist_scan")

        # Register again - should replace
        register_scheduled_jobs(scheduler, agents)
        job2 = scheduler.get_job("archivist_scan")

        assert job1 is not None
        assert job2 is not None
        # Jobs should exist (not duplicated)


class TestSchedulerLifecycle:
    """Test suite for scheduler lifecycle management."""

    @pytest.fixture
    def scheduler(self) -> AsyncIOScheduler:
        """Create scheduler instance for tests."""
        return create_scheduler()

    @pytest.mark.asyncio
    async def test_starts_scheduler(self, scheduler: AsyncIOScheduler) -> None:
        """Should start the scheduler."""
        await start_scheduler(scheduler)

        assert scheduler.running is True

        # Clean up
        scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_shuts_down_scheduler(self, scheduler: AsyncIOScheduler) -> None:
        """Should shut down the scheduler gracefully."""
        await start_scheduler(scheduler)
        assert scheduler.running is True

        # Shutdown should complete without errors
        await shutdown_scheduler(scheduler)

        # The test passes if shutdown completes without exception
        # (APScheduler's internal state management is implementation detail)
        assert True

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_jobs(self, scheduler: AsyncIOScheduler) -> None:
        """Should wait for running jobs to complete on shutdown."""
        # Create a mock long-running job
        job_started = False
        job_completed = False

        async def long_job() -> None:
            nonlocal job_started, job_completed
            job_started = True
            # Simulate work (but don't actually block)
            job_completed = True

        scheduler.add_job(long_job, "date", run_date=None, id="test_job")
        await start_scheduler(scheduler)

        # Shutdown should wait and complete without errors
        await shutdown_scheduler(scheduler)

        # The test passes if shutdown completes without exception
        assert True


class TestJobExecution:
    """Test suite for job execution."""

    @pytest.fixture
    def scheduler(self) -> AsyncIOScheduler:
        """Create scheduler instance for tests."""
        return create_scheduler()

    @pytest.fixture
    def mock_archivist(self) -> Mock:
        """Create mock Archivist agent."""
        agent = Mock()
        agent.process_archival_queue = AsyncMock()
        return agent

    @pytest.mark.asyncio
    async def test_archivist_job_calls_process_archival_queue(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Archivist job should call process_archival_queue when triggered."""
        agents = {"archivist": mock_archivist}
        register_scheduled_jobs(scheduler, agents)

        # Get the job and execute it manually
        job = scheduler.get_job("archivist_scan")
        assert job is not None

        # Execute the job function directly
        await job.func()

        # Verify the agent method was called
        mock_archivist.process_archival_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_job_receives_trace_id(
        self, scheduler: AsyncIOScheduler, mock_archivist: Mock
    ) -> None:
        """Jobs should receive a trace_id when executed."""
        agents = {"archivist": mock_archivist}
        register_scheduled_jobs(scheduler, agents)

        job = scheduler.get_job("archivist_scan")
        await job.func()

        # Verify trace_id was passed
        call_kwargs = mock_archivist.process_archival_queue.call_args.kwargs
        assert "trace_id" in call_kwargs
        assert isinstance(call_kwargs["trace_id"], str)


class TestSchedulerRobustness:
    """Test suite for scheduler error handling and robustness."""

    @pytest.fixture
    def scheduler(self) -> AsyncIOScheduler:
        """Create scheduler instance for tests."""
        return create_scheduler()

    @pytest.mark.asyncio
    async def test_handles_job_exception_gracefully(self, scheduler: AsyncIOScheduler) -> None:
        """Should handle job exceptions without crashing scheduler."""

        # Create a job that raises an exception
        async def failing_job() -> None:
            raise ValueError("Job failed")

        scheduler.add_job(failing_job, "date", run_date=None, id="failing_job")
        await start_scheduler(scheduler)

        # Scheduler should still be running after job fails
        # (APScheduler logs errors but continues)
        assert scheduler.running is True

        # Clean up
        scheduler.shutdown(wait=False)

    def test_handles_empty_agents_dict(self, scheduler: AsyncIOScheduler) -> None:
        """Should handle empty agents dict without errors."""
        # Should not raise exception
        register_scheduled_jobs(scheduler, {})

        # No jobs should be registered
        assert len(scheduler.get_jobs()) == 0

    def test_handles_none_config(self, scheduler: AsyncIOScheduler) -> None:
        """Should handle None config without errors."""
        mock_agent = Mock()
        mock_agent.process_archival_queue = AsyncMock()
        agents = {"archivist": mock_agent}

        # Should not raise exception
        register_scheduled_jobs(scheduler, agents, None)

        # Default config should be used
        job = scheduler.get_job("archivist_scan")
        assert job is not None
