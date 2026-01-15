# Progress

Current sprint: **Sprint 2 - Multi-Agent Architecture**

## Sprint 2 Status: IN PROGRESS (Wave 2)

**Goal:** Decompose orchestrator into specialized sub-agents with MCP integration

### Current Focus (Wave 2 - COMPLETE)

Wave 2 completed all core foundation tasks. Ready for Wave 3 (MCP integrations).

| Task | Description | Status | Assignee |
|------|-------------|--------|----------|
| T023 | Ingestor agent | **completed** | carpenter |
| T024 | Researcher agent | **completed** | carpenter |
| T026 | MCP client wrapper | **completed** | purser |
| T033 | Config hot-reload | **completed** | carpenter |

### Task Status

| Task | Description | Status | Assignee |
|------|-------------|--------|----------|
| T020 | Orchestrator intent classification | **completed** | carpenter |
| T021 | Agent delegation pattern | **completed** | carpenter |
| T022 | Retry utility | **completed** | carpenter |
| T023 | Ingestor agent | **completed** | carpenter |
| T024 | Researcher agent | **completed** | carpenter |
| T025 | Hybrid search queries | **completed** | navigator |
| T026 | MCP client wrapper | **completed** | purser |
| T027 | OAuth bootstrap | **completed** | purser |
| T028 | Google Workspace bridge | **completed** | purser |
| T029 | Executor agent | **completed** | carpenter |
| T030 | Gmail handlers | pending | purser |
| T031 | Calendar handlers | pending | purser |
| T032 | Agent config system | **completed** | carpenter |
| T033 | Config hot-reload | **completed** | carpenter |
| T034 | Main.py multi-agent | **completed** | carpenter |
| T035 | Integration tests | pending | inspector |

### Next Up (Wave 3 - After Wave 2 Completes)

| Task | Assignee | Blocked By |
|------|----------|------------|
| T027 | purser | T026 |
| T029 | carpenter | T021 (done), T028 |

### Sprint 2 Completed Tasks

| Task | Description | Completed |
|------|-------------|-----------|
| T020 | Orchestrator intent classification | 2026-01-15 |
| T021 | Agent delegation pattern | 2026-01-15 |
| T022 | Retry utility | 2026-01-15 |
| T023 | Ingestor agent | 2026-01-15 |
| T024 | Researcher agent | 2026-01-15 |
| T025 | Hybrid search queries | 2026-01-15 |
| T026 | MCP client wrapper | 2026-01-15 |
| T027 | Google OAuth bootstrap | 2026-01-15 |
| T028 | Google Workspace MCP bridge | 2026-01-15 |
| T029 | Executor agent | 2026-01-15 |
| T032 | Agent config system | 2026-01-15 |
| T033 | Config hot-reload (Quartermaster) | 2026-01-15 |
| T034 | Main.py multi-agent startup | 2026-01-15 |

### Key Decisions (Sprint 2)

1. **Keyword-based intent classification**: Fast and deterministic for common patterns. LLM fallback can be added for ambiguous cases in future iterations.

2. **Intent priority order**: Search > Action > Ingestion > Conversation (first keyword match wins)

3. **Handler stubs for delegation**: T020 implements stub handlers that fall back to conversation. Full agent delegation wired in T021.

4. **Background task management**: Fire-and-forget tasks stored in `_background_tasks` set with done callback for proper cleanup.

5. **dispatch-and-wait pattern**: Uses `response_queue` field in `AgentMessage` for synchronous inter-agent calls.

6. **YAML-based config**: Agent configs in `config/agents/`, checksum-based hot-reload detection via ConfigManager.

7. **Thread-safe hot-reload**: Quartermaster bridges watchdog's observer thread with asyncio event loop using `call_soon_threadsafe` for proper async coordination. Debouncing prevents multiple rapid reloads from editor autosave.

8. **Comprehensive extraction prompt**: Ingestor includes all 20+ relationship types from ONTOLOGY.md in extraction prompt for rich entity extraction.

9. **Fire-and-forget ingestion**: Ingestor returns None from process_message(), never blocks orchestrator response to user.

10. **LLM retry pattern**: Applied @retry_on_llm_errors decorator to all LLM calls for resilience against transient failures.

11. **Graceful extraction failures**: Invalid JSON, invalid entity labels, and LLM errors are logged but don't crash the agent.

12. **Pattern-based query classification**: Researcher uses regex patterns for fast search type classification (SEMANTIC, STRUCTURAL, TEMPORAL, HYBRID) without LLM calls.

13. **Search graceful degradation**: When Graphiti or Neo4j unavailable, Researcher returns empty results rather than crashing, with fallback to semantic search for unparseable queries.

14. **Parametrized queries only**: All Cypher queries use $param placeholders, never f-strings or string concatenation. QueryBuilder wraps Neo4jClient with timing metadata via QueryResult dataclass.

15. **Comprehensive query library**: CypherQueries class provides 20+ query strings covering Person, Task, Event, Temporal, Thread, and Graph Traversal categories. All temporal queries correctly filter expired relationships.

16. **OAuth bootstrap script**: Interactive script guides users through Google OAuth2 setup, storing refresh tokens in .env with timestamped backups. Verifies credentials with test API calls before saving. Follows least-privilege principle with minimal scopes (gmail.modify, calendar.events only).

17. **Resilient MCP response parsing**: Google Workspace bridge uses forgiving parsing that fills in defaults for missing fields rather than skipping entries. Enables maximum data availability even with malformed responses.

