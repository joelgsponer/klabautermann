# Set Up Nautical Logging System

## Metadata
- **ID**: T008
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [LOGGING.md](../../specs/quality/LOGGING.md)
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md) Section 6

## Dependencies
- [ ] T003 - Project directory structure
- [ ] T005 - Pydantic models (for structured log data)

## Context
Klabautermann uses nautical-themed log levels to maintain the personality even in technical output. The logging system must support structured JSON logging for production analysis while remaining human-readable for development.

## Requirements
- [ ] Create `src/klabautermann/core/logger.py` with:

### Nautical Log Levels
- [ ] DEBUG = [WHISPER] - Internal state, raw LLM prompts
- [ ] INFO = [CHART] - Navigational progress
- [ ] SUCCESS = [BEACON] - Successful operations (custom level)
- [ ] WARNING = [SWELL] - Recoverable issues
- [ ] ERROR = [STORM] - Failed actions
- [ ] CRITICAL = [SHIPWRECK] - System-level failures

### Features
- [ ] JSON structured logging for file output
- [ ] Human-readable format for console
- [ ] Trace ID support in log context
- [ ] Agent name in log context
- [ ] Configurable log level via environment
- [ ] Dual handler: console + file (`logs/ship_ledger.jsonl`)

## Acceptance Criteria
- [ ] `logger.info("[CHART] Processing request")` works
- [ ] Log output includes timestamp, level, message
- [ ] JSON logs written to `logs/ship_ledger.jsonl`
- [ ] Console output is colorized by level
- [ ] Trace ID appears in structured output
- [ ] `LOG_LEVEL` environment variable controls verbosity

## Implementation Notes

```python
import logging
import sys
import json
from datetime import datetime
from pathlib import Path

# Custom SUCCESS level (between INFO and WARNING)
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")

class NauticalFormatter(logging.Formatter):
    """Format logs with nautical prefixes."""

    LEVEL_NAMES = {
        logging.DEBUG: "[WHISPER]",
        logging.INFO: "[CHART]",
        SUCCESS: "[BEACON]",
        logging.WARNING: "[SWELL]",
        logging.ERROR: "[STORM]",
        logging.CRITICAL: "[SHIPWRECK]",
    }

    def format(self, record):
        nautical = self.LEVEL_NAMES.get(record.levelno, "[LOG]")
        record.nautical = nautical
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured analysis."""

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "nautical": getattr(record, "nautical", None),
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add extra fields if present
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "agent"):
            log_data["agent"] = record.agent

        return json.dumps(log_data)


def setup_logger(name: str = "klabautermann") -> logging.Logger:
    """Configure and return the application logger."""
    import os

    logger = logging.getLogger(name)
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    # Console handler with nautical formatting
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(NauticalFormatter(
        "%(asctime)s %(nautical)s %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(console)

    # File handler with JSON formatting
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "ship_ledger.jsonl")
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger


# Module-level logger instance
logger = setup_logger()


def log_success(message: str, **kwargs):
    """Log at SUCCESS level."""
    logger.log(SUCCESS, message, **kwargs)
```

Usage:
```python
from klabautermann.core.logger import logger, log_success

logger.info("[CHART] Processing user request", extra={"trace_id": trace_id})
log_success("[BEACON] Entity extraction complete")
logger.error("[STORM] Neo4j connection failed")
```
