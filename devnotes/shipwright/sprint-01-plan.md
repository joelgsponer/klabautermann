# Sprint 1 Plan Log

**Sprint**: 1 - Foundation ("Setting Sail")
**Planned Start**: Week 1
**Planned Duration**: 5 days
**Created**: 2026-01-15

---

## Sprint Goal

Establish infrastructure and validate critical path with minimal working assistant.

**Success Definition**: "I met Sarah from Acme" creates Person and Organization nodes with WORKS_AT relationship.

---

## Task Allocation

### Day 1: Infrastructure (4 tasks)

| ID | Task | Assignee | Effort |
|----|------|----------|--------|
| T001 | Docker Compose configuration | @devops-engineer | M |
| T002 | Python Dockerfile | @devops-engineer | S |
| T003 | Project directory structure | @backend-engineer | S |
| T004 | Environment configuration template | @devops-engineer | S |

**Day 1 Deliverable**: `docker-compose up -d` starts containers

### Day 2: Graph Foundation (4 tasks)

| ID | Task | Assignee | Effort |
|----|------|----------|--------|
| T005 | Pydantic core models | @backend-engineer | M |
| T006 | Ontology constants | @graph-engineer | S |
| T007 | Database initialization script | @graph-engineer | M |
| T008 | Nautical logging system | @backend-engineer | S |

**Day 2 Deliverable**: Schema exists in Neo4j, logging works

### Day 3: Memory Layer (4 tasks)

| ID | Task | Assignee | Effort |
|----|------|----------|--------|
| T009 | Graphiti client wrapper | @graph-engineer | L |
| T010 | Neo4j direct client | @graph-engineer | M |
| T011 | Thread manager | @backend-engineer | M |
| T012 | Custom exceptions | @backend-engineer | S |

**Day 3 Deliverable**: Can ingest episodes, query graph

### Day 4: CLI Channel (3 tasks)

| ID | Task | Assignee | Effort |
|----|------|----------|--------|
| T013 | Base channel interface | @backend-engineer | S |
| T014 | CLI driver | @backend-engineer | M |
| T015 | CLI thread persistence | @backend-engineer | M |

**Day 4 Deliverable**: CLI accepts input, persists messages

### Day 5: Orchestrator & Integration (4 tasks)

| ID | Task | Assignee | Effort |
|----|------|----------|--------|
| T016 | Base agent class | @backend-engineer | M |
| T017 | Simple Orchestrator | @backend-engineer | L |
| T018 | Main application entry | @backend-engineer | M |
| T019 | E2E integration test | @qa-engineer | M |

**Day 5 Deliverable**: Full loop works, Golden Scenario passes

---

## Parallel Work Opportunities

The following can be worked on simultaneously:

| Parallel Track A | Parallel Track B |
|------------------|------------------|
| T001 (Docker Compose) | T003 (Project Structure) |
| T005 (Models) | T006 (Ontology) |
| T008 (Logging) | T012 (Exceptions) |
| T013 (Base Channel) | T016 (Base Agent) |

---

## Critical Path

```
T001 --> T002 --> T018
T003 --> T005 --> T011 --> T015 --> T017 --> T018 --> T019
T003 --> T006 --> T007
T003 --> T006 --> T009 --> T017
```

**Blockers to Watch**:
1. Graphiti complexity (T009) - fallback to manual temporal pattern
2. Neo4j connectivity in Docker (T001) - test early

---

## Risk Register

| Risk | Mitigation | Owner |
|------|------------|-------|
| Graphiti learning curve | Allocate 2 days; document fallback | @graph-engineer |
| Docker networking issues | Test connectivity Day 1 | @devops-engineer |
| LLM API rate limits | Implement retry logic | @backend-engineer |
| Async pattern complexity | Start simple, refactor later | @backend-engineer |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-15 | Sprint 1 Orchestrator has no sub-agent delegation | Validate critical path before adding complexity |
| 2026-01-15 | Use fire-and-forget for ingestion | Don't block user response on graph updates |
| 2026-01-15 | Context window size: 15 messages | Balance between context and token cost |

---

## Notes

- **Graphiti Fallback**: If Graphiti proves too complex by Day 3, fall back to manual temporal pattern. Create decision note in `devnotes/navigator/graphiti-decision.md`.

- **Testing Strategy**: Unit tests written alongside implementation. E2E test (T019) validates sprint goal.

- **Documentation**: README updates deferred to Sprint 4. Focus on code and working system.

---

*"The manifest is set. Time to build the hull."* - The Shipwright
