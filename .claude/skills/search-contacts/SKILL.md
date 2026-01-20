---
name: search-contacts
description: Search for contacts and people in the knowledge graph
version: "1.0.0"
executor: researcher

parameters:
  - name: query
    type: string
    required: true
    description: Name or identifying information to search
  - name: organization
    type: string
    required: false
    description: Filter by organization/company
  - name: role
    type: string
    required: false
    description: Filter by job role/title
  - name: limit
    type: integer
    required: false
    default: 10
    description: Maximum number of results
---

# Search Contacts Skill

Finds people and contacts stored in the knowledge graph.

## Usage Examples

- "Find John's contact info"
- "Who works at Acme Corp?"
- "Search for engineers I've talked to"
- "Look up Sarah from marketing"

## Executor Integration

Routes to the `researcher` agent which queries the Neo4j knowledge graph:

```cypher
MATCH (p:Person)
WHERE p.name CONTAINS $query OR p.email CONTAINS $query
OPTIONAL MATCH (p)-[:WORKS_AT]->(o:Organization)
RETURN p, o
LIMIT $limit
```

## Response Format

Returns structured contact information:
- Name
- Email (if known)
- Organization
- Role/title
- Last interaction date
