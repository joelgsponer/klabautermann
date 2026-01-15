# CLAUDE.md

You have to read `CONTRIBUTING.md`

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Klabautermann is an agentic personal knowledge management (PKM) system using a multi-agent architecture with a temporal knowledge graph. It extracts entities from conversations, stores them in Neo4j via Graphiti, and enables agents to take actions (email, calendar) via MCP.

## Technology Stack

- **Language**: Python 3.11+
- **Graph Database**: Neo4j 5.26+ with Graphiti for temporal memory
- **LLM**: Claude (Sonnet for reasoning, Haiku for extraction/search)
- **Tool Integration**: MCP (Model Context Protocol) for Gmail, Calendar, Filesystem
- **Containerization**: Docker + Docker Compose

## Architecture

```
Communication Layer (CLI, Telegram)
         ↓
Orchestration Layer (delegates by intent)
         ↓
Agent Layer:
  - Ingestor (Haiku): extracts entities → Graphiti
  - Researcher (Haiku): hybrid vector+graph search
  - Executor (Sonnet): MCP tool execution
  - Archivist (Haiku): thread summarization, deduplication
  - Scribe (Haiku): daily journal generation
         ↓
Memory Layer (Neo4j + Graphiti temporal graph)
```
## Core Principles

1. **Validate Everything**: LLM outputs are untrusted until parsed through Pydantic
2. **Never Block**: Use async/await; never use `time.sleep()`
3. **Parametrize Queries**: Never use f-strings for Cypher queries (prevents injection)
4. **Log Extensively**: Use trace IDs, nautical log levels ([CHART], [STORM], etc.)
5. **Fail Gracefully**: Inform user, don't crash

## Testing Philosophy

**Tests define what code SHOULD do according to specs. If tests fail, fix the CODE, not the tests.**

Golden Scenarios (mandatory E2E tests):
1. New Contact: "I met John (john@example.com), PM at Acme" → creates Person, Org, WORKS_AT
2. Contextual Retrieval: "What did I talk about with John?" → finds thread, summarizes
3. Blocked Task: "Can't finish until John sends stats" → creates BLOCKS relationship
4. Temporal Time-Travel: Change employer, ask historical → returns old employer
5. Multi-Channel Threading: CLI + Telegram → separate threads, no context bleed

## Keep project root client
Utility scripts should go in scripts/. Migrations ins migrations/.

## On startup
Orient yourself. Run `tree` to understand project structure.
