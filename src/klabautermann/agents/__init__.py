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
- purser: State synchronization (The Purser)
- bard: Lore and storytelling (The Bard of the Bilge)
- cartographer: Community detection (The Cartographer)
"""

from klabautermann.agents.bard import (
    CANONICAL_TIDBITS,
    ActiveSaga,
    BardConfig,
    BardOfTheBilge,
    ChapterTooSoonError,
    LoreEpisode,
    SagaCompleteError,
    SagaLifecycleError,
    SagaLimitReachedError,
    SagaTimedOutError,
    SaltResult,
    generate_saga_name,
)
from klabautermann.agents.cartographer import (
    Cartographer,
    CartographerConfig,
    Community,
    CommunityMember,
    CommunityTheme,
    DetectionResult,
    classify_theme,
)
from klabautermann.agents.executor import Executor
from klabautermann.agents.hull_cleaner import (
    AuditEntry,
    DuplicateCandidate,
    HullCleaner,
    HullCleanerConfig,
    MergeResult,
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
from klabautermann.agents.pre_extraction import (
    PreExtractionConfig,
    PreExtractionEngine,
    pre_extract_entities,
)
from klabautermann.agents.purser import (
    EmailManifest,
    Purser,
    PurserConfig,
    RiskLevel,
    SyncResult,
    SyncService,
    SyncState,
    TheSieve,
)
from klabautermann.agents.scribe import Scribe


__all__ = [
    "ActiveSaga",
    "Alert",
    "AlertCheckResult",
    "AlertPriority",
    "AlertType",
    "AuditEntry",
    "BardConfig",
    "BardOfTheBilge",
    "CANONICAL_TIDBITS",
    "Cartographer",
    "CartographerConfig",
    "ChapterTooSoonError",
    "Community",
    "CommunityMember",
    "CommunityTheme",
    "DetectionResult",
    "DuplicateCandidate",
    "EmailManifest",
    "Executor",
    "HullCleaner",
    "HullCleanerConfig",
    "LoreEpisode",
    "MergeResult",
    "OfficerConfig",
    "OfficerOfTheWatch",
    "PreExtractionConfig",
    "PreExtractionEngine",
    "PruningAction",
    "PruningResult",
    "PruningRule",
    "Purser",
    "PurserConfig",
    "RiskLevel",
    "SagaCompleteError",
    "SagaLifecycleError",
    "SagaLimitReachedError",
    "SagaTimedOutError",
    "SaltResult",
    "Scribe",
    "SyncResult",
    "SyncService",
    "SyncState",
    "TheSieve",
    "classify_theme",
    "generate_saga_name",
    "pre_extract_entities",
]
