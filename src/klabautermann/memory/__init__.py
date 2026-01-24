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
- semantic_cache: Semantic query result caching with TTL
- weight_decay: Relationship weight decay for graph maintenance
- traversal: Optimized relationship traversal utilities
- temporal: Time expression parsing and temporal filtering
- audit_log: Persistent audit logging for graph maintenance operations
"""

from klabautermann.memory.audit_log import (
    AuditLogStats,
    AuditQueryFilter,
    StoredAuditEntry,
    delete_old_audit_entries,
    get_audit_stats,
    query_audit_log,
    save_audit_entries,
    save_audit_entry,
)
from klabautermann.memory.backup import (
    BackupMetadata,
    BackupSnapshot,
    RestoreResult,
    clear_database,
    create_backup,
    load_backup_from_file,
    restore_backup,
    save_backup_to_file,
    validate_backup,
)
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
from klabautermann.memory.semantic_cache import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_SECONDS,
    CacheEntry,
    CacheStats,
    SemanticCache,
    cache_search_results,
    clear_search_cache,
    get_cached_search_results,
    get_search_cache_stats,
    get_semantic_cache,
    hash_query,
    hash_query_with_params,
    invalidate_search_cache,
    reset_semantic_cache,
)
from klabautermann.memory.summary_cache import (
    CachedSummary,
    get_cache_statistics,
    get_cached_summary,
    get_or_compute_summary,
    invalidate_summary_cache,
    set_cached_summary,
)
from klabautermann.memory.temporal import (
    TemporalQueryResult,
    TimeExpressionType,
    TimeRange,
    execute_temporal_query,
    get_historical_relationships,
    parse_time_expression,
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
from klabautermann.memory.traversal import (
    NODE_SEARCH_INDEXES,
    RELATIONSHIP_INDEXES,
    BenchmarkResult,
    TraversalConfig,
    TraversalDirection,
    TraversalResult,
    TraversalStats,
    benchmark_traversal,
    find_connected_entities,
    find_shortest_path,
    get_index_hint,
    get_search_index,
    traverse_dependency_chain,
    traverse_from_node,
    traverse_reporting_chain,
)
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
    # Audit Log
    "AuditLogStats",
    "AuditQueryFilter",
    "StoredAuditEntry",
    "delete_old_audit_entries",
    "get_audit_stats",
    "query_audit_log",
    "save_audit_entries",
    "save_audit_entry",
    # Weight Decay
    "DEFAULT_ACCESS_BOOST",
    "DEFAULT_HALF_LIFE_SECONDS",
    "DEFAULT_INITIAL_WEIGHT",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MIN_WEIGHT",
    "DEFAULT_TTL_SECONDS",
    "NODE_SEARCH_INDEXES",
    "RELATIONSHIP_INDEXES",
    # Zoom Search
    "AIZoomLevelSelector",
    # Backup/Restore
    "BackupMetadata",
    "BackupSnapshot",
    # Traversal
    "BenchmarkResult",
    # Semantic Cache
    "CacheEntry",
    "CacheStats",
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
    "RestoreResult",
    # Relevance Scoring
    "ScoredItem",
    "SemanticCache",
    # Temporal
    "TemporalQueryResult",
    "ThreadManager",
    "TimeExpressionType",
    "TimeRange",
    "TraversalConfig",
    "TraversalDirection",
    "TraversalResult",
    "TraversalStats",
    "ZoomClassification",
    "ZoomLevel",
    "ZoomLevelSelector",
    "ai_zoom_search",
    "apply_decay_to_relationships",
    "auto_zoom_search",
    "benchmark_traversal",
    "cache_search_results",
    "calculate_boosted_weight",
    "calculate_decayed_weight",
    "clear_database",
    "clear_search_cache",
    "compute_connection_score",
    "compute_priority_score",
    "compute_recency_score",
    "compute_text_similarity_score",
    "create_backup",
    "delete_orphan_messages",
    "execute_temporal_query",
    "extract_items",
    "find_connected_entities",
    "find_duplicate_persons",
    "find_entities_by_date",
    "find_entities_in_range",
    "find_orphan_messages",
    "find_shortest_path",
    "get_cache_statistics",
    "get_cached_search_results",
    "get_cached_summary",
    "get_day_activities",
    "get_global_context_metrics",
    "get_graph_statistics",
    "get_health_monitor",
    "get_historical_relationships",
    "get_index_hint",
    "get_low_weight_relationships",
    "get_node_counts_by_type",
    "get_or_compute_summary",
    "get_or_create_day",
    "get_relationship_counts_by_type",
    "get_search_cache_stats",
    "get_search_index",
    "get_semantic_cache",
    "get_thread_context_metrics",
    "get_weekly_summary",
    "get_weight_statistics",
    "hash_query",
    "hash_query_with_params",
    "initialize_relationship_weights",
    "invalidate_search_cache",
    "invalidate_summary_cache",
    "link_to_day",
    "load_backup_from_file",
    "macro_search",
    "merge_entities",
    "meso_search",
    "micro_search",
    "parse_time_expression",
    "preview_merge",
    "reset_semantic_cache",
    "restore_backup",
    "save_backup_to_file",
    "score_and_truncate",
    "score_context_items",
    "set_cached_summary",
    "traverse_dependency_chain",
    "traverse_from_node",
    "traverse_reporting_chain",
    "truncate_by_relevance",
    "update_relationship_access",
    "validate_backup",
]
