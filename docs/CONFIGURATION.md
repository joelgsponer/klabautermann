# Configuration Guide

This document describes all configuration options for Klabautermann.

## Table of Contents

- [Environment Variables](#environment-variables)
- [Agent Configurations](#agent-configurations)
  - [Orchestrator](#orchestrator)
  - [Orchestrator v2](#orchestrator-v2)
  - [Executor](#executor)
  - [Researcher](#researcher)
  - [Ingestor](#ingestor)
  - [Archivist](#archivist)
  - [Scribe](#scribe)
  - [Syncer](#syncer)
- [Scheduler Configuration](#scheduler-configuration)
- [Hot-Reload](#hot-reload)

---

## Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key | `sk-ant-api03-...` |
| `OPENAI_API_KEY` | OpenAI key for embeddings | `sk-...` |
| `NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | `klabautermann` |

### Google Workspace (Optional)

Required for Gmail and Calendar integration:

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | OAuth2 client secret |
| `GOOGLE_REFRESH_TOKEN` | OAuth2 refresh token |

Run `python scripts/bootstrap_auth.py` to obtain the refresh token.

### Telegram (Optional)

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_FORMAT` | `text` | Log format (`json` for production, `text` for development) |
| `NO_COLOR` | - | Set to disable colored CLI output |
| `KLABAUTERMANN_NO_SPINNER` | - | Set to disable animated spinner |
| `DEBUG` | `false` | Enable debug mode |
| `DISABLE_INGESTION` | `false` | Disable entity extraction (for testing) |

---

## Agent Configurations

Agent configurations are stored in `config/agents/` and support **hot-reload** without restart.

### Orchestrator

**File**: `config/agents/orchestrator.yaml`

The main routing agent that delegates to sub-agents.

```yaml
# Enable v2 workflow (recommended)
use_v2_workflow: true

model:
  primary: claude-sonnet-4-20250514    # Main reasoning model
  fallback: claude-3-haiku-20240307    # Fallback model
  temperature: 0.7                      # Response creativity (0.0-1.0)
  max_context_tokens: 8000             # Max input context
  max_output_tokens: 4096              # Max response length

personality:
  name: klabautermann
  wit_level: 0.3                       # Personality wit (0.0-1.0)

# LLM-based intent classification
intent_classification:
  model: claude-3-5-haiku-20241022     # Fast model for classification
  timeout: 5.0                         # Seconds before heuristic fallback

# Agent delegation mapping
delegation:
  search: researcher
  action: executor
  ingest: ingestor

timeouts:
  agent_response: 30.0                 # Seconds to wait for sub-agent
  llm_call: 60.0                       # Seconds for LLM API call
  mcp_call: 30.0                       # Seconds for MCP tool call

retry:
  max_attempts: 3
  base_delay: 1.0                      # Initial retry delay (seconds)
  max_delay: 30.0                      # Maximum retry delay
  jitter: 0.25                         # Random jitter factor
```

### Orchestrator v2

**File**: `config/agents/orchestrator_v2.yaml`

Advanced multi-task parallel execution (Think-Dispatch-Synthesize pattern).

```yaml
model: claude-opus-4-5-20251101        # Planning model
synthesis_model: claude-opus-4-5-20251101  # Synthesis model

context:
  message_window: 20                   # Recent messages to include
  summary_hours: 12                    # Hours back for thread summaries
  include_pending_tasks: true          # Include pending tasks in context
  include_recent_entities: true        # Include recent entities
  recent_entity_hours: 24              # Hours back for entities
  include_islands: true                # Include Knowledge Island summaries

execution:
  max_research_depth: 2                # Max iterative research rounds
  parallel_timeout_seconds: 30         # Timeout for parallel sub-agents
  fire_and_forget_timeout_seconds: 60  # Timeout for async tasks

proactive_behavior:
  suggest_calendar_events: true        # Suggest creating events
  suggest_follow_ups: true             # Offer task follow-ups
  ask_clarifications: true             # Ask for clarification
```

### Executor

**File**: `config/agents/executor.yaml`

Executes actions via MCP tools (Gmail, Calendar, etc.).

```yaml
model:
  primary: claude-sonnet-4-20250514
  temperature: 0.3                     # Lower for consistent actions
  max_context_tokens: 4000
  max_output_tokens: 2048

tools:
  enabled_tools:
    - gmail
    - calendar
    - filesystem
  require_confirmation: true           # Require user confirmation
  dry_run: false                       # Preview without executing

# Email-specific settings
email:
  max_results: 20                      # Max emails from Gmail API
  max_display: 10                      # Max emails in formatted output

timeouts:
  agent_response: 60.0
  llm_call: 30.0
  mcp_call: 30.0

retry:
  max_attempts: 2
  base_delay: 2.0
  max_delay: 30.0
```

### Researcher

**File**: `config/agents/researcher.yaml`

Searches the knowledge graph for information.

```yaml
model:
  primary: claude-3-haiku-20240307     # Fast model for search
  temperature: 0.3
  max_context_tokens: 4000
  max_output_tokens: 2048

search:
  max_results: 10                      # Max search results
  min_score: 0.5                       # Minimum relevance score (0.0-1.0)
  use_vector_search: true              # Enable semantic search
  use_graph_traversal: true            # Enable graph traversal
  max_hops: 2                          # Max relationship hops

timeouts:
  agent_response: 30.0
  llm_call: 30.0

retry:
  max_attempts: 3
  base_delay: 1.0
  max_delay: 15.0
```

### Ingestor

**File**: `config/agents/ingestor.yaml`

Extracts entities and relationships from conversations.

```yaml
model:
  primary: claude-3-5-haiku-20241022
  temperature: 0.3
  max_context_tokens: 4000
  max_output_tokens: 1024

extraction:
  entity_types:
    - Person
    - Organization
    - Project
    - Goal
    - Task
    - Event
    - Location
  relationship_types:
    - WORKS_AT
    - PART_OF
    - CONTRIBUTES_TO
    - ATTENDED
    - HELD_AT
    - BLOCKS
    - MENTIONED_IN
    - KNOWS
    - ASSIGNED_TO
  confidence_threshold: 0.7            # Min confidence to save (0.0-1.0)

timeouts:
  agent_response: 30.0
  llm_call: 30.0

retry:
  max_attempts: 2
  base_delay: 1.0
  max_delay: 10.0
```

### Archivist

**File**: `config/agents/archivist.yaml`

Archives inactive threads and reduces graph clutter.

```yaml
name: archivist
model:
  primary: claude-3-5-haiku-20241022

cooldown_minutes: 60                   # Minutes between archive scans
max_threads_per_scan: 10               # Threads to process per scan

summarization:
  max_message_length: 1000             # Max message length in summary
  include_timestamps: true             # Include timestamps in summary
```

### Scribe

**File**: `config/agents/scribe.yaml`

Generates daily journal reflections.

```yaml
name: scribe
model:
  primary: claude-3-5-haiku-20241022
  temperature: 0.7                     # Higher for creative writing
  max_output_tokens: 1500

schedule:
  hour: 0                              # Hour to run (UTC)
  minute: 0                            # Minute to run

min_interactions: 1                    # Min interactions to generate journal

journal:
  include_highlights: true             # Include daily highlights
  max_content_length: 2000             # Max journal content length
```

### Syncer

**File**: `config/agents/syncer.yaml`

Imports emails and calendar events from Google Workspace.

```yaml
name: syncer
model:
  primary: claude-3-5-haiku-20241022

calendar:
  enabled: true
  lookback_days: 7                     # Days back to sync on first run
  lookahead_days: 14                   # Days ahead to sync

email:
  enabled: true
  lookback_hours: 24                   # Hours back to sync emails
  max_per_sync: 50                     # Max emails per sync cycle
  query: "is:inbox"                    # Gmail query filter
```

---

## Scheduler Configuration

**File**: `config/scheduler.yaml`

Controls periodic job execution for background agents.

```yaml
# Archivist: Scans and archives inactive threads
archivist:
  enabled: true
  interval_minutes: 15                 # Scan frequency

# Scribe: Daily journal generation
scribe:
  enabled: true
  hour: 0                              # Run at midnight UTC
  minute: 0

# Syncer: Imports from Google Workspace
syncer:
  enabled: true
  interval_minutes: 15                 # Sync frequency

# Scheduler settings
timezone: UTC                          # All jobs run in UTC
job_store: memory                      # 'memory' or 'sqlite'

# SQLite job store for persistence (if job_store: sqlite)
# sqlite_path: data/jobs.sqlite
```

---

## Hot-Reload

Agent configurations support hot-reload. Changes to YAML files in `config/agents/` are automatically detected and applied without restarting the application.

To verify a configuration change was applied, check the logs for:

```
[CONFIG] Reloaded config/agents/executor.yaml
```

### Common Adjustments

**Increase email results:**

```yaml
# config/agents/executor.yaml
email:
  max_results: 50   # Fetch more from API
  max_display: 25   # Show more in output
```

**Disable proactive suggestions:**

```yaml
# config/agents/orchestrator_v2.yaml
proactive_behavior:
  suggest_calendar_events: false
  suggest_follow_ups: false
  ask_clarifications: false
```

**Use faster models:**

```yaml
# config/agents/orchestrator.yaml
model:
  primary: claude-3-5-haiku-20241022  # Faster but less capable
```
