# Klabautermann

An agentic personal knowledge management (PKM) system using a multi-agent architecture with a temporal knowledge graph.

Klabautermann extracts entities from your conversations, stores them in Neo4j via Graphiti, and enables agents to take actions (email, calendar) via MCP.

## Features

- **Multi-Agent Architecture**: Orchestrator delegates to specialized agents (Ingestor, Researcher, Executor)
- **Temporal Knowledge Graph**: Neo4j + Graphiti for time-aware entity storage and retrieval
- **Entity Extraction**: Automatically extracts people, organizations, tasks, and relationships from conversations
- **Hybrid Search**: Combines semantic (vector), structural (graph), and temporal search strategies
- **Web Search**: Real-time information retrieval via Brave Search API for current events and news
- **Email Management**: Full Gmail integration - search, send, delete, archive, and label emails
- **Calendar Integration**: View and create calendar events with conflict detection
- **Hot-Reload Configuration**: Change agent configs without restarting

### Current Capabilities

| Feature | Status | Description |
|---------|--------|-------------|
| Entity Extraction | ✅ | Extract people, orgs, tasks from conversations |
| Knowledge Graph Search | ✅ | Query stored entities and relationships |
| Web Search | ✅ | Real-time news and current events via Brave API |
| Email Search | ✅ | Search emails with natural language queries |
| Email Send | ✅ | Compose and send emails (draft first for safety) |
| Email Delete | ✅ | Move emails to trash |
| Email Archive | ✅ | Archive emails (remove from inbox) |
| Email Labels | ✅ | Apply/remove labels, list available labels |
| Calendar List | ✅ | View today's events |
| Calendar Create | ✅ | Create events with conflict detection |
| CLI Interface | ✅ | Rich terminal interface with markdown |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Anthropic API key
- OpenAI API key (for embeddings)

### Setup

```bash
# Clone and enter directory
cd klabautermann3

# Create virtual environment
make venv
source .venv/bin/activate

# Install dependencies
make dev

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Start Neo4j
make docker-up

# Initialize database schema
make init-db

# Run the CLI
make run
```

### Google Workspace Setup (Optional)

For Gmail and Calendar integration:

```bash
# Interactive mode (opens browser)
python scripts/bootstrap_auth.py

# Headless mode (for servers)
python scripts/bootstrap_auth.py --headless
```

## Architecture

```
Communication Layer (CLI, Telegram)
         │
         ▼
Orchestration Layer (intent classification, delegation)
         │
         ▼
Agent Layer:
  ├─ Ingestor (Haiku)   → extracts entities → Graphiti
  ├─ Researcher (Haiku) → knowledge graph + web search
  └─ Executor (Sonnet)  → MCP tool execution
         │
         ▼
Memory Layer (Neo4j + Graphiti temporal graph)
```

## Testing

```bash
# Run all unit tests
make test

# Run with coverage
make test-cov

# Start test infrastructure (isolated Neo4j on port 7688)
make test-docker-up

# Run contract tests (requires test Neo4j)
make test-contracts

# Run golden scenario E2E tests (requires Neo4j + API keys)
make test-golden

# Stop test infrastructure
make test-docker-down
```

### Golden Scenarios

Five mandatory E2E tests that must pass before any release:

1. **New Contact**: "I met John (john@example.com), PM at Acme" → creates Person, Organization, WORKS_AT
2. **Contextual Retrieval**: "What did I talk about with John?" → finds thread, summarizes
3. **Blocked Task**: "Can't finish until John sends stats" → creates BLOCKS relationship
4. **Temporal Time-Travel**: Change employer, ask historical → returns old employer
5. **Multi-Channel Threading**: CLI + Telegram → separate threads, no context bleed

## Development

```bash
# Format code
make format

# Run linter
make lint

# Run type checker
make type-check

# Run all quality checks
make check
```

## Configuration

Agent configurations live in `config/agents/`. Changes are hot-reloaded without restart.

| File | Agent | Description |
|------|-------|-------------|
| `orchestrator.yaml` | Orchestrator | Intent classification, delegation rules |
| `ingestor.yaml` | Ingestor | Entity extraction prompts |
| `researcher.yaml` | Researcher | Search strategies, result formatting |
| `executor.yaml` | Executor | Action validation, email/calendar settings |

### Email Settings (executor.yaml)

```yaml
email:
  max_results: 20    # Max emails to fetch from Gmail API
  max_display: 10    # Max emails to show in output
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for agents |
| `NEO4J_PASSWORD` | Yes | Neo4j database password |
| `OPENAI_API_KEY` | No | For entity extraction (Graphiti) |
| `BRAVE_SEARCH_API_KEY` | No | For web search (Researcher agent) |
| `GOOGLE_CLIENT_ID` | No | For Gmail/Calendar integration |
| `GOOGLE_CLIENT_SECRET` | No | For Gmail/Calendar integration |
| `GOOGLE_REFRESH_TOKEN` | No | OAuth2 refresh token |
| `LOG_LEVEL` | No | Logging level (default: WARNING in CLI) |
| `NO_COLOR` | No | Disable colored output |
| `KLABAUTERMANN_NO_SPINNER` | No | Disable animated spinner |

## Project Structure

```
klabautermann3/
├── config/agents/       # Agent YAML configurations (hot-reload)
├── scripts/             # Utility scripts (bootstrap_auth, init_database)
├── src/klabautermann/
│   ├── agents/          # Agent implementations
│   ├── channels/        # CLI, Telegram drivers
│   ├── config/          # ConfigManager, Quartermaster
│   ├── core/            # Models, exceptions, logging
│   ├── mcp/             # MCP client, Google Workspace bridge
│   ├── memory/          # Graphiti, Neo4j, ThreadManager
│   └── utils/           # Retry, queries
├── tests/
│   ├── unit/            # Fast unit tests (mocked)
│   ├── integration/     # Contract tests (real services)
│   └── e2e/             # Golden scenarios (full system)
├── docker-compose.yml       # Development Neo4j
├── docker-compose.test.yml  # Isolated test Neo4j (port 7688)
└── Makefile                 # Common commands
```

## Roadmap

- **Sprint 1** (Complete): Foundation - Neo4j, CLI, simple orchestrator
- **Sprint 2** (Complete): Multi-Agent - Ingestor, Researcher, Executor, MCP
- **Sprint 3** (Next): Memory Lifecycle - Archivist, Scribe, daily notes
- **Sprint 4**: Production - Telegram, personality, full testing

See `specs/ROADMAP.md` for detailed planning.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, git practices, and coding standards.

## License

MIT License. See [LICENSE](LICENSE) for details.
