"""
Agent workflow inspection system for Klabautermann.

Provides detailed logging of agent workflows for debugging and analysis.
Each agent logs three phases:
1. REQUEST: The incoming message/task
2. THINKING: Internal processing, decisions, LLM calls
3. OUTPUT: The result/response

The inspector can be configured to log to file, console, or both,
with optional filtering by agent name or trace ID.

Reference: Issue #357
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from klabautermann.core.logger import logger


class WorkflowPhase(str, Enum):
    """Phases of agent workflow execution."""

    REQUEST = "REQUEST"
    THINKING = "THINKING"
    OUTPUT = "OUTPUT"


@dataclass
class WorkflowEntry:
    """A single workflow log entry."""

    trace_id: str
    agent_name: str
    phase: WorkflowPhase
    timestamp: datetime
    data: dict[str, Any]
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "trace_id": self.trace_id,
            "agent": self.agent_name,
            "phase": self.phase.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "data": self.data,
        }

    def format_console(self) -> str:
        """Format for console display with clear visual separation."""
        timestamp_str = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        phase_markers = {
            WorkflowPhase.REQUEST: ">>>",
            WorkflowPhase.THINKING: "...",
            WorkflowPhase.OUTPUT: "<<<",
        }
        marker = phase_markers.get(self.phase, "---")

        # Build header line
        header = f"{marker} [{self.phase.value}] {self.agent_name} | trace={self.trace_id[:8]} | {timestamp_str}"
        if self.duration_ms is not None:
            header += f" | {self.duration_ms:.1f}ms"

        # Build data section with indentation
        lines = [header]
        for key, value in self.data.items():
            if isinstance(value, dict):
                lines.append(f"    {key}:")
                for k, v in value.items():
                    # Truncate long values
                    v_str = str(v)
                    if len(v_str) > 200:
                        v_str = v_str[:200] + "..."
                    lines.append(f"      {k}: {v_str}")
            elif isinstance(value, list) and len(value) > 5:
                lines.append(f"    {key}: [{len(value)} items]")
            else:
                v_str = str(value)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                lines.append(f"    {key}: {v_str}")

        return "\n".join(lines)


@dataclass
class WorkflowInspector:
    """
    Inspects and logs agent workflows.

    Provides methods for agents to log their REQUEST, THINKING, and OUTPUT
    phases with structured data. Can write to file, console, or both.

    Usage:
        inspector = WorkflowInspector.get_instance()
        inspector.log_request(trace_id, "researcher", {"query": "find John"})
        inspector.log_thinking(trace_id, "researcher", {"search_type": "hybrid"})
        inspector.log_output(trace_id, "researcher", {"results": [...]})
    """

    enabled: bool = True
    log_to_file: bool = True
    log_to_console: bool = True
    log_file: Path | None = None
    filter_agents: set[str] = field(default_factory=set)
    filter_trace_ids: set[str] = field(default_factory=set)

    # In-memory buffer for recent entries (for testing/inspection)
    _entries: list[WorkflowEntry] = field(default_factory=list)
    _max_entries: int = 1000

    # Singleton instance
    _instance: WorkflowInspector | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize from environment variables."""
        # Check if inspection is enabled
        if os.getenv("WORKFLOW_INSPECT", "").lower() in ("false", "0", "no"):
            self.enabled = False

        # Log file path - only override if not explicitly passed and env var set
        log_path = os.getenv("WORKFLOW_LOG_FILE")
        if log_path:
            self.log_file = Path(log_path)
        elif self.log_file is None and self.log_to_file:
            self.log_file = Path("logs/workflow_inspection.jsonl")

        # Console output
        if os.getenv("WORKFLOW_CONSOLE", "").lower() in ("false", "0", "no"):
            self.log_to_console = False

        # Filter by agent names (comma-separated)
        if agent_filter := os.getenv("WORKFLOW_FILTER_AGENTS"):
            self.filter_agents = set(agent_filter.split(","))

    def _ensure_log_directory(self) -> None:
        """Ensure log file directory exists."""
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> WorkflowInspector:
        """Get or create the singleton inspector instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None

    def _should_log(self, agent_name: str, trace_id: str) -> bool:
        """Check if this entry should be logged based on filters."""
        if not self.enabled:
            return False

        # If filters are set, entry must match at least one
        if self.filter_agents and agent_name not in self.filter_agents:
            return False

        if self.filter_trace_ids and trace_id not in self.filter_trace_ids:
            return False

        return True

    def _log_entry(self, entry: WorkflowEntry) -> None:
        """Log an entry to all configured outputs."""
        if not self._should_log(entry.agent_name, entry.trace_id):
            return

        # Add to in-memory buffer
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

        # Log to file (JSON lines format)
        if self.log_to_file and self.log_file:
            self._ensure_log_directory()
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

        # Log to console via logger
        if self.log_to_console:
            # Use info level with special marker for workflow inspection
            logger.info(
                f"[WORKFLOW] {entry.format_console()}",
                extra={
                    "trace_id": entry.trace_id,
                    "agent_name": entry.agent_name,
                    "workflow_phase": entry.phase.value,
                },
            )

    def log_request(
        self,
        trace_id: str,
        agent_name: str,
        data: dict[str, Any],
    ) -> None:
        """
        Log the REQUEST phase of an agent workflow.

        Args:
            trace_id: Request trace ID for correlation.
            agent_name: Name of the agent receiving the request.
            data: Request data (intent, payload, source, etc.).
        """
        entry = WorkflowEntry(
            trace_id=trace_id,
            agent_name=agent_name,
            phase=WorkflowPhase.REQUEST,
            timestamp=datetime.now(UTC),
            data=data,
        )
        self._log_entry(entry)

    def log_thinking(
        self,
        trace_id: str,
        agent_name: str,
        data: dict[str, Any],
    ) -> None:
        """
        Log the THINKING phase of an agent workflow.

        Args:
            trace_id: Request trace ID for correlation.
            agent_name: Name of the agent processing.
            data: Thinking data (decisions, LLM prompts, intermediate results).
        """
        entry = WorkflowEntry(
            trace_id=trace_id,
            agent_name=agent_name,
            phase=WorkflowPhase.THINKING,
            timestamp=datetime.now(UTC),
            data=data,
        )
        self._log_entry(entry)

    def log_output(
        self,
        trace_id: str,
        agent_name: str,
        data: dict[str, Any],
        duration_ms: float | None = None,
    ) -> None:
        """
        Log the OUTPUT phase of an agent workflow.

        Args:
            trace_id: Request trace ID for correlation.
            agent_name: Name of the agent producing output.
            data: Output data (results, response, errors).
            duration_ms: Total processing time in milliseconds.
        """
        entry = WorkflowEntry(
            trace_id=trace_id,
            agent_name=agent_name,
            phase=WorkflowPhase.OUTPUT,
            timestamp=datetime.now(UTC),
            data=data,
            duration_ms=duration_ms,
        )
        self._log_entry(entry)

    def get_entries(
        self,
        trace_id: str | None = None,
        agent_name: str | None = None,
        phase: WorkflowPhase | None = None,
    ) -> list[WorkflowEntry]:
        """
        Get workflow entries from the in-memory buffer.

        Args:
            trace_id: Filter by trace ID.
            agent_name: Filter by agent name.
            phase: Filter by workflow phase.

        Returns:
            List of matching workflow entries.
        """
        entries = self._entries

        if trace_id:
            entries = [e for e in entries if e.trace_id == trace_id]

        if agent_name:
            entries = [e for e in entries if e.agent_name == agent_name]

        if phase:
            entries = [e for e in entries if e.phase == phase]

        return entries

    def get_workflow_summary(self, trace_id: str) -> dict[str, Any]:
        """
        Get a summary of all workflow entries for a trace.

        Args:
            trace_id: The trace ID to summarize.

        Returns:
            Dictionary with agents and their phases.
        """
        entries = self.get_entries(trace_id=trace_id)

        summary: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.agent_name not in summary:
                summary[entry.agent_name] = {
                    "phases": [],
                    "total_duration_ms": 0.0,
                }
            summary[entry.agent_name]["phases"].append(entry.phase.value)
            if entry.duration_ms:
                summary[entry.agent_name]["total_duration_ms"] += entry.duration_ms

        return {
            "trace_id": trace_id,
            "agents": summary,
            "total_entries": len(entries),
        }

    def clear(self) -> None:
        """Clear the in-memory entry buffer."""
        self._entries = []


# ===========================================================================
# Convenience Functions
# ===========================================================================


def get_inspector() -> WorkflowInspector:
    """Get the global workflow inspector instance."""
    return WorkflowInspector.get_instance()


def log_request(trace_id: str, agent_name: str, data: dict[str, Any]) -> None:
    """Log a REQUEST phase entry."""
    get_inspector().log_request(trace_id, agent_name, data)


def log_thinking(trace_id: str, agent_name: str, data: dict[str, Any]) -> None:
    """Log a THINKING phase entry."""
    get_inspector().log_thinking(trace_id, agent_name, data)


def log_output(
    trace_id: str,
    agent_name: str,
    data: dict[str, Any],
    duration_ms: float | None = None,
) -> None:
    """Log an OUTPUT phase entry."""
    get_inspector().log_output(trace_id, agent_name, data, duration_ms)


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "WorkflowEntry",
    "WorkflowInspector",
    "WorkflowPhase",
    "get_inspector",
    "log_output",
    "log_request",
    "log_thinking",
]
