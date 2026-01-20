# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Parallel test execution with pytest-xdist (#317)
- JUnit XML test results artifact for CI (#317)
- Unit tests for email list formatting with `total_available` parameter (#316)
- Coverage threshold (50%) and `show_missing` for test reports (#314)
- Email management operations: delete, archive, labels (#313)
- Configurable `max_results` and `max_display` for email searches (#312)

### Fixed
- CLI output readability and ANSI rendering issues (#311)

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
