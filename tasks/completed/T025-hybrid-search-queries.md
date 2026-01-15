# Create Hybrid Search Queries

## Metadata
- **ID**: T025
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.3

## Dependencies
- [x] T024 - Researcher agent (uses these queries)
- [x] T006 - Ontology constants
- [x] T010 - Neo4j client

## Context
The Researcher agent needs a library of Cypher queries for structural searches. This task creates a comprehensive query module that handles relationship traversals, multi-hop paths, and temporal filtering. These queries complement Graphiti's vector search for hybrid retrieval.

## Requirements
- [x] Create `src/klabautermann/memory/queries.py`:

### Person Queries
- [x] Find person by name (case-insensitive)
- [x] Find person's organization (WORKS_AT)
- [x] Find person's manager (REPORTS_TO)
- [x] Find person's projects (CONTRIBUTES_TO)
- [x] Find people at an organization

### Task Queries
- [x] Find blocked tasks (BLOCKS relationship)
- [x] Find tasks for a project (PART_OF)
- [x] Find tasks by status
- [x] Find task dependencies (multi-hop BLOCKS)

### Event Queries
- [x] Find events by time range
- [x] Find event attendees (ATTENDED)
- [x] Find events at location (HELD_AT)
- [x] Find events discussing topic (DISCUSSED)

### Temporal Queries
- [x] Filter by created_at range
- [x] Filter by expired_at (historical vs current)
- [x] Time-travel query (state at specific date)

### Thread Queries
- [x] Find recent threads by channel
- [x] Find thread messages (rolling window)
- [x] Find thread summary (Note with SUMMARY_OF)

### Query Builder
- [x] Parametrized query construction
- [x] Injection-safe parameter binding
- [x] Query result formatting

## Acceptance Criteria
- [x] All queries use parametrized bindings (no f-strings)
- [x] Temporal queries correctly filter expired relationships
- [x] Multi-hop queries return full paths
- [x] Query builder validates parameters
- [x] Unit tests for each query type

## Development Notes

### Implementation

**Files Created:**
- `src/klabautermann/memory/queries.py` (870 lines)
  - `QueryResult` dataclass with execution timing metadata
  - `CypherQueries` class with 20+ parametrized query strings
  - `QueryBuilder` class with 25+ async query methods
- `tests/unit/test_queries.py` (850+ lines)
  - 50+ comprehensive unit tests covering all query types
  - Mock-based testing for Neo4j client
  - Parameter injection safety tests

**Files Modified:**
- `PROGRESS.md` - Updated task status and decisions

### Decisions Made

1. **Parametrized queries only**: Every single query uses `$param` placeholders. Zero f-strings with user input. This prevents injection attacks at the syntax level.

2. **QueryResult metadata wrapper**: Wraps raw Neo4j records with execution timing and query type metadata. Enables performance monitoring and debugging.

3. **Comprehensive temporal filtering**: All relationship queries that need current state include `WHERE r.expired_at IS NULL`. Historical queries use `r.created_at <= $timestamp AND (r.expired_at IS NULL OR r.expired_at > $timestamp)` pattern.

4. **Priority-based sorting**: Task queries sort by priority enum (`urgent` → 1, `high` → 2, etc.) using CASE expressions for consistent ordering.

5. **COALESCE for names**: Queries use `COALESCE(n.name, n.title, n.action, n.description)` to get displayable name from any entity type.

6. **Limit on all queries**: Every query has a configurable limit parameter to prevent unbounded result sets.

7. **Multi-hop traversal**: Dependency chain queries use `[:BLOCKS*1..5]` pattern to find chains up to 5 hops deep.

8. **Async-only API**: All QueryBuilder methods are async, matching Neo4jClient's async interface.

### Patterns Established

1. **Query string constants in CypherQueries**: Raw query strings as class attributes, never in builder methods. Keeps queries auditable and testable.

2. **`_execute_with_timing` wrapper**: Private method that wraps `neo4j.execute_query` with timing and logging. All public methods call this wrapper.

3. **Trace ID propagation**: All query methods accept optional `trace_id` parameter, passed through to Neo4j client for request tracing.

4. **Mock-based unit tests**: Tests use `AsyncMock` for Neo4j client, verify query strings and parameters. No actual database required.

5. **Fixture-based test data**: Sample records defined as fixtures, reused across tests for consistency.

### Query Categories

