# Quickstart Guide

Get up and running with Klabautermann in 5 minutes.

## Prerequisites

- **Python 3.11+** - [Install Python](https://python.org/downloads/)
- **Docker** - For Neo4j database (or local Neo4j 5.26+)
- **API Keys** - Anthropic API key required, OpenAI optional

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/joelgsponer/klabautermann.git
cd klabautermann
```

### 2. Install Dependencies

We use [uv](https://github.com/astral-sh/uv) for fast dependency management:

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
```

### 3. Configure Environment

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
# Required
ANTHROPIC_API_KEY=your-anthropic-key

# Neo4j (use Docker defaults or your own)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

### 4. Start Neo4j

Using Docker Compose:

```bash
docker compose up -d neo4j
```

Wait for Neo4j to be ready (check http://localhost:7474).

### 5. Run Klabautermann

Start the CLI interface:

```bash
uv run python -m klabautermann
```

## First Conversation

Try these example interactions:

```
You: I met Sarah from Acme Corp today. She's a product manager.
Klabautermann: I've noted that you met Sarah, a Product Manager at Acme Corp.

You: Who is Sarah?
Klabautermann: Sarah is a Product Manager at Acme Corp. You met her recently.

You: Send an email to Sarah
Klabautermann: I'll draft an email to Sarah. What would you like to say?
```

## Project Structure

```
klabautermann/
├── src/klabautermann/
│   ├── agents/        # Orchestrator, Researcher, Executor, etc.
│   ├── channels/      # CLI, Telegram interfaces
│   ├── memory/        # Graphiti integration
│   └── mcp/           # Gmail, Calendar tools
├── config/            # Agent configurations
├── specs/             # Architecture documentation
└── tests/             # Test suites
```

## Next Steps

- [Telegram Setup](TELEGRAM_SETUP.md) - Enable Telegram bot
- [Configuration Guide](CONFIGURATION.md) - Customize behavior
- [Architecture Overview](../specs/architecture/AGENTS.md) - Understand the system
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues

## Common Commands

```bash
# Run with debug logging
LOG_LEVEL=DEBUG uv run python -m klabautermann

# Run tests
uv run pytest tests/

# Type check
uv run mypy src/klabautermann

# Format code
uv run ruff format src/ tests/
```

## Getting Help

- [GitHub Issues](https://github.com/joelgsponer/klabautermann/issues)
- [Contributing Guide](../CONTRIBUTING.md)
