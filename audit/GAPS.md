# Klabautermann Gap Analysis: Spec vs Implementation

**Date**: 2026-01-20
**Version**: 1.0
**Overall Completion**: ~70%

---

## Executive Summary

This document catalogs gaps between the specifications in `specs/` and the current implementation. Each gap is mapped to a recommended GitHub issue with priority and complexity ratings.

**Gap Categories**:
- **Missing**: Feature not implemented at all
- **Partial**: Feature started but incomplete
- **AI-First**: Feature uses keywords/regex but needs pure LLM intelligence
- **Unwired**: Module exists but not integrated

---

## 1. Agents (Spec: `AGENTS.md`, `AGENTS_EXTENDED.md`)

### 1.1 Primary Agents - Gaps

| Component | Spec Section | Status | Gap Description | Priority | Issue ID |
|-----------|--------------|--------|-----------------|----------|----------|
| Orchestrator | MAINAGENT.md 2.1 | AI-First | Intent classification uses keyword matching (search_keywords, action_keywords in config) instead of pure LLM | P0 | AGT-P-001 |
| Orchestrator | MAINAGENT.md 5.1 | Missing | True multi-model orchestration not implemented - uses single Sonnet model | P1 | AGT-P-002 |
| Orchestrator | PRD 8.4 | Missing | Storm Mode detection and response adaptation | P2 | AGT-P-004 |
| Ingestor | AGENTS.md 2.1 | Missing | LLM-based pre-extraction using Haiku - relies entirely on Graphiti | P1 | AGT-P-009 |
| Ingestor | ONTOLOGY.md 7 | Missing | Custom ontology validation on extracted entities | P1 | AGT-P-010 |
| Researcher | RESEARCHER.md 2.4 | Missing | Structural traversal queries (REPORTS_TO chains, etc.) | P1 | AGT-P-013 |
| Researcher | RESEARCHER.md 2.5 | Missing | Time-filtered temporal queries ("Who did X work for last year?") | P1 | AGT-P-014 |
| Researcher | RESEARCHER.md 2.6 | Missing | Island search (Knowledge Island exploration) | P2 | AGT-P-015 |
| Researcher | AGENTS_EXTENDED.md 4.4 | AI-First | Zoom level detection uses keyword matching | P0 | AGT-P-018 |
| Executor | MCP.md | Missing | Email reply-to-thread functionality | P1 | AGT-P-020 |
| Executor | MCP.md | Missing | Calendar event update/delete | P1 | AGT-P-021 |
| Executor | MCP.md | Missing | Recurring events support | P2 | AGT-P-022 |
| Archivist | AGENTS.md 3.4 | Unwired | Deduplication module exists but not integrated | P1 | AGT-P-024 |
| Scribe | AGENTS.md 3.5 | Partial | Personality voice generation uses template, not dynamic | P2 | AGT-P-025 |

### 1.2 Secondary Agents - Completely Missing

Per `specs/architecture/AGENTS_EXTENDED.md`, all 6 secondary agents are unimplemented:

| Agent | Spec Section | Purpose | Priority | Complexity | Issue Range |
|-------|--------------|---------|----------|------------|-------------|
| **Bard of the Bilge** | AGENTS_EXTENDED.md 1 | Progressive storytelling, tidbits, saga management | P2 | XL | AGT-S-001 to AGT-S-012 |
| **Purser** | AGENTS_EXTENDED.md 2 | Delta-sync Gmail/Calendar, TheSieve email filter | P1 | L | AGT-S-013 to AGT-S-022 |
| **First Officer** | AGENTS_EXTENDED.md 3 | Proactive alerts, morning briefings, deadline warnings | P1 | L | AGT-S-023 to AGT-S-032 |
| **Cartographer** | AGENTS_EXTENDED.md 4 | Community detection, Knowledge Islands, GDS algorithms | P2 | XL | AGT-S-033 to AGT-S-042 |
| **Hull Cleaner** | AGENTS_EXTENDED.md 5 | Graph pruning, weak relationship removal, dedup merge | P2 | M | AGT-S-043 to AGT-S-052 |
| **Quartermaster** | AGENTS_EXTENDED.md 6 | A/B testing prompts, model switching, optimization | P3 | M | AGT-S-053 to AGT-S-060 |

