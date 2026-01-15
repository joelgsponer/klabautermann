# Klabautermann: Product Requirements Document

**Version**: 1.0
**Status**: Ready for Implementation
**Last Updated**: January 2026

---

## Executive Summary

**Klabautermann** is an agentic personal knowledge management (PKM) system that serves as your digital navigator through life's information storm. Unlike static note-taking apps, Klabautermann maintains a **living, temporal knowledge graph** that evolves naturally through conversations, emails, calendar events, and shared links.

The system employs a **multi-agent architecture** where specialized AI agents handle distinct responsibilities: ingesting new information, searching your memory, executing real-world actions, and maintaining the graph's health. All agents communicate through **MCP (Model Context Protocol)** for standardized tool integration.

**Key Differentiators**:
- **Temporal Memory**: Every fact has a timeline. Ask "What was my goal last month?" and get an accurate historical answer.
- **Agentic Actions**: The system doesn't just store—it acts. Draft emails, schedule meetings, create reminders.
- **Witty Navigator**: The Klabautermann persona is a salty, efficient helper who guides you with nautical wit.

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [System Architecture](#2-system-architecture)
3. [The Knowledge Graph](#3-the-knowledge-graph)
4. [Multi-Agent System](#4-multi-agent-system)
5. [Communication Channels](#5-communication-channels)
6. [Tool Integration (MCP)](#6-tool-integration-mcp)
7. [Memory Lifecycle](#7-memory-lifecycle)
8. [Branding & Personality](#8-branding--personality)
9. [Infrastructure](#9-infrastructure)
10. [Quality Assurance](#10-quality-assurance)
11. [Security & Privacy](#11-security--privacy)
12. [Success Metrics](#12-success-metrics)

---

## 1. Vision & Goals

### 1.1 The Problem

Modern knowledge workers suffer from **information fragmentation**:
- Notes scattered across apps (Notion, Obsidian, Apple Notes)
- Contacts disconnected from context (who was that person I met at the conference?)
- Tasks orphaned from goals (why am I doing this again?)
- Email conversations lost in the void
- No single system that connects the "who," "what," "when," and "why"

### 1.2 The Solution

Klabautermann creates a **Personal Knowledge Graph** where:
- Every piece of information is a **node** (Person, Project, Task, Note, Event, Location)
- Relationships form a **web of context** (Sarah WORKS_AT Acme, Task PART_OF Project, Event HELD_AT Location)
- Time is a **first-class citizen** (relationships expire, facts evolve, history is preserved)
- An **agentic AI** navigates this graph to answer questions and take actions

### 1.3 Success Criteria

| Metric | Target |
|--------|--------|
| Information retrieval accuracy | >90% |
| Action execution success rate | >85% |
| Response latency | <3 seconds |
| Memory temporal accuracy | 100% for tagged events |
| User satisfaction (witty but efficient) | Net Promoter Score >8 |

---

## 2. System Architecture

Klabautermann follows a **layered architecture** with clear separation of concerns.

```
┌─────────────────────────────────────────────────────────────┐
│                    COMMUNICATION LAYER                       │
│   CLI Driver  │  Telegram Driver  │  Discord Driver (future) │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    ORCHESTRATION LAYER                       │
│                      The Orchestrator                        │
│   (Intent Classification → Agent Delegation → Response)      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     AGENT LAYER                              │
│  Ingestor  │  Researcher  │  Executor  │  Archivist  │ Scribe│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    INTEGRATION LAYER                         │
│         MCP Clients (Gmail, Calendar, Filesystem)            │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     MEMORY LAYER                             │
│          Graphiti + Neo4j (Temporal Knowledge Graph)         │
└─────────────────────────────────────────────────────────────┘
```

**Detailed Documentation**: [architecture/AGENTS.md](architecture/AGENTS.md)

---

## 3. The Knowledge Graph

The knowledge graph is the **long-term memory** of Klabautermann. It stores structured data about your life as interconnected nodes and relationships.

### 3.1 Core Entities (Nodes)

| Entity | Purpose | Key Properties |
|--------|---------|----------------|
| **Person** | Human contacts | name, email, bio, linkedin_url |
| **Organization** | Companies, groups | name, industry, website |
| **Project** | Goal-oriented endeavors | name, status, deadline |
| **Goal** | High-level objectives | description, timeframe |
| **Task** | Atomic action items | action, status, priority |
| **Event** | Meetings, occurrences | title, timestamp, location_context |
| **Location** | Physical places | name, address, coordinates |
| **Note** | Knowledge artifacts | title, content_summarized |
| **Resource** | External links, files | url, type |

### 3.2 Core Relationships (Edges)

| Relationship | Example | Purpose |
|--------------|---------|---------|
| `WORKS_AT` | Person → Organization | Professional context |
| `CONTRIBUTES_TO` | Project → Goal | Action hierarchy |
| `PART_OF` | Task → Project | Task grouping |
| `HELD_AT` | Event → Location | Spatial context |
| `BLOCKS` | Task → Task | Dependencies |
| `MENTIONED_IN` | Person → Note | Knowledge linking |

### 3.3 Temporal Versioning

Every relationship has temporal properties:
- `created_at`: When the relationship became valid
- `expired_at`: When the relationship ceased to be valid (null = current)

This enables **time-travel queries**: "Who did John work for last year?"

**Detailed Documentation**: [architecture/ONTOLOGY.md](architecture/ONTOLOGY.md)

---

## 4. Multi-Agent System

Klabautermann uses a **Leader-Follower architecture** where the Orchestrator delegates to specialized sub-agents.

### 4.1 Agent Roster

| Agent | Model | Role | Primary Tools |
|-------|-------|------|---------------|
| **Orchestrator** | Claude 3.5 Sonnet | CEO: routes intents, synthesizes responses | All (delegates) |
| **Ingestor** | Claude 3 Haiku | Extraction: turns text into graph entities | graphiti_add_episode |
| **Researcher** | Claude 3 Haiku | Librarian: hybrid search across memory | graphiti_search, neo4j_query |
| **Executor** | Claude 3.5 Sonnet | Admin: real-world actions via MCP | gmail_send, calendar_create |
| **Archivist** | Claude 3 Haiku | Janitor: summarizes threads, deduplicates | neo4j_query, graphiti_add_episode |
| **Scribe** | Claude 3 Haiku | Historian: daily reflection and journaling | neo4j_analytics |

### 4.2 Communication Pattern

Agents communicate via **async message passing** with a shared graph as the "blackboard":

```
User Input → Orchestrator → [Sub-agent Inbox Queue] → Sub-agent
                                                          ↓
User Response ← Orchestrator ← [Response Queue] ← Sub-agent
```

**Detailed Documentation**: [architecture/AGENTS.md](architecture/AGENTS.md)

---

## 5. Communication Channels

Klabautermann supports multiple interfaces through a **modular driver architecture**.

### 5.1 Supported Channels

| Channel | Status | Use Case |
|---------|--------|----------|
| **CLI** | MVP | Development, system administration |
| **Telegram** | Phase 2 | Mobile access, voice notes |
| **Discord** | Future | Team collaboration |

### 5.2 Thread Isolation

Each channel maintains separate **conversation threads** to prevent context bleed:
- Telegram chat_id → unique Thread node
- CLI session → unique Thread node
- Threads linked via `[:PRECEDES]` for message sequencing

### 5.3 Rolling Context Window

For each interaction, the driver retrieves the last **15-20 messages** from the thread to provide conversational context to the Orchestrator.

**Detailed Documentation**: [architecture/CHANNELS.md](architecture/CHANNELS.md)

---

## 6. Tool Integration (MCP)

The **Model Context Protocol (MCP)** provides standardized tool integration. Agents don't call APIs directly—they invoke MCP tools.

### 6.1 MCP Servers

| Server | Tools Provided |
|--------|----------------|
| **Google Workspace** | gmail_send_message, gmail_search_messages, calendar_create_event, calendar_list_events |
| **Filesystem** | read_file, write_file, list_directory |
| **Neo4j (Custom)** | execute_cypher |

### 6.2 Tool Invocation Pattern

```python
result = await invoke_mcp_tool(
    server_config=["npx", "-y", "@modelcontextprotocol/server-google-workspace"],
    tool_name="gmail_send_message",
    arguments={"to": "sarah@acme.com", "subject": "Budget Update"},
    context=ToolInvocationContext(trace_id=trace_id, agent_name="executor")
)
```

### 6.3 Security Isolation

- **Ingestor**: Read-only Gmail/Calendar access
- **Executor**: Write access to Gmail/Calendar
- **Researcher**: No MCP access (graph only)

**Detailed Documentation**: [architecture/MCP.md](architecture/MCP.md)

---

## 7. Memory Lifecycle

Information flows through three memory layers with different retention and retrieval characteristics.

### 7.1 The Three Layers

| Layer | Storage | Retention | Retrieval |
|-------|---------|-----------|-----------|
| **Short-Term** | Message nodes | ~20-50 messages | Sequential `[:PRECEDES]` traversal |
| **Mid-Term** | Note summaries | Indefinite | Vector search + Thread links |
| **Long-Term** | Graphiti entities | Permanent | Hybrid GraphRAG |

### 7.2 Archivist Workflow

1. **Cooldown Detection**: Thread inactive for 60+ minutes
2. **Summarization**: LLM extracts topics, action items, new facts
3. **Graph Promotion**: Create Note node, link to Thread and Day
4. **Pruning**: Remove original Message nodes (summary preserved)

### 7.3 Scribe Workflow (Daily Reflection)

At midnight:
1. Query day's analytics (interactions, new entities, completed tasks)
2. Generate journal entry with Klabautermann personality
3. Create JournalEntry node linked to Day

**Detailed Documentation**: [architecture/MEMORY.md](architecture/MEMORY.md)

---

## 8. Branding & Personality

**Klabautermann** is a mythical water sprite from nautical folklore—an invisible helper who maintains ships and warns of danger.

### 8.1 Persona: "The Salty Sage"

- **Tone**: Witty, dry, slightly mischievous, fundamentally helpful
- **Efficiency**: Answer first, wit second
- **Avoid**: Pirate caricature ("Arrr, matey")
- **Embrace**: Nautical metaphors ("Scouting the horizon," "The Locker," "The Manifest")

### 8.2 Visual Identity

| Element | Value |
|---------|-------|
| Primary Background | Deep Abyss (#1B262C) |
| Primary Accent | Compass Brass (#B68D40) |
| Alert Color | Emergency Flare (#D65A31) |
| Text Color | Seafoam (#D1E8E2) |
| Primary Font | JetBrains Mono |
| Secondary Font | Playfair Display |

### 8.3 The "Tidbit" Mechanic

1 in 10 responses includes a brief "sea story":

> "I'll get that email drafted. Reminds me of the time I had to navigate the Great Maelstrom of '98 using nothing but a rusted compass and a very confused seagull."

### 8.4 Storm Mode

When high task density detected, switch to terse, action-focused responses:

> "It's getting choppy out there. I've cleared your afternoon tasks. Focus on the budget; I'll handle the rest."

**Detailed Documentation**: [branding/PERSONALITY.md](branding/PERSONALITY.md)

---

## 9. Infrastructure

### 9.1 Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| LLM | Claude 3.5 Sonnet / 3 Haiku |
| Graph Database | Neo4j 5.26+ |
| Temporal Framework | Graphiti |
| Containerization | Docker + Docker Compose |
| Configuration | YAML with hot-reload |
| Credentials | .env files (local) |

### 9.2 Docker Services

```yaml
services:
  klabautermann-app:
    build: .
    env_file: .env
    depends_on:
      - neo4j
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs

  neo4j:
    image: neo4j:5.26
    ports:
      - "7474:7474"  # Browser
      - "7687:7687"  # Bolt
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
```

### 9.3 Credential Requirements

| Credential | Purpose |
|------------|---------|
| `ANTHROPIC_API_KEY` | Claude LLM access |
| `OPENAI_API_KEY` | Embeddings |
| `NEO4J_PASSWORD` | Database auth |
| `GOOGLE_CLIENT_ID` | OAuth2 |
| `GOOGLE_CLIENT_SECRET` | OAuth2 |
| `GOOGLE_REFRESH_TOKEN` | Headless Gmail/Calendar |
| `TELEGRAM_BOT_TOKEN` | Telegram channel |

**Detailed Documentation**: [infrastructure/DEPLOYMENT.md](infrastructure/DEPLOYMENT.md)

---

## 10. Quality Assurance

### 10.1 Testing Pyramid

```
                    /\
                   /  \
                  / E2E \ (Golden Scenarios)
                 /------\
                /        \
               /Integration\ (Agent interactions)
              /------------\
             /              \
            /  Unit Tests    \ (Logic + Models)
           /------------------\
```

### 10.2 Golden Scenarios (Mandatory E2E)

| Scenario | Test |
|----------|------|
| **New Contact** | "I met John Doe (john@example.com). He's a PM at Acme." → Person + Organization + WORKS_AT |
| **Contextual Retrieval** | "What did I talk about with John yesterday?" → Finds thread, summarizes |
| **Blocked Task** | "I can't finish until John sends stats." → Creates BLOCKS relationship |
| **Temporal Time-Travel** | Change employer, ask "Who did John work for last week?" → Historical answer |
| **Multi-Channel Threading** | CLI + Telegram conversations → Separate threads, no bleed |

### 10.3 CI/CD Pipeline

- **Pre-commit**: Ruff (linting), Mypy (types), YAML validation
- **GitHub Actions**: Unit tests, integration tests, type checking

**Detailed Documentation**: [quality/TESTING.md](quality/TESTING.md), [quality/CODING_STANDARDS.md](quality/CODING_STANDARDS.md)

---

## 11. Security & Privacy

### 11.1 Credential Management

- **Never commit**: `.env` files in `.gitignore`
- **Template provided**: `.env.example` as reference
- **Granular OAuth scopes**: `gmail.modify` not `mail.google.com`

### 11.2 Agent Isolation

| Agent | Neo4j Role | MCP Access |
|-------|------------|------------|
| Ingestor | WRITE | Read-only Gmail/Calendar |
| Researcher | READ | None |
| Executor | READ | Write Gmail/Calendar |
| Archivist | WRITE | None |

### 11.3 Audit Trail

All credential usage logged as Security Audit nodes in graph for prompt injection detection.

---

## 12. Success Metrics

### 12.1 Technical Metrics

| Metric | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 |
|--------|----------|----------|----------|----------|
| Neo4j Uptime | 100% | 100% | 100% | 100% |
| Episode Ingestion Rate | >95% | >95% | >95% | >95% |
| Agent Delegation Accuracy | - | >90% | >90% | >90% |
| MCP Tool Success Rate | - | >85% | >85% | >85% |
| Thread Summarization | - | - | 100% | 100% |
| Golden Scenarios Pass | - | - | - | 100% |

### 12.2 User Experience Metrics

| Metric | Target |
|--------|--------|
| Response Time | <3 seconds |
| Personality Appropriateness | "Efficient but witty" feedback |
| Memory Recall Accuracy | User validates >90% of retrieved facts |

---

## Appendices

### A. Document Index

| Document | Description |
|----------|-------------|
| [ROADMAP.md](ROADMAP.md) | Implementation timeline and sprint breakdown |
| [architecture/ONTOLOGY.md](architecture/ONTOLOGY.md) | Complete graph schema with all entities and relationships |
| [architecture/AGENTS.md](architecture/AGENTS.md) | Multi-agent system design and communication patterns |
| [architecture/MCP.md](architecture/MCP.md) | MCP integration guide and tool specifications |
| [architecture/MEMORY.md](architecture/MEMORY.md) | Graphiti temporal memory system |
| [architecture/CHANNELS.md](architecture/CHANNELS.md) | Communication driver architecture |
| [branding/PERSONALITY.md](branding/PERSONALITY.md) | Klabautermann voice and visual identity |
| [infrastructure/DEPLOYMENT.md](infrastructure/DEPLOYMENT.md) | Docker setup and deployment guide |
| [quality/TESTING.md](quality/TESTING.md) | Testing protocol and golden scenarios |
| [quality/CODING_STANDARDS.md](quality/CODING_STANDARDS.md) | Engineering standards and patterns |
| [quality/LOGGING.md](quality/LOGGING.md) | Observability and logging directive |

### B. Glossary

| Term | Definition |
|------|------------|
| **Episode** | A unit of information ingested into the graph (conversation, email, event) |
| **The Locker** | The knowledge graph / database |
| **The Manifest** | Task list |
| **Scouting the Horizon** | Searching memory |
| **Walking the Plank** | Deleting data |
| **Storm Mode** | High-stress terse response mode |
| **Temporal Spine** | Day nodes that anchor all events chronologically |

---

*"Ready to set sail, Captain."* - Klabautermann
