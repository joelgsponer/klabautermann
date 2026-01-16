---
name: lookup-person
description: Search the Klabautermann knowledge graph for information about a person. Use when user asks "who is X" or "find contact for X".
allowed-tools: Read, Grep
model: claude-sonnet-4-20250514
user-invocable: true
# Klabautermann orchestrator integration
klabautermann-task-type: research
klabautermann-agent: researcher
klabautermann-blocking: true
klabautermann-payload-schema:
  query:
    type: string
    required: true
    extract-from: user-message
    description: Person name or search query
---

# Lookup Person

Search the Klabautermann knowledge graph for information about a person.

## Instructions

1. Extract the person's name from the user request
2. Search for matching Person nodes in the knowledge graph
3. Include related information if found:
   - Email address
   - Organization (via WORKS_AT relationship)
   - Relationships with other people
   - Recent mentions in conversations
4. Summarize findings for the user

## For Claude Code

When invoked via `/lookup-person`:
1. Use Grep to search the codebase for relevant person data
2. Check the knowledge graph via the Klabautermann API
3. Present results in a clear, organized format

## For Klabautermann Orchestrator

When routing this skill:
- **task_type**: research
- **agent**: researcher
- **payload**: `{ "query": "<extracted name>", "zoom_level": "micro" }`
- **blocking**: true (wait for results)

The researcher agent will:
1. Execute vector search for the person name
2. Traverse graph relationships (WORKS_AT, KNOWS, etc.)
3. Return structured results including email, org, and context

## Examples

**User**: "Who is Sarah?"
- Extract: `query = "Sarah"`
- Search Person nodes matching "Sarah"
- Return profile summary with org and contact info

**User**: "Find John's contact info"
- Extract: `query = "John"`
- Search Person "John"
- Return email and phone if available

**User**: "What do I know about Maria from Acme?"
- Extract: `query = "Maria Acme"`
- Search with org context
- Return person details with WORKS_AT relationship
