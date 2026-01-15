# Sprint 1: Foundation - "Setting Sail"

**Duration**: Week 1 (5 days)
**Sprint Goal**: Establish infrastructure and validate critical path with minimal working assistant
**Theme**: Get the hull in the water and prove she floats

---

## Sprint Summary

By the end of Sprint 1, we must have:
1. Docker infrastructure running (Neo4j + Python app)
2. Graph schema initialized with constraints and indexes
3. Memory layer operational (Graphiti + Neo4j clients)
4. CLI channel accepting input
5. Simple Orchestrator completing the conversation loop
6. End-to-end test: "I met Sarah from Acme" creates graph nodes

---

## Success Criteria

```bash
# 1. Infrastructure starts cleanly
docker-compose up -d
# Expected: Both containers healthy

# 2. Database initialized
python scripts/init_database.py
# Expected: Constraints and indexes created

# 3. CLI accepts input and responds
docker attach klabautermann-app
> I met Sarah from Acme Corp
# Expected: Conversational response

# 4. Graph populated
# In Neo4j Browser:
MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT]->(o:Organization)
WHERE r.expired_at IS NULL
RETURN p, r, o
# Expected: Nodes and relationship visible

# 5. Persistence across restarts
# Restart CLI, ask about Sarah
# Expected: Agent remembers Sarah
```

---

## Task Breakdown

### Day 1: Infrastructure

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T001 | Create Docker Compose configuration | P0 | M | @devops-engineer |
| T002 | Create Python Dockerfile | P0 | S | @devops-engineer |
| T003 | Set up project directory structure | P0 | S | @backend-engineer |
| T004 | Create environment configuration template | P0 | S | @devops-engineer |

### Day 2: Graph Foundation

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T005 | Create Pydantic core models | P0 | M | @backend-engineer |
| T006 | Define ontology constants (labels, relationships) | P0 | S | @graph-engineer |
| T007 | Create database initialization script | P0 | M | @graph-engineer |
| T008 | Set up nautical logging system | P0 | S | @backend-engineer |

### Day 3: Memory Layer

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T009 | Implement Graphiti client wrapper | P0 | L | @graph-engineer |
| T010 | Implement Neo4j direct client | P0 | M | @graph-engineer |
| T011 | Create thread manager for persistence | P0 | M | @backend-engineer |
| T012 | Create custom exceptions module | P0 | S | @backend-engineer |

### Day 4: CLI Channel

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T013 | Create base channel abstract interface | P1 | S | @backend-engineer |
| T014 | Implement CLI driver | P1 | M | @backend-engineer |
| T015 | Add thread persistence to CLI | P1 | M | @backend-engineer |

### Day 5: Simple Orchestrator

| ID | Task | Priority | Effort | Assignee |
|----|------|----------|--------|----------|
| T016 | Create base agent abstract class | P0 | M | @backend-engineer |
| T017 | Implement simple Orchestrator (no sub-agents) | P0 | L | @backend-engineer |
| T018 | Create main application entry point | P1 | M | @backend-engineer |
| T019 | End-to-end integration test | P1 | M | @qa-engineer |

---

## Dependency Graph

```
T001 (Docker Compose)
  |
  +---> T002 (Dockerfile) --------+
  |                               |
  +---> T004 (Env Config) --------+---> T018 (Main Entry)
                                  |
T003 (Project Structure) ---------+
  |
  +---> T005 (Pydantic Models) ---+
  |     |                         |
  |     +---> T012 (Exceptions)   |
  |     |                         |
  |     +---> T008 (Logging) -----+
  |                               |
  +---> T006 (Ontology) ----------+---> T007 (Init Script)
                                  |
                                  +---> T009 (Graphiti Client)
                                  |       |
                                  +---> T010 (Neo4j Client)
                                          |
                                          +---> T011 (Thread Manager)
                                                  |
T013 (Base Channel) -------------------------+    |
  |                                          |    |
  +---> T014 (CLI Driver) ---------------+   |    |
          |                              |   |    |
          +---> T015 (Thread Persist) ---+---+----+
                                         |
T016 (Base Agent) -----------------------+
  |                                      |
  +---> T017 (Orchestrator) -------------+
                                         |
                                         +---> T019 (E2E Test)
```

