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
"""

from klabautermann.agents.executor import Executor
from klabautermann.agents.scribe import Scribe


__all__ = ["Executor", "Scribe"]
