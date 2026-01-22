"""
Tests for the structured logging system.

Reference: Issue #272
"""

from __future__ import annotations

import json
import logging
import os
from io import StringIO
from unittest.mock import patch

import pytest

from klabautermann.core.logger import (
    JSONFormatter,
    NauticalFormatter,
    clear_log_context,
    get_log_context,
    log_context,
    set_log_context,
    setup_logger,
)


class TestJSONFormatter:
    """Tests for JSONFormatter class."""

    @pytest.fixture
    def formatter(self) -> JSONFormatter:
        """Create a JSONFormatter instance."""
        # Clear static cache for clean tests
        JSONFormatter._static_fields = None
        return JSONFormatter()

    def test_format_basic_message(self, formatter: JSONFormatter) -> None:
        """Test formatting a basic log message."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Test message"
        assert data["level"] == "INFO"
        assert data["nautical_level"] == "[CHART]"
        assert data["logger"] == "test"
        assert "timestamp" in data
        assert data["service"] == "klabautermann"
        assert data["environment"] == "dev"
        assert "hostname" in data

    def test_format_with_trace_id(self, formatter: JSONFormatter) -> None:
        """Test that trace_id is included when present."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.trace_id = "abc12345"

        result = formatter.format(record)
        data = json.loads(result)

        assert data["trace_id"] == "abc12345"

    def test_format_with_agent_name(self, formatter: JSONFormatter) -> None:
        """Test that agent_name is included when present."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.agent_name = "researcher"

        result = formatter.format(record)
        data = json.loads(result)

        assert data["agent_name"] == "researcher"

    def test_format_with_performance_metrics(self, formatter: JSONFormatter) -> None:
        """Test that performance metrics are included."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Operation complete",
            args=(),
            exc_info=None,
        )
        record.latency_ms = 150.5
        record.tool_name = "send_email"

        result = formatter.format(record)
        data = json.loads(result)

        assert data["latency_ms"] == 150.5
        assert data["tool_name"] == "send_email"

    def test_format_with_exception(self, formatter: JSONFormatter) -> None:
        """Test that exception info is formatted properly."""
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "Test error"
        assert "traceback" in data["exception"]

    def test_format_all_log_levels(self, formatter: JSONFormatter) -> None:
        """Test nautical level mapping for all log levels."""
        levels = [
            (logging.DEBUG, "[WHISPER]"),
            (logging.INFO, "[CHART]"),
            (logging.WARNING, "[SWELL]"),
            (logging.ERROR, "[STORM]"),
            (logging.CRITICAL, "[SHIPWRECK]"),
        ]

        for level, expected_nautical in levels:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=10,
                msg="Test",
                args=(),
                exc_info=None,
            )
            result = formatter.format(record)
            data = json.loads(result)
            assert data["nautical_level"] == expected_nautical

    def test_format_with_custom_service_name(self) -> None:
        """Test that LOG_SERVICE_NAME env var is respected."""
        JSONFormatter._static_fields = None  # Clear cache
        with patch.dict(os.environ, {"LOG_SERVICE_NAME": "custom-service"}):
            formatter = JSONFormatter()
            JSONFormatter._static_fields = None  # Force refresh
            formatter = JSONFormatter()

            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            data = json.loads(result)

            assert data["service"] == "custom-service"

    def test_format_with_source_location(self) -> None:
        """Test that source location is included when enabled."""
        JSONFormatter._static_fields = None
        with patch.dict(os.environ, {"LOG_INCLUDE_SOURCE": "true"}):
            formatter = JSONFormatter()

            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="/path/to/test.py",
                lineno=42,
                msg="Test",
                args=(),
                exc_info=None,
            )
            record.funcName = "test_function"

            result = formatter.format(record)
            data = json.loads(result)

            assert "source" in data
            assert data["source"]["file"] == "/path/to/test.py"
            assert data["source"]["line"] == 42
            assert data["source"]["function"] == "test_function"


