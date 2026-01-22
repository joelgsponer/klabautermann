# News

User-visible changes to Klabautermann.

## [Unreleased]

### Added

- **Graph Maintenance Agent**: Meet the Hull Cleaner - an agent that removes barnacles from your knowledge graph. It finds weak relationships (low weight, old age) and prunes them to keep the graph performant. Now also detects and removes orphan messages - nodes that lost their thread connections and are just floating in the graph. Run in dry-run mode to preview changes before committing. View pruning statistics to monitor graph health. All deletions are logged in an audit trail for review.
- **Optimized Graph Traversal**: Navigate your knowledge graph efficiently with new traversal utilities. Find shortest paths between entities, explore connected neighborhoods within N hops, and trace task dependency chains. Traversal is configurable - control direction (outgoing, incoming, both), depth limits, and temporal filtering. Performance benchmarking built-in for tuning complex queries.
- **Semantic Query Caching**: Search results are now cached based on query similarity. Similar queries return cached results instead of re-running expensive graph traversals. Cache entries expire after 5 minutes (configurable). Track cache performance with hit rate statistics. Configure with `SEMANTIC_CACHE_TTL` and `SEMANTIC_CACHE_MAX_ENTRIES`.
- **Graph Backup & Restore**: Export your knowledge graph to JSON and restore it later. Create backups with `create_backup()`, save to file with timestamps and metadata. Restore with optional `clear_existing` mode. Validates integrity before restore - checks counts, orphan relationships, and duplicate UUIDs.
- **Channel Auto-Recovery**: Channels now automatically restart when they fail. If Telegram drops, it restarts with exponential backoff. After 3 failed attempts, it stops retrying and notifies you. Broadcast messages to all channels at once with `broadcast()`.
- **Channel Metrics**: Monitor your channels with Prometheus metrics. Track message counts, response latencies, error rates, and health status per channel. See which channels are active, healthy, and how many broadcasts succeeded or failed.
- **Distributed Tracing**: Track requests across agents with W3C Trace Context compatible trace IDs. Each request gets a unique 128-bit trace ID that propagates through all agent calls. Create spans to track individual operations with `trace_span("operation.name")`. Export traces to stdout for development or configure OTLP export for production. Enable with `TRACING_ENABLED=true` and `TRACING_EXPORT=stdout`.
- **Message Queue**: Messages are now queued when the Orchestrator is busy processing. The queue holds up to 100 messages (configurable), processes them in FIFO order, and handles overflow gracefully. When full, it can drop the oldest message, drop the newest, or reject new ones. Configure with `MESSAGE_QUEUE_MAX_SIZE`, `MESSAGE_QUEUE_OVERFLOW`, and `MESSAGE_QUEUE_TIMEOUT` environment variables.
- **Container Resource Limits**: The monitoring stack now runs with CPU and memory limits to prevent runaway resource usage. Prometheus gets 1 CPU and 1G memory, Grafana gets 1 CPU and 512M memory, and Alertmanager gets 0.5 CPU and 256M memory. All services restart automatically if they hit memory limits.
- **Alerting Rules**: Get notified when things go wrong. 22 pre-configured Prometheus alerts watch for high error rates, slow responses, channel failures, and resource issues. Alertmanager routes critical alerts immediately, batches warnings, and groups related issues. Start with `docker-compose -f docker-compose.monitoring.yml up -d` and access Alertmanager at http://localhost:9093.
- **Smart Duplicate Detection**: Klabautermann now detects and merges duplicate entities using fuzzy matching. High-confidence duplicates (like "John Doe" and "John D." with matching emails) are auto-merged. Medium-confidence matches are flagged for your review - you can merge them with a simple confirm or dismiss if they're actually different people.
- **Telegram Bot Support**: Access Klabautermann from your phone via Telegram. Create a bot with @BotFather, set `TELEGRAM_BOT_TOKEN`, and chat with your knowledge assistant from anywhere. Supports text messages and voice transcription with commands `/start`, `/help`, `/status`.
- **Grafana Dashboard**: Pre-built dashboard for visualizing Klabautermann metrics. Monitor agent performance, API latency, error rates, LLM usage, and graph operations. Start with `docker-compose -f docker-compose.monitoring.yml up -d` and visit http://localhost:3000.
- **Prometheus Metrics**: Export application metrics to Prometheus via `/metrics` endpoint. Track agent performance (requests, successes, errors, latency), API health (request counts, latency, WebSocket connections), graph operations, and LLM usage (calls, tokens, latency). Scrape with Prometheus, visualize with Grafana.
- **Structured Logging**: JSON log format for log aggregation systems (Elasticsearch, Loki, CloudWatch). Enable with `LOG_FORMAT=json`. Includes trace IDs, timestamps, service name, environment, and hostname in every log entry. Use `with log_context(trace_id="...")` to add context to all logs in a scope.
- **Agent Workflow Inspector**: Debug agent behavior with detailed logging of each agent's request, thinking, and output phases. Enable with `WORKFLOW_INSPECT=true` or filter specific agents with `WORKFLOW_FILTER_AGENTS=researcher,executor`. Logs to file, console, or both.
- **Skill Documentation Generator**: Automatically generate documentation for skills with `generate_skill_docs()`. Outputs markdown or HTML with descriptions, parameters, trigger phrases, and usage examples. Generate index pages for skill catalogs.
- **Skill Validation**: New validation system catches skill definition errors before runtime - malformed names, missing fields, and configuration issues are now reported with clear error messages.
- **Thread Summarization Skill**: Summarize any conversation or email thread with a simple command ("summarize this thread", "TLDR", "what was discussed?"). Works with both email threads and conversation history.
- **Email Thread Summaries**: Get AI-powered summaries of long email threads with key points, action items, and sentiment analysis ("summarize this email thread", "what's the gist of that conversation with Sarah?")
- **Email Draft Management**: Save emails as drafts for later, edit them, and send when ready ("save this as a draft", "update my draft to Sarah", "send my draft")
- **Custom Gmail Labels**: Create, update, and organize emails with custom labels including nested folders ("create a Projects/Work label", "add the urgent label")
- **Calendar Search**: Find events by searching titles and descriptions ("find my meetings with Sarah", "show standup meetings next week")
- **Meeting Time Finder**: Find available meeting slots across your calendars ("when am I free for a 30-minute call?", "find open slots this week")
- **Email Attachments**: View, download, and save email attachments ("download that PDF from Sarah's email", "save the spreadsheet to my downloads folder")
- **File Operations**: Read and write local files via secure sandboxed access for attachment storage and file-based workflows
- **Recurring Calendar Events**: Create recurring meetings and appointments ("schedule daily standup at 9am", "add weekly team meeting every Tuesday")
- **Calendar Event Management**: Update and delete calendar events via natural language ("reschedule my meeting to 3pm", "cancel my 2pm appointment")
- **Response Synthesis with Opus**: Orchestrator now uses Claude Opus to synthesize coherent responses from multiple subagent results, with proactive suggestions based on configuration
- **Gmail & Calendar Integration**: Check emails and calendar events via natural language ("any unread emails?", "what's on my calendar today?")
- **Google OAuth Helper**: `scripts/get_google_token.py` for easy OAuth credential setup
- **Email Reply-to-Thread**: Reply to email threads with proper threading ("reply to that email from Sarah saying I'll attend")
- **Daily Journal Generation**: Klabautermann generates daily reflections with personality (VOYAGE SUMMARY, KEY INTERACTIONS, PROGRESS REPORT, WORKFLOW OBSERVATIONS, SAILOR'S THINKING)
- **CLI Interface**: Interactive command-line REPL for conversations with the knowledge assistant
- **Knowledge Graph**: Neo4j-based temporal knowledge graph for storing entities and relationships
- **Entity Extraction**: Automatic extraction of people, organizations, and relationships from conversations
- **Thread Persistence**: Conversations are persisted and can be resumed across sessions
- **Docker Support**: One-command setup with `docker-compose up`

### Improved

- **AI-First Intent Classification**: Intent classification now uses pure LLM semantic understanding - no keyword matching fallback, ensuring more intelligent and context-aware routing
- **AI-First Zoom Level Detection**: Search queries now use LLM semantic understanding to determine retrieval granularity (macro/meso/micro) - no keyword matching
- **Multi-Intent Message Handling**: Orchestrator now identifies and handles multiple intents in a single message (e.g., "Learned that Sarah works at Acme. What's her email?")
- **Parallel Subagent Execution**: Independent tasks (search, ingestion, actions) execute concurrently for faster responses
- **Richer Context Awareness**: Cross-thread summaries and Knowledge Island context inform responses, enabling more intelligent suggestions
- **Proactive Suggestions**: System now offers follow-ups and confirmations based on conversation context (e.g., "Should I follow up with her to confirm?")
- **Search Results**: Knowledge graph search results now displayed in natural language instead of raw data
- **Intent Classification**: Better distinction between knowledge graph queries and external service actions

### Fixed

- **Entity Search**: Fixed parameter conflict in Graphiti entity search queries
- **Action Classification**: "any unread emails?" now correctly routes to Gmail instead of knowledge graph
- **Entity Memory**: "I met John, PM at Acme" now correctly links John and Acme to your message, enabling queries like "What did I talk about with John?"
- **Schedule Queries**: "What's my schedule this week?" now returns all events instead of truncating to first 10

### Developer Notes

- Run `make dev` to install development dependencies
- Run `make check` to run all quality checks before committing
- See `CONTRIBUTING.md` for workflow guidelines
