"""
Memory module - The Locker (knowledge graph interface).

Contains:
- graphiti_client: Wrapper around Graphiti library
- neo4j_client: Direct Neo4j driver access
- thread_manager: Conversation thread persistence
- queries: Parametrized Cypher query library
- graph_statistics: Graph node/relationship counts
- context_statistics: Context window token/overflow tracking
- orphan_cleanup: Find and remove orphan messages
- health_monitor: Memory system health monitoring
- zoom_search: Multi-level retrieval (macro/meso/micro)
- entity_merge: Duplicate entity detection and merging
- temporal_spine: Day-based temporal queries
- relevance_scoring: Context relevance scoring for prioritization
- summary_cache: Thread summary caching
- weight_decay: Relationship weight decay for graph maintenance
"""

from klabautermann.memory.context_statistics import (
    ContextWindowMetrics,
    GlobalContextMetrics,
    get_global_context_metrics,
    get_thread_context_metrics,
)
from klabautermann.memory.entity_merge import (
    DuplicateCandidate,
    MergePreview,
    MergeResult,
    find_duplicate_persons,
    merge_entities,
    preview_merge,
)
from klabautermann.memory.graph_statistics import (
    GraphStatistics,
    get_graph_statistics,
    get_node_counts_by_type,
    get_relationship_counts_by_type,
)
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.health_monitor import (
    MemoryHealthMonitor,
    MemoryHealthStatus,
    get_health_monitor,
)
from klabautermann.memory.neo4j_client import Neo4jClient, QueryTimeoutError
from klabautermann.memory.orphan_cleanup import (
    OrphanCleanupResult,
    delete_orphan_messages,
    find_orphan_messages,
)
from klabautermann.memory.queries import CypherQueries, QueryBuilder, QueryResult
from klabautermann.memory.relevance_scoring import (
    ScoredItem,
    compute_connection_score,
    compute_priority_score,
    compute_recency_score,
    compute_text_similarity_score,
    extract_items,
    score_and_truncate,
    score_context_items,
    truncate_by_relevance,
)
from klabautermann.memory.summary_cache import (
    CachedSummary,
    get_cache_statistics,
    get_cached_summary,
    get_or_compute_summary,
    invalidate_summary_cache,
    set_cached_summary,
)
from klabautermann.memory.temporal_spine import (
    DayActivity,
    DayNode,
    find_entities_by_date,
    find_entities_in_range,
    get_day_activities,
    get_or_create_day,
    get_weekly_summary,
    link_to_day,
)
from klabautermann.memory.thread_manager import ThreadManager
from klabautermann.memory.weight_decay import (
    DEFAULT_ACCESS_BOOST,
    DEFAULT_HALF_LIFE_SECONDS,
    DEFAULT_INITIAL_WEIGHT,
    DEFAULT_MIN_WEIGHT,
    DecayResult,
    RelationshipWeight,
    apply_decay_to_relationships,
    calculate_boosted_weight,
    calculate_decayed_weight,
    get_low_weight_relationships,
    get_weight_statistics,
    initialize_relationship_weights,
    update_relationship_access,
)
from klabautermann.memory.zoom_search import (
    AIZoomLevelSelector,
    MacroSearchResult,
    MesoSearchResult,
    MicroSearchResult,
    ZoomClassification,
    ZoomLevel,
    ZoomLevelSelector,
    ai_zoom_search,
    auto_zoom_search,
    macro_search,
    meso_search,
    micro_search,
)


__all__ = [
    # Weight Decay
    "DEFAULT_ACCESS_BOOST",
    "DEFAULT_HALF_LIFE_SECONDS",
    "DEFAULT_INITIAL_WEIGHT",
    "DEFAULT_MIN_WEIGHT",
    # Zoom Search
    "AIZoomLevelSelector",
    # Summary Cache
    "CachedSummary",
    # Context Statistics
    "ContextWindowMetrics",
    # Clients
    "CypherQueries",
    # Temporal Spine
    "DayActivity",
    "DayNode",
    "DecayResult",
    # Entity Merge
    "DuplicateCandidate",
    "GlobalContextMetrics",
    # Graph Statistics
    "GraphStatistics",
    "GraphitiClient",
    "MacroSearchResult",
    # Health Monitor
    "MemoryHealthMonitor",
    "MemoryHealthStatus",
    "MergePreview",
    "MergeResult",
    "MesoSearchResult",
    "MicroSearchResult",
    "Neo4jClient",
    # Orphan Cleanup
    "OrphanCleanupResult",
    "QueryBuilder",
    "QueryResult",
    "QueryTimeoutError",
    "RelationshipWeight",
    # Relevance Scoring
    "ScoredItem",
    "ThreadManager",
    "ZoomClassification",
    "ZoomLevel",
    "ZoomLevelSelector",
    "ai_zoom_search",
    "apply_decay_to_relationships",
    "auto_zoom_search",
    "calculate_boosted_weight",
    "calculate_decayed_weight",
    "compute_connection_score",
    "compute_priority_score",
    "compute_recency_score",
    "compute_text_similarity_score",
    "delete_orphan_messages",
    "extract_items",
    "find_duplicate_persons",
    "find_entities_by_date",
    "find_entities_in_range",
    "find_orphan_messages",
    "get_cache_statistics",
    "get_cached_summary",
    "get_day_activities",
    "get_global_context_metrics",
    "get_graph_statistics",
    "get_health_monitor",
    "get_low_weight_relationships",
    "get_node_counts_by_type",
    "get_or_compute_summary",
    "get_or_create_day",
    "get_relationship_counts_by_type",
    "get_thread_context_metrics",
    "get_weekly_summary",
    "get_weight_statistics",
    "initialize_relationship_weights",
    "invalidate_summary_cache",
    "link_to_day",
    "macro_search",
    "merge_entities",
    "meso_search",
    "micro_search",
    "preview_merge",
    "score_and_truncate",
    "score_context_items",
    "set_cached_summary",
    "truncate_by_relevance",
    "update_relationship_access",
]
