"""
Tests for the agent workflow inspection system.

Reference: Issue #357
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from klabautermann.core.workflow_inspector import (
    WorkflowEntry,
    WorkflowInspector,
    WorkflowPhase,
    get_inspector,
    log_output,
    log_request,
    log_thinking,
)


class TestWorkflowPhase:
    """Tests for WorkflowPhase enum."""

    def test_phase_values(self) -> None:
        """Verify phase enum values."""
        assert WorkflowPhase.REQUEST.value == "REQUEST"
        assert WorkflowPhase.THINKING.value == "THINKING"
        assert WorkflowPhase.OUTPUT.value == "OUTPUT"

    def test_phase_string_enum(self) -> None:
        """Verify phase is a string enum for JSON serialization."""
        assert isinstance(WorkflowPhase.REQUEST.value, str)


class TestWorkflowEntry:
    """Tests for WorkflowEntry dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        timestamp = datetime.now(UTC)
        entry = WorkflowEntry(
            trace_id="abc123",
            agent_name="researcher",
            phase=WorkflowPhase.REQUEST,
            timestamp=timestamp,
            data={"query": "find John"},
            duration_ms=150.5,
        )

        result = entry.to_dict()

        assert result["trace_id"] == "abc123"
        assert result["agent"] == "researcher"
        assert result["phase"] == "REQUEST"
        assert result["timestamp"] == timestamp.isoformat()
        assert result["duration_ms"] == 150.5
        assert result["data"]["query"] == "find John"

    def test_to_dict_without_duration(self) -> None:
        """Test conversion when duration is None."""
        entry = WorkflowEntry(
            trace_id="abc123",
            agent_name="ingestor",
            phase=WorkflowPhase.THINKING,
            timestamp=datetime.now(UTC),
            data={"step": "cleaning"},
        )

        result = entry.to_dict()
        assert result["duration_ms"] is None

    def test_format_console_request(self) -> None:
        """Test console formatting for REQUEST phase."""
        entry = WorkflowEntry(
            trace_id="abc12345",
            agent_name="executor",
            phase=WorkflowPhase.REQUEST,
            timestamp=datetime.now(UTC),
            data={"action": "send email", "to": "john@example.com"},
        )

        output = entry.format_console()

        assert ">>>" in output  # REQUEST marker
        assert "[REQUEST]" in output
        assert "executor" in output
        assert "abc12345"[:8] in output
        assert "action: send email" in output

    def test_format_console_thinking(self) -> None:
        """Test console formatting for THINKING phase."""
        entry = WorkflowEntry(
            trace_id="def67890",
            agent_name="researcher",
            phase=WorkflowPhase.THINKING,
            timestamp=datetime.now(UTC),
            data={"step": "planning search"},
        )

        output = entry.format_console()

        assert "..." in output  # THINKING marker
        assert "[THINKING]" in output

    def test_format_console_output(self) -> None:
        """Test console formatting for OUTPUT phase."""
        entry = WorkflowEntry(
            trace_id="ghi11111",
            agent_name="ingestor",
            phase=WorkflowPhase.OUTPUT,
            timestamp=datetime.now(UTC),
            data={"status": "success"},
            duration_ms=250.0,
        )

        output = entry.format_console()

        assert "<<<" in output  # OUTPUT marker
        assert "[OUTPUT]" in output
        assert "250.0ms" in output

    def test_format_console_truncates_long_values(self) -> None:
        """Test that long values are truncated in console output."""
        long_text = "x" * 300
        entry = WorkflowEntry(
            trace_id="truncate123",
            agent_name="test",
            phase=WorkflowPhase.REQUEST,
            timestamp=datetime.now(UTC),
            data={"long_field": long_text},
        )

        output = entry.format_console()

        assert "..." in output
        # Should not contain the full 300 chars
        assert len(output) < len(long_text) + 200


