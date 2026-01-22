"""
Agents module - The crew of Klabautermann.

Contains:
- base_agent: Abstract base class for all agents
- orchestrator: Main coordinating agent (The Captain's Mate)
- executor: MCP tool execution (The Admin)
- ingestor: Entity extraction (The Deckhand)
- researcher: Hybrid search (The Librarian)
- archivist: Thread summarization (The Archivist)
- scribe: Daily journals (The Scribe)
- hull_cleaner: Graph maintenance (The Hull Cleaner)
- officer: Proactive alerts (The Officer of the Watch)
"""

from klabautermann.agents.executor import Executor
from klabautermann.agents.hull_cleaner import (
    AuditEntry,
    HullCleaner,
    HullCleanerConfig,
    PruningAction,
    PruningResult,
    PruningRule,
)
from klabautermann.agents.officer import (
    Alert,
    AlertCheckResult,
    AlertPriority,
    AlertType,
    OfficerConfig,
    OfficerOfTheWatch,
)
from klabautermann.agents.scribe import Scribe


__all__ = [
    "Alert",
    "AlertCheckResult",
    "AlertPriority",
    "AlertType",
    "AuditEntry",
    "Executor",
    "HullCleaner",
    "HullCleanerConfig",
    "OfficerConfig",
    "OfficerOfTheWatch",
    "PruningAction",
    "PruningResult",
    "PruningRule",
    "Scribe",
]
