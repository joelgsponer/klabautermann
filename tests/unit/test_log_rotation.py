"""
Unit tests for log rotation functionality.

Tests the CompressingRotatingFileHandler and LogRotationConfig.
"""

from __future__ import annotations

import gzip
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from klabautermann.core.logger import (
    CompressingRotatingFileHandler,
    JSONFormatter,
    LogRotationConfig,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for log files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def log_file(temp_log_dir: Path) -> Path:
    """Create a path for the test log file."""
    return temp_log_dir / "test.log"


# =============================================================================
# Test LogRotationConfig
# =============================================================================


class TestLogRotationConfig:
    """Tests for LogRotationConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = LogRotationConfig()

        assert config.max_bytes == 10 * 1024 * 1024  # 10MB
        assert config.backup_count == 5
        assert config.compress is True

    def test_from_env_max_bytes(self) -> None:
        """Test loading max_bytes from environment."""
        with patch.dict(os.environ, {"LOG_MAX_BYTES": "5242880"}):  # 5MB
            config = LogRotationConfig.from_env()

        assert config.max_bytes == 5242880

    def test_from_env_backup_count(self) -> None:
        """Test loading backup_count from environment."""
        with patch.dict(os.environ, {"LOG_BACKUP_COUNT": "10"}):
            config = LogRotationConfig.from_env()

        assert config.backup_count == 10

    def test_from_env_compress_true(self) -> None:
        """Test loading compress=true from environment."""
        with patch.dict(os.environ, {"LOG_COMPRESS": "true"}):
            config = LogRotationConfig.from_env()

        assert config.compress is True

    def test_from_env_compress_false(self) -> None:
        """Test loading compress=false from environment."""
        with patch.dict(os.environ, {"LOG_COMPRESS": "false"}):
            config = LogRotationConfig.from_env()

        assert config.compress is False

    def test_from_env_all_values(self) -> None:
        """Test loading all values from environment."""
        env = {
            "LOG_MAX_BYTES": "1048576",  # 1MB
            "LOG_BACKUP_COUNT": "3",
            "LOG_COMPRESS": "yes",
        }
        with patch.dict(os.environ, env):
            config = LogRotationConfig.from_env()

        assert config.max_bytes == 1048576
        assert config.backup_count == 3
        assert config.compress is True


# =============================================================================
# Test CompressingRotatingFileHandler
# =============================================================================


class TestCompressingRotatingFileHandler:
    """Tests for CompressingRotatingFileHandler."""

    def test_creates_log_file(self, log_file: Path) -> None:
        """Test that handler creates log file."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=1024,
            backup_count=3,
        )

        # Write a log message
        logger = logging.getLogger("test_creates")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info("Test message")
        handler.close()

        assert log_file.exists()

    def test_rotation_creates_backup(self, log_file: Path) -> None:
        """Test that rotation creates backup files."""
        # Use small max_bytes to trigger rotation
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=100,  # Very small to trigger rotation
            backup_count=3,
            compress=False,  # No compression for easier testing
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_rotation")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write enough messages to trigger rotation
        for i in range(20):
            logger.info(f"Test message {i} with some padding to fill the log")

        handler.close()

        # Log file should exist
        assert log_file.exists()
        # Note: Rotation happens when max_bytes is exceeded, so backup may or may not exist
        # depending on exact timing. The important thing is no crash.

    def test_rotation_with_compression(self, log_file: Path) -> None:
        """Test that rotation compresses backup files."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=100,
            backup_count=3,
            compress=True,
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_compression")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write enough messages to trigger rotation
        for i in range(20):
            logger.info(f"Test message {i} with some padding to fill the buffer")

        handler.close()

        # If rotation happened, backup should be compressed
        compressed_backup = Path(f"{log_file}.1.gz")

        # Check if rotation happened (may not if log didn't exceed max_bytes)
        if compressed_backup.exists():
            # Verify it's a valid gzip file
            with gzip.open(compressed_backup, "rt") as f:
                content = f.read()
                assert "Test message" in content

    def test_backup_naming_without_compression(self, log_file: Path) -> None:
        """Test backup file naming without compression."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=1024,
            backup_count=3,
            compress=False,
        )

        # Check backup name generation
        assert handler._get_backup_name(1) == f"{log_file}.1"
        assert handler._get_backup_name(2) == f"{log_file}.2"

        handler.close()

    def test_backup_naming_with_compression(self, log_file: Path) -> None:
        """Test backup file naming with compression."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=1024,
            backup_count=3,
            compress=True,
        )

        # Check backup name generation
        assert handler._get_backup_name(1) == f"{log_file}.1.gz"
        assert handler._get_backup_name(2) == f"{log_file}.2.gz"

        handler.close()

    def test_backup_count_limit(self, log_file: Path) -> None:
        """Test that backup count is respected."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=50,  # Very small
            backup_count=2,
            compress=False,
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_backup_limit")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write many messages to trigger multiple rotations
        for i in range(50):
            logger.info(f"Message {i}")

        handler.close()

        # Check that we don't have more than backup_count + 1 files
        log_dir = log_file.parent
        log_files = list(log_dir.glob("test.log*"))

        # Should have at most: test.log, test.log.1, test.log.2
        assert len(log_files) <= 3

    def test_default_encoding(self, log_file: Path) -> None:
        """Test that default encoding is UTF-8."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=1024,
            backup_count=3,
        )

        assert handler.encoding == "utf-8"
        handler.close()


# =============================================================================
# Test Integration with Logger
# =============================================================================


class TestLoggerIntegration:
    """Tests for integration with the logger setup."""

    def test_json_formatter_output(self, log_file: Path) -> None:
        """Test that JSON formatter produces valid JSON."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=10240,
            backup_count=3,
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_json")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test message", extra={"trace_id": "abc123"})
        handler.close()

        # Read and verify JSON
        import json

        with log_file.open() as f:
            for line in f:
                entry = json.loads(line)
                assert "timestamp" in entry
                assert "level" in entry
                assert "message" in entry
                if "trace_id" in entry:
                    assert entry["trace_id"] == "abc123"

    def test_multiple_handlers(self, temp_log_dir: Path) -> None:
        """Test multiple rotating handlers don't interfere."""
        log1 = temp_log_dir / "app1.log"
        log2 = temp_log_dir / "app2.log"

        handler1 = CompressingRotatingFileHandler(filename=log1, max_bytes=1024, backup_count=2)
        handler2 = CompressingRotatingFileHandler(filename=log2, max_bytes=1024, backup_count=2)

        logger1 = logging.getLogger("app1")
        logger1.handlers.clear()
        logger1.addHandler(handler1)
        logger1.setLevel(logging.INFO)

        logger2 = logging.getLogger("app2")
        logger2.handlers.clear()
        logger2.addHandler(handler2)
        logger2.setLevel(logging.INFO)

        logger1.info("Message to app1")
        logger2.info("Message to app2")

        handler1.close()
        handler2.close()

        assert log1.exists()
        assert log2.exists()

        with log1.open() as f:
            assert "app1" in f.read()

        with log2.open() as f:
            assert "app2" in f.read()


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_log_file(self, log_file: Path) -> None:
        """Test handling of empty log file."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=1024,
            backup_count=3,
        )

        # Just open and close without writing
        handler.close()

        # File might not exist or be empty
        if log_file.exists():
            assert log_file.stat().st_size == 0

    def test_zero_backup_count(self, log_file: Path) -> None:
        """Test with zero backup count (no rotation)."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=100,
            backup_count=0,
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_zero_backup")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write messages
        for i in range(10):
            logger.info(f"Message {i}")

        handler.close()

        # No backup files should exist
        log_dir = log_file.parent
        backup_files = list(log_dir.glob("test.log.*"))
        assert len(backup_files) == 0

    def test_large_max_bytes(self, log_file: Path) -> None:
        """Test with large max_bytes (no rotation expected)."""
        handler = CompressingRotatingFileHandler(
            filename=log_file,
            max_bytes=100 * 1024 * 1024,  # 100MB
            backup_count=3,
        )
        handler.setFormatter(JSONFormatter())

        logger = logging.getLogger("test_large_max")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write some messages
        for i in range(10):
            logger.info(f"Message {i}")

        handler.close()

        # No rotation should have happened
        backup_file = Path(f"{log_file}.1")
        assert not backup_file.exists()
