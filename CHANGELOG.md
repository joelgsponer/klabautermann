# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Remove keyword-based intent classification fallback - pure LLM semantic understanding only (#2, #354)
- Remove keyword-based zoom level detection fallback - AI-first approach with graceful degradation (#355)

### Added
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
