# Klabautermann Implementation Roadmap

**Version**: 1.1
**Timeline**: 4 Core Sprints + 4 Enhancement Phases
**Approach**: Iterative with continuous working functionality

---

## Related Specifications

This roadmap references the following specification documents:

| Category | Document | Key Content |
|----------|----------|-------------|
| **Architecture** | [AGENTS.md](./architecture/AGENTS.md) | Primary crew (6 agents), delegation patterns |
| **Architecture** | [AGENTS_EXTENDED.md](./architecture/AGENTS_EXTENDED.md) | Secondary crew (6 agents), utility agents |
| **Architecture** | [ONTOLOGY.md](./architecture/ONTOLOGY.md) | Graph schema, entities, relationships |
| **Architecture** | [MEMORY.md](./architecture/MEMORY.md) | Graphiti integration, multi-level retrieval |
| **Architecture** | [LORE_SYSTEM.md](./architecture/LORE_SYSTEM.md) | Progressive storytelling, saga management |
| **Architecture** | [CHANNELS.md](./architecture/CHANNELS.md) | CLI, Telegram, channel abstraction |
| **Architecture** | [MCP_INTEGRATION.md](./architecture/MCP_INTEGRATION.md) | Tool access, Google Workspace |
| **Branding** | [PERSONALITY.md](./branding/PERSONALITY.md) | Voice, tidbits, Bard integration |
| **Quality** | [CODING_STANDARDS.md](./quality/CODING_STANDARDS.md) | Python standards, async patterns |
| **Quality** | [TESTING.md](./quality/TESTING.md) | Golden scenarios, test strategy |
| **Quality** | [OPTIMIZATIONS.md](./quality/OPTIMIZATIONS.md) | The Sieve, barnacle scraping, pruning |

---

## Overview

This roadmap breaks down Klabautermann into **four core sprints** (MVP), followed by **enhancement phases** that add the full feature set. Every sprint ends with a deployable system.

```
═══════════════════════════════════════ CORE SPRINTS (MVP) ═══════════════════════════════════════

Week 1                Week 2                Week 3                Week 4
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Foundation  │────▶│  The Crew    │────▶│   Memory     │────▶│  Production  │
│              │     │              │     │  Lifecycle   │     │              │
│ Neo4j+CLI+   │     │ Multi-Agent+ │     │  Archivist+  │     │ Telegram+    │
│ Orchestrator │     │     MCP      │     │    Scribe    │     │  Branding    │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘

═════════════════════════════════════ ENHANCEMENT PHASES ═════════════════════════════════════════

Phase 2               Phase 3               Phase 4               Phase 5
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Secondary    │────▶│  Knowledge   │────▶│ Progressive  │────▶│    Graph     │
│   Crew       │     │   Islands    │     │ Storytelling │     │ Optimization │
│              │     │              │     │              │     │              │
│ Purser+Sieve │     │ Cartographer │     │    Bard+     │     │ Hull Cleaner │
│  +Officer    │     │ +Multi-Level │     │    Sagas     │     │ +Quartermastr│
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘

Phase 6               Phase 7               Phase 8
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Personal     │────▶│  The Bridge  │────▶│  Enterprise  │
│    Life      │     │  Dashboard   │     │   & Scale    │
│              │     │              │     │              │
│ Family+Hobby │     │  React UI+   │     │ Multi-User+  │
│ +Health+Pet  │     │ Graph Viz    │     │    SSO       │
└──────────────┘     └──────────────┘     └──────────────┘
```

---

## Sprint 1: Foundation - "Setting Sail"

**Duration**: Week 1 (5 days)
**Goal**: Establish infrastructure and validate critical path with minimal working assistant

**Key Specs**: [ONTOLOGY.md](./architecture/ONTOLOGY.md), [MEMORY.md](./architecture/MEMORY.md), [CHANNELS.md](./architecture/CHANNELS.md), [CODING_STANDARDS.md](./quality/CODING_STANDARDS.md)

### Day-by-Day Breakdown

| Day | Focus | Deliverables |
|-----|-------|--------------|
| 1 | Infrastructure | Docker Compose, Neo4j running, project structure created |
| 2 | Graph Foundation | Graphiti initialized, ontology defined, indexes created |
| 3 | Memory Layer | graphiti_client.py, neo4j_client.py, test episode ingestion |
| 4 | CLI Channel | base_channel.py, cli_driver.py, thread persistence |
| 5 | Simple Orchestrator | Basic conversational loop, memory search, end-to-end test |