---

## Task Details

### T001: Create Docker Compose Configuration

**File**: `tasks/pending/T001-docker-compose-config.md`

Creates `docker-compose.yml` with:
- Neo4j 5.26+ service with persistence
- Python application service
- Shared network
- Volume mounts for data/logs

**Depends on**: Nothing (foundational)

---

### T002: Create Python Dockerfile

**File**: `tasks/pending/T002-python-dockerfile.md`

Creates `Dockerfile` with:
- Python 3.11+ base
- Poetry/pip dependency management
- Multi-stage build for production
- Non-root user

**Depends on**: T001

---

### T003: Set Up Project Directory Structure

**File**: `tasks/pending/T003-project-structure.md`

Creates directory hierarchy:
```
klabautermann/
  core/
  agents/
  channels/
  memory/
  mcp/
  utils/
scripts/
config/
tests/
```

**Depends on**: Nothing

---

### T004: Create Environment Configuration Template

**File**: `tasks/pending/T004-env-template.md`

Creates `.env.example` with all required credentials documented.
Creates `.gitignore` with proper exclusions.

**Depends on**: T001

---

### T005: Create Pydantic Core Models

**File**: `tasks/pending/T005-pydantic-models.md`

Implements models in `klabautermann/core/models.py`:
- `PersonNode`, `OrganizationNode`, `ProjectNode`, etc.
- `AgentMessage` for inter-agent communication
- `ThreadContext`, `SearchResult`

**Depends on**: T003

---

### T006: Define Ontology Constants

**File**: `tasks/pending/T006-ontology-constants.md`

Implements in `klabautermann/core/ontology.py`:
- `NodeLabel` enum
- `RelationType` enum
- Constraint/index definitions as strings

**Depends on**: T003

---

### T007: Create Database Initialization Script

**File**: `tasks/pending/T007-init-database.md`

Implements `scripts/init_database.py`:
- Creates all constraints from ONTOLOGY.md
- Creates all indexes (full-text, vector, temporal)
- Validates connection before running
- Idempotent (safe to re-run)

**Depends on**: T006

---

### T008: Set Up Nautical Logging System

**File**: `tasks/pending/T008-logging-system.md`

Implements `klabautermann/core/logger.py`:
- Nautical log levels ([CHART], [STORM], etc.)
- JSON structured logging
- Trace ID support
- File + console handlers

**Depends on**: T003, T005

---

### T009: Implement Graphiti Client Wrapper

**File**: `tasks/pending/T009-graphiti-client.md`

Implements `klabautermann/memory/graphiti_client.py`:
- Wrapper around Graphiti library
- `add_episode()` for ingestion
- `search()` for retrieval
- Connection management

**Depends on**: T006, T008

---

### T010: Implement Neo4j Direct Client

**File**: `tasks/pending/T010-neo4j-client.md`

Implements `klabautermann/memory/neo4j_client.py`:
- Direct Neo4j driver access
- Parametrized query execution
- Connection pooling
- Transaction support

**Depends on**: T006, T008

---

### T011: Create Thread Manager

**File**: `tasks/pending/T011-thread-manager.md`

Implements `klabautermann/memory/thread_manager.py`:
- Create/retrieve Thread nodes
- Add Message nodes with [:PRECEDES] links
- Get rolling context window (last N messages)
- Thread status management

**Depends on**: T009, T010

---

### T012: Create Custom Exceptions Module

**File**: `tasks/pending/T012-exceptions.md`

Implements `klabautermann/core/exceptions.py`:
- `GraphConnectionError`
- `ExternalServiceError`
- `ValidationError`
- `CircuitOpenError`

**Depends on**: T005

---

### T013: Create Base Channel Interface

**File**: `tasks/pending/T013-base-channel.md`

Implements `klabautermann/channels/base_channel.py`:
- Abstract `BaseChannel` class
- `receive_message()`, `send_message()` interfaces
- Thread mapping interface

**Depends on**: T003