18. **Auto-start MCP servers**: Bridge automatically starts MCP server on first operation, removing need for explicit lifecycle management. Idempotent start() allows safe repeated calls.

19. **Structured result objects**: Email/calendar operations return Result objects (SendEmailResult, CreateEventResult) with success/error state for graceful error handling at agent level.

20. **Keyword-based action parsing**: Executor uses simple keyword detection for action classification (EMAIL_SEND, EMAIL_SEARCH, CALENDAR_CREATE, CALENDAR_LIST) keeping the agent lightweight and deterministic.

21. **Three-phase action processing**: All actions follow parse → validate → execute pattern with strict validation before any MCP operations.

22. **Security-first validation**: Executor NEVER sends emails to unverified addresses, NEVER creates events without valid times, and NEVER guesses missing information. Always asks user for clarification.

23. **Clean application lifecycle**: Main.py implements three-phase pattern (initialize → start → shutdown) with proper resource management and signal handling. All agents, clients, and config watchers created once and shared across system.

24. **Graceful degradation**: System continues without Graphiti/Ingestor if OPENAI_API_KEY missing. Graphiti is optional for entity extraction but system remains functional for search and actions.

---

## Sprint 1 Status: COMPLETE

**Goal:** Build the skeleton that everything else hangs on.

### Completed Tasks

| Task | Description | Status |
|------|-------------|--------|
| T001 | Docker Compose configuration | Done |
| T002 | Python Dockerfile | Done |
| T003 | Project directory structure | Done |
| T004 | Environment configuration | Done |
| T005 | Pydantic core models | Done |
| T006 | Ontology constants | Done |
| T007 | Database initialization | Done |
| T008 | Nautical logging system | Done |
| T009 | Graphiti client wrapper | Done |
| T010 | Neo4j direct client | Done |
| T011 | Thread manager | Done |
| T012 | Custom exceptions | Done |
| T013 | Base channel interface | Done |
| T014 | CLI driver | Done |
| T015 | Thread persistence | Done |
| T016 | Base agent class | Done |
| T017 | Simple Orchestrator | Done |
| T018 | Main entry point | Done |
| T019 | E2E integration test | Done |

### Key Decisions Made

1. **Simple Orchestrator First**: Sprint 1 orchestrator calls Claude directly without sub-agent delegation. Full multi-agent architecture deferred to Sprint 2.

2. **Fire-and-Forget Ingestion**: Entity extraction runs asynchronously via `asyncio.create_task()` - user responses not blocked by graph updates.

3. **Graphiti Optional**: System gracefully degrades if Graphiti unavailable, falls back to direct Neo4j operations.

4. **Context Window**: 15 messages default for conversation context.

5. **Nautical Logging Levels**: [WHISPER] debug, [CHART] info, [BEACON] warning, [SWELL] error, [STORM] critical, [SHIPWRECK] fatal.

### Patterns Established

- All data structures use Pydantic models with validation
- Neo4j queries always parametrized (never f-strings with user input)
- All I/O operations are async
- Trace IDs propagated through all operations
- Channel abstraction allows multiple input sources
- Intent classification keywords as `ClassVar[list[str]]` class attributes
- Handler methods prefixed with `_handle_` for intent dispatch

### Next Steps (Wave 3 - MCP Integration)

1. **T027**: OAuth2 bootstrap script for Google Workspace
2. **T028**: Google Workspace MCP bridge (Gmail + Calendar)
3. **T029**: Executor agent with MCP tool invocation
4. **T030/T031**: Gmail and Calendar tool handlers

## Blockers

None currently.

## Recent Activity

- 2026-01-15: T034 completed - Main.py multi-agent startup with clean lifecycle management (initialize → start → shutdown). All agents, shared resources, signal handlers, and hot-reload wired up for Sprint 2 architecture
- 2026-01-15: T029 completed - Executor agent with 48 unit tests (syntax validated). Implements secure action execution with parse-validate-execute pattern and never hallucniates missing information
- 2026-01-15: T028 completed - Google Workspace MCP bridge with 27 passing unit tests. Provides clean interface to Gmail and Calendar via MCP with Pydantic-validated responses
- 2026-01-15: T027 completed - Google OAuth bootstrap script with interactive credential setup, verification, and secure .env storage
- 2026-01-15: **Wave 2 COMPLETE** - All core agent and infrastructure tasks completed
- 2026-01-15: T025 completed - Hybrid search queries with 50+ unit tests. Parametrized Cypher query library with QueryBuilder and QueryResult metadata tracking
- 2026-01-15: T026 completed - MCP client wrapper with 13 passing unit tests, JSON-RPC over stdio, async queue testing pattern established
- 2026-01-15: T033 completed - Quartermaster hot-reload with 28 unit tests, thread-safe watchdog integration for zero-downtime config updates
- 2026-01-15: T024 completed - Researcher agent with 36 unit tests, all passing. Implements hybrid search with SEMANTIC, STRUCTURAL, TEMPORAL, and HYBRID strategies
- 2026-01-15: T023 completed - Ingestor agent with 15 unit tests, all passing
- 2026-01-15: Wave 2 started - T023, T024, T026, T033 in progress
- 2026-01-15: T021, T022, T032 completed - Wave 1 complete
- 2026-01-15: T020 complete - Intent classification with 26 unit tests
- 2026-01-15: Sprint 1 complete - all 19 foundation tasks implemented
