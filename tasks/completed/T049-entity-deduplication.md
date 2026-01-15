# Entity Deduplication

## Metadata
- **ID**: T049
- **Priority**: P2
- **Category**: core
- **Effort**: L
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 7.1 (Deduplication)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.5 (Archivist deduplication)

## Dependencies
- [x] T010 - Neo4j client
- [x] T040 - Archivist Agent Skeleton

## Context
Over time, the same person or organization may be created multiple times with slight name variations ("Sarah", "Sarah Johnson", "S. Johnson"). The Archivist needs to detect and merge these duplicates. High-confidence matches are merged automatically; ambiguous cases are flagged for user review.

## Requirements
- [x] Create `src/klabautermann/memory/deduplication.py`:

### Duplicate Detection
- [x] `find_duplicate_persons(driver: AsyncDriver) -> list[DuplicateCandidate]`
  - Find Person nodes with similar names
  - Find Person nodes with same email
  - Score similarity (0.0 to 1.0)

- [x] `find_duplicate_organizations(driver: AsyncDriver) -> list[DuplicateCandidate]`
  - Find Org nodes with similar names
  - Find Org nodes with same domain

### DuplicateCandidate Model
- [x] Add to `core/models.py`:
  ```python
  class DuplicateCandidate(BaseModel):
      uuid1: str
      uuid2: str
      name1: str
      name2: str
      entity_type: str  # Person, Organization
      similarity_score: float
      match_reasons: list[str]  # ["same_email", "similar_name"]
  ```

### Merge Operations
- [x] `merge_entities(keep_uuid: str, remove_uuid: str, entity_type: str) -> bool`
  - Transfer all relationships to kept node
  - Merge properties (keep existing, fill missing)
  - Delete duplicate node
  - Log merge action

- [x] `flag_for_review(candidate: DuplicateCandidate) -> str`
  - Create [:POTENTIAL_DUPLICATE] relationship
  - Add to user review queue
  - Return flag UUID

### Similarity Scoring
- [x] Name similarity: Levenshtein distance or fuzzy match
- [x] Email match: exact match = 1.0, domain match = 0.5
- [x] Combined score with weights

### Thresholds
- [x] Auto-merge: score >= 0.9
- [x] Flag for review: 0.7 <= score < 0.9
- [x] Ignore: score < 0.7

## Acceptance Criteria
- [x] Same-email persons detected as duplicates
- [x] Similar names scored appropriately
- [x] High-confidence duplicates auto-merged
- [x] Ambiguous duplicates flagged for review
- [x] Merge transfers all relationships
- [x] Merge preserves merged-into node properties
- [x] Unit tests for detection and merging

## Implementation Notes

```python
from rapidfuzz import fuzz
from pydantic import BaseModel

class DuplicateCandidate(BaseModel):
    uuid1: str
    uuid2: str
    name1: str
    name2: str
    entity_type: str
    similarity_score: float
    match_reasons: list[str]


async def find_duplicate_persons(
    driver: AsyncDriver,
    min_score: float = 0.7
) -> list[DuplicateCandidate]:
    """Find potential duplicate Person nodes."""
    candidates = []

    async with driver.session() as session:
        # Find exact email matches
        email_result = await session.run(
            """
            MATCH (p1:Person), (p2:Person)
            WHERE p1.uuid < p2.uuid
              AND p1.email IS NOT NULL
              AND p1.email = p2.email
            RETURN p1.uuid as uuid1, p1.name as name1,
                   p2.uuid as uuid2, p2.name as name2,
                   p1.email as email
            """
        )
        for record in await email_result.data():
            candidates.append(DuplicateCandidate(
                uuid1=record["uuid1"],
                uuid2=record["uuid2"],
                name1=record["name1"],
                name2=record["name2"],
                entity_type="Person",
                similarity_score=1.0,
                match_reasons=["same_email"]
            ))

        # Find similar names
        name_result = await session.run(
            """
            MATCH (p:Person)
            RETURN p.uuid as uuid, p.name as name
            """
        )
        persons = await name_result.data()

        # Compare all pairs (O(n^2) - consider optimization for large graphs)
        for i, p1 in enumerate(persons):
            for p2 in persons[i+1:]:
                name_similarity = fuzz.ratio(
                    p1["name"].lower(),
                    p2["name"].lower()
                ) / 100.0

                if name_similarity >= min_score:
                    # Check if already in candidates (from email match)
                    if not _already_candidate(candidates, p1["uuid"], p2["uuid"]):
                        candidates.append(DuplicateCandidate(
                            uuid1=p1["uuid"],
                            uuid2=p2["uuid"],
                            name1=p1["name"],
                            name2=p2["name"],
                            entity_type="Person",
                            similarity_score=name_similarity,
                            match_reasons=["similar_name"]
                        ))

    return candidates


async def merge_entities(
    driver: AsyncDriver,
    keep_uuid: str,
    remove_uuid: str,
    entity_type: str
) -> bool:
    """Merge duplicate entities, keeping all relationships."""
    async with driver.session() as session:
        # Transfer incoming relationships
        await session.run(
            f"""
            MATCH (keep:{entity_type} {{uuid: $keep_uuid}})
            MATCH (remove:{entity_type} {{uuid: $remove_uuid}})

            // Transfer incoming relationships
            MATCH (remove)<-[r]-(other)
            WHERE other <> keep
            WITH keep, remove, r, other, type(r) as rel_type
            CALL apoc.create.relationship(other, rel_type, properties(r), keep) YIELD rel
            DELETE r

            // Transfer outgoing relationships
            WITH keep, remove
            MATCH (remove)-[r]->(other)
            WHERE other <> keep
            WITH keep, remove, r, other, type(r) as rel_type
            CALL apoc.create.relationship(keep, rel_type, properties(r), other) YIELD rel
            DELETE r
            """,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid}
        )

        # Merge properties (keep existing, fill missing)
        await session.run(
            f"""
            MATCH (keep:{entity_type} {{uuid: $keep_uuid}})
            MATCH (remove:{entity_type} {{uuid: $remove_uuid}})
            SET keep.bio = COALESCE(keep.bio, remove.bio),
                keep.phone = COALESCE(keep.phone, remove.phone),
                keep.linkedin_url = COALESCE(keep.linkedin_url, remove.linkedin_url),
                keep.updated_at = timestamp()
            DELETE remove
            """,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid}
        )

        logger.info(f"[BEACON] Merged {entity_type} {remove_uuid} into {keep_uuid}")
        return True


async def process_duplicates(
    driver: AsyncDriver,
    auto_merge_threshold: float = 0.9,
    review_threshold: float = 0.7
) -> dict:
    """Find and process all duplicates."""
    stats = {"auto_merged": 0, "flagged_for_review": 0}

    candidates = await find_duplicate_persons(driver, min_score=review_threshold)

    for candidate in candidates:
        if candidate.similarity_score >= auto_merge_threshold:
            await merge_entities(
                driver,
                candidate.uuid1,
                candidate.uuid2,
                candidate.entity_type
            )
            stats["auto_merged"] += 1
        else:
            await flag_for_review(driver, candidate)
            stats["flagged_for_review"] += 1

    return stats
```