### Deliverables Checklist

**Infrastructure**
- [ ] `docker-compose.yml` with Neo4j 5.26+
- [ ] `Dockerfile` for Python app
- [ ] `.env.example` with all credential templates
- [ ] `.gitignore` properly configured
- [ ] Project directory structure created

**Core Package**
- [ ] `klabautermann/core/models.py` - All Pydantic models
- [ ] `klabautermann/core/ontology.py` - Node labels, relationship types
- [ ] `klabautermann/core/logger.py` - Nautical logging system
- [ ] `klabautermann/core/exceptions.py` - Custom exceptions

**Memory Layer**
- [ ] `klabautermann/memory/graphiti_client.py` - Graphiti wrapper
- [ ] `klabautermann/memory/neo4j_client.py` - Direct Neo4j access
- [ ] `klabautermann/memory/thread_manager.py` - Thread persistence
- [ ] `scripts/init_database.py` - Schema setup script

**Channel Layer**
- [ ] `klabautermann/channels/base_channel.py` - Abstract interface
- [ ] `klabautermann/channels/cli_driver.py` - CLI implementation

**Agent Layer**
- [ ] `klabautermann/agents/orchestrator.py` - Simple (no sub-agents)

### Verification Criteria

```bash
# 1. Start infrastructure
docker-compose up -d
# Expected: Both containers healthy

# 2. Initialize database
python scripts/init_database.py
# Expected: Constraints and indexes created

# 3. Verify Neo4j
# Open http://localhost:7474
# Run: SHOW CONSTRAINTS
# Run: SHOW INDEXES
# Expected: See Person, Organization, Thread constraints

# 4. Start CLI
docker attach klabautermann-app
# Expected: Prompt appears

# 5. Test ingestion
> I met Sarah from Acme Corp
# Expected: Conversational response

# 6. Verify graph
# In Neo4j Browser:
MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT]->(o:Organization)
WHERE r.expired_at IS NULL
RETURN p, r, o
# Expected: Nodes and relationship visible

# 7. Test persistence
# Restart CLI, ask about Sarah
# Expected: Agent remembers Sarah
```

### Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Graphiti complexity | Medium | High | Allocate 2 days for learning; fallback to manual temporal pattern |
| Neo4j Docker networking | Low | Medium | Test network connectivity Day 1 |
| Embedding API issues | Low | Medium | Have OpenAI and local embedding options ready |

### Definition of Done

- [ ] Docker containers start with `docker-compose up -d`
- [ ] CLI accepts input and returns responses
- [ ] Entities extracted from conversation appear in Neo4j
- [ ] Thread persistence works across CLI restarts
- [ ] Response latency <5 seconds

---

## Sprint 2: The Crew - "Multi-Agent Architecture"

**Duration**: Week 2 (5 days)
**Goal**: Decompose orchestrator into specialized sub-agents with MCP integration

**Key Specs**: [AGENTS.md](./architecture/AGENTS.md), [MCP_INTEGRATION.md](./architecture/MCP_INTEGRATION.md), [CODING_STANDARDS.md](./quality/CODING_STANDARDS.md)

### Day-by-Day Breakdown

| Day | Focus | Deliverables |
|-----|-------|--------------|
| 1 | Base Agent | base_agent.py, async message passing pattern |
| 2 | Ingestor + Researcher | Entity extraction, hybrid search |
| 3 | MCP Setup | Google OAuth bootstrap, Google Workspace MCP |
| 4 | Executor | Action execution via MCP tools |
| 5 | Integration | Orchestrator delegation, config hot-reload, logging |

### Deliverables Checklist

**Agent Architecture**
- [ ] `klabautermann/agents/base_agent.py` - Abstract base with inbox queue
- [ ] `klabautermann/agents/orchestrator.py` - Refactored for delegation
- [ ] `klabautermann/agents/ingestor.py` - Entity extraction
- [ ] `klabautermann/agents/researcher.py` - Hybrid search
- [ ] `klabautermann/agents/executor.py` - MCP tool execution

**MCP Integration**
- [ ] `klabautermann/mcp/client.py` - Generic MCP wrapper
- [ ] `klabautermann/mcp/google_workspace.py` - Gmail/Calendar bridge
- [ ] `scripts/bootstrap_auth.py` - OAuth2 setup script

