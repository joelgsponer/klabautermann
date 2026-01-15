"""
APScheduler Integration for Klabautermann.

Provides scheduled job execution for agents that need to run on a periodic basis.
The Archivist scans for inactive threads every 15 minutes, and the Scribe generates
daily reflections at midnight.

Features:
- AsyncIOScheduler for async/await compatibility
- Configurable job stores (memory or SQLite)
- Coalescing to prevent duplicate runs
- Graceful shutdown handling
- UTC timezone by default

Reference: specs/architecture/AGENTS.md Section 8 (Deployment Configuration)
Task: T047 - APScheduler Integration
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.agents.base_agent import BaseAgent


def create_scheduler(
    job_store: str = "memory",
    timezone: str = "UTC",
    sqlite_path: str = "jobs.sqlite",
) -> AsyncIOScheduler:
    """
    Create and configure APScheduler instance.

    Args:
        job_store: Job store type ("memory" or "sqlite")
        timezone: Scheduler timezone (default: UTC)
        sqlite_path: Path to SQLite database if using SQLite job store

    Returns:
        Configured AsyncIOScheduler instance

    Example:
        >>> scheduler = create_scheduler()
        >>> scheduler = create_scheduler(job_store="sqlite", sqlite_path="data/jobs.db")
    """
    # Configure job store
    if job_store == "sqlite":
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{sqlite_path}")}
        logger.info(f"[CHART] Using SQLite job store: {sqlite_path}")
    else:
        jobstores = {"default": MemoryJobStore()}
        logger.debug("[WHISPER] Using memory job store")

    # Configure executor
    executors = {"default": AsyncIOExecutor()}

    # Job defaults
    job_defaults = {
        "coalesce": True,  # Combine missed runs into one
        "max_instances": 1,  # Only one instance of each job at a time
        "misfire_grace_time": 3600,  # 1 hour grace period for missed jobs
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone=timezone,
    )

    logger.info(f"[CHART] Scheduler created with timezone: {timezone}")

    return scheduler


def register_scheduled_jobs(
    scheduler: AsyncIOScheduler,
    agents: dict[str, BaseAgent],
    config: dict[str, Any] | None = None,
) -> None:
    """
    Register all scheduled agent jobs.

    Args:
        scheduler: AsyncIOScheduler instance
        agents: Dictionary of agent instances (keyed by agent name)
        config: Optional scheduler configuration (overrides defaults)

    Jobs registered:
    - Archivist: Scan for inactive threads every 15 minutes
    - Scribe: Generate daily reflection at midnight UTC

    Example:
        >>> scheduler = create_scheduler()
        >>> register_scheduled_jobs(scheduler, agents)
        >>> # With custom config:
        >>> config = {"archivist": {"enabled": True, "interval_minutes": 30}}
        >>> register_scheduled_jobs(scheduler, agents, config)
    """
    trace_id = str(uuid.uuid4())
    config = config or {}

    # ========================================================================
    # Archivist: Scan for inactive threads
    # ========================================================================
    archivist_config = config.get("archivist", {})
    archivist_enabled = archivist_config.get("enabled", True)
    archivist_interval = archivist_config.get("interval_minutes", 15)

    if archivist_enabled and "archivist" in agents:
        archivist = agents["archivist"]

        # Wrap the job to pass trace_id
        async def archivist_job() -> None:
            job_trace_id = str(uuid.uuid4())
            logger.info(
                "[BEACON] Scheduled Archivist scan triggered",
                extra={"trace_id": job_trace_id, "agent_name": "archivist"},
            )
            await archivist.process_archival_queue(trace_id=job_trace_id)  # type: ignore[attr-defined]

        scheduler.add_job(
            archivist_job,
            trigger=IntervalTrigger(minutes=archivist_interval),
            id="archivist_scan",
            name="Archivist Thread Scan",
            replace_existing=True,
        )
        logger.info(
            f"[CHART] Registered Archivist scan job (every {archivist_interval} min)",
            extra={"trace_id": trace_id},
        )
    elif not archivist_enabled:
        logger.info(
            "[CHART] Archivist scan job disabled by config",
            extra={"trace_id": trace_id},
        )
    else:
        logger.warning(
            "[SWELL] Archivist agent not available, skipping scheduled job",
            extra={"trace_id": trace_id},
        )

    # ========================================================================
    # Scribe: Generate daily reflection
    # ========================================================================
    scribe_config = config.get("scribe", {})
    scribe_enabled = scribe_config.get("enabled", True)
    scribe_hour = scribe_config.get("hour", 0)
    scribe_minute = scribe_config.get("minute", 0)

    if scribe_enabled and "scribe" in agents:
        scribe = agents["scribe"]

        # Wrap the job to pass trace_id
        async def scribe_job() -> None:
            job_trace_id = str(uuid.uuid4())
            logger.info(
                "[BEACON] Scheduled Scribe reflection triggered",
                extra={"trace_id": job_trace_id, "agent_name": "scribe"},
            )
            await scribe.generate_daily_reflection(trace_id=job_trace_id)  # type: ignore[attr-defined]

        scheduler.add_job(
            scribe_job,
            trigger=CronTrigger(hour=scribe_hour, minute=scribe_minute),
            id="scribe_reflection",
            name="Scribe Daily Reflection",
            replace_existing=True,
        )
        logger.info(
            f"[CHART] Registered Scribe reflection job (daily {scribe_hour:02d}:{scribe_minute:02d})",
            extra={"trace_id": trace_id},
        )
    elif not scribe_enabled:
        logger.info(
            "[CHART] Scribe reflection job disabled by config",
            extra={"trace_id": trace_id},
        )
    else:
        logger.warning(
            "[SWELL] Scribe agent not available, skipping scheduled job",
            extra={"trace_id": trace_id},
        )


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Start the scheduler.

    This must be called after all jobs are registered but before the main
    event loop blocks.

    Args:
        scheduler: AsyncIOScheduler instance to start

    Example:
        >>> scheduler = create_scheduler()
        >>> register_scheduled_jobs(scheduler, agents)
        >>> await start_scheduler(scheduler)
    """
    scheduler.start()
    logger.info("[BEACON] Scheduler started")


async def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Gracefully shutdown the scheduler.

    Waits for all running jobs to complete before shutting down.

    Args:
        scheduler: AsyncIOScheduler instance to shut down

    Example:
        >>> await shutdown_scheduler(scheduler)
    """
    scheduler.shutdown(wait=True)
    logger.info("[BEACON] Scheduler shutdown complete")


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "create_scheduler",
    "register_scheduled_jobs",
    "start_scheduler",
    "shutdown_scheduler",
]