### Note on APOC
The merge queries use APOC procedures for dynamic relationship creation. If APOC is not available, use multiple type-specific queries instead.

### Performance Optimization
For large graphs, consider:
- Blocking by first letter of name
- Using trigram indexes
- Batch processing with limits

---

## Development Notes

### Implementation
**Files Created:**
- `src/klabautermann/memory/deduplication.py` - Full deduplication module with all required functions
- `tests/unit/test_deduplication.py` - Comprehensive unit tests (22 tests, all passing)

**Files Modified:**
- `src/klabautermann/core/models.py` - Added `DuplicateCandidate` Pydantic model with validation
- `pyproject.toml` - Added `rapidfuzz>=3.0` dependency for fuzzy string matching

### Decisions Made

1. **APOC-Free Implementation**: Used type-specific FOREACH queries instead of APOC's dynamic relationship creation to avoid external dependency. This keeps the implementation portable across Neo4j deployments.

2. **Similarity Algorithm**: Chose `rapidfuzz.fuzz.ratio()` (Levenshtein-based) for name matching. It provides good balance between accuracy and performance for short strings like names.

3. **Multi-Stage Detection**:
   - Exact email match (score = 1.0)
   - Email domain match combined with name similarity (score = (0.5 + name_sim) / 2)
   - Pure name similarity using fuzzy matching
   This catches different types of duplicates at appropriate confidence levels.

4. **Graceful Error Handling**: Used `.get()` for dict access to handle empty query results without crashing. Returns False on merge failure, allowing caller to handle appropriately.

5. **Property Merging Strategy**: COALESCE approach - keep existing properties on kept node, only fill in missing values from removed node. This preserves higher-quality data.

### Patterns Established

1. **Neo4jClient Usage**: All queries use `execute_read` for read-only operations and `execute_write` for mutations, following the established pattern in `memory/queries.py`.

2. **Nautical Logging**: Used consistent logging levels:
   - `[CHART]` for starting operations
   - `[BEACON]` for successful completions
   - `[WHISPER]` for debug details
   - `[STORM]` for errors

3. **Parametrized Queries**: All Cypher queries use parameter binding (`$param`) to prevent injection, following the safety pattern from `neo4j_client.py`.

4. **Type-Specific Merge Queries**: Separate property merge logic for Person vs Organization, allowing for entity-specific field handling.

### Testing

**Test Coverage:**
- Duplicate detection (exact email, domain match, name similarity)
- Threshold filtering (min_score respected)
- Duplicate avoidance (no repeated candidates)
- Merge operations (persons, organizations, error handling)
- Flag for review functionality
- Full pipeline processing (auto-merge, flag, ignore)
- Pydantic model validation

**All 22 tests passing.** Tests use AsyncMock for Neo4jClient to avoid database dependency.

### Issues Encountered

1. **Initial Test Failure**: Name similarity scores were higher than expected. "John Smith" vs "John Smyth" = 0.95, "Robert" vs "Roberto" = 0.92. Had to use "Michael" vs "Michelle" (0.80) for medium-confidence test case.

2. **Dict Access Error**: Initial implementation used `result[0]["key"]` which threw KeyError on empty results. Changed to `result[0].get("key", 0) if result else 0` for safety.

### Next Steps

This module can be integrated into the Archivist agent for periodic deduplication runs. Consider:
- Adding scheduled execution (daily/weekly)
- Building UI for reviewing flagged duplicates
- Optimizing for large graphs (>1000 entities) with blocking strategies
- Adding metrics tracking (merge rate, false positive rate)
