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
from klabautermann.memory.zoom_search import (
    MacroSearchResult,
    MesoSearchResult,
    MicroSearchResult,
    ZoomLevelSelector,
    auto_zoom_search,
    macro_search,
    meso_search,
    micro_search,
)


__all__ = [
    # Clients
    "CypherQueries",
    "GraphitiClient",
    "Neo4jClient",
    "QueryBuilder",
    "QueryResult",
    "QueryTimeoutError",
    "ThreadManager",
    # Graph Statistics
    "GraphStatistics",
    "get_graph_statistics",
    "get_node_counts_by_type",
    "get_relationship_counts_by_type",
    # Context Statistics
    "ContextWindowMetrics",
    "GlobalContextMetrics",
    "get_global_context_metrics",
    "get_thread_context_metrics",
    # Orphan Cleanup
    "OrphanCleanupResult",
    "delete_orphan_messages",
    "find_orphan_messages",
    # Health Monitor
    "MemoryHealthMonitor",
    "MemoryHealthStatus",
    "get_health_monitor",
    # Zoom Search
    "MacroSearchResult",
    "MesoSearchResult",
    "MicroSearchResult",
    "ZoomLevelSelector",
    "auto_zoom_search",
    "macro_search",
    "meso_search",
    "micro_search",
    # Entity Merge
    "DuplicateCandidate",
    "MergePreview",
    "MergeResult",
    "find_duplicate_persons",
    "merge_entities",
    "preview_merge",
    # Temporal Spine
    "DayActivity",
    "DayNode",
    "find_entities_by_date",
    "find_entities_in_range",
    "get_day_activities",
    "get_or_create_day",
    "get_weekly_summary",
    "link_to_day",
]
