# Skill Creation Guide

This guide explains how to create custom skills for Klabautermann using the Claude Code skill format.

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [SKILL.md Format](#skillmd-format)
- [Klabautermann Integration](#klabautermann-integration)
- [Payload Schema](#payload-schema)
- [Skill Types](#skill-types)
- [Examples](#examples)
- [Testing Skills](#testing-skills)
- [Best Practices](#best-practices)

---

## Overview

Skills are reusable capabilities that define specific tasks Klabautermann can perform. Each skill:

1. Has a YAML frontmatter defining metadata
2. Contains markdown instructions for execution
3. Optionally integrates with the Klabautermann orchestrator
4. Can extract structured payloads from user input

The skill system uses **AI-first discovery** - Claude semantically matches user requests to skills based on their descriptions, not keyword patterns.

---

## Directory Structure

Skills are stored in `.claude/skills/` directories:

```
project/
├── .claude/
│   └── skills/
│       ├── lookup-person/
│       │   └── SKILL.md
│       ├── send-email/
│       │   └── SKILL.md
│       └── schedule-meeting/
│           └── SKILL.md
└── ...

# Personal skills (applies to all projects)
~/.claude/skills/
└── my-custom-skill/
    └── SKILL.md
```

**Loading Priority**: Project skills take precedence over personal skills with the same name.

---

## SKILL.md Format

Each skill is defined in a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does and when to use it
allowed-tools: Read, Grep, Bash
model: claude-sonnet-4-20250514
user-invocable: true
---

# My Skill

Instructions and documentation...
```

### Standard Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier (lowercase, hyphens, max 64 chars) |
| `description` | string | Yes | What the skill does - used for AI matching |
| `allowed-tools` | string/list | No | Tools Claude can use without asking |
| `model` | string | No | Claude model to use when skill is active |
| `user-invocable` | boolean | No | Show in slash command menu (default: true) |
| `context` | string | No | Set to "fork" for isolated sub-agent context |
| `agent` | string | No | Agent type when context=fork |

### Description Best Practices

The `description` field is crucial for AI-first skill matching:

```yaml
# GOOD - Specific triggers and use cases
description: Search the knowledge graph for information about a person. Use when user asks "who is X" or "find contact for X".

# BAD - Too vague
description: Find things about people.
```

Include:
- What the skill does
- When to use it (trigger phrases)
- What input it expects

---

## Klabautermann Integration

To integrate with the Klabautermann orchestrator, add `klabautermann-*` fields:

```yaml
---
name: lookup-person
description: Search for information about a person in the knowledge graph.
# Standard Claude Code fields
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
```

### Klabautermann Fields

| Field | Type | Description |
|-------|------|-------------|
| `klabautermann-task-type` | string | Maps to PlannedTask.task_type: `ingest`, `research`, `execute` |
| `klabautermann-agent` | string | Target agent: `ingestor`, `researcher`, `executor` |
| `klabautermann-blocking` | boolean | Whether orchestrator waits for result (default: true) |
| `klabautermann-requires-confirmation` | boolean | Confirm before execution (default: false) |
| `klabautermann-payload-schema` | object | Schema for extracting payload from user message |

---

## Payload Schema

The `klabautermann-payload-schema` defines how to extract structured data from user input:

```yaml
klabautermann-payload-schema:
  recipient:
    type: string
    required: true
    extract-from: user-message
    description: Email address or contact name
  subject:
    type: string
    required: false
    extract-from: user-message
    description: Email subject line
  body:
    type: string
    required: false
    extract-from: user-message
    description: Email body content
  draft_only:
    type: boolean
    required: false
    default: false
    description: Create draft instead of sending
```

### Field Properties

| Property | Type | Description |
|----------|------|-------------|
| `type` | string | Data type: `string`, `boolean`, `number`, `array`, `object` |
| `required` | boolean | Whether field is required |
| `default` | any | Default value if not extracted |
| `extract-from` | string | Source: `user-message`, `context`, `prompt` |
| `description` | string | What this field represents (guides extraction) |

### Extraction Process

The AI-first extraction process:

1. User sends message: "Send an email to Sarah about the meeting"
2. Skill discovery matches to `send-email` skill
3. LLM extracts payload based on schema:
   ```json
   {
     "recipient": "Sarah",
     "subject": "meeting",
     "body": null
   }
   ```
4. Orchestrator routes to executor agent with payload

---

## Skill Types

### Research Skills

For querying the knowledge graph:

```yaml
klabautermann-task-type: research
klabautermann-agent: researcher
```

Use cases:
- Finding people, organizations, projects
- Searching conversation history
- Retrieving context for decisions

### Execute Skills

For taking actions via MCP tools:

```yaml
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-requires-confirmation: true  # For destructive actions
```

Use cases:
- Sending emails
- Creating calendar events
- Managing files

### Ingest Skills

For adding information to the knowledge graph:

```yaml
klabautermann-task-type: ingest
klabautermann-agent: ingestor
```

Use cases:
- Adding notes
- Recording new contacts
- Capturing decisions

---

## Examples

### Research Skill: Lookup Person

```yaml
---
name: lookup-person
description: Search the Klabautermann knowledge graph for information about a person. Use when user asks "who is X" or "find contact for X".
allowed-tools: Read, Grep
model: claude-sonnet-4-20250514
user-invocable: true
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

Search the knowledge graph for information about a person.

## Instructions

1. Extract the person's name from the user request
2. Search for matching Person nodes in the knowledge graph
3. Include related information if found:
   - Email address
   - Organization (via WORKS_AT relationship)
   - Relationships with other people
4. Summarize findings for the user

## Examples

**User**: "Who is Sarah?"
- Extract: `query = "Sarah"`
- Search Person nodes matching "Sarah"
- Return profile summary with org and contact info
```

### Execute Skill: Send Email

```yaml
---
name: send-email
description: Send an email to a contact. Use when user says "send email to X" or "email X about Y".
allowed-tools: Read, Grep, Bash
model: claude-sonnet-4-20250514
user-invocable: true
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: true
klabautermann-payload-schema:
  recipient:
    type: string
    required: true
    extract-from: user-message
    description: Email address or contact name
  subject:
    type: string
    required: false
    extract-from: user-message
    description: Email subject line
  body:
    type: string
    required: false
    extract-from: user-message
    description: Email body content
  draft_only:
    type: boolean
    required: false
    default: false
    description: Create draft instead of sending
---

# Send Email

Send an email to a contact via Gmail integration.

## Instructions

1. Extract the recipient from the user request
2. Extract or ask for subject and body
3. Show preview and ask for confirmation
4. Send or create draft

## Safety Rules

- **Never send** to unverified email addresses
- **Always confirm** before sending (not drafting)
```

### Ingest Skill: Create Note

```yaml
---
name: create-note
description: Create and save a text note to the knowledge graph.
allowed-tools: Read, Write
model: claude-sonnet-4-20250514
user-invocable: true
klabautermann-task-type: ingest
klabautermann-agent: ingestor
klabautermann-blocking: true
klabautermann-payload-schema:
  title:
    type: string
    required: false
    extract-from: user-message
    description: Note title
  content:
    type: string
    required: true
    extract-from: user-message
    description: Note content
---

# Create Note

Save information as a note in the knowledge graph.

## Instructions

1. Extract title and content from user message
2. Create Note node with content
3. Link to relevant entities (people, projects) mentioned
4. Confirm note was saved
```

---

## Testing Skills

### Verify Loading

```python
from klabautermann.skills.loader import SkillLoader

loader = SkillLoader()
loader.load_all()

# List all skills
for name in loader.list_skills():
    skill = loader.get(name)
    print(f"{name}: {skill.description}")

# Check orchestrator integration
for skill in loader.get_orchestrator_skills():
    print(f"{skill.name}: {skill.klabautermann.task_type} -> {skill.klabautermann.agent}")
```

### Test Discovery

```python
from klabautermann.skills.discovery import SkillDiscovery
from klabautermann.skills.loader import SkillLoader

discovery = SkillDiscovery(loader=SkillLoader())

# Test skill matching
skill = await discovery.discover_skill(
    "Who is Sarah?",
    trace_id="test-123",
    min_confidence=0.5
)
print(f"Matched: {skill.name if skill else 'None'}")
```

### Test Payload Extraction

```python
# Test payload extraction
payload = await discovery.extract_payload_with_llm(
    skill=skill,
    user_input="Send an email to john@example.com about the project",
    trace_id="test-123"
)
print(f"Extracted: {payload}")
```

---

## Best Practices

### Naming

- Use lowercase with hyphens: `lookup-person`, `send-email`
- Keep names under 64 characters
- Make names descriptive but concise

### Descriptions

- Be specific about when to use the skill
- Include trigger phrases users might say
- Mention what input is expected

### Payload Schema

- Only mark fields as `required` if truly necessary
- Provide good `description` fields to guide extraction
- Use sensible defaults for optional fields

### Safety

- Always set `klabautermann-requires-confirmation: true` for destructive actions
- Never send emails without confirmation
- Validate extracted payloads before execution

### Documentation

- Include clear instructions in the markdown body
- Provide examples of user input and expected behavior
- Document any safety rules or edge cases

---

## Skill Architecture

```
User Input
    │
    ▼
┌─────────────────┐
│ SkillDiscovery  │ ◄── AI-first semantic matching
│ (LLM)           │
└────────┬────────┘
         │ Matched skill
         ▼
┌─────────────────┐
│ Payload Extract │ ◄── LLM extracts structured data
│ (LLM)           │
└────────┬────────┘
         │ Payload
         ▼
┌─────────────────┐
│ Orchestrator    │ ◄── Routes to appropriate agent
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Agent           │ ◄── Ingestor / Researcher / Executor
│ (task_type)     │
└────────┬────────┘
         │
         ▼
     Response
```

---

## File Reference

| File | Purpose |
|------|---------|
| `src/klabautermann/skills/models.py` | Pydantic models for skill definitions |
| `src/klabautermann/skills/loader.py` | Loads SKILL.md files from directories |
| `src/klabautermann/skills/discovery.py` | AI-first skill matching via LLM |
| `src/klabautermann/skills/planner.py` | Converts skills to PlannedTask objects |