**Detailed Bard gaps**:
- No BardOfTheBilge class
- No LoreEpisode node creation
- No saga management (SagaManager class)
- No tidbit selection logic
- No integration with Orchestrator response formatting
- No cross-channel saga persistence

**Detailed Purser gaps**:
- No delta-sync for Gmail
- No delta-sync for Calendar
- No TheSieve email filtering class
- No VIP whitelist management
- No external_id tracking for duplicates

**Detailed First Officer gaps**:
- No proactive alert system
- No morning briefing generation
- No deadline monitoring
- No meeting reminder integration
- No "Quiet Watch" mode for focus time

---

## 2. Lore System (Spec: `LORE_SYSTEM.md`)

**Status**: Completely unimplemented (0%)

| Component | Spec Section | Gap Description | Priority | Issue ID |
|-----------|--------------|-----------------|----------|----------|
| LoreEpisode Node | LORE_SYSTEM.md 2.1 | Node type not defined in implementation | P2 | LORE-001 |
| TOLD_TO Relationship | LORE_SYSTEM.md 2.2 | Relationship not implemented | P2 | LORE-002 |
| EXPANDS_UPON Relationship | LORE_SYSTEM.md 2.2 | Saga chaining not implemented | P2 | LORE-003 |
| SAGA_STARTED_BY Relationship | LORE_SYSTEM.md 2.2 | Saga initiation tracking missing | P2 | LORE-004 |
| SagaManager Class | LORE_SYSTEM.md 3.3 | Saga lifecycle management missing | P2 | LORE-005 |
| Canonical Adventures | LORE_SYSTEM.md 4.1 | CANONICAL_SAGAS data missing | P2 | LORE-006 |
| Standalone Tidbits | LORE_SYSTEM.md 4.1 | STANDALONE_TIDBITS data missing | P2 | LORE-007 |
| Tidbit Selection Logic | LORE_SYSTEM.md 4.2 | Selection algorithm missing | P2 | LORE-008 |
| Orchestrator Integration | LORE_SYSTEM.md 5.1 | salt_response not called | P2 | LORE-009 |
| Scribe Integration | LORE_SYSTEM.md 5.2 | Saga progress in daily reflection missing | P3 | LORE-010 |
| Cross-Channel Persistence | LORE_SYSTEM.md 1.2 | Captain-context vs thread-context not implemented | P2 | LORE-011 |
| Saga Query Patterns | LORE_SYSTEM.md 6 | Cypher queries for lore retrieval missing | P2 | LORE-012 |
| Bard Config | LORE_SYSTEM.md 7.1 | config/agents/bard.yaml missing | P3 | LORE-013 |
| Unit Tests | LORE_SYSTEM.md 8.1 | test_lore_system.py missing | P2 | LORE-014 |
| E2E Test | LORE_SYSTEM.md 8.2 | Cross-conversation saga test missing | P2 | LORE-015 |

---

## 3. Channels (Spec: `CHANNELS.md`)

### 3.1 Implementation Status

| Channel | Spec Section | Status | Completion |
|---------|--------------|--------|------------|
| CLI | CHANNELS.md 2 | Functional | 90% |
| Telegram | CHANNELS.md 3 | Missing | 0% |
| Discord | CHANNELS.md 6.1 | Missing | 0% |
| Web | CHANNELS.md 6.2 | Partial | 20% |
| Channel Manager | CHANNELS.md 5.2 | Missing | 0% |

### 3.2 CLI Gaps

| Feature | Spec Section | Status | Issue ID |
|---------|--------------|--------|----------|
| /status command | CHANNELS.md 2.2 | Missing | CHAN-001 |
| Session reset on /clear | CHANNELS.md 2.2 | Partial | CHAN-002 |

### 3.3 Telegram - Complete Implementation Needed

