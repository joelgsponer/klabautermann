# APScheduler Integration

## Metadata
- **ID**: T047
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 8 (Deployment Configuration)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)

## Dependencies
- [x] T040 - Archivist Agent Skeleton
- [x] T046 - Scribe Agent Implementation

## Context
Both the Archivist and Scribe operate on schedules: Archivist scans for inactive threads every 15 minutes, Scribe generates reflections at midnight. APScheduler provides robust job scheduling with persistence, ensuring jobs run even if the app restarts. This task integrates APScheduler into the main application.

## Requirements
- [ ] Create `src/klabautermann/utils/scheduler.py`:

### Scheduler Setup
- [ ] Configure AsyncIOScheduler for async compatibility
- [ ] Use SQLite or memory job store (configurable)
- [ ] Configure timezone (UTC default)
- [ ] Graceful shutdown handling

### Scheduled Jobs
- [ ] Archivist scan: every 15 minutes
  - `archivist.process_archival_queue()`
  - Coalescing enabled (skip if previous still running)

- [ ] Scribe reflection: daily at midnight
  - `scribe.generate_daily_reflection()`
  - Misfire grace time: 1 hour

### Job Registration
- [ ] `register_scheduled_jobs(scheduler, agents: dict) -> None`
  - Register all agent jobs
  - Accept agents dict from main.py

### Integration with Main
- [ ] Export scheduler instance
- [ ] Start scheduler in main.py after agents initialized
- [ ] Shutdown scheduler on SIGTERM/SIGINT

## Acceptance Criteria
- [ ] Scheduler starts with application
- [ ] Archivist runs every 15 minutes
- [ ] Scribe runs at midnight UTC
- [ ] Jobs coalesce (no duplicate runs)
- [ ] Scheduler shuts down gracefully
- [ ] Jobs logged when triggered
- [ ] Unit tests for job registration

## Implementation Notes

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
import logging

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure APScheduler instance."""
    jobstores = {
        'default': MemoryJobStore()
    }
    executors = {
        'default': AsyncIOExecutor()
    }
    job_defaults = {
        'coalesce': True,  # Combine missed runs into one
        'max_instances': 1,  # Only one instance at a time
        'misfire_grace_time': 3600  # 1 hour grace for missed jobs
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone='UTC'
    )

    return scheduler


def register_scheduled_jobs(
    scheduler: AsyncIOScheduler,
    agents: dict
) -> None:
    """Register all scheduled agent jobs."""

    # Archivist: scan every 15 minutes
    if 'archivist' in agents:
        scheduler.add_job(
            agents['archivist'].process_archival_queue,
            trigger=IntervalTrigger(minutes=15),
            id='archivist_scan',
            name='Archivist Thread Scan',
            replace_existing=True
        )
        logger.info("[CHART] Registered Archivist scan job (every 15 min)")

    # Scribe: daily at midnight
    if 'scribe' in agents:
        scheduler.add_job(
            agents['scribe'].generate_daily_reflection,
            trigger=CronTrigger(hour=0, minute=0),
            id='scribe_reflection',
            name='Scribe Daily Reflection',
            replace_existing=True
        )
        logger.info("[CHART] Registered Scribe reflection job (daily midnight)")


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Start the scheduler."""
    scheduler.start()
    logger.info("[BEACON] Scheduler started")


async def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Gracefully shutdown the scheduler."""
    scheduler.shutdown(wait=True)
    logger.info("[BEACON] Scheduler shutdown complete")
```

### Integration in main.py
```python
from klabautermann.utils.scheduler import (
    create_scheduler,
    register_scheduled_jobs,
    start_scheduler,
    shutdown_scheduler
)

async def main():
    # ... initialize agents ...

    # Create and start scheduler
    scheduler = create_scheduler()
    register_scheduled_jobs(scheduler, agents)
    await start_scheduler(scheduler)

    try:
        # ... run CLI or message loop ...
    finally:
        await shutdown_scheduler(scheduler)
```

### Configuration (config/scheduler.yaml)
```yaml
archivist:
  enabled: true
  interval_minutes: 15

scribe:
  enabled: true
  hour: 0
  minute: 0

timezone: UTC
job_store: memory  # or 'sqlite' for persistence
```

### Persistent Job Store (Optional)
For production, use SQLite to survive restarts:
```python
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')
}
```
