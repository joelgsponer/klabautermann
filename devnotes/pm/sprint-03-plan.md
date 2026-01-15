# Sprint 3 Plan: Memory Lifecycle - "The Archivist & Scribe"

**Sprint**: 3
**Duration**: Week 3 (5 days)
**Goal**: Implement memory management, thread summarization, and daily reflection

## Overview

Sprint 3 transforms raw conversation data into durable knowledge. The Archivist agent detects inactive threads, summarizes them, and promotes key facts to the graph. The Scribe agent generates daily reflections, creating a personal journal with Klabautermann's voice.

## Key Specs

- [AGENTS.md](../../specs/architecture/AGENTS.md) - Archivist (Section 1.5) and Scribe (Section 1.6)
- [MEMORY.md](../../specs/architecture/MEMORY.md) - Thread management, Day nodes, temporal queries
- [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Note, JournalEntry, Day node schemas

## Sprint Goal

By the end of Sprint 3:
1. Inactive threads automatically detected and summarized
2. Summaries include structured extraction (topics, action items, facts, conflicts)
3. Original messages pruned but summary queryable
4. Daily reflection generated at midnight
5. Journal includes Klabautermann personality
6. Time-travel queries return historical state
7. Entity deduplication working

## Task List

### Day 1: Thread Detection (T036-T037)

| Task | Description | Assignee | Priority | Effort |
|------|-------------|----------|----------|--------|
| T036 | Cooldown Detection Query | navigator | P0 | S |
| T037 | Thread Status Lifecycle | carpenter | P0 | M |

### Day 2: Summarization (T038-T040)

| Task | Description | Assignee | Priority | Effort |
|------|-------------|----------|----------|--------|
| T038 | Thread Summary Pydantic Models | carpenter | P0 | S |
| T039 | LLM Summarization Pipeline | alchemist | P0 | L |
| T040 | Archivist Agent Skeleton | carpenter | P0 | M |

### Day 3: Graph Promotion (T041-T043)

| Task | Description | Assignee | Priority | Effort |
|------|-------------|----------|----------|--------|
| T041 | Note Node Creation | navigator | P0 | M |
| T042 | Day Node Management | navigator | P0 | M |
| T043 | Message Pruning After Archival | navigator | P1 | S |

### Day 4: Scribe Agent (T044-T046)

| Task | Description | Assignee | Priority | Effort |
|------|-------------|----------|----------|--------|
| T044 | Scribe Analytics Queries | navigator | P1 | M |
| T045 | Journal Generation Pipeline | alchemist | P1 | M |
| T046 | Scribe Agent Implementation | carpenter | P1 | M |

### Day 5: Integration (T047-T050)

| Task | Description | Assignee | Priority | Effort |
|------|-------------|----------|----------|--------|
| T047 | APScheduler Integration | engineer | P0 | M |
| T048 | Conflict Detection in Summaries | alchemist | P2 | M |
| T049 | Entity Deduplication | navigator | P2 | L |
| T050 | Sprint 3 Integration Tests | inspector | P1 | L |

## Dependencies

```
T036 (Cooldown Query) ─────┬─────> T037 (Thread Status) ─────> T040 (Archivist Skeleton)
                          │                                          │
T038 (Summary Models) ─────┴─────> T039 (Summarization Pipeline) ────┤
                                                                      │
                                    T041 (Note Creation) <────────────┤
                                          │                           │
T042 (Day Nodes) <────────────────────────┤                           │
      │                                   │                           │
      └────> T043 (Message Pruning) <─────┘                           │
                                                                      │
T044 (Analytics Queries) ─────────> T045 (Journal Pipeline) ──────────┤
                                          │                           │
                                          v                           │
                                    T046 (Scribe Agent) <─────────────┤
                                          │                           │
T047 (Scheduler) ────────────────────────>│                           │
                                          │                           │
T048 (Conflict Detection) ────────────────┤                           │
                                          │                           │
T049 (Deduplication) ─────────────────────┤                           │
                                          │                           │
                                          v                           │
                                    T050 (Integration Tests) <────────┘
```

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Summarization quality | Medium | Medium | Structured Pydantic output; keep thread link for drill-down |
| Over-pruning | Medium | High | User validation flag; keep summaries queryable |
| Scribe boring content | Medium | Low | Rich prompt with examples; pass analytics data |
| Scheduler conflicts | Low | Medium | Ensure single execution via APScheduler job store |

## Success Criteria

```
[ ] Inactive thread → automatically summarized
[ ] Summary → Note node in graph
[ ] Daily reflection → JournalEntry created
[ ] "What did I do yesterday?" → journal returned
[ ] Time-travel query → historical state returned
```

## Parallel Work Opportunities

- T044 (Analytics Queries) can parallelize with T041-T043
- T047 (Scheduler) can parallelize with T044-T046
- T048 (Conflict Detection) can parallelize with T049 (Deduplication)

## Notes

- Day nodes form the "temporal spine" - all time-bound entities link to their Day
- Archivist runs on 15-minute interval to check for inactive threads
- Scribe runs at midnight to generate daily reflection
- Message pruning is aggressive - only summaries remain after archival
