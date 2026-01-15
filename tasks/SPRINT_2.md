# Sprint 2: The Crew - "Multi-Agent Architecture"

**Duration**: Week 2 (5 days)
**Sprint Goal**: Decompose orchestrator into specialized sub-agents with MCP integration
**Theme**: Build the crew that runs the ship

---

## Sprint Summary

By the end of Sprint 2, we must have:
1. Refactored Orchestrator with intent classification and delegation
2. Ingestor agent extracting entities from conversations
3. Researcher agent performing hybrid search (vector + graph)
4. MCP client infrastructure with Google OAuth
5. Executor agent handling Gmail and Calendar actions
6. Configuration hot-reload system for agents

---

## Success Criteria

```bash
# 1. Test agent delegation
> Who is Sarah?
# Expected: Logs show Orchestrator -> Researcher delegation

# 2. Test ingestion
> I had lunch with Tom from Google today
# Expected: Logs show Orchestrator -> Ingestor (async)
# Verify: Tom and Google nodes in Neo4j

# 3. Google OAuth setup
python scripts/bootstrap_auth.py
# Expected: Browser opens, authorize, refresh token saved to .env

# 4. Test Gmail MCP
> What emails did I get today?
# Expected: List of recent emails

# 5. Test Calendar MCP
> What's on my schedule tomorrow?
# Expected: Calendar events listed

# 6. Test config hot-reload
# Edit config/agents/orchestrator.yaml (change a prompt)
# Send message
# Expected: New behavior reflected without restart

# 7. Verify logging
# Check logs/ship_ledger.jsonl
# Expected: Trace IDs, agent names, [CHART]/[BEACON] levels
```

---

## Task Breakdown

### Day 1: Agent Architecture Refactor

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T020 | Refactor Orchestrator for intent classification | P0 | L | @backend-engineer |
| T021 | Implement async agent delegation pattern | P0 | M | @backend-engineer |
| T022 | Create retry utility with exponential backoff | P1 | S | @backend-engineer |

### Day 2: Ingestor + Researcher Agents

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T023 | Implement Ingestor agent | P0 | L | @backend-engineer |
| T024 | Implement Researcher agent | P0 | L | @backend-engineer |
| T025 | Create hybrid search queries | P0 | M | @graph-engineer |

### Day 3: MCP Infrastructure

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T026 | Create MCP client wrapper | P0 | M | @integration-engineer |
| T027 | Implement Google OAuth bootstrap script | P0 | M | @integration-engineer |
| T028 | Create Google Workspace MCP bridge | P0 | L | @integration-engineer |

### Day 4: Executor Agent

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T029 | Implement Executor agent | P0 | L | @backend-engineer |
| T030 | Add Gmail tool handlers | P1 | M | @integration-engineer |
| T031 | Add Calendar tool handlers | P1 | M | @integration-engineer |

### Day 5: Configuration + Integration

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T032 | Create agent configuration system | P1 | M | @backend-engineer |
| T033 | Implement config hot-reload (Quartermaster) | P1 | M | @backend-engineer |
| T034 | Update main.py for multi-agent startup | P1 | M | @backend-engineer |
| T035 | Sprint 2 integration tests | P1 | M | @qa-engineer |

---

## Dependency Graph

```
T020 (Orchestrator Refactor) ─────────────────────────────────────┐
  │                                                               │
  ├──> T021 (Agent Delegation) ─┬──> T023 (Ingestor) ────────────┤
  │                             │                                 │
  │                             └──> T024 (Researcher) ──┬────────┤
  │                                                      │        │
  │                                   T025 (Hybrid Search)        │
  │                                                               │
T022 (Retry Utility) ───────────────────────────────────────────> │
                                                                  │
T026 (MCP Client) ────────────────────────────────────────┐       │
  │                                                       │       │
  ├──> T027 (OAuth Bootstrap) ──┐                        │       │
  │                             │                        │       │
  │                             └──> T028 (Google MCP) ──┴──────> │
  │                                         │                     │
  │                                         └──> T029 (Executor)──┤
  │                                               │               │
  │                                               ├──> T030 (Gmail)
  │                                               │               │
  │                                               └──> T031 (Calendar)
  │                                                               │
T032 (Config System) ────────────────────────────────────────────>│
  │                                                               │
  └──> T033 (Hot Reload) ────────────────────────────────────────>│
                                                                  │
T034 (Main.py Update) <───────────────────────────────────────────┤
  │                                                               │
  └──> T035 (Integration Tests) <─────────────────────────────────┘
```

