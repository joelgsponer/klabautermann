# News

User-visible changes to Klabautermann.

## [Unreleased]

### Added

- **Response Synthesis with Opus**: Orchestrator now uses Claude Opus to synthesize coherent responses from multiple subagent results, with proactive suggestions based on configuration
- **Gmail & Calendar Integration**: Check emails and calendar events via natural language ("any unread emails?", "what's on my calendar today?")
- **Google OAuth Helper**: `scripts/get_google_token.py` for easy OAuth credential setup
- **Daily Journal Generation**: Klabautermann generates daily reflections with personality (VOYAGE SUMMARY, KEY INTERACTIONS, PROGRESS REPORT, WORKFLOW OBSERVATIONS, SAILOR'S THINKING)
- **CLI Interface**: Interactive command-line REPL for conversations with the knowledge assistant
- **Knowledge Graph**: Neo4j-based temporal knowledge graph for storing entities and relationships
- **Entity Extraction**: Automatic extraction of people, organizations, and relationships from conversations
- **Thread Persistence**: Conversations are persisted and can be resumed across sessions
- **Docker Support**: One-command setup with `docker-compose up`

### Improved

- **Search Results**: Knowledge graph search results now displayed in natural language instead of raw data
- **Intent Classification**: Better distinction between knowledge graph queries and external service actions

### Fixed

- **Entity Search**: Fixed parameter conflict in Graphiti entity search queries
- **Action Classification**: "any unread emails?" now correctly routes to Gmail instead of knowledge graph

### Developer Notes

- Run `make dev` to install development dependencies
- Run `make check` to run all quality checks before committing
- See `CONTRIBUTING.md` for workflow guidelines