**Configuration**
- [ ] `config/quartermaster.py` - Hot-reload manager
- [ ] `config/agents/orchestrator.yaml` - Orchestrator config
- [ ] `config/agents/ingestor.yaml` - Ingestor config
- [ ] `config/agents/researcher.yaml` - Researcher config
- [ ] `config/agents/executor.yaml` - Executor config

**Utilities**
- [ ] `klabautermann/utils/retry.py` - Exponential backoff decorator

### Verification Criteria

```bash
# 1. Test agent delegation
> Who is Sarah?
# Expected: Logs show Orchestrator → Researcher delegation

# 2. Test ingestion
> I had lunch with Tom from Google today
# Expected: Logs show Orchestrator → Ingestor (async)
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

### Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| MCP tool unreliable | Medium | High | Use MCP Inspector to test independently first |
| Google OAuth headless | Medium | Medium | Detailed bootstrap script with prompts |
| Agent coordination bugs | Medium | High | Comprehensive logging from Day 1 |

### Definition of Done

- [ ] Orchestrator correctly delegates to sub-agents based on intent
- [ ] Ingestor extracts entities in background (non-blocking)
- [ ] Researcher performs hybrid search (vector + graph traversal)
- [ ] Executor can send Gmail and create Calendar events
- [ ] Config changes hot-reload without restart
- [ ] All agent interactions logged with trace IDs

---

## Sprint 3: Memory Lifecycle - "The Archivist & Scribe"

**Duration**: Week 3 (5 days)
**Goal**: Implement memory management, thread summarization, and daily reflection

**Key Specs**: [AGENTS.md](./architecture/AGENTS.md), [MEMORY.md](./architecture/MEMORY.md), [ONTOLOGY.md](./architecture/ONTOLOGY.md)

### Day-by-Day Breakdown

| Day | Focus | Deliverables |
|-----|-------|--------------|
| 1 | Thread Detection | Cooldown query, thread status lifecycle |
| 2 | Summarization | LLM summarization pipeline with Pydantic output |
| 3 | Graph Promotion | Note creation, Day linking, message pruning |
| 4 | Scribe Agent | Daily reflection, journal generation |
| 5 | Integration | Scheduler, conflict resolution, deduplication |

### Deliverables Checklist

**Archivist Agent**
- [ ] `klabautermann/agents/archivist.py` - Thread summarization
- [ ] Cooldown detection (60-minute inactivity)
- [ ] Summarization pipeline (topics, action items, facts, conflicts)
- [ ] Note node creation with [:SUMMARY_OF] link
- [ ] Day node linking (temporal spine)
- [ ] Message pruning after archival
- [ ] Entity deduplication logic

**Scribe Agent**
- [ ] `klabautermann/agents/scribe.py` - Daily reflection
- [ ] Analytics queries (interactions, entities, tasks)
- [ ] Journal generation with Klabautermann personality
- [ ] JournalEntry node creation

**Utilities**
- [ ] `klabautermann/utils/scheduler.py` - APScheduler integration
- [ ] `klabautermann/memory/queries.py` - Cypher query library

**Enhanced Ontology**
- [ ] Full relationship set (20+ types)
- [ ] JournalEntry node type
- [ ] Day node management

### Verification Criteria

```bash
# 1. Test thread archival
# Have a conversation, then manually trigger:
python -c "from klabautermann.agents.archivist import Archivist; import asyncio; asyncio.run(Archivist().scan_for_inactive_threads())"
# Expected: Thread marked as archived

# 2. Verify summary
# In Neo4j Browser:
MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread)
RETURN n.title, n.content_summarized
# Expected: Summary with topics, action items

# 3. Verify pruning
MATCH (m:Message)-[:BELONGS_TO]->(t:Thread {status: 'archived'})
RETURN count(m)
# Expected: 0 (messages pruned)

# 4. Test daily reflection
python -c "from klabautermann.agents.scribe import Scribe; import asyncio; asyncio.run(Scribe().generate_daily_reflection())"
# Expected: JournalEntry created

# 5. Verify journal
MATCH (j:JournalEntry)-[:OCCURRED_ON]->(d:Day)
RETURN j.content, d.date
# Expected: Journal with Klabautermann personality