---

## Task Details

### T020: Refactor Orchestrator for Intent Classification

**File**: `tasks/pending/T020-orchestrator-intent-classification.md`

Refactor the simple Orchestrator from Sprint 1 to:
- Classify user intent (search, action, ingestion, conversation)
- Prepare for delegation to sub-agents
- Implement the "search first, never hallucinate" rule

**Depends on**: T017 (Sprint 1 Orchestrator)

---

### T021: Implement Async Agent Delegation Pattern

**File**: `tasks/pending/T021-agent-delegation-pattern.md`

Implement the dispatch/wait pattern for agent communication:
- `_dispatch_and_wait()` for synchronous agent calls
- `_dispatch_fire_and_forget()` for async background tasks
- Response aggregation from multiple agents

**Depends on**: T020

---

### T022: Create Retry Utility

**File**: `tasks/pending/T022-retry-utility.md`

Implement exponential backoff decorator for resilient API calls:
- Configurable retry count and delay
- Jitter for distributed systems
- Exception filtering

**Depends on**: Nothing

---

### T023: Implement Ingestor Agent

**File**: `tasks/pending/T023-ingestor-agent.md`

Create the Ingestor agent for entity extraction:
- Extract entities (Person, Organization, Project, etc.)
- Extract relationships (WORKS_AT, PART_OF, etc.)
- Call Graphiti's `add_episode()` to update graph
- Handle temporal awareness (past tense -> expiration)

**Depends on**: T021, T009 (Graphiti client)

---

### T024: Implement Researcher Agent

**File**: `tasks/pending/T024-researcher-agent.md`

Create the Researcher agent for hybrid search:
- Vector search via Graphiti
- Structural search via Cypher
- Temporal search with time filters
- Result attribution and confidence

**Depends on**: T021, T009, T010 (Neo4j client)

---

### T025: Create Hybrid Search Queries

**File**: `tasks/pending/T025-hybrid-search-queries.md`

Implement the Cypher query library for structural searches:
- Relationship traversal queries
- Time-filtered queries
- Multi-hop path queries

**Depends on**: T024

---

### T026: Create MCP Client Wrapper

**File**: `tasks/pending/T026-mcp-client-wrapper.md`

Implement the generic MCP client infrastructure:
- Server process management
- Tool invocation pattern
- Response parsing
- Error handling

**Depends on**: Nothing

---

### T027: Implement Google OAuth Bootstrap Script

**File**: `tasks/pending/T027-google-oauth-bootstrap.md`

Create `scripts/bootstrap_auth.py` for OAuth setup:
- Browser-based OAuth2 flow
- Refresh token acquisition
- Credential storage in .env
- Scope configuration

**Depends on**: T026

---

### T028: Create Google Workspace MCP Bridge

**File**: `tasks/pending/T028-google-workspace-bridge.md`

Implement the Google Workspace MCP integration:
- Gmail read/send capabilities
- Calendar read/create capabilities
- Event formatting and parsing

**Depends on**: T026, T027

---

### T029: Implement Executor Agent

**File**: `tasks/pending/T029-executor-agent.md`

Create the Executor agent for real-world actions:
- Verify required information before execution
- Construct MCP tool calls
- Handle confirmations for destructive actions
- Error reporting

**Depends on**: T021, T028

---

### T030: Add Gmail Tool Handlers

**File**: `tasks/pending/T030-gmail-tool-handlers.md`

