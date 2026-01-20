# Cypher Query Cookbook

This cookbook provides ready-to-use Cypher queries for common Klabautermann use cases. All queries use parametrized placeholders (`$param`) for security.

## Table of Contents

- [Query Security](#query-security)
- [Basic CRUD Operations](#basic-crud-operations)
- [Person Queries](#person-queries)
- [Organization Queries](#organization-queries)
- [Task & Project Queries](#task--project-queries)
- [Event Queries](#event-queries)
- [Temporal Queries](#temporal-queries)
- [Thread & Message Queries](#thread--message-queries)
- [Graph Traversal](#graph-traversal)
- [Analytics Queries](#analytics-queries)
- [Email & Calendar Queries](#email--calendar-queries)
- [Index Reference](#index-reference)

---

## Query Security

All queries must use parametrized placeholders to prevent injection attacks.

```python
# CORRECT - Parametrized query
query = """
MATCH (p:Person {name: $name})
RETURN p
"""
await client.execute_query(query, {"name": user_input})

# WRONG - String interpolation (NEVER do this)
query = f"MATCH (p:Person {{name: '{user_input}'}})"  # Vulnerable!
```

---

## Basic CRUD Operations

### Create a Node

```cypher
// Create Person
CREATE (p:Person {
    uuid: $uuid,
    name: $name,
    email: $email,
    created_at: timestamp()
})
RETURN p.uuid as uuid
```

### Create with MERGE (Idempotent)

```cypher
// Create or update Person by email
MERGE (p:Person {email: $email})
ON CREATE SET
    p.uuid = $uuid,
    p.name = $name,
    p.created_at = timestamp()
ON MATCH SET
    p.name = $name,
    p.updated_at = timestamp()
RETURN p.uuid as uuid, p.name as name
```

### Create Relationship

```cypher
// Link Person to Organization
MATCH (p:Person {uuid: $person_uuid})
MATCH (o:Organization {uuid: $org_uuid})
CREATE (p)-[r:WORKS_AT {
    title: $title,
    department: $department,
    created_at: timestamp()
}]->(o)
RETURN p.name as person, o.name as organization
```

### Update Node Properties

```cypher
// Update Person
MATCH (p:Person {uuid: $uuid})
SET p.name = $name,
    p.email = $email,
    p.updated_at = timestamp()
RETURN p
```

### Delete Node (with Relationships)

```cypher
// Delete Person and all relationships
MATCH (p:Person {uuid: $uuid})
DETACH DELETE p
```

---

## Person Queries

### Find Person by Name

```cypher
// Case-insensitive partial match
MATCH (p:Person)
WHERE toLower(p.name) CONTAINS toLower($name)
RETURN p.uuid as uuid, p.name as name, p.email as email,
       p.bio as bio, p.created_at as created_at
LIMIT $limit
```

### Find Person's Current Organization

```cypher
// Only active (non-expired) relationships
MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
WHERE r.expired_at IS NULL
RETURN p.name as person, o.name as organization,
       r.title as title, r.department as department,
       r.created_at as started
```

### Find Person's Manager Chain

```cypher
// Traverse reporting chain up to 5 levels
MATCH path = (p:Person)-[:REPORTS_TO*1..5]->(top:Person)
WHERE toLower(p.name) CONTAINS toLower($name)
WITH p, top, path, length(path) as chain_length
RETURN p.name as person, top.name as top_manager,
       [node in nodes(path) | node.name] as chain,
       chain_length
ORDER BY chain_length
LIMIT $limit
```

### Find Person's Connections

```cypher
// Find people a person knows (via RELATES_TO edges from Graphiti)
MATCH (a:Person)-[r:RELATES_TO]->(b:Person)
WHERE toLower(a.name) CONTAINS toLower($name)
  AND r.name =~ '(?i).*(knows|friend|connected|acquainted).*'
  AND r.expired_at IS NULL
RETURN a.name as person, b.name as connection,
       r.name as relationship_type,
       r.fact as context
ORDER BY r.created_at DESC
LIMIT $limit
```

### Find All People at Organization

```cypher
// List employees at organization
MATCH (p:Person)-[r:WORKS_AT]->(o:Organization {uuid: $org_uuid})
WHERE r.expired_at IS NULL
RETURN p.uuid as uuid, p.name as name, p.email as email,
       r.title as title, r.department as department
ORDER BY p.name
LIMIT $limit
```

---

## Organization Queries

### Find Organization by Name

```cypher
// Using fulltext index
CALL db.index.fulltext.queryNodes("org_search", $query)
YIELD node, score
RETURN node.uuid as uuid, node.name as name,
       node.industry as industry, score
ORDER BY score DESC
LIMIT $limit
```

### Find Organization's Projects

```cypher
// Active projects at organization
MATCH (o:Organization {uuid: $org_uuid})<-[:AFFILIATED_WITH]-(p:Project)
WHERE p.status = 'active'
RETURN p.uuid as uuid, p.name as name,
       p.deadline as deadline, p.status as status
ORDER BY p.deadline ASC NULLS LAST
LIMIT $limit
```

---

## Task & Project Queries

### Find Tasks by Status

```cypher
// Tasks with optional project info
MATCH (t:Task {status: $status})
OPTIONAL MATCH (t)-[:PART_OF]->(p:Project)
RETURN t.uuid as uuid, t.action as task, t.priority as priority,
       t.due_date as due_date, t.created_at as created_at,
       p.name as project_name, p.uuid as project_uuid
ORDER BY
    CASE t.priority
        WHEN 'urgent' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        WHEN 'low' THEN 4
        ELSE 5
    END,
    t.due_date ASC NULLS LAST
LIMIT $limit
```

### Find Blocked Tasks

```cypher
// Tasks blocking other tasks
MATCH (blocker:Task)-[r:BLOCKS]->(blocked:Task)
WHERE blocked.status <> 'done' AND blocker.status <> 'done'
RETURN blocker.action as blocker_task, blocker.uuid as blocker_uuid,
       blocker.status as blocker_status,
       blocked.action as blocked_task, blocked.uuid as blocked_uuid,
       blocked.status as blocked_status, r.reason as reason
LIMIT $limit
```

### Find Task Dependency Chain

```cypher
// All tasks blocking a specific task (up to 5 levels deep)
MATCH path = (t:Task)-[:BLOCKS*1..5]->(target:Task {uuid: $task_uuid})
RETURN [node in nodes(path) | {
    uuid: node.uuid,
    action: node.action,
    status: node.status
}] as chain,
length(path) as chain_length
ORDER BY chain_length
```

### Find Project Tasks with Priority

```cypher
// All tasks for a project, ordered by priority
MATCH (t:Task)-[:PART_OF]->(p:Project {uuid: $project_uuid})
RETURN t.uuid as uuid, t.action as task, t.status as status,
       t.priority as priority, t.due_date as due_date
ORDER BY
    CASE t.priority
        WHEN 'urgent' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        WHEN 'low' THEN 4
        ELSE 5
    END,
    t.created_at ASC
LIMIT $limit
```

### Find Project Goal Contributions

```cypher
// Projects contributing to goals with weights
MATCH (proj:Project)-[r:CONTRIBUTES_TO]->(goal:Goal)
WHERE toLower(proj.name) CONTAINS toLower($name)
  AND r.expired_at IS NULL
RETURN proj.name as project, goal.description as goal,
       r.weight as contribution_weight, r.how as contribution_how
ORDER BY r.weight DESC NULLS LAST
LIMIT $limit
```

---

## Event Queries

### Find Events in Time Range

```cypher
// Events between two timestamps
MATCH (e:Event)
WHERE e.start_time >= $start_timestamp
  AND e.start_time <= $end_timestamp
RETURN e.uuid as uuid, e.title as title,
       e.start_time as start_time, e.end_time as end_time,
       e.location_context as location, e.description as description
ORDER BY e.start_time ASC
LIMIT $limit
```

### Find Event Attendees

```cypher
// People who attended an event, ordered by role
MATCH (p:Person)-[r:ATTENDED]->(e:Event {uuid: $event_uuid})
RETURN p.uuid as person_uuid, p.name as name, p.email as email,
       r.role as role
ORDER BY
    CASE r.role
        WHEN 'organizer' THEN 1
        WHEN 'speaker' THEN 2
        WHEN 'attendee' THEN 3
        ELSE 4
    END,
    p.name
```

### Find Topics Discussed in Event

```cypher
// Projects, Tasks, or Goals discussed in an event
MATCH (e:Event {uuid: $event_uuid})-[:DISCUSSED]->(item)
RETURN labels(item)[0] as item_type, item.uuid as uuid,
       COALESCE(item.name, item.action, item.description) as item_name
```

---

## Temporal Queries

### Time-Travel Query (Historical State)

```cypher
// Get relationships as they existed at a specific point in time
MATCH (a)-[r]->(b)
WHERE r.created_at IS NOT NULL
  AND r.created_at <= $as_of_timestamp
  AND (r.expired_at IS NULL OR r.expired_at > $as_of_timestamp)
RETURN labels(a)[0] as source_type,
       COALESCE(a.name, a.title, a.action) as source_name,
       type(r) as relationship,
       labels(b)[0] as target_type,
       COALESCE(b.name, b.title, b.action) as target_name,
       r.created_at as valid_from,
       r.expired_at as valid_until
ORDER BY r.created_at DESC
LIMIT $limit
```

### Find Historical Employer

```cypher
// Where did someone work at a specific date?
MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
WHERE r.created_at <= $as_of_timestamp
  AND (r.expired_at IS NULL OR r.expired_at > $as_of_timestamp)
RETURN p.name as person, o.name as organization,
       r.title as title, r.created_at as started,
       r.expired_at as ended
```

### Find Expired Relationships

```cypher
// Relationships that ended within a time range
MATCH (a)-[r]->(b)
WHERE r.expired_at IS NOT NULL
  AND r.expired_at >= $start_timestamp
  AND r.expired_at <= $end_timestamp
RETURN labels(a)[0] as source_type,
       COALESCE(a.name, a.title, a.action) as source_name,
       type(r) as relationship,
       labels(b)[0] as target_type,
       COALESCE(b.name, b.title, b.action) as target_name,
       r.created_at as created_at,
       r.expired_at as expired_at
ORDER BY r.expired_at DESC
LIMIT $limit
```

### Find Entities Created in Range

```cypher
// All entities created within a time range
MATCH (n)
WHERE n.created_at >= $start_timestamp
  AND n.created_at <= $end_timestamp
  AND n.created_at IS NOT NULL
WITH DISTINCT n, labels(n)[0] as label
WHERE label IN ['Person', 'Organization', 'Project', 'Task', 'Event',
                'Note', 'Goal', 'Location', 'Resource']
RETURN label as type, n.uuid as uuid,
       COALESCE(n.name, n.title, n.action, n.description) as name,
       n.created_at as created_at
ORDER BY n.created_at DESC
LIMIT $limit
```

---

## Thread & Message Queries

### Find Recent Threads

```cypher
// Active or archived threads for a channel
MATCH (t:Thread)
WHERE t.channel_type = $channel_type
  AND t.status IN ['active', 'archived']
RETURN t.uuid as uuid, t.external_id as external_id,
       t.status as status, t.last_message_at as last_activity,
       t.created_at as created_at
ORDER BY t.last_message_at DESC
LIMIT $limit
```

### Get Thread Messages

```cypher
// Recent messages in a thread
MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
RETURN m.uuid as uuid, m.role as role, m.content as content,
       m.timestamp as timestamp, m.metadata as metadata
ORDER BY m.timestamp DESC
LIMIT $limit
```

### Get Thread Summary

```cypher
// Most recent summary note for a thread
MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread {uuid: $thread_uuid})
RETURN n.uuid as uuid, n.title as title,
       n.content_summarized as summary, n.created_at as created_at
ORDER BY n.created_at DESC
LIMIT 1
```

### Count Thread Messages

```cypher
// Total messages in a thread
MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
RETURN count(m) as message_count
```

### Find Inactive Threads

```cypher
// Threads inactive for archival
MATCH (t:Thread)
WHERE t.status = 'active'
  AND t.last_message_at < $cutoff_timestamp
RETURN t.uuid as uuid, t.external_id as external_id,
       t.last_message_at as last_activity
ORDER BY t.last_message_at ASC
LIMIT $limit
```

---

## Graph Traversal

### Find Related Entities (1-2 Hops)

```cypher
// Entities related to a starting node
MATCH (start {uuid: $entity_uuid})-[r*1..2]-(related)
WHERE r[0].expired_at IS NULL OR r[0].expired_at > timestamp()
WITH DISTINCT related, labels(related)[0] as label
WHERE label IN ['Person', 'Organization', 'Project', 'Task', 'Event',
                'Note', 'Goal', 'Location']
RETURN label as type, related.uuid as uuid,
       COALESCE(related.name, related.title, related.action) as name
LIMIT $limit
```

### Find Shortest Path

```cypher
// Shortest path between two entities
MATCH path = shortestPath(
    (a {uuid: $from_uuid})-[*1..6]-(b {uuid: $to_uuid})
)
RETURN [node in nodes(path) | {
    type: labels(node)[0],
    uuid: node.uuid,
    name: COALESCE(node.name, node.title, node.action)
}] as path_nodes,
[rel in relationships(path) | type(rel)] as path_relationships,
length(path) as path_length
```

### Find Entities Mentioning Topic

```cypher
// Notes mentioning a specific entity
MATCH (e)-[:MENTIONED_IN]->(n:Note)
WHERE e.uuid = $entity_uuid
RETURN n.uuid as note_uuid, n.title as title,
       n.content_summarized as summary, n.created_at as created_at
ORDER BY n.created_at DESC
LIMIT $limit
```

---

## Analytics Queries

### Daily Activity Count

```cypher
// Count entities created per day
MATCH (n)
WHERE n.created_at >= $start_timestamp
  AND n.created_at <= $end_timestamp
  AND n.created_at IS NOT NULL
WITH labels(n)[0] as entity_type,
     date(datetime({epochMillis: toInteger(n.created_at * 1000)})) as day
RETURN day, entity_type, count(*) as count
ORDER BY day DESC, entity_type
```

### Entity Type Distribution

```cypher
// Count of each entity type
MATCH (n)
WHERE labels(n)[0] IN ['Person', 'Organization', 'Project', 'Task',
                        'Event', 'Note', 'Goal', 'Location']
RETURN labels(n)[0] as entity_type, count(n) as count
ORDER BY count DESC
```

### Relationship Type Distribution

```cypher
// Count of each relationship type
MATCH ()-[r]->()
RETURN type(r) as relationship_type, count(r) as count
ORDER BY count DESC
LIMIT 20
```

### Most Connected Entities

```cypher
// Entities with most relationships
MATCH (n)-[r]-()
WITH n, count(r) as connection_count, labels(n)[0] as label
WHERE label IN ['Person', 'Organization', 'Project']
RETURN label, n.uuid as uuid,
       COALESCE(n.name, n.title) as name,
       connection_count
ORDER BY connection_count DESC
LIMIT 20
```

---

## Email & Calendar Queries

### Search Emails

```cypher
// Full-text search on email subject and snippet
CALL db.index.fulltext.queryNodes("email_search", $query)
YIELD node, score
WHERE score > 0.5
RETURN node.uuid as uuid, node.subject as subject,
       node.sender as sender, node.date as date,
       node.snippet as snippet, score
ORDER BY node.date DESC
LIMIT $limit
```

### Find Emails in Date Range

```cypher
// Emails within date range
MATCH (e:Email)
WHERE e.date >= $start_date AND e.date <= $end_date
RETURN e.uuid as uuid, e.subject as subject,
       e.sender as sender, e.date as date,
       e.is_unread as unread
ORDER BY e.date DESC
LIMIT $limit
```

### Find Calendar Events

```cypher
// Calendar events in time range
MATCH (c:CalendarEvent)
WHERE c.start_time >= $start_timestamp
  AND c.start_time <= $end_timestamp
RETURN c.uuid as uuid, c.title as title,
       c.start_time as start_time, c.end_time as end_time,
       c.location as location, c.attendees as attendees
ORDER BY c.start_time ASC
LIMIT $limit
```

---

## Index Reference

### Fulltext Indexes (for Search)

| Index | Label | Properties | Use Case |
|-------|-------|------------|----------|
| `person_search` | Person | name, email, bio | Find people |
| `org_search` | Organization | name, description | Find orgs |
| `note_search` | Note | title, content_summarized | Search notes |
| `project_search` | Project | name, description | Find projects |
| `email_search` | Email | subject, snippet | Search emails |
| `calendarevent_search` | CalendarEvent | title, description | Search events |

**Usage:**

```cypher
CALL db.index.fulltext.queryNodes("person_search", "john developer")
YIELD node, score
RETURN node.name, score
ORDER BY score DESC
```

### B-Tree Indexes (for Filtering)

| Index | Label | Properties | Use Case |
|-------|-------|------------|----------|
| `message_timestamp` | Message | timestamp | Message ordering |
| `thread_status` | Thread | status, last_message_at | Thread queries |
| `task_status` | Task | status, due_date | Task filtering |
| `email_date` | Email | date | Email date range |
| `calendarevent_start` | CalendarEvent | start_time | Event scheduling |

### Temporal Indexes (for Time-Travel)

| Index | Relationship | Properties | Use Case |
|-------|-------------|------------|----------|
| `works_at_temporal` | WORKS_AT | created_at, expired_at | Employment history |
| `located_in_temporal` | LOCATED_IN | created_at, expired_at | Location history |

### Vector Indexes (for Semantic Search)

| Index | Label | Property | Dimensions |
|-------|-------|----------|------------|
| `person_vector` | Person | vector_embedding | 1536 |
| `note_vector` | Note | vector_embedding | 1536 |
| `resource_vector` | Resource | vector_embedding | 1536 |

**Usage (via Graphiti client):**

```python
results = await graphiti_client.search(
    query="Who worked on the authentication feature?",
    limit=5
)
```

---

## Query Performance Tips

1. **Use indexes**: Always query on indexed properties
2. **Limit results**: Always include `LIMIT $limit` in queries
3. **Use parameters**: Never concatenate strings into queries
4. **Profile queries**: Use `PROFILE` prefix to analyze performance
5. **Avoid label scans**: Start with specific property matches when possible

```cypher
// Profile a query to analyze performance
PROFILE
MATCH (p:Person {uuid: $uuid})-[:WORKS_AT]->(o:Organization)
RETURN p, o
```
