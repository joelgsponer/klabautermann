# News

User-visible changes to Klabautermann.

## [Unreleased]

### Added

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
