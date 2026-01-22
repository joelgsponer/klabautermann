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
from klabautermann.agents.scribe import Scribe


__all__ = [
    "AuditEntry",
    "Executor",
    "HullCleaner",
    "HullCleanerConfig",
    "PruningAction",
    "PruningResult",
    "PruningRule",
    "Scribe",
]
