"""
Nautical logging system for Klabautermann.

Provides themed log levels and structured logging for tracing agent operations.
All log levels are mapped to nautical terminology to maintain the ship spirit personality.

Reference: specs/quality/LOGGING.md
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar


if TYPE_CHECKING:
    from logging import LogRecord


# ===========================================================================
# Custom Log Level: SUCCESS (between INFO and WARNING)
# ===========================================================================

SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")


# ===========================================================================
# Custom Logger Class
# ===========================================================================


class KlabautermannLogger(logging.Logger):
    """Custom logger with nautical-themed convenience methods."""

    def success(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at SUCCESS level (successful operations)."""
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, msg, args, **kwargs)

    # Nautical-themed aliases
    def whisper(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[WHISPER] Debug-level internal state."""
        self.debug(msg, *args, **kwargs)

    def chart(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[CHART] Navigational progress."""
        self.info(msg, *args, **kwargs)

    def beacon(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[BEACON] Successful completions."""
        self.success(msg, *args, **kwargs)

    def swell(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[SWELL] Recoverable issues."""
        self.warning(msg, *args, **kwargs)

    def storm(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[STORM] Failed actions."""
        self.error(msg, *args, **kwargs)

    def shipwreck(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """[SHIPWRECK] Critical failures."""
        self.critical(msg, *args, **kwargs)


# ===========================================================================
# Formatters
# ===========================================================================


class NauticalFormatter(logging.Formatter):
    """Formatter that converts levels to nautical names with optional color."""

    LEVEL_MAP: ClassVar[dict[str, str]] = {
        "DEBUG": "[WHISPER]",
        "INFO": "[CHART]",
        "SUCCESS": "[BEACON]",
        "WARNING": "[SWELL]",
        "ERROR": "[STORM]",
        "CRITICAL": "[SHIPWRECK]",
    }

    # ANSI color codes for terminal output
    COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[90m",  # Gray
        "INFO": "\033[36m",  # Cyan
        "SUCCESS": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
        "RESET": "\033[0m",
    }

    def __init__(self, use_colors: bool = True) -> None:
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record: LogRecord) -> str:
        # Get nautical level name
        nautical_level = self.LEVEL_MAP.get(record.levelname, f"[{record.levelname}]")

        # Build timestamp
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")

        # Get trace_id and agent_name from extra fields (handle None values)
        trace_id = getattr(record, "trace_id", None) or "-"
        agent_name = getattr(record, "agent_name", None) or "-"

        # Apply colors if enabled
        if self.use_colors:
            color = self.COLORS.get(record.levelname, "")
            reset = self.COLORS["RESET"]
            nautical_level = f"{color}{nautical_level}{reset}"

        # Log line layout: timestamp, trace_id, agent, level, message
        base_msg = f"{timestamp} | {trace_id:8} | {agent_name:12} | {nautical_level:12} | {record.getMessage()}"

        # Add exception info if present
        if record.exc_info:
            base_msg += f"\n{self.formatException(record.exc_info)}"

        return base_msg


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured log aggregation."""

    def format(self, record: LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "nautical_level": NauticalFormatter.LEVEL_MAP.get(record.levelname, record.levelname),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add trace context if present
        for key in ("trace_id", "agent_name", "thread_id", "user_id"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # Add performance metrics if present
        for key in ("latency_ms", "tool_name", "operation"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


# ===========================================================================
# Logger Setup
# ===========================================================================

# Store reference to console handler for suppression control
_console_handler: logging.Handler | None = None


def setup_logger(
    name: str = "klabautermann",
    level: str | None = None,
    log_file: Path | None = None,
    json_output: bool = False,
) -> KlabautermannLogger:
    """
    Configure and return the Klabautermann logger.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, etc.). Defaults to LOG_LEVEL env var or INFO.
        log_file: Optional file path for log output
        json_output: Use JSON format for console (for log aggregation)

    Returns:
        Configured KlabautermannLogger instance
    """
    # Register custom logger class
    logging.setLoggerClass(KlabautermannLogger)

    # Create logger
    log: KlabautermannLogger = logging.getLogger(name)  # type: ignore[assignment]

    # Set level from arg, env var, or default
    resolved_level = level or os.getenv("LOG_LEVEL") or "INFO"
    log.setLevel(getattr(logging, resolved_level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates
    log.handlers.clear()

    # Prevent propagation to root logger
    log.propagate = False

    # Console handler (use stdout so patch_stdout() can coordinate with CLI input)
    global _console_handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output or os.getenv("LOG_FORMAT") == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(NauticalFormatter())
    log.addHandler(console_handler)
    _console_handler = console_handler  # Store for suppression control

    # File handler (always JSON for structured analysis)
    if log_file or os.getenv("LOG_TO_FILE", "").lower() in ("true", "1", "yes"):
        file_path = log_file or Path("logs/ship_ledger.jsonl")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(JSONFormatter())
        log.addHandler(file_handler)

    return log


# ===========================================================================
# Global Logger Instance
# ===========================================================================

# Create the global logger instance
logger: KlabautermannLogger = setup_logger()


# ===========================================================================
# Console Logging Control
# ===========================================================================


def suppress_console_logging() -> None:
    """Suppress console log output (for CLI mode to avoid interfering with input)."""
    global _console_handler
    if _console_handler and _console_handler in logger.handlers:
        logger.removeHandler(_console_handler)


def restore_console_logging() -> None:
    """Restore console log output after CLI session ends."""
    global _console_handler
    if _console_handler and _console_handler not in logger.handlers:
        logger.addHandler(_console_handler)


def set_cli_log_level() -> None:
    """Set log level appropriate for CLI mode.

    In CLI mode, only show warnings and errors by default to avoid
    cluttering the interactive output. Users can override with LOG_LEVEL
    environment variable or toggle with /logs command.
    """
    # Respect explicit LOG_LEVEL setting
    if os.getenv("LOG_LEVEL"):
        return
    # Default CLI mode to WARNING (only [SWELL], [STORM], [SHIPWRECK])
    logger.setLevel(logging.WARNING)


# ===========================================================================
# Convenience Functions
# ===========================================================================


def get_logger(name: str) -> KlabautermannLogger:
    """Get a child logger with the given name."""
    return logging.getLogger(f"klabautermann.{name}")  # type: ignore[return-value]


def log_with_context(
    level: int,
    message: str,
    trace_id: str | None = None,
    agent_name: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a message with standard context fields."""
    extra: dict[str, Any] = {}
    if trace_id:
        extra["trace_id"] = trace_id
    if agent_name:
        extra["agent_name"] = agent_name
    extra.update(kwargs)
    logger.log(level, message, extra=extra)


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "SUCCESS",
    "JSONFormatter",
    "KlabautermannLogger",
    "NauticalFormatter",
    "get_logger",
    "log_with_context",
    "logger",
    "restore_console_logging",
    "set_cli_log_level",
    "setup_logger",
    "suppress_console_logging",
]