# 6. Test temporal query
> What did I do yesterday?
# Expected: Retrieves journal, not individual messages

# 7. Test time-travel
# Update Sarah's employer, then ask:
> Who did Sarah work for last week?
# Expected: Historical answer (Acme Corp)
```

### Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Summarization quality | Medium | Medium | Structured Pydantic output; keep thread link for drill-down |
| Over-pruning | Medium | High | User validation flag; keep summaries queryable |
| Scribe boring content | Medium | Low | Rich prompt with examples; pass analytics data |

### Definition of Done

- [ ] Inactive threads automatically detected and summarized
- [ ] Summaries include structured extraction (topics, items, facts)
- [ ] Original messages pruned but summary queryable
- [ ] Daily reflection generated at midnight
- [ ] Journal includes Klabautermann personality
- [ ] Time-travel queries return historical state
- [ ] Entity deduplication working

---

## Sprint 4: Production - "Full Deployment"

**Duration**: Week 4 (5 days)
**Goal**: Add Telegram channel, implement personality, testing suite, production readiness

**Key Specs**: [CHANNELS.md](./architecture/CHANNELS.md), [PERSONALITY.md](./branding/PERSONALITY.md), [TESTING.md](./quality/TESTING.md)

### Day-by-Day Breakdown

| Day | Focus | Deliverables |
|-----|-------|--------------|
| 1 | Telegram Driver | python-telegram-bot, thread mapping |
| 2 | Voice + Personality | Whisper transcription, nautical lexicon |
| 3 | Testing Suite | Unit tests, integration tests, Golden Scenarios |
| 4 | CI/CD | Pre-commit hooks, GitHub Actions |
| 5 | Documentation | README, deployment guide, troubleshooting |

### Deliverables Checklist

**Telegram Channel**
- [ ] `klabautermann/channels/telegram_driver.py` - Telegram bot
- [ ] Long polling for headless operation
- [ ] Thread mapping (chat_id → Thread)
- [ ] Voice message handler with Whisper transcription
- [ ] Media handler (URLs → Resource nodes)

**Personality System**
- [ ] `klabautermann/persona/voice.py` - Nautical formatting
- [ ] `klabautermann/persona/tidbits.py` - Sea story database
- [ ] `klabautermann/persona/storm_detection.py` - Stress mode
- [ ] `config/personality.yaml` - Branding configuration

**Testing**
- [ ] `tests/unit/` - Component tests (models, queries)
- [ ] `tests/integration/` - Agent interaction tests
- [ ] `tests/e2e/test_golden_scenarios.py` - 5 mandatory scenarios
- [ ] `tests/conftest.py` - Pytest configuration

**CI/CD**
- [ ] `.pre-commit-config.yaml` - Ruff, Mypy hooks
- [ ] `.github/workflows/ci.yml` - GitHub Actions pipeline

**Documentation**
- [ ] `README.md` - Setup guide, architecture overview
- [ ] `docs/DEPLOYMENT.md` - Docker deployment instructions
- [ ] `docs/TROUBLESHOOTING.md` - Common issues

### Verification Criteria

```bash
# 1. Test Telegram bot
# Send message to bot on Telegram
# Expected: Response received

# 2. Test voice message
# Send voice note to bot
# Expected: Transcribed and processed

# 3. Test multi-channel isolation
# CLI conversation about "Project A"
# Telegram conversation about "Project B"
# Ask "What project am I working on?" on each
# Expected: Different answers, no bleed

# 4. Test personality
# Check responses include nautical terminology
# Expected: "Scouting the horizon," "The Manifest," etc.

# 5. Run Golden Scenarios
pytest tests/e2e/test_golden_scenarios.py -v
# Expected: All 5 pass

# 6. Test pre-commit
pre-commit run --all-files
# Expected: All checks pass

# 7. Test CI pipeline
git push origin feature-branch
# Expected: GitHub Actions pass
```

### Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Telegram rate limits | Medium | Medium | Response queuing, exponential backoff |
| Personality annoyance | Low | Medium | Configurable wit_level, user feedback |
| Test coverage gaps | Medium | Low | Focus on Golden Scenarios first |

### Definition of Done

- [ ] Telegram bot responds to messages
- [ ] Voice messages transcribed and processed
- [ ] Multi-channel threads isolated (no context bleed)
- [ ] Klabautermann personality evident in responses
- [ ] All 5 Golden Scenarios pass
- [ ] Pre-commit hooks block bad code
- [ ] CI pipeline runs on push
- [ ] README provides complete setup instructions

---

## Critical Path

The following items are on the **critical path** and must be completed before dependent work can proceed:

```
Week 1, Day 1-2: Graphiti + Neo4j Setup
       │
       ▼