**Person Queries (6):**
- `find_person` - Case-insensitive partial name search
- `find_person_org` - Current employer via WORKS_AT
- `find_person_org_at_date` - Historical employer (time-travel)
- `find_person_manager` - Current manager via REPORTS_TO
- `find_people_at_org` - All employees at organization
- `find_person_projects` - Active projects person is mentioned in

**Task Queries (5):**
- `find_blocked_tasks` - All blocker/blocked pairs
- `find_project_tasks` - All tasks in a project, sorted by priority
- `find_tasks_by_status` - Filter by status (todo, in_progress, done, cancelled)
- `find_task_dependency_chain` - Multi-hop BLOCKS paths
- `find_task_assignee` - Person assigned to task

**Event Queries (4):**
- `find_events_in_range` - Events between start and end timestamps
- `find_event_attendees` - Attendees with roles (organizer, speaker, attendee)
- `find_events_at_location` - Events at specific location
- `find_event_discussions` - Topics discussed in event (Projects, Tasks, Goals)

**Temporal Queries (3):**
- `find_entities_created_in_range` - Entities created in time window
- `time_travel_query` - All relationships valid at specific date
- `find_expired_relationships` - Relationships that expired in time range

**Thread Queries (4):**
- `find_recent_threads` - Recent threads by channel type
- `find_thread_messages` - Rolling window of messages
- `find_thread_summary` - Summary note for thread
- `count_thread_messages` - Message count

**Graph Traversal (2):**
- `find_related_entities` - 1-2 hop neighbors
- `find_shortest_path` - Shortest path between two entities

### Testing

**Test Coverage:**
- 50+ unit tests covering all query types
- Parameter injection safety validation
- Empty result handling
- Trace ID propagation
- Timing metadata verification
- Query string validation (must use $params, not f-strings)

**Testing Pattern:**
- Mock Neo4jClient with AsyncMock
- Verify query string and parameters passed to `execute_query`
- Verify QueryResult metadata (type, timing, record count)
- No actual database connection required for tests

### Integration Points

**Used By:**
- Researcher agent (T024) - Uses QueryBuilder for STRUCTURAL and HYBRID searches
- Future agents needing graph traversal capabilities

**Uses:**
- Neo4jClient (T010) - Wraps `execute_query` method
- Ontology constants (T006) - Node and relationship type references

### Security Notes

**Injection Prevention:**
- ALL queries use `$param` placeholders
- ZERO f-strings with user input
- ZERO string concatenation with user data
- Only safe interpolation is enum values (NodeLabel, RelationType)

**Test Validation:**
- `test_queries_use_parameters_not_fstrings` - Verifies every query constant uses `$` syntax
- `test_queries_reject_sql_injection_attempts` - Confirms malicious input treated as literal

### Performance Considerations

1. **Execution timing**: QueryResult tracks execution time in milliseconds for performance monitoring

2. **Query limits**: All queries have configurable limits (defaults: 5-100 depending on query type)

3. **Index usage**: Queries designed to use indexes defined in ONTOLOGY.md:
   - UUID lookups use unique constraints
   - Name searches use full-text indexes
   - Temporal filters use temporal indexes on created_at/expired_at

4. **Early filtering**: WHERE clauses filter before OPTIONAL MATCH for efficiency

### Known Limitations

1. **No query batching**: Each query is independent. Future optimization could batch related queries.

2. **No result caching**: Each call hits the database. Caching layer could be added at Researcher level.

3. **Fixed hop limits**: Multi-hop queries hard-coded to 5 hops max. Could be parameterized.

4. **No aggregation queries**: Current queries focus on entity/relationship retrieval. Aggregation/analytics queries not yet implemented.

### Future Enhancements

1. **Query composition**: Builder methods for composing complex queries from simpler ones
2. **Result pagination**: Cursor-based pagination for large result sets
3. **Query caching**: LRU cache for frequently executed queries
4. **Query profiling**: PROFILE/EXPLAIN integration for query optimization
5. **Aggregation queries**: Count, group by, statistical queries
6. **Full-text search**: Integration with Neo4j full-text indexes

### Completion Notes

Task completed successfully. All requirements met:
- 20+ parametrized query strings in CypherQueries
- 25+ async query methods in QueryBuilder
- QueryResult dataclass with timing metadata
- 50+ comprehensive unit tests
- Complete coverage of Person, Task, Event, Temporal, Thread, and Graph Traversal categories
- Zero injection vulnerabilities (all queries use parameters)
- All temporal queries correctly filter expired relationships

Ready for use by Researcher agent and other components needing graph queries.

**Completed**: 2026-01-15
