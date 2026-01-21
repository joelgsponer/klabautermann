"""
Orchestrator package for Klabautermann.

The Orchestrator is the "CEO" agent that routes intents, delegates to
sub-agents, and synthesizes responses.

This package contains:
- _orchestrator.py: Main Orchestrator class implementation
- prompts.py: All LLM prompt constants
"""

from klabautermann.agents.orchestrator._orchestrator import Orchestrator
from klabautermann.agents.orchestrator.prompts import (
    CLASSIFICATION_MODEL,
    CLASSIFICATION_PROMPT,
    SYNTHESIS_PROMPT,
    SYSTEM_PROMPT,
    TASK_PLANNING_PROMPT,
)


__all__ = [
    "CLASSIFICATION_MODEL",
    "CLASSIFICATION_PROMPT",
    "SYNTHESIS_PROMPT",
    "SYSTEM_PROMPT",
    "TASK_PLANNING_PROMPT",
    "Orchestrator",
]
