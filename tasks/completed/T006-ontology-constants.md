# Define Ontology Constants

## Metadata
- **ID**: T006
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: @graph-engineer

## Specs
- Primary: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section on Agent Instructions

## Dependencies
- [ ] T003 - Project directory structure

## Context
The ontology constants define the allowed node labels and relationship types in the knowledge graph. These enums ensure type safety and consistency across all graph operations. They also serve as the source of truth for database initialization.

## Requirements
- [ ] Create `src/klabautermann/core/ontology.py` with:

### Node Labels Enum
- [ ] `NodeLabel` enum containing all 21 node types from ONTOLOGY.md:
  - Core: Person, Organization, Project, Goal, Task, Event, Location, Note, Resource
  - Personal Life: Hobby, HealthMetric, Pet, Milestone, Routine, Preference, Community, LoreEpisode
  - System: Thread, Message, Day, JournalEntry, Tag

### Relationship Types Enum
- [ ] `RelationType` enum containing all 40+ relationship types:
  - Professional: WORKS_AT, REPORTS_TO, AFFILIATED_WITH
  - Action: CONTRIBUTES_TO, PART_OF, SUBTASK_OF, BLOCKS, DEPENDS_ON, ASSIGNED_TO
  - Spatial: HELD_AT, LOCATED_IN, CREATED_AT_LOCATION
  - Knowledge: REFERENCES, SUMMARIZES, SUMMARY_OF, MENTIONED_IN, DISCUSSED
  - Event: ATTENDED, ORGANIZED_BY
  - Lineage: VERSION_OF, REPLIES_TO, ATTACHED_TO
  - Interpersonal: KNOWS, INTRODUCED_BY
  - Family: FAMILY_OF, SPOUSE_OF, PARENT_OF, CHILD_OF, SIBLING_OF, FRIEND_OF
  - Personal: PRACTICES, INTERESTED_IN, PREFERS, OWNS, CARES_FOR, RECORDED, ACHIEVES, FOLLOWS_ROUTINE
  - Community: PART_OF_ISLAND
  - Lore: EXPANDS_UPON, TOLD_TO, SAGA_STARTED_BY
  - Thread: CONTAINS, PRECEDES
  - Temporal: OCCURRED_ON
  - Categorization: TAGGED_WITH

### Constraint Definitions
- [ ] `CONSTRAINTS` list with all Cypher constraint statements
- [ ] `INDEXES` list with all Cypher index statements

## Acceptance Criteria
- [ ] `NodeLabel.PERSON.value` returns "Person"
- [ ] `RelationType.WORKS_AT.value` returns "WORKS_AT"
- [ ] All enums match ONTOLOGY.md exactly
- [ ] Constraint strings are valid Cypher
- [ ] Index strings are valid Cypher

## Implementation Notes

```python
from enum import Enum

class NodeLabel(str, Enum):
    """Valid node labels for the knowledge graph."""
    # Core Entities
    PERSON = "Person"
    ORGANIZATION = "Organization"
    PROJECT = "Project"
    GOAL = "Goal"
    TASK = "Task"
    EVENT = "Event"
    LOCATION = "Location"
    NOTE = "Note"
    RESOURCE = "Resource"
    # ... continue with all labels

class RelationType(str, Enum):
    """Valid relationship types for the knowledge graph."""
    # Professional Context
    WORKS_AT = "WORKS_AT"
    REPORTS_TO = "REPORTS_TO"
    # ... continue with all types

# Constraint definitions (from ONTOLOGY.md Section 4.1)
CONSTRAINTS = [
    "CREATE CONSTRAINT person_uuid IF NOT EXISTS FOR (p:Person) REQUIRE p.uuid IS UNIQUE",
    "CREATE CONSTRAINT organization_uuid IF NOT EXISTS FOR (o:Organization) REQUIRE o.uuid IS UNIQUE",
    # ... all constraints
]

# Index definitions (from ONTOLOGY.md Section 4.2)
INDEXES = [
    "CREATE FULLTEXT INDEX person_search IF NOT EXISTS FOR (p:Person) ON EACH [p.name, p.email, p.bio]",
    # ... all indexes
]
```

Reference ONTOLOGY.md Section 4 for the complete list of constraints and indexes.