---

### T014: Implement CLI Driver

**File**: `tasks/pending/T014-cli-driver.md`

Implements `klabautermann/channels/cli_driver.py`:
- Async REPL loop
- Input handling with history
- Output formatting
- Session management

**Depends on**: T013

---

### T015: Add Thread Persistence to CLI

**File**: `tasks/pending/T015-cli-thread-persistence.md`

Enhances CLI driver:
- Create/retrieve CLI thread on startup
- Store messages via Thread Manager
- Load context window for Orchestrator

**Depends on**: T011, T014

---

### T016: Create Base Agent Abstract Class

**File**: `tasks/pending/T016-base-agent.md`

Implements `klabautermann/agents/base_agent.py`:
- Abstract `BaseAgent` class
- Async inbox queue pattern
- Message processing interface
- Error handling wrapper

**Depends on**: T005, T008

---

### T017: Implement Simple Orchestrator

**File**: `tasks/pending/T017-simple-orchestrator.md`

Implements `klabautermann/agents/orchestrator.py`:
- Receives user input
- Loads thread context
- Calls Claude for response (simple, no delegation)
- Fires background ingestion task
- Returns formatted response

**Depends on**: T009, T011, T016

---

### T018: Create Main Application Entry Point

**File**: `tasks/pending/T018-main-entry.md`

Implements `main.py`:
- Initialize all components
- Wire up Orchestrator + CLI
- Start async event loop
- Graceful shutdown handling

**Depends on**: T002, T004, T017, T015

---

### T019: End-to-End Integration Test

**File**: `tasks/pending/T019-e2e-test.md`

Implements `tests/e2e/test_sprint1_foundation.py`:
- Golden Scenario 1: "I met Sarah from Acme" creates nodes
- Verify graph state after conversation
- Verify persistence across restart

**Depends on**: T018

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Graphiti complexity | Medium | High | Allocate 2 days for learning; fallback to manual temporal pattern |
| Neo4j Docker networking | Low | Medium | Test network connectivity Day 1 |
| Embedding API issues | Low | Medium | Have OpenAI and local embedding options ready |
| Async pattern complexity | Medium | Medium | Start with simple patterns, refactor later |

---

## Parallel Work Opportunities

These can be worked on simultaneously:
- T001 + T003 (infrastructure + project structure)
- T005 + T006 (models + ontology)
- T008 + T012 (logging + exceptions)
- T013 + T016 (base channel + base agent)

---

## Definition of Done

Sprint 1 is complete when:

- [ ] `docker-compose up -d` starts both containers healthy
- [ ] `python scripts/init_database.py` creates schema without errors
- [ ] Neo4j Browser shows constraints via `SHOW CONSTRAINTS`
- [ ] CLI accepts input and returns conversational responses
- [ ] "I met Sarah from Acme" creates Person and Organization nodes
- [ ] WORKS_AT relationship exists between Sarah and Acme
- [ ] Restart CLI and ask about Sarah - agent remembers
- [ ] Response latency under 5 seconds
- [ ] All code passes `ruff check` and `mypy`
- [ ] E2E test passes

---

## Crew Assignments

| Role | Primary Responsibilities |
|------|-------------------------|
| @devops-engineer | T001, T002, T004 - Infrastructure |
| @backend-engineer | T003, T005, T008, T012, T013, T014, T015, T016, T017, T018 - Core Python |
| @graph-engineer | T006, T007, T009, T010, T011 - Graph layer |
| @qa-engineer | T019 - Integration testing |

---

## Notes

- **Graphiti Fallback**: If Graphiti proves too complex by Day 3, fall back to manual temporal pattern in Neo4j. Document the decision in `devnotes/graph/graphiti-decision.md`.

- **Simple First**: The Sprint 1 Orchestrator is deliberately simple - no sub-agent delegation. This validates the critical path before adding complexity in Sprint 2.

- **Thread Persistence**: Even without the Archivist (Sprint 3), we need basic thread persistence for context windows. Keep it simple - just Message nodes and rolling retrieval.

---

*"First we build the hull. Then we fit the sails."* - The Shipwright