Implement Gmail-specific tool handling:
- `gmail_send_message` - Send or draft email
- `gmail_search_messages` - Search inbox
- Response formatting

**Depends on**: T029, T028

---

### T031: Add Calendar Tool Handlers

**File**: `tasks/pending/T031-calendar-tool-handlers.md`

Implement Calendar-specific tool handling:
- `calendar_create_event` - Create events
- `calendar_list_events` - Check availability
- Time zone handling

**Depends on**: T029, T028

---

### T032: Create Agent Configuration System

**File**: `tasks/pending/T032-agent-config-system.md`

Implement YAML-based agent configuration:
- Model selection per agent
- Temperature and token limits
- Intent classification keywords
- Delegation mappings

**Depends on**: Nothing

---

### T033: Implement Config Hot-Reload

**File**: `tasks/pending/T033-config-hot-reload.md`

Implement the Quartermaster config watcher:
- File change detection (watchdog)
- Checksum-based reload
- Agent configuration refresh

**Depends on**: T032

---

### T034: Update Main.py for Multi-Agent Startup

**File**: `tasks/pending/T034-main-multiagent-startup.md`

Update `main.py` to initialize all agents:
- Create agent instances
- Wire up agent registry
- Start agent processing loops
- Graceful multi-agent shutdown

**Depends on**: T020, T023, T024, T029, T033

---

### T035: Sprint 2 Integration Tests

**File**: `tasks/pending/T035-sprint2-integration-tests.md`

Create integration tests for Sprint 2 functionality:
- Test intent classification
- Test agent delegation
- Test entity extraction
- Test MCP tool invocation (mock)
- Test config reload

**Depends on**: T034

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| MCP tool unreliable | Medium | High | Use MCP Inspector to test independently first |
| Google OAuth headless | Medium | Medium | Detailed bootstrap script with prompts |
| Agent coordination bugs | Medium | High | Comprehensive logging from Day 1 |
| LLM extraction quality | Medium | Medium | Start with Haiku, upgrade to Sonnet if needed |

---

## Parallel Work Opportunities

These can be worked on simultaneously:
- T020 + T022 + T026 + T032 (independent foundations)
- T023 + T024 (after T021 complete, both can parallelize)
- T030 + T031 (after T029 complete)
- T027 can start while T026 is in progress

---

## Definition of Done

Sprint 2 is complete when:

- [ ] Orchestrator correctly classifies intents (search, action, ingest, conversation)
- [ ] Orchestrator delegates to appropriate sub-agent
- [ ] Ingestor extracts entities and creates graph nodes
- [ ] Ingestor runs in background (non-blocking)
- [ ] Researcher performs hybrid search (vector + graph traversal)
- [ ] MCP client can invoke external tools
- [ ] Google OAuth bootstrap works in headless environment
- [ ] Executor can send Gmail messages
- [ ] Executor can create Calendar events
- [ ] Config changes hot-reload without restart
- [ ] All agent interactions logged with trace IDs
- [ ] Integration tests pass

---

## Crew Assignments

| Role | Primary Responsibilities |
|------|-------------------------|
| @backend-engineer | T020, T021, T022, T023, T024, T029, T032, T033, T034 - Agent architecture |
| @graph-engineer | T025 - Search queries |
| @integration-engineer | T026, T027, T028, T030, T031 - MCP infrastructure |
| @qa-engineer | T035 - Integration testing |

---

## Notes

- **Haiku First**: All extraction and search agents start with Haiku. If quality is insufficient, upgrade to Sonnet and document the decision.

- **MCP Testing**: Before integrating MCP tools, test them independently with MCP Inspector to verify behavior.

- **Background Ingestion**: The Ingestor must be fire-and-forget. Never block the user response for entity extraction.

- **Search First Rule**: The Orchestrator must ALWAYS query the Researcher before answering factual questions. No hallucination.

---

*"Now we fit the crew. Each hand knows their duty."* - The Shipwright