| Feature | Spec Section | Status | Issue ID |
|---------|--------------|--------|----------|
| TelegramDriver base class | CHANNELS.md 3.3 | Missing | CHAN-003 |
| Bot token configuration | CHANNELS.md 3.4 | Missing | CHAN-004 |
| /start command | CHANNELS.md 3.3 | Missing | CHAN-005 |
| /help command | CHANNELS.md 3.3 | Missing | CHAN-006 |
| /status command | CHANNELS.md 3.3 | Missing | CHAN-007 |
| Text message handling | CHANNELS.md 3.3 | Missing | CHAN-008 |
| Voice message handling | CHANNELS.md 3.3 | Missing | CHAN-009 |
| Whisper transcription | CHANNELS.md 3.3 | Missing | CHAN-010 |
| User whitelist | CHANNELS.md 3.3 | Missing | CHAN-011 |
| Typing indicators | CHANNELS.md 3.3 | Missing | CHAN-012 |
| Markdown formatting | CHANNELS.md 3.3 | Missing | CHAN-013 |
| Thread isolation | CHANNELS.md 4 | Missing | CHAN-014 |
| Config file | CHANNELS.md 3.4 | Missing | CHAN-015 |
| Integration test | CHANNELS.md 7.2 | Missing | CHAN-016 |
| E2E test | CHANNELS.md 7.2 | Missing | CHAN-017 |

### 3.4 Discord - Stub Implementation Needed

| Feature | Spec Section | Status | Issue ID |
|---------|--------------|--------|----------|
| DiscordDriver class | CHANNELS.md 6.1 | Missing | CHAN-018 |
| Guild management | CHANNELS.md 6.1 | Missing | CHAN-019 |
| Slash commands | CHANNELS.md 6.1 | Missing | CHAN-020 |
| Rich embeds | CHANNELS.md 6.1 | Missing | CHAN-021 |
| Role-based auth | CHANNELS.md 8.1 | Missing | CHAN-022 |

### 3.5 Channel Manager

| Feature | Spec Section | Status | Issue ID |
|---------|--------------|--------|----------|
| ChannelManager class | CHANNELS.md 5.2 | Missing | CHAN-023 |
| Multi-channel startup | CHANNELS.md 5.2 | Missing | CHAN-024 |
| Health monitoring | CHANNELS.md 5.2 | Missing | CHAN-025 |
| Graceful shutdown | CHANNELS.md 5.2 | Missing | CHAN-026 |

---

## 4. Ontology (Spec: `ONTOLOGY.md`)

### 4.1 Missing Entity Types

| Entity | Spec Section | Status | Issue ID |
|--------|--------------|--------|----------|
| Hobby | ONTOLOGY.md 1.2 | Missing in code | ONT-001 |
| HealthMetric | ONTOLOGY.md 1.2 | Missing in code | ONT-002 |
| Pet | ONTOLOGY.md 1.2 | Missing in code | ONT-003 |
| Milestone | ONTOLOGY.md 1.2 | Missing in code | ONT-004 |
| Routine | ONTOLOGY.md 1.2 | Missing in code | ONT-005 |
| Preference | ONTOLOGY.md 1.2 | Missing in code | ONT-006 |
| Community | ONTOLOGY.md 1.2 | Missing in code | ONT-007 |
| LoreEpisode | ONTOLOGY.md 1.2 | Missing in code | ONT-008 |

### 4.2 Missing Relationship Types

