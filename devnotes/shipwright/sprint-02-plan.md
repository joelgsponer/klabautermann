# Sprint 2 Implementation Plan

**Date:** 2026-01-15
**Sprint:** Multi-Agent Architecture
**Status:** In Progress

---

## Current State Assessment

### Completed (Sprint 1)
- T001-T019: All foundation tasks complete
- Base agent class, simple orchestrator, CLI, Neo4j/Graphiti clients ready

### In Progress
- **T020** - Orchestrator Intent Classification (in tasks/in-progress/)

### Pending
- T021-T035: 15 tasks awaiting implementation

---

## Dependency Analysis

### Critical Path
```
T020 (in-progress)
  |
  +-> T021 (agent delegation) - BLOCKED on T020
      |
      +-> T023 (ingestor) -----------> T034 (main startup)
      +-> T024 (researcher) -> T025 --> T034
      +-> T029 (executor) -----------> T034
```

### Parallel Tracks

**Track 1: Orchestrator/Agents (carpenter)**
- T020 (in-progress) -> T021 -> T023, T024, T029 -> T034

**Track 2: MCP/Integration (purser)**
- T026 (no deps) -> T027 -> T028 -> T030, T031

**Track 3: Config System (carpenter)**
- T032 (no deps) -> T033 -> T034

**Track 4: Graph Queries (navigator)**
- T025 (depends on T024 being designed, not implemented)

**Track 5: Integration Tests (inspector)**
- T035 (depends on T034)

---

## Tasks That Can Start Immediately

These tasks have NO blockers and can start in parallel:

| Task | Description | Assignee | Why Unblocked |
|------|-------------|----------|---------------|
| T022 | Retry utility | carpenter | Independent utility |
| T026 | MCP client wrapper | purser | Foundation work |
| T032 | Agent config system | carpenter | Independent infrastructure |

---

## Implementation Waves

### Wave 1: Foundations (Parallel Start NOW)

| Task | Assignee | Dependencies | Notes |
|------|----------|--------------|-------|
| T020 | carpenter | IN PROGRESS | Complete ASAP - critical blocker |
| T022 | carpenter | None | Small utility, quick win |
| T026 | purser | None | MCP foundation |
| T032 | carpenter | None | Config foundation |

**Wave 1 Goal:** Unblock all downstream tasks

### Wave 2: Sub-Agents (After T020, T021)

| Task | Assignee | Dependencies | Notes |
|------|----------|--------------|-------|
| T021 | carpenter | T020 | Agent delegation pattern |
| T027 | purser | T026 | OAuth bootstrap |
| T033 | carpenter | T032 | Config hot-reload |

**Wave 2 Goal:** Enable agent creation

### Wave 3: Core Agents (After T021)

| Task | Assignee | Dependencies | Notes |
|------|----------|--------------|-------|
| T023 | carpenter | T021 | Ingestor agent |
| T024 | carpenter | T021 | Researcher agent |
| T028 | purser | T026, T027 | Google Workspace bridge |
| T025 | navigator | T024 design | Cypher queries (can start when T024 interface defined) |

**Wave 3 Goal:** Core agent functionality

### Wave 4: Executor Chain (After T028)

| Task | Assignee | Dependencies | Notes |
|------|----------|--------------|-------|
| T029 | carpenter | T021, T028 | Executor agent |
| T030 | purser | T029, T028 | Gmail handlers |
| T031 | purser | T029, T028 | Calendar handlers |

**Wave 4 Goal:** Action execution capability

### Wave 5: Integration (After Waves 3-4)

| Task | Assignee | Dependencies | Notes |
|------|----------|--------------|-------|
| T034 | carpenter | T020, T023, T024, T029, T033 | Main.py update |
| T035 | inspector | T034 | Integration tests |

**Wave 5 Goal:** System integration and validation

---

## Assignments by Subagent

### carpenter (Backend Tasks)
**Priority Order:**
1. T020 - Complete orchestrator refactor (IN PROGRESS)
2. T022 - Retry utility (parallel, quick)
3. T032 - Config system (parallel, independent)
4. T021 - Agent delegation (after T020)
5. T033 - Hot reload (after T032)
6. T023 - Ingestor (after T021)
7. T024 - Researcher (after T021, parallel with T023)
8. T029 - Executor (after T021 + T028)
9. T034 - Main startup (final integration)

### purser (MCP/Integration Tasks)
**Priority Order:**
1. T026 - MCP client wrapper (START NOW)
2. T027 - OAuth bootstrap (after T026)
3. T028 - Google Workspace bridge (after T027)
4. T030 - Gmail handlers (after T029)
5. T031 - Calendar handlers (after T029, parallel with T030)

### navigator (Graph Tasks)
**Priority Order:**
1. T025 - Hybrid search queries (can start when T024 interface is defined)

### inspector (QA Tasks)
**Priority Order:**
1. T035 - Integration tests (after T034)

---

## Coordination Points

### Handoff 1: T021 -> T023, T024, T029
Once T021 (agent delegation) is complete, carpenter should notify PM so T023, T024, and T029 can proceed.

### Handoff 2: T028 -> T029
purser completes Google Workspace bridge, then carpenter can implement Executor agent.

### Handoff 3: T024 -> T025
Once carpenter defines the Researcher interface (search method signatures), navigator can implement queries.

### Handoff 4: T034 -> T035
Once main.py integration is complete, inspector can write integration tests.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| T020 takes too long | Already in progress; carpenter focus here first |
| MCP proves unreliable | T028 designed with fallback to direct API |
| OAuth headless issues | T027 has detailed bootstrap script |
| Agent coordination bugs | Comprehensive logging from Sprint 1 |

---

## Immediate Actions

### For carpenter:
1. **PRIORITY 1:** Finish T020 (orchestrator intent classification)
2. Start T022 (retry utility) in parallel if bandwidth allows
3. Start T032 (config system) in parallel if bandwidth allows

### For purser:
1. **START NOW:** T026 (MCP client wrapper) - no blockers
2. Plan T027, T028 implementation while T026 in progress

### For navigator:
1. **WAIT:** Monitor T024 progress
2. Review Researcher task file to understand interface expectations
3. Can start designing T025 queries based on spec

### For inspector:
1. **WAIT:** Monitor T034 progress
2. Review T035 task file and prepare test framework
3. Can start designing test scenarios based on specs

---

## Success Metrics

Sprint 2 complete when:
- [ ] All 16 tasks (T020-T035) in tasks/completed/
- [ ] Integration tests pass
- [ ] `make check` passes
- [ ] Manual verification of:
  - Intent classification working
  - Agent delegation working
  - Entity extraction working
  - Gmail/Calendar actions working
  - Config hot-reload working

---

*"The charts are laid. Now the crew sets sail."* - The Shipwright