class TestWorkflowInspector:
    """Tests for WorkflowInspector class."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> None:
        """Reset the singleton before each test."""
        WorkflowInspector.reset_instance()

    def test_singleton_pattern(self) -> None:
        """Test that get_instance returns singleton."""
        inspector1 = WorkflowInspector.get_instance()
        inspector2 = WorkflowInspector.get_instance()

        assert inspector1 is inspector2

    def test_log_request(self) -> None:
        """Test logging a REQUEST phase entry."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_request(
            trace_id="req123",
            agent_name="researcher",
            data={"query": "find Sarah"},
        )

        entries = inspector.get_entries()
        assert len(entries) == 1
        assert entries[0].phase == WorkflowPhase.REQUEST
        assert entries[0].agent_name == "researcher"
        assert entries[0].data["query"] == "find Sarah"

    def test_log_thinking(self) -> None:
        """Test logging a THINKING phase entry."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_thinking(
            trace_id="think456",
            agent_name="executor",
            data={"step": "validating email"},
        )

        entries = inspector.get_entries()
        assert len(entries) == 1
        assert entries[0].phase == WorkflowPhase.THINKING
        assert entries[0].data["step"] == "validating email"

    def test_log_output(self) -> None:
        """Test logging an OUTPUT phase entry."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_output(
            trace_id="out789",
            agent_name="ingestor",
            data={"status": "success", "entities_created": 3},
            duration_ms=100.5,
        )

        entries = inspector.get_entries()
        assert len(entries) == 1
        assert entries[0].phase == WorkflowPhase.OUTPUT
        assert entries[0].duration_ms == 100.5
        assert entries[0].data["entities_created"] == 3

    def test_disabled_inspector_doesnt_log(self) -> None:
        """Test that disabled inspector doesn't record entries."""
        inspector = WorkflowInspector(enabled=False, log_to_file=False, log_to_console=False)

        inspector.log_request("test", "agent", {"key": "value"})

        assert len(inspector.get_entries()) == 0

    def test_filter_by_agent(self) -> None:
        """Test filtering entries by agent name."""
        inspector = WorkflowInspector(
            enabled=True,
            log_to_file=False,
            log_to_console=False,
            filter_agents={"researcher"},
        )

        inspector.log_request("trace1", "researcher", {"a": 1})
        inspector.log_request("trace2", "executor", {"b": 2})
        inspector.log_request("trace3", "researcher", {"c": 3})

        # Only researcher entries should be logged
        entries = inspector.get_entries()
        assert len(entries) == 2
        assert all(e.agent_name == "researcher" for e in entries)

    def test_get_entries_filters(self) -> None:
        """Test filtering when retrieving entries."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_request("trace1", "agent1", {})
        inspector.log_thinking("trace1", "agent1", {})
        inspector.log_output("trace1", "agent1", {})
        inspector.log_request("trace2", "agent2", {})

        # Filter by trace_id
        entries = inspector.get_entries(trace_id="trace1")
        assert len(entries) == 3

        # Filter by agent_name
        entries = inspector.get_entries(agent_name="agent2")
        assert len(entries) == 1

        # Filter by phase
        entries = inspector.get_entries(phase=WorkflowPhase.REQUEST)
        assert len(entries) == 2

        # Combined filters
        entries = inspector.get_entries(trace_id="trace1", phase=WorkflowPhase.THINKING)
        assert len(entries) == 1

    def test_get_workflow_summary(self) -> None:
        """Test generating workflow summary."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_request("trace1", "researcher", {})
        inspector.log_thinking("trace1", "researcher", {})
        inspector.log_output("trace1", "researcher", {}, duration_ms=100.0)
        inspector.log_request("trace1", "executor", {})
        inspector.log_output("trace1", "executor", {}, duration_ms=50.0)

        summary = inspector.get_workflow_summary("trace1")

        assert summary["trace_id"] == "trace1"
        assert summary["total_entries"] == 5
        assert "researcher" in summary["agents"]
        assert "executor" in summary["agents"]
        assert summary["agents"]["researcher"]["total_duration_ms"] == 100.0
        assert summary["agents"]["executor"]["total_duration_ms"] == 50.0

    def test_max_entries_limit(self) -> None:
        """Test that buffer respects max entries limit."""
        inspector = WorkflowInspector(
            enabled=True, log_to_file=False, log_to_console=False, _max_entries=5
        )

        for i in range(10):
            inspector.log_request(f"trace{i}", "agent", {"index": i})

        entries = inspector.get_entries()
        assert len(entries) == 5
        # Should keep the latest entries
        assert entries[-1].data["index"] == 9

    def test_clear_entries(self) -> None:
        """Test clearing the entry buffer."""
        inspector = WorkflowInspector(enabled=True, log_to_file=False, log_to_console=False)

        inspector.log_request("trace1", "agent", {})
        inspector.log_request("trace2", "agent", {})

        inspector.clear()

        assert len(inspector.get_entries()) == 0

    def test_log_to_file(self) -> None:
        """Test logging entries to a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "workflow.jsonl"
            inspector = WorkflowInspector(
                enabled=True,
                log_to_file=True,
                log_to_console=False,
                log_file=log_file,
            )

            inspector.log_request("file_trace", "agent", {"key": "value"})

            # Verify file was written
            assert log_file.exists()

            # Verify content
            with log_file.open() as f:
                line = f.readline()
                entry = json.loads(line)
                assert entry["trace_id"] == "file_trace"
                assert entry["phase"] == "REQUEST"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> None:
        """Reset the singleton before each test."""
        WorkflowInspector.reset_instance()

    def test_get_inspector(self) -> None:
        """Test get_inspector returns singleton."""
        inspector = get_inspector()
        assert isinstance(inspector, WorkflowInspector)
        assert get_inspector() is inspector

    @patch.object(WorkflowInspector, "log_request")
    def test_log_request_function(self, mock_log: object) -> None:
        """Test log_request convenience function."""
        log_request("trace", "agent", {"data": 1})
        # Verifies the function calls through to the singleton

    @patch.object(WorkflowInspector, "log_thinking")
    def test_log_thinking_function(self, mock_log: object) -> None:
        """Test log_thinking convenience function."""
        log_thinking("trace", "agent", {"step": "test"})

    @patch.object(WorkflowInspector, "log_output")
    def test_log_output_function(self, mock_log: object) -> None:
        """Test log_output convenience function."""
        log_output("trace", "agent", {"result": "ok"}, duration_ms=50.0)


class TestEnvironmentConfiguration:
    """Tests for environment variable configuration."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> None:
        """Reset the singleton before each test."""
        WorkflowInspector.reset_instance()

    def test_disabled_via_env(self) -> None:
        """Test disabling via WORKFLOW_INSPECT=false."""
        with patch.dict("os.environ", {"WORKFLOW_INSPECT": "false"}):
            inspector = WorkflowInspector()
            assert not inspector.enabled

    def test_filter_agents_via_env(self) -> None:
        """Test filtering agents via WORKFLOW_FILTER_AGENTS."""
        with patch.dict("os.environ", {"WORKFLOW_FILTER_AGENTS": "researcher,executor"}):
            inspector = WorkflowInspector()
            assert "researcher" in inspector.filter_agents
            assert "executor" in inspector.filter_agents

    def test_console_disabled_via_env(self) -> None:
        """Test disabling console via WORKFLOW_CONSOLE=false."""
        with patch.dict("os.environ", {"WORKFLOW_CONSOLE": "false"}):
            inspector = WorkflowInspector()
            assert not inspector.log_to_console