| Relationship | Spec Section | Status | Issue ID |
|--------------|--------------|--------|----------|
| FAMILY_OF | ONTOLOGY.md 2.8 | Missing | ONT-009 |
| SPOUSE_OF | ONTOLOGY.md 2.8 | Missing | ONT-010 |
| PARENT_OF | ONTOLOGY.md 2.8 | Missing | ONT-011 |
| CHILD_OF | ONTOLOGY.md 2.8 | Missing | ONT-012 |
| SIBLING_OF | ONTOLOGY.md 2.8 | Missing | ONT-013 |
| FRIEND_OF | ONTOLOGY.md 2.8 | Missing | ONT-014 |
| PRACTICES | ONTOLOGY.md 2.9 | Missing | ONT-015 |
| OWNS | ONTOLOGY.md 2.9 | Missing | ONT-016 |
| RECORDED | ONTOLOGY.md 2.9 | Missing | ONT-017 |
| ACHIEVES | ONTOLOGY.md 2.9 | Missing | ONT-018 |
| FOLLOWS_ROUTINE | ONTOLOGY.md 2.9 | Missing | ONT-019 |
| PREFERS | ONTOLOGY.md 2.9 | Missing | ONT-020 |
| PART_OF_ISLAND | ONTOLOGY.md 2.10 | Missing | ONT-021 |
| EXPANDS_UPON | ONTOLOGY.md 2.11 | Missing | ONT-022 |
| TOLD_TO | ONTOLOGY.md 2.11 | Missing | ONT-023 |
| SAGA_STARTED_BY | ONTOLOGY.md 2.11 | Missing | ONT-024 |

### 4.3 Database Setup Gaps

| Component | Spec Section | Status | Issue ID |
|-----------|--------------|--------|----------|
| Personal life constraints | ONTOLOGY.md 4.1 | Missing | ONT-025 |
| Personal life indexes | ONTOLOGY.md 4.2 | Missing | ONT-026 |
| Lore indexes | ONTOLOGY.md 4.2 | Missing | ONT-027 |
| Family temporal indexes | ONTOLOGY.md 4.2 | Missing | ONT-028 |
| Pydantic models for personal life | ONTOLOGY.md 6 | Missing | ONT-029 |

---

## 5. Memory (Spec: `MEMORY.md`)

| Feature | Spec Section | Status | Gap Description | Issue ID |
|---------|--------------|--------|-----------------|----------|
| Multi-level retrieval | MEMORY.md | Partial | Zoom levels not implemented | MEM-001 |
| Zoom level detection | MEMORY.md | AI-First | Uses keyword matching | MEM-002 |
| Deduplication wiring | MEMORY.md | Unwired | Module exists, not integrated | MEM-003 |
| Orphan message detection | MEMORY.md | Missing | No cleanup routine | MEM-004 |
| Entity merge utility | MEMORY.md | Missing | No merge function | MEM-005 |
| Temporal spine queries | MEMORY.md | Partial | Day node queries limited | MEM-006 |

---

## 6. MCP/Integrations (Spec: `MCP.md`)

| Feature | Spec Section | Status | Issue ID |
|---------|--------------|--------|----------|
| Email reply-to-thread | MCP.md | Missing | MCP-001 |
| Email attachments | MCP.md | Missing | MCP-002 |
| Calendar update event | MCP.md | Missing | MCP-003 |
| Calendar delete event | MCP.md | Missing | MCP-004 |
| Recurring events | MCP.md | Missing | MCP-005 |
| Add attendees | MCP.md | Missing | MCP-006 |
| Filesystem MCP wiring | MCP.md | Unwired | MCP-007 |
| OAuth refresh handling | MCP.md | Partial | MCP-008 |
| Rate limiting | MCP.md | Missing | MCP-009 |

---

## 7. Testing (Spec: `TESTING.md`)

### 7.1 Test Infrastructure Gaps

| Issue | Status | Impact | Issue ID |
|-------|--------|--------|----------|
| Import errors in test suite | Broken | Tests cannot run | TEST-001 |
| pytest-asyncio configuration | Missing | Async tests fail | TEST-002 |
| Fixtures for agents | Partial | Limited test coverage | TEST-003 |
| Mock Graphiti client | Missing | Cannot test ingestion | TEST-004 |
| Mock MCP servers | Missing | Cannot test actions | TEST-005 |

### 7.2 Golden Scenarios (Spec: `TESTING.md`)

| Scenario | Spec Section | Status | Issue ID |
|----------|--------------|--------|----------|
| New Contact | TESTING.md 10.2 | Defined, untested | TEST-006 |
| Contextual Retrieval | TESTING.md 10.2 | Defined, untested | TEST-007 |
| Blocked Task | TESTING.md 10.2 | Defined, untested | TEST-008 |
| Temporal Time-Travel | TESTING.md 10.2 | Defined, untested | TEST-009 |
| Multi-Channel Threading | TESTING.md 10.2 | Defined, untested | TEST-010 |

