# Create Environment Configuration Template

## Metadata
- **ID**: T004
- **Priority**: P0
- **Category**: deployment
- **Effort**: S
- **Status**: pending
- **Assignee**: @devops-engineer

## Specs
- Primary: [DEPLOYMENT.md](../../specs/infrastructure/DEPLOYMENT.md)
- Related: [PRD.md](../../specs/PRD.md) Section 9.3

## Dependencies
- [ ] T001 - Docker Compose configuration

## Context
Environment variables manage secrets and configuration. A proper template ensures developers can set up the project quickly while keeping actual secrets out of version control.

## Requirements
- [ ] Create `.env.example` with all required credentials:
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY (for embeddings)
  - NEO4J_URI
  - NEO4J_USERNAME
  - NEO4J_PASSWORD
  - Future: GOOGLE_* credentials (documented but optional)
  - Future: TELEGRAM_BOT_TOKEN (documented but optional)
- [ ] Create comprehensive `.gitignore` including:
  - .env (actual secrets)
  - __pycache__/
  - *.pyc
  - .pytest_cache/
  - .mypy_cache/
  - logs/
  - data/
  - *.pem, *.key
  - credentials.json
  - .google_token.json
  - .venv/, venv/
  - .idea/, .vscode/
  - *.egg-info/
  - dist/, build/
- [ ] Document each variable's purpose in comments

## Acceptance Criteria
- [ ] `.env.example` contains all Sprint 1 required variables
- [ ] `.gitignore` prevents accidental secret commits
- [ ] Copying `.env.example` to `.env` and filling values allows app to start
- [ ] Future credentials (Google, Telegram) are documented but marked optional

## Implementation Notes

Template structure:
```bash
# Klabautermann Environment Configuration
# Copy to .env and fill in values

# === REQUIRED FOR SPRINT 1 ===

# Anthropic API (Claude)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI API (Embeddings)
OPENAI_API_KEY=sk-...

# Neo4j Database
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-secure-password

# === REQUIRED FOR SPRINT 2 (MCP) ===

# Google OAuth2 (Gmail, Calendar)
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GOOGLE_REFRESH_TOKEN=

# === REQUIRED FOR SPRINT 4 (Telegram) ===

# Telegram Bot
# TELEGRAM_BOT_TOKEN=

# === OPTIONAL ===

# Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# Model selection overrides
# ORCHESTRATOR_MODEL=claude-3-5-sonnet-20241022
# HAIKU_MODEL=claude-3-haiku-20240307
```
