---
name: create-note
description: Create and save a text note to the knowledge graph
version: "1.0.0"
executor: ingestor

parameters:
  - name: content
    type: string
    required: true
    description: The note content/text
  - name: title
    type: string
    required: false
    description: Optional title for the note
  - name: tags
    type: array[string]
    required: false
    description: Tags for categorization
  - name: related_to
    type: string
    required: false
    description: Person or topic this note relates to
---

# Create Note Skill

Saves text notes to the knowledge graph with entity extraction.

## Usage Examples

- "Create a note about the project meeting"
- "Save this: John mentioned the deadline is moved to Friday"
- "Remember this for later: API key is in the config file"
- "Write a note about Sarah's feedback on the design"

## Executor Integration

Routes to the `ingestor` agent which:
1. Extracts entities (people, orgs, dates, etc.)
2. Creates a Note node in the graph
3. Links to related entities via relationships

## Entity Extraction

The ingestor will automatically extract:
- Person mentions → Person nodes
- Organization mentions → Organization nodes
- Date references → Temporal edges
- Topic keywords → Tags

## Response Format

Returns confirmation with:
- Note ID
- Extracted entities
- Related nodes created
