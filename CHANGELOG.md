# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Remove keyword-based intent classification fallback - pure LLM semantic understanding only (#2, #354)
- Remove keyword-based zoom level detection fallback - AI-first approach with graceful degradation (#355)

### Fixed
- Integration test mocks for Archivist, Scribe, Executor, and Context flows (#247, #248, #249, #250)
  - Fix `create_note_with_links` mock to return expected `note_uuid` and `entity_link_count`
  - Fix Executor test to use correct method name `_handle_gmail_send`
  - Fix context query function patches to use correct module path with `AsyncMock`

### Added
- HullCleaner orphan message management (#82, #83)
  - `find_orphan_messages()` detects messages without thread connections
  - `remove_orphan_messages()` with dry-run support and audit logging
  - `scrape_barnacles()` now includes orphan cleanup in full maintenance
  - Configurable via `remove_orphan_messages` and `orphan_batch_size` settings
  - Integration with existing `orphan_cleanup.py` infrastructure
  - 8 new unit tests (33 total for HullCleaner)
- HullCleaner agent for graph maintenance (#79, #80, #81, #88)
  - `HullCleaner` agent skeleton extending `BaseAgent`
  - `HullCleanerConfig` for configurable pruning behavior (threshold, age_days, dry_run)
  - `PruningAction` enum for tracking operation types (DELETE_RELATIONSHIP, PREVIEW, etc.)
  - `AuditEntry` and `PruningResult` dataclasses for audit trail
  - `find_weak_relationships()` for detecting pruning candidates by weight and age
  - `prune_weak_relationships()` with dry-run support and audit logging
  - `scrape_barnacles()` main maintenance routine
  - `get_pruning_statistics()` for graph health metrics
  - `process_message()` support for inter-agent communication
  - 25 new unit tests for comprehensive coverage
- Optimized relationship traversal utilities (#201)
  - `TraversalDirection` enum for directional traversal control (outgoing, incoming, both)
  - `TraversalConfig` for configurable traversal parameters (max_depth, direction, relationship_types, include_expired, limit)
  - `TraversalStats` and `TraversalResult` for structured traversal responses
  - `BenchmarkResult` for performance measurement
  - Index hint mappings for relationship types (`RELATIONSHIP_INDEXES`) and node labels (`NODE_SEARCH_INDEXES`)
  - `traverse_from_node()` for general graph exploration with temporal filtering
  - `find_shortest_path()` for path finding between nodes
  - `traverse_dependency_chain()` for task BLOCKS relationships
  - `find_connected_entities()` for N-hop neighborhood discovery (capped at 3 hops for performance)
  - `benchmark_traversal()` for performance measurement
  - 30 new unit tests for comprehensive coverage
- Semantic query caching with TTL and LRU eviction (#197)
  - `SemanticCache` class with hash-based query lookup
  - TTL expiration (default 5 minutes, configurable via `SEMANTIC_CACHE_TTL`)
  - LRU eviction when max entries reached (`SEMANTIC_CACHE_MAX_ENTRIES`)
  - `hash_query()` and `hash_query_with_params()` for cache keys
  - `CacheStats` tracks hits, misses, evictions, expirations, hit rate
  - Global cache via `get_semantic_cache()`, `cache_search_results()`, `get_cached_search_results()`
  - 33 new unit tests for comprehensive coverage
- JSON-based graph backup and restore (#203, #204)
  - `create_backup()` exports all nodes and relationships to JSON
  - `restore_backup()` imports snapshot with optional `clear_existing`
  - `BackupMetadata` tracks timestamps, counts, labels, version
  - `BackupSnapshot` contains complete graph state
  - `RestoreResult` reports success, counts, errors
  - `validate_backup()` checks consistency before restore
  - `save_backup_to_file()` and `load_backup_from_file()` for persistence
  - `clear_database()` for controlled data removal
  - 24 new unit tests for backup/restore functionality
- Channel auto-restart with exponential backoff (#154)
  - Auto-restart unhealthy channels during health monitoring
  - Configurable `max_restart_attempts` and `restart_backoff_seconds`
  - Track restart attempts per channel with exponential backoff
  - Failure callbacks for notifications (sync and async supported)
  - `reset_restart_attempts()` and `get_restart_attempts()` methods
  - Environment variables: `CHANNEL_AUTO_RESTART`, `CHANNEL_MAX_RESTART_ATTEMPTS`, `CHANNEL_RESTART_BACKOFF`
- Cross-channel broadcast messaging (#156)
  - `broadcast()` method sends message to all active channels
  - Support for custom `thread_ids` per channel
  - `exclude_channels` parameter to skip specific channels
  - `BroadcastResult` with delivery tracking and error details
  - `send_to_channel()` for targeted messaging
  - 15 new unit tests for auto-restart and broadcast
- Channel integration test suite (#161)
  - CLI integration with orchestrator (5 tests)
  - Telegram integration with orchestrator (4 tests)
  - Thread isolation ensuring no context bleed between channels (4 tests)
  - Multi-channel concurrent operation (4 tests)
  - Message routing and response formatting (4 tests)
  - Channel status and health reporting (2 tests)
  - 23 new integration tests total
- Channel metrics collection via Prometheus (#159)
  - `klabautermann_channel_messages_total`: Messages processed per channel
  - `klabautermann_channel_response_latency_ms`: Response latency histogram
  - `klabautermann_channel_errors_total`: Errors by channel and error type
  - `klabautermann_channel_status`: Channel running status gauge
  - `klabautermann_channel_healthy`: Channel health status gauge
  - `klabautermann_channel_broadcasts_total`: Broadcast message count
  - `klabautermann_channel_broadcast_deliveries_total`: Delivery results by status
  - `klabautermann_channel_active_count`: Active channel count gauge
  - Helper functions: `record_channel_message()`, `record_channel_latency()`, etc.
  - 13 new unit tests for channel metrics
- Distributed tracing with W3C Trace Context support (#273)
  - W3C Trace Context compatible trace IDs (128-bit) and span IDs (64-bit)
  - Context propagation via contextvars
  - Span tracking for nested operations with parent relationships
  - Span attributes, events, and error recording
  - Export to stdout (development) or placeholder for OTLP (production)
  - `Tracer` class with `span()` context manager
  - `TraceContext` for W3C traceparent parsing/generation
  - Environment variables: `TRACING_ENABLED`, `TRACING_EXPORT`, `OTEL_SERVICE_NAME`
  - 32 new unit tests
- Message queue for channel resilience (#160)
  - `MessageQueue` class with FIFO processing
  - Configurable max size (default 100)
  - Overflow policies: drop_oldest, drop_newest, reject
  - Processing timeout (default 5 minutes)
  - Async enqueue with `wait_for_result()` for response retrieval
  - Statistics: total_enqueued, total_processed, total_failed, total_dropped, average_wait_ms
  - `clear()` to drop all pending messages
  - Environment variables: `MESSAGE_QUEUE_MAX_SIZE`, `MESSAGE_QUEUE_OVERFLOW`, `MESSAGE_QUEUE_TIMEOUT`
  - 18 new unit tests
- Container resource limits for monitoring stack (#269)
  - Prometheus: 1 CPU / 1G memory
  - Alertmanager: 0.5 CPU / 256M memory
  - Grafana: 1 CPU / 512M memory
  - OOM handling via restart policy
  - Tuning guidance in comments
- Prometheus alerting rules (#275)
  - 22 alerting rules covering agents, API, channels, graph, LLM, and WebSockets
  - Agent alerts: HighErrorRate, CriticalErrorRate, HighLatency, CriticalLatency, Stopped
  - API alerts: HighErrorRate, CriticalErrorRate, HighLatency
  - Channel alerts: Down, Unhealthy, HighErrorRate, HighLatency, AllChannelsDown, BroadcastFailures
  - Graph alerts: HighLatency, CriticalLatency
  - LLM alerts: HighLatency, HighTokenUsage
  - WebSocket alerts: NoConnections, HighConnections
  - Prometheus self-monitoring: TargetDown, ConfigReloadFailed
  - Alertmanager service with severity-based routing (critical/warning/info)
  - Alert grouping and inhibition rules
- Fuzzy entity deduplication with user review workflow (#35)
  - Wire `deduplication.py` module to Archivist (replaces simple `entity_merge.py`)
  - Use `rapidfuzz` for fuzzy name similarity scoring
  - Auto-merge high-confidence duplicates (>= 0.9 similarity)
  - Flag medium-confidence duplicates (0.7-0.9) via `POTENTIAL_DUPLICATE` relationships
  - `get_flagged_duplicates()` retrieves pending review items
  - `resolve_flagged_duplicate()` merges or dismisses flagged pairs
  - 10 new unit tests for deduplication integration
- TelegramDriver for Telegram bot integration (#129, #130, #131, #132, #133, #134)
  - `TelegramDriver` class extending `BaseChannel`
  - Bot token configuration via `TELEGRAM_BOT_TOKEN` env or config
  - `/start`, `/help`, `/status` commands
  - Text message handling with input sanitization
  - Voice message transcription via OpenAI Whisper
  - User authorization via `allowed_user_ids` whitelist
  - Thread isolation per `chat_id`
  - 21 new unit tests
- Grafana dashboard for metrics visualization (#274)
- Dashboard panels: Agent Performance, API Performance, LLM Performance, Graph Operations
- `docker-compose.monitoring.yml` for Prometheus + Grafana monitoring stack
- Auto-provisioned Grafana dashboards and datasources
- Prometheus metrics export with `/metrics` endpoint (#271)
- Agent metrics: `klabautermann_agent_requests_total`, `klabautermann_agent_successes_total`, `klabautermann_agent_errors_total`, `klabautermann_agent_request_latency_ms`, `klabautermann_agent_running`, `klabautermann_agent_inbox_size`
- API metrics: `klabautermann_api_requests_total`, `klabautermann_api_request_latency_seconds`, `klabautermann_api_websocket_connections`
- Graph metrics: `klabautermann_graph_operations_total`, `klabautermann_graph_operation_latency_seconds`
- LLM metrics: `klabautermann_llm_calls_total`, `klabautermann_llm_tokens_total`, `klabautermann_llm_call_latency_seconds`
- Helper functions: `record_agent_*`, `record_api_*`, `record_graph_*`, `record_llm_*`
- `timed_operation` decorator for automatic latency tracking
- 27 new unit tests for Prometheus metrics
- Enhanced `JSONFormatter` with service/environment/hostname fields (#272)
- `log_context()` context manager for scoped structured logging fields
- `get_log_context()`, `set_log_context()`, `clear_log_context()` functions
- Structured exception formatting with type/message/traceback in JSON logs
- Optional source location logging via LOG_INCLUDE_SOURCE env var
- Environment variables: LOG_SERVICE_NAME, LOG_ENVIRONMENT, LOG_FORMAT
- 23 new unit tests for structured logging
- `WorkflowInspector` class for agent workflow debugging (#357)
- `WorkflowEntry` dataclass for structured workflow log entries
- `WorkflowPhase` enum with REQUEST, THINKING, OUTPUT phases
- `log_request()`, `log_thinking()`, `log_output()` convenience functions
- Automatic REQUEST/OUTPUT logging in `BaseAgent._handle_message()`
- THINKING phase logging in Ingestor, Researcher, and Executor agents
- File output (JSONL), console output, and in-memory buffer for testing
- Environment configuration: WORKFLOW_INSPECT, WORKFLOW_FILTER_AGENTS, WORKFLOW_CONSOLE
- 26 new unit tests for workflow inspection
- `SkillDocsGenerator` class for automatic skill documentation generation (#298)
- `SkillDoc` and `SkillParameter` dataclasses for structured documentation
- `generate_skill_docs()` and `generate_skill_doc()` convenience functions
- Markdown and HTML output support with trigger phrase extraction
- Index page generation for skill catalogs
- 11 new unit tests for documentation generation
- `SkillValidator` class for comprehensive skill definition validation (#297)
- `ValidationResult` and `ValidationError` types for structured validation reporting
- `validate_skill()`, `validate_skill_file()`, `validate_all_skills()` functions
- Validation rules: name format, description quality, tool/model references, orchestrator config
- Strict mode that treats warnings as errors
- 13 new unit tests for skill validation
- `summarize-thread` skill for AI-powered thread summarization (#295)
- Skill supports both email threads and conversation threads
- Orchestrator integration with research task type and researcher agent
- Payload schema with thread_id, thread_type, and query parameters
- 6 new unit tests for skill loading and matching
- Email thread summarization with `get_thread()` and `summarize_email_thread()` methods (#221)
- `EmailThread` model with participant tracking, message_count, and date_range helpers
- `EmailThreadSummary` model with summary, key_points, action_items, sentiment analysis
- AI-powered thread summarization using Claude Haiku with tool_use pattern
- 8 new unit tests for email thread handling and summarization
- Email draft management: list, get, update, send, delete drafts (#219)
- `EmailDraft` model with id, message_id, thread_id, subject, to, cc, body, snippet
- `DraftOperationResult` model for draft operation responses
- Custom label management: create, update, delete labels (#217)
- Nested label support (e.g., "Projects/Work") with visibility settings
- 21 new unit tests for draft and label management
- Calendar event search with `search_events()` method (#220)
- Calendar free slot finder with `find_free_slots()` method using FreeBusy API (#218)
- `FreeSlot` model with duration helpers and display formatting
- 14 new unit tests for calendar search and free slots
- Email attachment support: parsing, download, and save to local storage (#208)
- `EmailAttachment` model with attachment metadata (id, filename, mime_type, size)
- `has_attachments` property and `attachments` list on `EmailMessage`
- `download_attachment()` and `save_attachment()` methods in GoogleWorkspaceBridge
- `FilesystemBridge` class for sandboxed file operations via MCP server (#213)
- `FilesystemConfig` for configuring allowed paths and timeouts
- Filesystem operations: read, write, list, create, move, get_file_info
- 10 new unit tests for email attachment handling
- 18 new unit tests for filesystem bridge
- Recurring calendar events support with RFC 5545 RRULE (#211)
- `RecurrenceBuilder` helper class for common recurrence patterns (daily, weekly, monthly, yearly)
- `recurrence_rule` parameter in `create_event()` and `update_event()`
- `recurrence_rule` and `recurring_event_id` fields in `CalendarEvent` model
- 14 new unit tests for recurring events functionality
- Calendar event update with PATCH semantics for partial updates (#209)
- Calendar event delete functionality (#210)
- `update_event()` and `delete_event()` methods in GoogleWorkspaceBridge
- `CALENDAR_UPDATE` and `CALENDAR_DELETE` action types in Executor
- `UpdateEventResult` and `DeleteEventResult` response models
- 10 new unit tests for calendar update/delete operations
- Parallel test execution with pytest-xdist (#317)
- JUnit XML test results artifact for CI (#317)
- Unit tests for email list formatting with `total_available` parameter (#316)
- Coverage threshold (50%) and `show_missing` for test reports (#314)
- Email management operations: delete, archive, labels (#313)
- Configurable `max_results` and `max_display` for email searches (#312)
- `GraphitiClient.get_entities_from_episode()` to query entities after ingestion (#350)
- Entity-to-message linking after Graphiti ingestion via MENTIONED_IN relationships (#350)
- `neo4j_client` parameter to Ingestor agent for v2 workflow entity linking (#350)
- `reply_to_email()` method in GoogleWorkspaceBridge for email thread replies (#207)
- Email threading headers (In-Reply-To, References) for proper Gmail thread context (#207)
- Reply-all support with original CC recipients (#207)

### Fixed
- CLI output readability and ANSI rendering issues (#311)
- Graphiti-extracted entities now linked to source messages via MENTIONED_IN (#350)
- Schedule queries return all events (limit 100) instead of truncating to 10 (#349)

## [0.1.0] - 2026-01-20

### Added

#### Core Architecture
- Multi-agent architecture with Orchestrator, Ingestor, Researcher, and Executor
- Orchestrator v2 workflow with intent classification and task planning
- Intelligent Researcher with zoom level support and hybrid search
- Thread management for multi-channel conversations
- Proactive behavior support for background tasks

#### Knowledge Graph
- Neo4j + Graphiti integration for temporal knowledge storage
- Entity extraction from conversations (people, organizations, tasks)
- Temporal versioning with time-travel queries
- Idempotent entity extraction to prevent duplicates

#### Gmail Integration
- Email search with natural language queries
- Full email body display in search results
- Email composition and sending
- Reply formatting with quoted content
- Draft support for safety

#### Calendar Integration
- View calendar events
- Create events with conflict detection

#### Skills System
- AI-first skill discovery
- 4 built-in skills for common operations
- Shared skill definitions for Claude Code + orchestrator

#### User Interfaces
- Rich CLI with markdown rendering
- NO_COLOR/FORCE_COLOR environment variable support
- Rust/Ratatui TUI client with vim mode
- FastAPI WebSocket server for TUI
- Telegram channel support (planned)

#### Infrastructure
- GitHub Actions CI workflow (lint, type-check, test, coverage)
- Security, release, and Docker workflows
- Dependabot configuration
- Docker health checks and production compose
- Backup/restore scripts

#### Documentation
- README with features and configuration
- Quickstart guide
- API documentation
- Telegram setup guide
- Troubleshooting guide
- Architecture diagrams

### Changed
- Orchestrator v2 enabled by default
- Researcher refactored with relaxed Pydantic validation for Graphiti scores

### Fixed
- Email query construction (removed keyword-only limitation)
- SearchType test compatibility after researcher refactor
- v2 workflow test signature for `_store_response`

## [0.0.1] - Initial Development

### Added
- Project scaffolding
- Neo4j Docker setup
- Basic CLI driver
- Initial Pydantic models

[Unreleased]: https://github.com/joelgsponer/klabautermann/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/joelgsponer/klabautermann/releases/tag/v0.1.0
[0.0.1]: https://github.com/joelgsponer/klabautermann/releases/tag/v0.0.1
