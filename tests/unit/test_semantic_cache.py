"""Unit tests for semantic query caching."""

from __future__ import annotations

import time

import pytest

from klabautermann.memory.semantic_cache import (
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


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_global_cache() -> None:
    """Reset global cache before each test."""
    reset_semantic_cache()


@pytest.fixture
def cache() -> SemanticCache:
    """Create a fresh cache instance."""
    return SemanticCache(max_entries=10, default_ttl=60.0)


@pytest.fixture
def sample_results() -> list[dict]:
    """Sample search results."""
    return [
        {"uuid": "person-1", "name": "John Doe", "score": 0.95},
        {"uuid": "person-2", "name": "Jane Smith", "score": 0.87},
    ]


# =============================================================================
# Hash Function Tests
# =============================================================================


class TestHashQuery:
    """Test query hashing functions."""

    def test_hash_query_produces_consistent_hash(self) -> None:
        """Test that same query produces same hash."""
        query = "What is John's email?"
        hash1 = hash_query(query)
        hash2 = hash_query(query)

        assert hash1 == hash2

    def test_hash_query_normalizes_case(self) -> None:
        """Test that queries are case-normalized."""
        hash1 = hash_query("What is JOHN's email?")
        hash2 = hash_query("what is john's email?")

        assert hash1 == hash2

    def test_hash_query_normalizes_whitespace(self) -> None:
        """Test that queries are whitespace-normalized."""
        hash1 = hash_query("  What is John's email?  ")
        hash2 = hash_query("What is John's email?")

        assert hash1 == hash2

    def test_hash_query_returns_16_chars(self) -> None:
        """Test that hash is 16 hex characters."""
        query_hash = hash_query("Test query")

        assert len(query_hash) == 16
        assert all(c in "0123456789abcdef" for c in query_hash)

    def test_different_queries_produce_different_hashes(self) -> None:
        """Test that different queries produce different hashes."""
        hash1 = hash_query("What is John's email?")
        hash2 = hash_query("Who does John work for?")

        assert hash1 != hash2

    def test_hash_with_params_includes_params(self) -> None:
        """Test that params affect the hash."""
        query = "Find people"
        hash1 = hash_query_with_params(query, {"limit": 10})
        hash2 = hash_query_with_params(query, {"limit": 20})
        hash3 = hash_query_with_params(query, None)

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_hash_with_params_sorted_consistently(self) -> None:
        """Test that param order doesn't affect hash."""
        query = "Find people"
        hash1 = hash_query_with_params(query, {"limit": 10, "offset": 5})
        hash2 = hash_query_with_params(query, {"offset": 5, "limit": 10})

        assert hash1 == hash2


# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_entry_not_expired_when_fresh(self) -> None:
        """Test fresh entry is not expired."""
        entry = CacheEntry(
            query_hash="abc123",
            query_text="test query",
            results=[],
            cached_at=time.time(),
            ttl_seconds=60.0,
        )

        assert not entry.is_expired

    def test_entry_expired_after_ttl(self) -> None:
        """Test entry expires after TTL."""
        entry = CacheEntry(
            query_hash="abc123",
            query_text="test query",
            results=[],
            cached_at=time.time() - 120,  # 2 minutes ago
            ttl_seconds=60.0,  # 1 minute TTL
        )

        assert entry.is_expired

    def test_age_seconds_calculation(self) -> None:
        """Test age calculation."""
        entry = CacheEntry(
            query_hash="abc123",
            query_text="test query",
            results=[],
            cached_at=time.time() - 30,  # 30 seconds ago
            ttl_seconds=60.0,
        )

        assert 29 <= entry.age_seconds <= 32


# =============================================================================
# CacheStats Tests
# =============================================================================


class TestCacheStats:
    """Test CacheStats dataclass."""

    def test_hit_rate_calculation(self) -> None:
        """Test hit rate is calculated correctly."""
        stats = CacheStats(hits=7, misses=3)

        assert stats.hit_rate == 0.7

    def test_hit_rate_zero_when_no_requests(self) -> None:
        """Test hit rate is 0 when no requests."""
        stats = CacheStats()

        assert stats.hit_rate == 0.0

    def test_miss_rate_calculation(self) -> None:
        """Test miss rate is inverse of hit rate."""
        stats = CacheStats(hits=7, misses=3)

        assert abs(stats.miss_rate - 0.3) < 0.001

    def test_to_dict(self) -> None:
        """Test converting stats to dictionary."""
        stats = CacheStats(
            hits=10,
            misses=5,
            evictions=2,
            expirations=1,
            current_size=50,
            max_size=100,
        )

        data = stats.to_dict()

        assert data["hits"] == 10
        assert data["misses"] == 5
        assert data["evictions"] == 2
        assert data["hit_rate"] == round(10 / 15, 4)


# =============================================================================
# SemanticCache Tests
# =============================================================================


class TestSemanticCache:
    """Test SemanticCache class."""

    def test_get_returns_none_for_miss(self, cache: SemanticCache) -> None:
        """Test get returns None on cache miss."""
        result = cache.get("unknown query")

        assert result is None

    def test_set_and_get_basic(self, cache: SemanticCache, sample_results: list[dict]) -> None:
        """Test basic set and get."""
        query = "Find John"

        cache.set(query, sample_results)
        result = cache.get(query)

        assert result == sample_results

    def test_get_returns_none_after_expiration(self, sample_results: list[dict]) -> None:
        """Test that expired entries return None."""
        cache = SemanticCache(default_ttl=0.1)  # 100ms TTL

        cache.set("test query", sample_results)
        time.sleep(0.15)  # Wait for expiration

        result = cache.get("test query")

        assert result is None

    def test_stats_track_hits_and_misses(
        self, cache: SemanticCache, sample_results: list[dict]
    ) -> None:
        """Test that stats track hits and misses."""
        cache.set("query1", sample_results)

        cache.get("query1")  # Hit
        cache.get("query1")  # Hit
        cache.get("query2")  # Miss

        stats = cache.get_stats()

        assert stats.hits == 2
        assert stats.misses == 1

    def test_lru_eviction_on_capacity(self, sample_results: list[dict]) -> None:
        """Test LRU eviction when cache is full."""
        cache = SemanticCache(max_entries=3)

        cache.set("query1", sample_results)
        cache.set("query2", sample_results)
        cache.set("query3", sample_results)
        cache.set("query4", sample_results)  # Should evict query1

        assert cache.get("query1") is None  # Evicted
        assert cache.get("query2") is not None
        assert cache.get("query4") is not None

    def test_lru_updates_on_access(self, sample_results: list[dict]) -> None:
        """Test that accessing an entry updates its LRU position."""
        cache = SemanticCache(max_entries=3)

        cache.set("query1", sample_results)
        cache.set("query2", sample_results)
        cache.set("query3", sample_results)

        # Access query1 to move it to end
        cache.get("query1")

        # Add new entry - should evict query2 (oldest unused)
        cache.set("query4", sample_results)

        assert cache.get("query1") is not None  # Still present
        assert cache.get("query2") is None  # Evicted
        assert cache.get("query3") is not None

    def test_invalidate_removes_entry(
        self, cache: SemanticCache, sample_results: list[dict]
    ) -> None:
        """Test invalidate removes specific entry."""
        cache.set("query1", sample_results)
        cache.set("query2", sample_results)

        result = cache.invalidate("query1")

        assert result is True
        assert cache.get("query1") is None
        assert cache.get("query2") is not None

    def test_invalidate_returns_false_for_missing(self, cache: SemanticCache) -> None:
        """Test invalidate returns False for missing entry."""
        result = cache.invalidate("nonexistent")

        assert result is False

    def test_clear_removes_all_entries(
        self, cache: SemanticCache, sample_results: list[dict]
    ) -> None:
        """Test clear removes all entries."""
        cache.set("query1", sample_results)
        cache.set("query2", sample_results)

        count = cache.clear()

        assert count == 2
        assert cache.get("query1") is None
        assert cache.get("query2") is None

    def test_cleanup_expired_removes_old_entries(self, sample_results: list[dict]) -> None:
        """Test cleanup_expired removes expired entries."""
        cache = SemanticCache(default_ttl=0.1)

        cache.set("query1", sample_results)
        time.sleep(0.15)  # Let it expire
        cache.set("query2", sample_results)  # Fresh entry

        removed = cache.cleanup_expired()

        assert removed == 1
        assert cache.get("query2") is not None

    def test_params_affect_cache_key(
        self, cache: SemanticCache, sample_results: list[dict]
    ) -> None:
        """Test that different params create different cache entries."""
        query = "Find people"

        cache.set(query, sample_results, params={"limit": 10})
        cache.set(query, [{"different": "results"}], params={"limit": 20})

        result1 = cache.get(query, params={"limit": 10})
        result2 = cache.get(query, params={"limit": 20})

        assert result1 == sample_results
        assert result2 == [{"different": "results"}]

    def test_custom_ttl_per_entry(self, cache: SemanticCache, sample_results: list[dict]) -> None:
        """Test that TTL can be customized per entry."""
        cache.set("short", sample_results, ttl=0.1)
        cache.set("long", sample_results, ttl=60.0)

        time.sleep(0.15)

        assert cache.get("short") is None
        assert cache.get("long") is not None

    def test_reset_stats_keeps_entries(
        self, cache: SemanticCache, sample_results: list[dict]
    ) -> None:
        """Test reset_stats clears stats but keeps entries."""
        cache.set("query", sample_results)
        cache.get("query")  # Hit

        stats_before = cache.get_stats()
        assert stats_before.hits == 1

        cache.reset_stats()

        stats_after = cache.get_stats()
        assert stats_after.hits == 0
        assert cache.get("query") is not None  # Entry still there


# =============================================================================
# Global Cache Functions Tests
# =============================================================================


class TestGlobalCacheFunctions:
    """Test convenience functions using global cache."""

    def test_get_semantic_cache_returns_singleton(self) -> None:
        """Test that get_semantic_cache returns singleton."""
        cache1 = get_semantic_cache()
        cache2 = get_semantic_cache()

        assert cache1 is cache2

    def test_cache_and_get_search_results(self, sample_results: list[dict]) -> None:
        """Test convenience functions for caching."""
        cache_search_results("test query", sample_results)
        result = get_cached_search_results("test query")

        assert result == sample_results

    def test_invalidate_search_cache_function(self, sample_results: list[dict]) -> None:
        """Test invalidate convenience function."""
        cache_search_results("test query", sample_results)
        invalidate_search_cache("test query")

        assert get_cached_search_results("test query") is None

    def test_clear_search_cache_function(self, sample_results: list[dict]) -> None:
        """Test clear convenience function."""
        cache_search_results("query1", sample_results)
        cache_search_results("query2", sample_results)

        count = clear_search_cache()

        assert count == 2
        assert get_cached_search_results("query1") is None

    def test_get_search_cache_stats_function(self, sample_results: list[dict]) -> None:
        """Test stats convenience function."""
        cache_search_results("query", sample_results)
        get_cached_search_results("query")
        get_cached_search_results("missing")

        stats = get_search_cache_stats()

        assert stats.hits == 1
        assert stats.misses == 1

    def test_reset_semantic_cache_creates_new_instance(self, sample_results: list[dict]) -> None:
        """Test reset creates new cache instance."""
        cache_search_results("query", sample_results)

        reset_semantic_cache()

        assert get_cached_search_results("query") is None