Week 1, Day 3-4: Memory Layer + Thread Persistence
       │
       ▼
Week 1, Day 5: Simple Orchestrator (validates architecture)
       │
       ▼
Week 2, Day 1-2: Agent Base + Delegation Pattern
       │
       ▼
Week 2, Day 3: Google OAuth (blocks MCP tools)
       │
       ▼
Week 2, Day 4-5: Executor + Researcher Integration
       │
       ▼
Week 3, Day 1-3: Archivist (thread summarization)
       │
       ▼
Week 4, Day 1-2: Telegram Driver
       │
       ▼
Week 4, Day 5: Golden Scenarios (validates entire system)
```

---

## Parallel Work Opportunities

The following can be done **in parallel** with the critical path:

| Task | Can Parallelize With |
|------|---------------------|
| Scribe (daily reflection) | Archivist development |
| Personality system | Telegram driver |
| Unit tests | All feature development |
| Documentation | All sprints |
| CI/CD setup | Week 3-4 |

---

## Contingency Plans

### Scenario 1: Graphiti Too Complex (Sprint 1)

**Symptoms**: Can't get temporal versioning working by Day 3

**Contingency**:
1. Fall back to manual Neo4j temporal pattern:
   ```cypher
   CREATE (p:Person)-[r:WORKS_AT {valid_from: timestamp(), valid_to: null}]->(o:Organization)
   ```
2. Implement custom `expire_relationship()` helper
3. Revisit Graphiti in future sprint

### Scenario 2: MCP Integration Blocked (Sprint 2)

**Symptoms**: Google Workspace MCP unreliable or undocumented

**Contingency**:
1. Build custom Google API wrappers:
   ```python
   class GoogleClient:
       async def send_email(self, to, subject, body): ...
       async def create_event(self, title, start, end): ...
   ```
2. Maintain MCP-like interface for future migration
3. Document limitation in user guide

### Scenario 3: Telegram Rate Limits (Sprint 4)

**Symptoms**: Bot gets blocked or delayed responses

**Contingency**:
1. Implement response queuing with rate limit awareness
2. Add exponential backoff on all Telegram API calls
3. Document limitations: "High-volume usage may experience delays"
4. Consider webhook deployment as future improvement

### Scenario 4: Testing Time Crunch (Sprint 4)

**Symptoms**: Not enough time for full test suite

**Contingency**:
1. Prioritize Golden Scenarios (E2E validation)
2. Manual testing checklist for remaining features
3. Mark unit test gaps as technical debt
4. Plan test coverage sprint post-launch

---

## Resource Requirements

### Development Team

| Role | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 |
|------|----------|----------|----------|----------|
| Backend Developer | 1 | 1 | 1 | 1 |
| (Optional) Second Dev | - | - | - | 1 (testing) |

### External Services

| Service | Required By | Estimated Cost |
|---------|-------------|----------------|
| Anthropic API | Sprint 1 | ~$50/month (dev) |
| OpenAI API (embeddings) | Sprint 1 | ~$10/month |
| Neo4j Aura (optional) | Sprint 1 | Free tier available |
| Google Cloud Project | Sprint 2 | Free |
| Telegram Bot | Sprint 4 | Free |

### Infrastructure

| Component | Required By | Specification |
|-----------|-------------|---------------|
| Development Machine | Sprint 1 | 8GB RAM, Docker |
| Production Server | Sprint 4 | 4GB RAM, Docker, 50GB disk |

---

## Post-Launch Roadmap

After the initial 4-week implementation, the following features are prioritized for future phases:

### Phase 2: Secondary Crew (Weeks 5-6)

**Key Specs**: [AGENTS_EXTENDED.md](./architecture/AGENTS_EXTENDED.md), [OPTIMIZATIONS.md](./quality/OPTIMIZATIONS.md)

| Feature | Agent | Description |
|---------|-------|-------------|
| **The Purser** | Utility | External API synchronization (Gmail, Calendar delta-sync) |
| **The Sieve** | Utility | Email filtering pipeline (noise, promotions, security) |
| **The Officer of the Watch** | Haiku | Proactive alerts, morning briefings, deadline warnings |
| **Basic Maintenance** | Scheduler | Nightly background tasks for graph health |

**Deliverables**:
- [ ] `klabautermann/agents/purser.py` - Delta-sync with external APIs
- [ ] `klabautermann/filtering/sieve.py` - Email filter pipeline
- [ ] `klabautermann/agents/officer.py` - Proactive notifications
- [ ] Morning briefing generation
- [ ] VIP whitelist management

### Phase 3: Knowledge Islands (Weeks 7-8)

**Key Specs**: [AGENTS_EXTENDED.md](./architecture/AGENTS_EXTENDED.md), [MEMORY.md](./architecture/MEMORY.md), [ONTOLOGY.md](./architecture/ONTOLOGY.md)

| Feature | Agent | Description |
|---------|-------|-------------|
| **The Cartographer** | Algorithmic | Community detection via Neo4j GDS (Louvain/Leiden) |
| **Knowledge Islands** | Graph | Community nodes with thematic clustering |
| **Multi-Level Retrieval** | Researcher | Macro/Meso/Micro zoom mechanics |
| **Island Summaries** | Scribe | AI-generated summaries for each island |

**Deliverables**:
- [ ] `klabautermann/agents/cartographer.py` - Community detection
- [ ] Community node schema and `[:PART_OF_ISLAND]` relationships
- [ ] `ZoomLevelSelector` class for automatic query routing
- [ ] Weekly community re-detection schedule
- [ ] Island summary generation

### Phase 4: Progressive Storytelling (Weeks 9-10)

**Key Specs**: [LORE_SYSTEM.md](./architecture/LORE_SYSTEM.md), [PERSONALITY.md](./branding/PERSONALITY.md), [AGENTS_EXTENDED.md](./architecture/AGENTS_EXTENDED.md)

| Feature | Agent | Description |
|---------|-------|-------------|
| **The Bard of the Bilge** | Haiku | Progressive storytelling with saga continuity |
| **LoreEpisode Nodes** | Graph | Multi-chapter narratives linked via `[:EXPANDS_UPON]` |
| **Parallel Memory** | Memory | Separate query space for lore (Captain-bound, not Thread-bound) |
| **Canonical Adventures** | Content | 5 pre-written saga templates |

**Deliverables**:
- [ ] `klabautermann/agents/bard.py` - Story generation and continuation
- [ ] `klabautermann/memory/lore_memory.py` - Saga retrieval
- [ ] LoreEpisode graph schema
- [ ] Cross-channel saga persistence
- [ ] Saga progress in Scribe daily reflection

### Phase 5: Graph Optimization (Weeks 11-12)

**Key Specs**: [OPTIMIZATIONS.md](./quality/OPTIMIZATIONS.md), [AGENTS_EXTENDED.md](./architecture/AGENTS_EXTENDED.md)

| Feature | Agent | Description |
|---------|-------|-------------|
| **The Hull Cleaner** | Utility | Automatic graph pruning (barnacle removal) |
| **Hallucination Tracking** | Utility | Confidence scoring and fact reinforcement |
| **Transitive Reduction** | Algorithm | Remove redundant relationship paths |
| **The Quartermaster** | Utility | Config hot-reload, prompt A/B testing |

**Deliverables**:
- [ ] `klabautermann/maintenance/hull_cleaner.py` - Pruning logic
- [ ] `klabautermann/maintenance/hallucination_tracker.py` - Fact confidence
- [ ] Weak relationship expiration (weight < 0.2, age > 90 days)
- [ ] Duplicate entity flagging and merge workflow
- [ ] Message cleanup post-archival

### Phase 6: Personal Life Domain (Weeks 13-14)

**Key Specs**: [ONTOLOGY.md](./architecture/ONTOLOGY.md)

| Feature | Category | Description |
|---------|----------|-------------|
| **Family Relationships** | Ontology | `FAMILY_OF`, `SPOUSE_OF`, `PARENT_OF`, `CHILD_OF`, `SIBLING_OF` |
| **Hobby Tracking** | Ontology | `Hobby` nodes with `[:PRACTICES]` relationships |
| **Pet Management** | Ontology | `Pet` nodes with `[:OWNS]` relationships |
| **Health Metrics** | Ontology | `HealthMetric` nodes with `[:RECORDED]` relationships |
| **Milestones** | Ontology | `Milestone` nodes for personal achievements |
| **Routines** | Ontology | `Routine` nodes for recurring activities |

**Deliverables**:
- [ ] Extended ontology with 8 personal life entities
- [ ] 14+ personal relationship types
- [ ] Family tree visualization queries
- [ ] Personal preferences tracking
- [ ] Life theme detection via Knowledge Islands

### Phase 7: The Bridge Dashboard (Weeks 15+)

| Feature | Component | Description |
|---------|-----------|-------------|
| **The Chronometer** | Widget | System health and uptime metrics |
| **The Captain's Log** | Widget | Live log stream with filtering |
| **The Horizon** | Widget | Chat interface for web |
| **The Locker Explorer** | Widget | Graph visualization and browsing |
| **The Scribe's Ledger** | Widget | Journal timeline view |
| **Storm Warnings** | Widget | Active alerts panel |

**Deliverables**:
- [ ] React-based dashboard application
- [ ] WebSocket connection for live updates
- [ ] Graph visualization with D3.js/Cytoscape
- [ ] Mobile-responsive design

### Phase 8: Enterprise & Scale (Future)

- **Multi-User Support**: Team knowledge graphs with isolation
- **Enterprise Features**: SSO, audit logs, compliance (21 CFR Part 11)
- **Voice-First Interface**: Always-on voice assistant
- **Mobile App**: React Native with push notifications

---

## Success Criteria by Sprint

### Sprint 1 Success
```
✓ docker-compose up -d → all services healthy
✓ CLI input → conversational response
✓ "I met Sarah from Acme" → nodes in Neo4j
✓ Restart CLI → agent remembers conversation
```

### Sprint 2 Success
```
✓ Intent → correct sub-agent delegated
✓ Ingestion happens in background (non-blocking)
✓ Gmail retrieval via MCP working
✓ Calendar retrieval via MCP working
✓ Config change → reflected without restart
```

### Sprint 3 Success
```
✓ Inactive thread → automatically summarized
✓ Summary → Note node in graph
✓ Daily reflection → JournalEntry created
✓ "What did I do yesterday?" → journal returned
✓ Time-travel query → historical state returned
```

### Sprint 4 Success
```
✓ Telegram message → bot response
✓ Voice note → transcribed and processed
✓ CLI + Telegram → separate threads
✓ Response → includes nautical terms
✓ 5 Golden Scenarios → all pass
✓ git push → CI pipeline passes
```

### Phase 2 Success (Secondary Crew)
```
✓ Gmail sync → only new emails processed (delta-sync)
✓ Newsletter email → filtered, not ingested
✓ VIP email → bypass filters, priority ingestion
✓ Morning → proactive briefing notification
✓ Deadline approaching → Officer alert triggered
```

### Phase 3 Success (Knowledge Islands)
```
✓ Weekly run → Community nodes created
✓ "Overview of my life" → Island summaries returned
✓ "What's the Q1 budget status?" → Meso-level results
✓ "When did Sarah change jobs?" → Micro-level results
✓ Island summaries → generated by Scribe
```

### Phase 4 Success (Progressive Storytelling)
```
✓ ~5% of responses → include saga content
✓ Continue saga on CLI → continue same saga on Telegram
✓ Saga chapter → LoreEpisode node created
✓ Saga linked to Captain → not Thread
✓ Daily reflection → includes "From the Ship's Tales"
```

### Phase 5 Success (Graph Optimization)
```
✓ Weak relationships (weight < 0.2, 90+ days) → auto-expired
✓ Archived thread → messages deleted
✓ Duplicate persons flagged → [:POTENTIAL_DUPLICATE] created
✓ Low-confidence facts (no reinforcement) → expired
✓ Config change → hot-reloaded without restart
```

### Phase 6 Success (Personal Life)
```
✓ "My wife's birthday" → stored with SPOUSE_OF relationship
✓ "I went hiking" → Hobby node with [:PRACTICES]
✓ "My dog Max" → Pet node with [:OWNS]
✓ "Ran 5k this morning" → HealthMetric recorded
✓ Family members → cluster into Family Island
```

---

*"The ship is charted, Captain. Fair winds await."* - Klabautermann