---

## 8. Infrastructure (Spec: `DEPLOYMENT.md`)

### 8.1 CI/CD - Completely Missing

| Component | Status | Issue ID |
|-----------|--------|----------|
| .github/workflows/ directory | Missing | INFRA-001 |
| ci.yml workflow | Missing | INFRA-002 |
| test.yml workflow | Missing | INFRA-003 |
| lint.yml workflow | Missing | INFRA-004 |
| type-check.yml workflow | Missing | INFRA-005 |
| coverage.yml workflow | Missing | INFRA-006 |
| Dependabot config | Missing | INFRA-007 |

### 8.2 Docker Gaps

| Component | Status | Issue ID |
|-----------|--------|----------|
| Production Dockerfile optimization | Partial | INFRA-008 |
| Health check endpoint | Partial | INFRA-009 |
| Backup scripts | Missing | INFRA-010 |
| Multi-stage build | Missing | INFRA-011 |

---

## 9. Documentation Gaps

| Document | Status | Issue ID |
|----------|--------|----------|
| QUICKSTART.md | Missing | DOC-001 |
| Telegram setup guide | Missing | DOC-002 |
| API documentation | Missing | DOC-003 |
| Troubleshooting guide | Missing | DOC-004 |
| Architecture diagrams | Partial | DOC-005 |

---

## 10. Skills Framework Gaps

| Feature | Status | Issue ID |
|---------|--------|----------|
| schedule-meeting skill | Missing | SKILL-001 |
| search-contacts skill | Missing | SKILL-002 |
| create-note skill | Missing | SKILL-003 |
| add-task skill | Missing | SKILL-004 |
| Natural language skill discovery | AI-First | SKILL-006 |
| Skill chaining | Missing | SKILL-007 |

---

## Summary Statistics

| Category | Total Gaps | P0 | P1 | P2 | P3 |
|----------|------------|----|----|----|----|
| Agents (Primary) | 25 | 2 | 10 | 11 | 2 |
| Agents (Secondary) | 60 | 0 | 20 | 35 | 5 |
| Lore System | 30 | 0 | 0 | 26 | 4 |
| Channels | 35 | 0 | 20 | 15 | 0 |
| Ontology | 25 | 0 | 10 | 15 | 0 |
| Memory | 20 | 0 | 8 | 10 | 2 |
| MCP | 20 | 0 | 12 | 8 | 0 |
| Testing | 35 | 5 | 20 | 10 | 0 |
| Infrastructure | 25 | 3 | 15 | 7 | 0 |
| Documentation | 15 | 0 | 5 | 8 | 2 |
| Skills | 10 | 0 | 2 | 6 | 2 |
| **TOTAL** | **300** | **10** | **122** | **151** | **17** |

---

## Critical Path (Blocking Chain)

```
TEST-001 (Fix test environment) [P0]
    ↓
INFRA-001 (Create CI/CD workflow) [P0]
    ↓
AGT-P-001 (Remove keyword intent classification) [P0] [AI-FIRST]
    ↓
CHAN-003 (Telegram driver base) [P1]
    ↓
AGT-S-001 (Bard agent skeleton) [P2]
    ↓
LORE-001+ (Lore system) [P2]
```

---

## AI-First Priority Issues

These issues MUST use pure LLM intelligence, no keywords or regex:

| Issue ID | Description | Current Approach | Required Approach |
|----------|-------------|------------------|-------------------|
| AGT-P-001 | Intent classification | Keyword lists in config | LLM tool_use classification |
| AGT-P-018 | Query zoom level detection | Keyword matching | LLM semantic understanding |
| MEM-002 | Retrieval zoom detection | Keyword matching | LLM context analysis |
| SKILL-006 | Skill discovery | Pattern matching | Natural language understanding |

---

*"Every gap is a voyage waiting to begin."* - Klabautermann