class TestLogContext:
    """Tests for log context management."""

    @pytest.fixture(autouse=True)
    def reset_context(self) -> None:
        """Reset log context before each test."""
        clear_log_context()

    def test_get_log_context_empty(self) -> None:
        """Test getting empty context."""
        context = get_log_context()
        assert context == {}

    def test_set_log_context(self) -> None:
        """Test setting context fields."""
        set_log_context(trace_id="abc123", user_id="user1")

        context = get_log_context()
        assert context["trace_id"] == "abc123"
        assert context["user_id"] == "user1"

    def test_set_log_context_returns_token(self) -> None:
        """Test that set_log_context returns reset token."""
        token = set_log_context(trace_id="abc123")
        assert token is not None

    def test_log_context_manager(self) -> None:
        """Test log_context context manager."""
        with log_context(trace_id="ctx123", agent_name="test"):
            context = get_log_context()
            assert context["trace_id"] == "ctx123"
            assert context["agent_name"] == "test"

        # Context should be cleared after exiting
        context = get_log_context()
        assert "trace_id" not in context

    def test_log_context_manager_nested(self) -> None:
        """Test nested log_context managers."""
        with log_context(trace_id="outer"):
            with log_context(agent_name="inner"):
                context = get_log_context()
                # Both should be present
                assert context["trace_id"] == "outer"
                assert context["agent_name"] == "inner"

            # Inner context cleared, outer remains
            context = get_log_context()
            assert context["trace_id"] == "outer"
            assert "agent_name" not in context

    def test_clear_log_context(self) -> None:
        """Test clearing all context."""
        set_log_context(trace_id="abc", user_id="user")
        clear_log_context()

        context = get_log_context()
        assert context == {}

    def test_context_included_in_json_output(self) -> None:
        """Test that context is included in JSON formatted logs."""
        JSONFormatter._static_fields = None
        formatter = JSONFormatter()

        with log_context(trace_id="ctx456", custom_field="custom_value"):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test with context",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            data = json.loads(result)

            assert data["trace_id"] == "ctx456"
            assert data["custom_field"] == "custom_value"


class TestNauticalFormatter:
    """Tests for NauticalFormatter class."""

    def test_format_with_colors_disabled(self) -> None:
        """Test formatting without colors."""
        formatter = NauticalFormatter(use_colors=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        assert "[CHART]" in result
        assert "Test message" in result
        # No ANSI codes
        assert "\033[" not in result

    def test_format_includes_trace_id(self) -> None:
        """Test that trace_id is included in output."""
        formatter = NauticalFormatter(use_colors=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.trace_id = "abc12345"

        result = formatter.format(record)

        assert "abc12345" in result

    def test_format_includes_agent_name(self) -> None:
        """Test that agent_name is included in output."""
        formatter = NauticalFormatter(use_colors=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.agent_name = "researcher"

        result = formatter.format(record)

        assert "researcher" in result


class TestSetupLogger:
    """Tests for setup_logger function."""

    def test_setup_logger_returns_logger(self) -> None:
        """Test that setup_logger returns a KlabautermannLogger."""
        log = setup_logger("test_setup")
        assert log is not None
        assert log.name == "test_setup"

    def test_setup_logger_with_json_output(self) -> None:
        """Test setup_logger with JSON output enabled."""
        log = setup_logger("test_json", json_output=True)

        # Check that the handler uses JSONFormatter
        assert len(log.handlers) > 0
        handler = log.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_setup_logger_respects_log_level(self) -> None:
        """Test that setup_logger respects LOG_LEVEL env var."""
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            log = setup_logger("test_level")
            assert log.level == logging.DEBUG

    def test_setup_logger_with_log_format_json(self) -> None:
        """Test that LOG_FORMAT=json enables JSON output."""
        with patch.dict(os.environ, {"LOG_FORMAT": "json"}):
            log = setup_logger("test_format")

            handler = log.handlers[0]
            assert isinstance(handler.formatter, JSONFormatter)


class TestIntegration:
    """Integration tests for structured logging."""

    @pytest.fixture(autouse=True)
    def reset_context(self) -> None:
        """Reset log context before each test."""
        clear_log_context()
        JSONFormatter._static_fields = None

    def test_end_to_end_json_logging(self) -> None:
        """Test complete flow of JSON logging."""
        # Create a logger with JSON output to a string buffer
        log = setup_logger("test_e2e", json_output=True)

        # Capture output
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        handler.setFormatter(JSONFormatter())
        log.handlers = [handler]

        # Log with context
        with log_context(trace_id="e2e-trace", user_id="test-user"):
            log.info(
                "Processing request",
                extra={"agent_name": "orchestrator", "operation": "handle_input"},
            )

        # Parse output
        output = buffer.getvalue()
        data = json.loads(output.strip())

        # Verify all fields
        assert data["message"] == "Processing request"
        assert data["trace_id"] == "e2e-trace"
        assert data["user_id"] == "test-user"
        assert data["agent_name"] == "orchestrator"
        assert data["operation"] == "handle_input"
        assert data["level"] == "INFO"
        assert data["nautical_level"] == "[CHART]"
