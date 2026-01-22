"""
Semantic query caching for Klabautermann.

Caches search results based on query similarity to avoid redundant
embedding computations and graph traversals. Uses hash-based lookup
with TTL expiration.

Features:
- Hash query embeddings for fast lookup
- TTL-based expiration (default 5 minutes)
- LRU eviction when cache is full
- Statistics tracking (hit/miss rates)

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from klabautermann.core.logger import logger


# =============================================================================
# Configuration
# =============================================================================

# Default TTL for cached results (5 minutes)
DEFAULT_TTL_SECONDS = float(os.getenv("SEMANTIC_CACHE_TTL", "300"))

# Maximum number of cached entries
DEFAULT_MAX_ENTRIES = int(os.getenv("SEMANTIC_CACHE_MAX_ENTRIES", "1000"))


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CacheEntry:
    """A cached search result with metadata."""

    query_hash: str
    query_text: str
    results: list[dict[str, Any]]
    cached_at: float
    ttl_seconds: float
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return time.time() - self.cached_at > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Time since this entry was cached."""
        return time.time() - self.cached_at


@dataclass
class CacheStats:
    """Statistics about cache performance."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    current_size: int = 0
    max_size: int = DEFAULT_MAX_ENTRIES

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def miss_rate(self) -> float:
        """Calculate cache miss rate."""
        return 1.0 - self.hit_rate

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "current_size": self.current_size,
            "max_size": self.max_size,
            "hit_rate": round(self.hit_rate, 4),
        }


# =============================================================================
# Query Hashing
# =============================================================================


def hash_query(query: str) -> str:
    """
    Generate a hash for a query string.

    Uses SHA-256 truncated to 16 characters for compact storage
    while maintaining collision resistance for practical use.

    Args:
        query: The query string to hash.

    Returns:
        16-character hex hash string.
    """
    # Normalize query: lowercase, strip whitespace
    normalized = query.lower().strip()
    # Generate SHA-256 hash and truncate
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def hash_query_with_params(
    query: str,
    params: dict[str, Any] | None = None,
) -> str:
    """
    Generate a hash for a query with parameters.

    Includes any search parameters (limit, filters, etc.) in the hash
    to distinguish queries with different configurations.

    Args:
        query: The query string.
        params: Optional dictionary of search parameters.

    Returns:
        16-character hex hash string.
    """
    # Normalize query
    normalized = query.lower().strip()

    # Add sorted params to hash input
    if params:
        param_str = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
        normalized = f"{normalized}|{param_str}"

    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# =============================================================================
# Semantic Cache
# =============================================================================


class SemanticCache:
    """
    In-memory cache for semantic search results.

    Provides hash-based lookup with TTL expiration and LRU eviction.
    Thread-safe for single-threaded async use (no concurrent mutations).
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        default_ttl: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Initialize the semantic cache.

        Args:
            max_entries: Maximum number of entries to store.
            default_ttl: Default TTL in seconds for cached entries.
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._stats = CacheStats(max_size=max_entries)

    def get(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """
        Get cached results for a query.

        Args:
            query: The search query.
            params: Optional search parameters.
            trace_id: Optional trace ID for logging.

        Returns:
            Cached results if found and valid, None otherwise.
        """
        query_hash = hash_query_with_params(query, params)

        entry = self._cache.get(query_hash)

        if entry is None:
            self._stats.misses += 1
            logger.debug(
                f"[WHISPER] Cache miss for query: {query[:50]}...",
                extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
            )
            return None

        # Check expiration
        if entry.is_expired:
            self._stats.misses += 1
            self._stats.expirations += 1
            del self._cache[query_hash]
            self._stats.current_size = len(self._cache)
            logger.debug(
                f"[WHISPER] Cache expired for query: {query[:50]}...",
                extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
            )
            return None

        # Cache hit - move to end for LRU
        self._cache.move_to_end(query_hash)
        entry.hit_count += 1
        self._stats.hits += 1

        logger.debug(
            f"[WHISPER] Cache hit for query: {query[:50]}... "
            f"(age={entry.age_seconds:.1f}s, hits={entry.hit_count})",
            extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
        )

        return entry.results

    def set(
        self,
        query: str,
        results: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        ttl: float | None = None,
        trace_id: str | None = None,
    ) -> None:
        """
        Cache results for a query.

        Args:
            query: The search query.
            results: Search results to cache.
            params: Optional search parameters.
            ttl: Optional TTL override in seconds.
            trace_id: Optional trace ID for logging.
        """
        query_hash = hash_query_with_params(query, params)
        ttl_seconds = ttl if ttl is not None else self._default_ttl

        # Create entry
        entry = CacheEntry(
            query_hash=query_hash,
            query_text=query,
            results=results,
            cached_at=time.time(),
            ttl_seconds=ttl_seconds,
        )

        # Evict if at capacity
        if len(self._cache) >= self._max_entries and query_hash not in self._cache:
            # Remove oldest (first) entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._stats.evictions += 1

        # Store entry
        self._cache[query_hash] = entry
        self._cache.move_to_end(query_hash)
        self._stats.current_size = len(self._cache)

        logger.debug(
            f"[WHISPER] Cached results for query: {query[:50]}... "
            f"(results={len(results)}, ttl={ttl_seconds}s)",
            extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
        )

    def invalidate(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """
        Invalidate a specific cached query.

        Args:
            query: The search query.
            params: Optional search parameters.
            trace_id: Optional trace ID for logging.

        Returns:
            True if entry was found and removed, False otherwise.
        """
        query_hash = hash_query_with_params(query, params)

        if query_hash in self._cache:
            del self._cache[query_hash]
            self._stats.current_size = len(self._cache)
            logger.debug(
                f"[WHISPER] Invalidated cache for query: {query[:50]}...",
                extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
            )
            return True

        return False

    def clear(self, trace_id: str | None = None) -> int:
        """
        Clear all cached entries.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Number of entries cleared.
        """
        count = len(self._cache)
        self._cache.clear()
        self._stats.current_size = 0

        logger.info(
            f"[CHART] Cleared {count} cache entries",
            extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
        )

        return count

    def cleanup_expired(self, trace_id: str | None = None) -> int:
        """
        Remove all expired entries.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Number of entries removed.
        """
        expired_keys = [k for k, v in self._cache.items() if v.is_expired]

        for key in expired_keys:
            del self._cache[key]
            self._stats.expirations += 1

        self._stats.current_size = len(self._cache)

        if expired_keys:
            logger.debug(
                f"[WHISPER] Cleaned up {len(expired_keys)} expired cache entries",
                extra={"trace_id": trace_id, "agent_name": "semantic_cache"},
            )

        return len(expired_keys)

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        self._stats.current_size = len(self._cache)
        return self._stats

    def reset_stats(self) -> None:
        """Reset cache statistics (keeps entries)."""
        self._stats = CacheStats(max_size=self._max_entries)
        self._stats.current_size = len(self._cache)


# =============================================================================
# Global Cache Instance
# =============================================================================

_global_cache: SemanticCache | None = None


def get_semantic_cache() -> SemanticCache:
    """Get the global semantic cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = SemanticCache()
    return _global_cache


def reset_semantic_cache() -> None:
    """Reset the global semantic cache (for testing)."""
    global _global_cache
    _global_cache = None


# =============================================================================
# Convenience Functions
# =============================================================================


def cache_search_results(
    query: str,
    results: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    ttl: float | None = None,
    trace_id: str | None = None,
) -> None:
    """Cache search results using global cache."""
    get_semantic_cache().set(query, results, params, ttl, trace_id)


def get_cached_search_results(
    query: str,
    params: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Get cached search results from global cache."""
    return get_semantic_cache().get(query, params, trace_id)


def invalidate_search_cache(
    query: str,
    params: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> bool:
    """Invalidate a specific query in global cache."""
    return get_semantic_cache().invalidate(query, params, trace_id)


def clear_search_cache(trace_id: str | None = None) -> int:
    """Clear all entries from global cache."""
    return get_semantic_cache().clear(trace_id)


def get_search_cache_stats() -> CacheStats:
    """Get statistics from global cache."""
    return get_semantic_cache().get_stats()


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_SECONDS",
    "CacheEntry",
    "CacheStats",
    "SemanticCache",
    "cache_search_results",
    "clear_search_cache",
    "get_cached_search_results",
    "get_search_cache_stats",
    "get_semantic_cache",
    "hash_query",
    "hash_query_with_params",
    "invalidate_search_cache",
    "reset_semantic_cache",
]
