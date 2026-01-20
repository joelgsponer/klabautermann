"""
Nautical logging system for Klabautermann.

Provides themed log levels and structured logging for tracing agent operations.
All log levels are mapped to nautical terminology to maintain the ship spirit personality.

Features:
- Nautical-themed log levels ([WHISPER], [CHART], [BEACON], [SWELL], [STORM], [SHIPWRECK])
- JSON structured logging for file output
- Log rotation with configurable size/count limits
- Gzip compression for old logs

Reference: specs/quality/LOGGING.md
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
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
# Log Rotation Configuration
# ===========================================================================


class LogRotationConfig:
    """Configuration for log rotation behavior."""

    # Maximum size of a single log file (default: 10MB)
    max_bytes: int = 10 * 1024 * 1024

    # Number of backup files to keep (default: 5)
    backup_count: int = 5

    # Whether to compress old logs with gzip
    compress: bool = True

    @classmethod
    def from_env(cls) -> LogRotationConfig:
        """Load configuration from environment variables."""
        config = cls()

        if max_bytes_str := os.getenv("LOG_MAX_BYTES"):
            config.max_bytes = int(max_bytes_str)

        if backup_count_str := os.getenv("LOG_BACKUP_COUNT"):
            config.backup_count = int(backup_count_str)

        if compress_str := os.getenv("LOG_COMPRESS"):
            config.compress = compress_str.lower() in ("true", "1", "yes")

        return config


class CompressingRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler that compresses old log files with gzip.

    When a log file is rotated, the old file is compressed to save disk space.
    This reduces storage requirements by ~80-90% for typical log files.

    Configuration via environment variables:
    - LOG_MAX_BYTES: Maximum size before rotation (default: 10MB)
    - LOG_BACKUP_COUNT: Number of backup files to keep (default: 5)
    - LOG_COMPRESS: Whether to compress old logs (default: true)
    """

    def __init__(
        self,
        filename: str | Path,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        compress: bool = True,
        encoding: str | None = "utf-8",
    ) -> None:
        """
        Initialize the compressing rotating file handler.

        Args:
            filename: Path to the log file.
            max_bytes: Maximum size of log file before rotation (default 10MB).
            backup_count: Number of backup files to keep (default 5).
            compress: Whether to gzip rotated files (default True).
            encoding: File encoding (default utf-8).
        """
        self.compress = compress
        super().__init__(
            filename=str(filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )

    def doRollover(self) -> None:
        """
        Perform log rotation with optional compression.

        Overrides RotatingFileHandler.doRollover() to add gzip compression
        for the rotated file.
        """
        # Close the current stream
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]

        # Build the rollover file names
        if self.backupCount > 0:
            # Shift existing files
            for i in range(self.backupCount - 1, 0, -1):
                sfn = Path(self._get_backup_name(i))
                dfn = Path(self._get_backup_name(i + 1))

                if sfn.exists():
                    if dfn.exists():
                        dfn.unlink()
                    sfn.rename(dfn)

            # Rotate current file to .1
            dfn = Path(self._get_backup_name(1))
            if dfn.exists():
                dfn.unlink()

            # Compress current file to .1.gz (or just rename to .1)
            if self.compress:
                self._compress_file(self.baseFilename, str(dfn))
            else:
                Path(self.baseFilename).rename(dfn)

        # Reopen the main log file
        if not self.delay:
            self.stream = self._open()

    def _get_backup_name(self, index: int) -> str:
        """Get backup file name for given index."""
        if self.compress:
            return f"{self.baseFilename}.{index}.gz"
        return f"{self.baseFilename}.{index}"

    def _compress_file(self, src: str, dst: str) -> None:
        """Compress source file to destination with gzip."""
        src_path = Path(src)
        dst_path = Path(dst)
        try:
            with src_path.open("rb") as f_in, gzip.open(dst_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            src_path.unlink()
        except OSError:
            # If compression fails, just rename the file
            if src_path.exists():
                src_path.rename(Path(dst.replace(".gz", "")))


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

    # File handler with rotation (always JSON for structured analysis)
    if log_file or os.getenv("LOG_TO_FILE", "").lower() in ("true", "1", "yes"):
        file_path = log_file or Path("logs/ship_ledger.jsonl")
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Load rotation config from environment
        rotation_config = LogRotationConfig.from_env()

        file_handler = CompressingRotatingFileHandler(
            filename=file_path,
            max_bytes=rotation_config.max_bytes,
            backup_count=rotation_config.backup_count,
            compress=rotation_config.compress,
        )
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
    "CompressingRotatingFileHandler",
    "JSONFormatter",
    "KlabautermannLogger",
    "LogRotationConfig",
    "NauticalFormatter",
    "get_logger",
    "log_with_context",
    "logger",
    "restore_console_logging",
    "set_cli_log_level",
    "setup_logger",
    "suppress_console_logging",
]
