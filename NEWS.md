# News

User-visible changes to Klabautermann.

## [Unreleased]

### Added

- **CLI Interface**: Interactive command-line REPL for conversations with the knowledge assistant
- **Knowledge Graph**: Neo4j-based temporal knowledge graph for storing entities and relationships
- **Entity Extraction**: Automatic extraction of people, organizations, and relationships from conversations
- **Thread Persistence**: Conversations are persisted and can be resumed across sessions
- **Docker Support**: One-command setup with `docker-compose up`

### Developer Notes

- Run `make dev` to install development dependencies
- Run `make check` to run all quality checks before committing
- See `CONTRIBUTING.md` for workflow guidelines
