# Klabautermann Memory System

**Version**: 1.0
**Purpose**: Graphiti-based temporal knowledge graph implementation

---

## Overview

Klabautermann's memory is built on **Graphiti**, a temporal knowledge graph framework that treats time as a first-class citizen. Unlike traditional databases where updates overwrite data, Graphiti preserves the complete history of facts—enabling "time travel" queries and conflict-free state evolution.

```
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Short-Term  │ → │  Mid-Term   │ → │  Long-Term  │     │
│  │  (Messages) │    │   (Notes)   │    │  (Entities) │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│       │                   │                   │             │
│       │     Archivist     │     Graphiti     │             │
│       └───────────────────┴──────────────────┘             │
│                                                             │
│  Storage: Neo4j + Vector Index                              │
│  Framework: Graphiti                                        │
│  Access: GraphitiClient wrapper                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Memory Layers

### 1.1 Short-Term Memory (Messages)

**Purpose**: Immediate conversational context
**Storage**: Message nodes linked via [:PRECEDES]
**Retention**: Until thread is archived (60+ minute cooldown)
**Retrieval**: Sequential chain traversal

```cypher
// Get last 15 messages in thread
MATCH (t:Thread {uuid: $thread_id})-[:CONTAINS]->(m:Message)
WITH m ORDER BY m.timestamp DESC LIMIT 15
WITH collect(m) as messages
UNWIND reverse(messages) as msg
RETURN msg.role, msg.content, msg.timestamp
ORDER BY msg.timestamp ASC
```

**Properties**:
| Property | Type | Description |
|----------|------|-------------|
| `uuid` | String | Unique identifier |
| `role` | String | "user" or "assistant" |
| `content` | String | Message text |
| `timestamp` | Float | Unix timestamp |
| `metadata` | JSON String | Additional data (voice file URL, etc.) |

---

### 1.2 Mid-Term Memory (Notes)

**Purpose**: Summarized conversations and captured knowledge
**Storage**: Note nodes linked to Threads and Days
**Retention**: Indefinite
**Retrieval**: Vector search + graph traversal

```cypher
// Find notes related to a topic
CALL db.index.vector.queryNodes('note_vector', 5, $query_embedding)
YIELD node, score
MATCH (node)-[:SUMMARY_OF]->(t:Thread)
RETURN node.title, node.content_summarized, t.uuid, score
ORDER BY score DESC
```

**Properties**:
| Property | Type | Description |
|----------|------|-------------|
| `uuid` | String | Unique identifier |
| `title` | String | Note title |
| `content_summarized` | String | AI-generated summary |
| `topics` | String[] | Extracted topics |
| `action_items` | JSON String | Pending/completed items |
| `vector_embedding` | Float[] | Semantic embedding |
| `created_at` | Float | Creation timestamp |

---

### 1.3 Long-Term Memory (Entities)

**Purpose**: Structured knowledge about people, projects, organizations
**Storage**: Entity nodes managed by Graphiti with temporal relationships
**Retention**: Permanent (historical states preserved)
**Retrieval**: Hybrid vector + graph traversal (GraphRAG)

```cypher
// Find person and their current relationships
MATCH (p:Person {name: $name})-[r]->(target)
WHERE r.expired_at IS NULL
RETURN p, type(r) as relationship, target
```

---

## 2. Graphiti Integration

### 2.1 What is Graphiti?

Graphiti is a framework for building **Temporal Knowledge Graphs** with these key features:

1. **Episode-Based Ingestion**: Information enters as "episodes" (conversations, emails, events)
2. **Automatic Entity Extraction**: LLM extracts entities and relationships
3. **Temporal Versioning**: Relationships have valid_from/valid_to timestamps
4. **Hybrid Search**: Combines vector similarity with graph traversal
5. **Conflict Resolution**: Handles contradictions through temporal logic

### 2.2 GraphitiClient Wrapper

```python
# klabautermann/memory/graphiti_client.py
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from pydantic import BaseModel

class SearchResult(BaseModel):
    fact: str
    uuid: str
    score: float
    source_episode: Optional[str] = None
    created_at: float
    valid_at: Optional[float] = None
    invalid_at: Optional[float] = None

class GraphitiClient:
    def __init__(self, uri: str, user: str, password: str):
        self.client = Graphiti(uri, user, password)
        self._initialized = False

    async def initialize(self):
        """Setup Graphiti indexes and constraints"""
        if self._initialized:
            return

        await self.client.build_indices_and_constraints()
        self._initialized = True

    async def ingest_episode(
        self,
        name: str,
        content: str,
        episode_type: str = "text",
        source_description: str = "Conversation",
        reference_time: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ingest an episode into the temporal knowledge graph.

        Args:
            name: Episode identifier
            content: Text content of the episode
            episode_type: "text", "voice", "email", "calendar"
            source_description: Where this came from
            reference_time: When this episode occurred
            metadata: Additional metadata (thread_id, trace_id, etc.)

        Returns:
            Extraction results (entities, relationships, facts)
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        episode_type_map = {
            "text": EpisodeType.text,
            "voice": EpisodeType.text,  # Transcribed
            "email": EpisodeType.text,
            "calendar": EpisodeType.text
        }

        result = await self.client.add_episode(
            name=name,
            episode_body=content,
            episode_type=episode_type_map.get(episode_type, EpisodeType.text),
            source_description=source_description,
            reference_time=reference_time,
            source=metadata or {}
        )

        return {
            "episode_uuid": str(result.uuid) if hasattr(result, 'uuid') else None,
            "entities_extracted": len(result.nodes) if hasattr(result, 'nodes') else 0,
            "relationships_created": len(result.edges) if hasattr(result, 'edges') else 0
        }

    async def search(
        self,
        query: str,
        limit: int = 10,
        include_expired: bool = False
    ) -> List[SearchResult]:
        """
        Hybrid search: vector similarity + graph context.

        Args:
            query: Natural language search query
            limit: Maximum results to return
            include_expired: Whether to include historical (expired) facts

        Returns:
            List of search results with facts and metadata
        """
        results = await self.client.search(query, num_results=limit)

        search_results = []
        for r in results:
            # Filter expired if requested
            if not include_expired and r.invalid_at is not None:
                continue

            search_results.append(SearchResult(
                fact=r.fact,
                uuid=str(r.uuid),
                score=r.score if hasattr(r, 'score') else 1.0,
                source_episode=str(r.source_episode_uuid) if hasattr(r, 'source_episode_uuid') else None,
                created_at=r.created_at.timestamp() if hasattr(r, 'created_at') else 0,
                valid_at=r.valid_at.timestamp() if hasattr(r, 'valid_at') else None,
                invalid_at=r.invalid_at.timestamp() if hasattr(r, 'invalid_at') else None
            ))

        return search_results[:limit]

    async def get_entity(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get an entity by UUID"""
        # Direct Neo4j query for entity lookup
        async with self.client.driver.session() as session:
            result = await session.run(
                "MATCH (n {uuid: $uuid}) RETURN n, labels(n) as labels",
                {"uuid": uuid}
            )
            record = await result.single()
            if record:
                return {
                    "properties": dict(record["n"]),
                    "labels": record["labels"]
                }
        return None

    async def expire_relationship(
        self,
        source_uuid: str,
        relationship_type: str,
        target_uuid: str,
        expired_at: Optional[datetime] = None
    ):
        """
        Mark a relationship as expired (temporal update).

        This is the key temporal operation: we don't delete,
        we mark the end of validity.
        """
        if expired_at is None:
            expired_at = datetime.now(timezone.utc)

        async with self.client.driver.session() as session:
            await session.run(
                f"""
                MATCH (s {{uuid: $source_uuid}})-[r:{relationship_type}]->(t {{uuid: $target_uuid}})
                WHERE r.expired_at IS NULL
                SET r.expired_at = $expired_at
                """,
                {
                    "source_uuid": source_uuid,
                    "target_uuid": target_uuid,
                    "expired_at": expired_at.timestamp()
                }
            )

    async def time_travel_query(
        self,
        query: str,
        as_of: datetime
    ) -> List[SearchResult]:
        """
        Query the graph state as it was at a specific point in time.

        Args:
            query: Search query
            as_of: Point in time to query

        Returns:
            Results filtered to that temporal snapshot
        """
        # Get all results including expired
        all_results = await self.search(query, limit=50, include_expired=True)

        # Filter to those valid at the specified time
        as_of_ts = as_of.timestamp()
        time_filtered = []

        for r in all_results:
            # Valid if: created before as_of AND (not expired OR expired after as_of)
            created_valid = r.created_at <= as_of_ts
            not_yet_expired = r.invalid_at is None or r.invalid_at > as_of_ts

            if created_valid and not_yet_expired:
                time_filtered.append(r)

        return time_filtered

    async def close(self):
        """Close the Graphiti client connection"""
        await self.client.close()
```

### 2.3 Episode Types

| Type | Source | Example |
|------|--------|---------|
| `text` | Conversation | User message about meeting Sarah |
| `voice` | Transcribed audio | Voice note about project status |
| `email` | Gmail ingestion | Email from Sarah about budget |
| `calendar` | Calendar event | Meeting invite with attendees |

---

## 3. Thread Management

### 3.1 Thread Lifecycle

```
Created → Active → Archiving → Archived
   │         │          │          │
   │         │          │          └── Summary queryable
   │         │          └── Archivist processing
   │         └── Receiving messages
   └── First message received
```

### 3.2 ThreadManager Implementation

```python
# klabautermann/memory/thread_manager.py
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from neo4j import AsyncDriver
import uuid as uuid_lib

class ThreadManager:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def get_or_create_thread(
        self,
        external_id: str,
        channel_type: str,
        user_id: Optional[str] = None
    ) -> str:
        """Get existing thread or create new one"""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MERGE (t:Thread {external_id: $external_id, channel_type: $channel_type})
                ON CREATE SET
                    t.uuid = $uuid,
                    t.status = 'active',
                    t.user_id = $user_id,
                    t.created_at = timestamp(),
                    t.last_message_at = timestamp()
                ON MATCH SET
                    t.last_message_at = timestamp()
                RETURN t.uuid
                """,
                {
                    "external_id": external_id,
                    "channel_type": channel_type,
                    "uuid": str(uuid_lib.uuid4()),
                    "user_id": user_id
                }
            )
            record = await result.single()
            return record["t.uuid"]

    async def add_message(
        self,
        thread_uuid: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add message to thread with PRECEDES linking"""
        message_uuid = str(uuid_lib.uuid4())
        timestamp = datetime.now(timezone.utc).timestamp()

        async with self.driver.session() as session:
            # Create message and link to thread
            await session.run(
                """
                MATCH (t:Thread {uuid: $thread_uuid})

                // Find the current last message (if any)
                OPTIONAL MATCH (t)-[:CONTAINS]->(prev:Message)
                WHERE NOT (prev)-[:PRECEDES]->()

                // Create new message
                CREATE (m:Message {
                    uuid: $message_uuid,
                    role: $role,
                    content: $content,
                    timestamp: $timestamp,
                    metadata: $metadata
                })

                // Link to thread
                CREATE (t)-[:CONTAINS]->(m)

                // Link to previous message if exists
                FOREACH (p IN CASE WHEN prev IS NOT NULL THEN [prev] ELSE [] END |
                    CREATE (p)-[:PRECEDES]->(m)
                )

                // Update thread timestamp
                SET t.last_message_at = $timestamp
                """,
                {
                    "thread_uuid": thread_uuid,
                    "message_uuid": message_uuid,
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                    "metadata": json.dumps(metadata) if metadata else None
                }
            )

        return message_uuid

    async def get_context(
        self,
        thread_uuid: str,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Get rolling context window for thread"""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
                WITH m ORDER BY m.timestamp DESC LIMIT $limit
                WITH collect(m) as messages
                UNWIND reverse(messages) as msg
                RETURN msg.role as role, msg.content as content, msg.timestamp as timestamp
                ORDER BY msg.timestamp ASC
                """,
                {"thread_uuid": thread_uuid, "limit": limit}
            )
            records = await result.data()
            return records

    async def get_inactive_threads(
        self,
        cooldown_minutes: int = 60
    ) -> List[str]:
        """Find threads inactive for longer than cooldown"""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).timestamp()

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Thread {status: 'active'})
                WHERE t.last_message_at < $cutoff
                RETURN t.uuid
                """,
                {"cutoff": cutoff}
            )
            records = await result.data()
            return [r["t.uuid"] for r in records]

    async def get_full_thread(self, thread_uuid: str) -> List[Dict[str, Any]]:
        """Get all messages in thread for archival"""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
                RETURN m.role as role, m.content as content, m.timestamp as timestamp
                ORDER BY m.timestamp ASC
                """,
                {"thread_uuid": thread_uuid}
            )
            return await result.data()

    async def archive_thread(
        self,
        thread_uuid: str,
        summary_uuid: str
    ):
        """Mark thread as archived and link to summary"""
        async with self.driver.session() as session:
            # Update status and link summary
            await session.run(
                """
                MATCH (t:Thread {uuid: $thread_uuid})
                MATCH (n:Note {uuid: $summary_uuid})
                SET t.status = 'archived'
                CREATE (n)-[:SUMMARY_OF]->(t)
                """,
                {"thread_uuid": thread_uuid, "summary_uuid": summary_uuid}
            )

            # Delete messages (summary preserved)
            await session.run(
                """
                MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
                DETACH DELETE m
                """,
                {"thread_uuid": thread_uuid}
            )
```

---

## 4. Temporal Queries

### 4.1 Current State Queries

```python
# klabautermann/memory/queries.py

class TemporalQueries:
    """Library of temporal Cypher patterns"""

    @staticmethod
    def get_current_employer(person_uuid: str) -> tuple:
        """Get person's current employer"""
        return (
            """
            MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
            WHERE r.expired_at IS NULL
            RETURN o.name as employer, r.title as title, r.created_at as since
            """,
            {"person_uuid": person_uuid}
        )

    @staticmethod
    def get_employer_at_time(person_uuid: str, as_of: float) -> tuple:
        """Get person's employer at a specific point in time"""
        return (
            """
            MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
            WHERE r.created_at <= $as_of
              AND (r.expired_at IS NULL OR r.expired_at > $as_of)
            RETURN o.name as employer, r.title as title
            """,
            {"person_uuid": person_uuid, "as_of": as_of}
        )

    @staticmethod
    def get_employment_history(person_uuid: str) -> tuple:
        """Get full employment history for a person"""
        return (
            """
            MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
            RETURN o.name as employer, r.title as title,
                   r.created_at as started, r.expired_at as ended
            ORDER BY r.created_at DESC
            """,
            {"person_uuid": person_uuid}
        )

    @staticmethod
    def get_blocking_tasks() -> tuple:
        """Get all tasks that are blocked by other tasks"""
        return (
            """
            MATCH (blocked:Task {status: 'todo'})<-[:BLOCKS]-(blocker:Task)
            WHERE blocker.status <> 'done'
            RETURN blocked.action as blocked_task, blocked.uuid as blocked_uuid,
                   blocker.action as blocked_by, blocker.uuid as blocker_uuid
            """,
            {}
        )

    @staticmethod
    def get_project_chain(task_uuid: str) -> tuple:
        """Get full chain from task to goal"""
        return (
            """
            MATCH (t:Task {uuid: $task_uuid})-[:PART_OF]->(p:Project)-[:CONTRIBUTES_TO]->(g:Goal)
            RETURN t.action as task, p.name as project, g.description as goal
            """,
            {"task_uuid": task_uuid}
        )

    @staticmethod
    def get_meeting_context(person_name: str) -> tuple:
        """Get context for upcoming meeting with person"""
        return (
            """
            MATCH (p:Person {name: $person_name})

            // Get current employment
            OPTIONAL MATCH (p)-[w:WORKS_AT {expired_at: null}]->(org:Organization)

            // Get recent shared events
            OPTIONAL MATCH (p)-[:ATTENDED]->(e:Event)
            WHERE e.start_time > (timestamp() - 30*24*60*60*1000)  // Last 30 days

            // Get notes mentioning this person
            OPTIONAL MATCH (p)-[:MENTIONED_IN]->(n:Note)

            RETURN p.name, p.email, org.name as company, w.title as role,
                   collect(DISTINCT {event: e.title, date: e.start_time}) as recent_events,
                   collect(DISTINCT n.content_summarized)[0..3] as recent_notes
            """,
            {"person_name": person_name}
        )
```

### 4.2 Using Temporal Queries

```python
# Example: Time-travel query
async def who_did_sarah_work_for_last_month(graph_client):
    last_month = (datetime.now() - timedelta(days=30)).timestamp()

    query, params = TemporalQueries.get_employer_at_time("sarah-uuid", last_month)

    async with graph_client.driver.session() as session:
        result = await session.run(query, params)
        record = await result.single()

        if record:
            return f"Last month, Sarah worked at {record['employer']} as {record['title']}"
        return "I don't have records of Sarah's employment last month"
```

---

## 5. Day Nodes (Temporal Spine)

### 5.1 Purpose

Day nodes form the "temporal spine" of the graph—a chronological backbone that anchors all time-bound entities.

```cypher
// Structure
(Event)-[:OCCURRED_ON]->(Day)
(Note)-[:OCCURRED_ON]->(Day)
(JournalEntry)-[:OCCURRED_ON]->(Day)
```

### 5.2 Day Node Management

```python
async def get_or_create_day(driver: AsyncDriver, date: datetime) -> str:
    """Get or create Day node for a specific date"""
    date_str = date.strftime("%Y-%m-%d")
    day_of_week = date.strftime("%A")
    is_weekend = day_of_week in ["Saturday", "Sunday"]

    async with driver.session() as session:
        result = await session.run(
            """
            MERGE (d:Day {date: $date})
            ON CREATE SET
                d.day_of_week = $day_of_week,
                d.is_weekend = $is_weekend
            RETURN d.date
            """,
            {
                "date": date_str,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend
            }
        )
        record = await result.single()
        return record["d.date"]

async def link_to_day(driver: AsyncDriver, node_uuid: str, label: str, date: datetime):
    """Link an entity to its Day node"""
    date_str = date.strftime("%Y-%m-%d")

    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (n:{label} {{uuid: $node_uuid}})
            MERGE (d:Day {{date: $date}})
            MERGE (n)-[:OCCURRED_ON]->(d)
            """,
            {"node_uuid": node_uuid, "date": date_str}
        )
```

### 5.3 Day-Based Queries

```cypher
// What happened on a specific day?
MATCH (d:Day {date: '2025-01-15'})<-[:OCCURRED_ON]-(item)
RETURN labels(item)[0] as type,
       item.title as title,
       item.start_time as time
ORDER BY item.start_time

// Get weekly summary
MATCH (d:Day)
WHERE d.date >= '2025-01-13' AND d.date <= '2025-01-19'
MATCH (d)<-[:OCCURRED_ON]-(item)
RETURN d.date, d.day_of_week, collect(item.title) as activities
ORDER BY d.date
```

---

## 6. Vector Search + Graph Traversal

### 6.1 The GraphRAG Pattern

GraphRAG combines:
1. **Vector search** to find the "entry point" into the graph
2. **Graph traversal** to expand context around that entry point

```python
async def graphrag_search(
    graphiti: GraphitiClient,
    driver: AsyncDriver,
    query: str,
    expansion_depth: int = 2
) -> Dict[str, Any]:
    """
    Hybrid search: vector finds entry, graph expands context.

    Example: "What was discussed with Sarah about the budget?"
    1. Vector search finds Notes mentioning "Sarah" and "budget"
    2. Graph traversal finds: Sarah's org, related Projects, upcoming Events
    """

    # Step 1: Vector search for entry points
    vector_results = await graphiti.search(query, limit=5)

    if not vector_results:
        return {"facts": [], "context": {}}

    # Step 2: Graph expansion from each result
    entry_uuids = [r.uuid for r in vector_results]

    async with driver.session() as session:
        # Expand context around entry points
        result = await session.run(
            """
            UNWIND $uuids as entry_uuid
            MATCH (entry {uuid: entry_uuid})

            // Get directly connected nodes
            OPTIONAL MATCH (entry)-[r1]-(neighbor1)
            WHERE type(r1) IN ['MENTIONED_IN', 'DISCUSSED', 'ATTENDED', 'WORKS_AT', 'PART_OF']

            // Get second-degree connections
            OPTIONAL MATCH (neighbor1)-[r2]-(neighbor2)
            WHERE type(r2) IN ['WORKS_AT', 'CONTRIBUTES_TO']
              AND neighbor2 <> entry

            RETURN entry, collect(DISTINCT neighbor1) as first_degree,
                   collect(DISTINCT neighbor2) as second_degree
            """,
            {"uuids": entry_uuids}
        )

        expansion = await result.data()

    return {
        "facts": [r.fact for r in vector_results],
        "scores": [r.score for r in vector_results],
        "context": expansion
    }
```

### 6.2 Example: Meeting Preparation

```python
async def prepare_for_meeting(
    graphiti: GraphitiClient,
    driver: AsyncDriver,
    person_name: str
) -> str:
    """
    Gather all relevant context before a meeting.

    Uses GraphRAG to find:
    - Person's current role and organization
    - Recent conversations/notes
    - Shared events
    - Related projects
    - Any pending tasks involving them
    """

    # Vector search for person context
    results = await graphiti.search(f"meeting {person_name}", limit=10)

    # Structured graph query for relationships
    async with driver.session() as session:
        query_result = await session.run(
            """
            MATCH (p:Person {name: $name})

            // Current employment
            OPTIONAL MATCH (p)-[w:WORKS_AT {expired_at: null}]->(org)

            // Recent shared events (last 60 days)
            OPTIONAL MATCH (p)-[:ATTENDED]->(e:Event)
            WHERE e.start_time > timestamp() - 60*24*60*60*1000

            // Notes mentioning them
            OPTIONAL MATCH (p)-[:MENTIONED_IN]->(n:Note)

            // Tasks involving them
            OPTIONAL MATCH (t:Task)-[:ASSIGNED_TO]->(p)
            WHERE t.status <> 'done'

            // Projects they're involved with
            OPTIONAL MATCH (p)-[:MENTIONED_IN]->(:Note)-[:DISCUSSED]->(proj:Project)

            RETURN p.name, p.email, p.bio,
                   org.name as company, w.title as role,
                   collect(DISTINCT {title: e.title, date: e.start_time})[0..5] as recent_events,
                   collect(DISTINCT n.content_summarized)[0..3] as notes,
                   collect(DISTINCT t.action) as pending_tasks,
                   collect(DISTINCT proj.name) as related_projects
            """,
            {"name": person_name}
        )

        record = await query_result.single()

    if not record:
        return f"I don't have much context on {person_name} in The Locker."

    # Format response
    context_parts = [f"**{record['p.name']}**"]

    if record.get("company"):
        context_parts.append(f"- Works at {record['company']} as {record.get('role', 'unknown role')}")

    if record.get("recent_events"):
        events = [e["title"] for e in record["recent_events"] if e["title"]]
        if events:
            context_parts.append(f"- Recent meetings: {', '.join(events)}")

    if record.get("notes"):
        context_parts.append(f"- Recent notes: {'; '.join(record['notes'][:3])}")

    if record.get("pending_tasks"):
        context_parts.append(f"- Pending tasks: {', '.join(record['pending_tasks'])}")

    if record.get("related_projects"):
        context_parts.append(f"- Related projects: {', '.join(record['related_projects'])}")

    return "\n".join(context_parts)
```

---

## 7. Memory Maintenance

### 7.1 Deduplication

```python
async def find_duplicate_persons(driver: AsyncDriver) -> List[Dict]:
    """Find potential duplicate Person nodes"""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p1:Person), (p2:Person)
            WHERE p1.uuid < p2.uuid
              AND (
                toLower(p1.name) = toLower(p2.name)
                OR p1.email = p2.email
              )
            RETURN p1.uuid as uuid1, p1.name as name1,
                   p2.uuid as uuid2, p2.name as name2,
                   p1.email as email1, p2.email as email2
            """
        )
        return await result.data()

async def merge_persons(driver: AsyncDriver, keep_uuid: str, remove_uuid: str):
    """Merge duplicate persons, keeping all relationships"""
    async with driver.session() as session:
        # Transfer all relationships to kept node
        await session.run(
            """
            MATCH (keep:Person {uuid: $keep_uuid})
            MATCH (remove:Person {uuid: $remove_uuid})

            // Transfer incoming relationships
            MATCH (remove)<-[r]-(other)
            WHERE other <> keep
            MERGE (keep)<-[new_r:KNOWS]-(other)
            SET new_r = properties(r)
            DELETE r

            // Transfer outgoing relationships
            MATCH (remove)-[r]->(other)
            WHERE other <> keep
            MERGE (keep)-[new_r:KNOWS]->(other)
            SET new_r = properties(r)
            DELETE r

            // Merge properties (keep existing, add missing)
            SET keep.bio = COALESCE(keep.bio, remove.bio)
            SET keep.phone = COALESCE(keep.phone, remove.phone)
            SET keep.linkedin_url = COALESCE(keep.linkedin_url, remove.linkedin_url)

            // Delete duplicate
            DELETE remove
            """,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid}
        )
```

### 7.2 Orphan Cleanup

```python
async def find_orphan_nodes(driver: AsyncDriver) -> List[Dict]:
    """Find nodes with no relationships (potential cleanup candidates)"""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            WHERE NOT (n)--()
              AND NOT n:Day  // Days can be orphaned temporarily
            RETURN labels(n)[0] as type, n.uuid as uuid,
                   n.name as name, n.created_at as created
            ORDER BY n.created_at DESC
            LIMIT 100
            """
        )
        return await result.data()
```

---

## 8. Performance Optimization

### 8.1 Index Usage

Always use indexed properties in WHERE clauses:

```cypher
// GOOD: Uses uuid index
MATCH (p:Person {uuid: $uuid})

// BAD: Full scan
MATCH (p:Person)
WHERE p.bio CONTAINS 'engineer'

// GOOD: Uses full-text index
CALL db.index.fulltext.queryNodes('person_search', 'engineer')
```

### 8.2 Query Batching

```python
async def batch_ingest_messages(driver: AsyncDriver, messages: List[Dict]):
    """Batch insert multiple messages efficiently"""
    async with driver.session() as session:
        await session.run(
            """
            UNWIND $messages as msg
            MATCH (t:Thread {uuid: msg.thread_uuid})
            CREATE (m:Message {
                uuid: msg.uuid,
                role: msg.role,
                content: msg.content,
                timestamp: msg.timestamp
            })
            CREATE (t)-[:CONTAINS]->(m)
            """,
            {"messages": messages}
        )
```

### 8.3 Connection Pooling

```python
# Use Neo4j driver with connection pooling
driver = AsyncGraphDatabase.driver(
    uri,
    auth=(user, password),
    max_connection_pool_size=50,
    connection_acquisition_timeout=60.0
)
```

---

## 9. Multi-Level Retrieval (Zoom Mechanics)

### 9.1 Overview

The memory system supports three levels of retrieval granularity, allowing queries to "zoom" in or out depending on what information is needed. This enables executive summaries for broad questions and precise facts for specific queries.

```
┌─────────────────────────────────────────────────────────────────┐
│                    RETRIEVAL ZOOM LEVELS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  MACRO (Community/Islands)                               │   │
│  │  "What are my main life themes?"                        │   │
│  │  → Work Island, Family Island, Health Island            │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  MESO (Projects/Notes)                                   │   │
│  │  "What's happening with the Q1 budget?"                 │   │
│  │  → Project details, recent discussions, related goals   │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  MICRO (Entities/Episodes)                              │   │
│  │  "When did Sarah change jobs?"                          │   │
│  │  → Specific Person facts, relationship timestamps       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 Macro View: Knowledge Islands

For high-level overviews and "executive summary" queries.

```python
async def macro_search(
    driver: AsyncDriver,
    captain_uuid: str,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Macro-level retrieval: Get Knowledge Island summaries.

    Use for:
    - "What are the big themes in my life right now?"
    - "Give me an overview of my activities"
    - "What areas need attention?"
    """
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Community)
            WHERE EXISTS((c)<-[:PART_OF_ISLAND]-())

            // Get node counts and recent activity
            OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(member)
            WITH c, count(member) as member_count,
                 max(member.updated_at) as last_activity

            // Get island health metrics
            OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(t:Task {status: 'todo'})
            WITH c, member_count, last_activity, count(t) as pending_tasks

            RETURN c.uuid as island_uuid,
                   c.name as island_name,
                   c.theme as theme,
                   c.summary as summary,
                   member_count,
                   pending_tasks,
                   last_activity
            ORDER BY pending_tasks DESC, last_activity DESC
            """,
            {"captain_uuid": captain_uuid}
        )
        return await result.data()
```

**Example Query Results**:
```json
[
  {
    "island_name": "Work Island",
    "theme": "professional",
    "summary": "Career activities, projects, and professional relationships",
    "member_count": 247,
    "pending_tasks": 12,
    "last_activity": 1705320000000
  },
  {
    "island_name": "Family Island",
    "theme": "family",
    "summary": "Family relationships, events, and milestones",
    "member_count": 45,
    "pending_tasks": 3,
    "last_activity": 1705280000000
  }
]
```

### 9.3 Meso View: Projects and Notes

For thread-level context and project overviews.

```python
async def meso_search(
    driver: AsyncDriver,
    query: str,
    island_filter: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Meso-level retrieval: Get Project and Note context.

    Use for:
    - "What's the status of the Q1 budget?"
    - "What have I discussed about the marketing campaign?"
    - "What are my current projects?"
    """
    island_clause = ""
    if island_filter:
        island_clause = "AND (proj)-[:PART_OF_ISLAND]->(:Community {name: $island_filter})"

    async with driver.session() as session:
        # Vector search for relevant notes
        note_result = await session.run(
            f"""
            CALL db.index.vector.queryNodes('note_vector', $limit, $query_embedding)
            YIELD node, score
            WHERE score > 0.7

            // Get project connections
            OPTIONAL MATCH (node)-[:DISCUSSED]->(proj:Project)
            {island_clause}

            // Get related persons
            OPTIONAL MATCH (node)<-[:MENTIONED_IN]-(person:Person)

            // Get goal alignment
            OPTIONAL MATCH (proj)-[:CONTRIBUTES_TO]->(goal:Goal)

            RETURN node.uuid as note_uuid,
                   node.title as note_title,
                   node.content_summarized as summary,
                   node.created_at as created_at,
                   score,
                   collect(DISTINCT proj.name) as related_projects,
                   collect(DISTINCT person.name) as mentioned_persons,
                   collect(DISTINCT goal.description) as aligned_goals
            ORDER BY score DESC
            """,
            {
                "query_embedding": await get_embedding(query),
                "limit": limit,
                "island_filter": island_filter
            }
        )
        return await note_result.data()

async def get_project_context(
    driver: AsyncDriver,
    project_uuid: str
) -> Dict[str, Any]:
    """Get comprehensive meso-level context for a project"""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Project {uuid: $project_uuid})

            // Get goal alignment
            OPTIONAL MATCH (p)-[:CONTRIBUTES_TO]->(g:Goal)

            // Get related notes
            OPTIONAL MATCH (n:Note)-[:DISCUSSED]->(p)

            // Get tasks
            OPTIONAL MATCH (t:Task)-[:PART_OF]->(p)

            // Get involved persons
            OPTIONAL MATCH (person:Person)-[:MENTIONED_IN]->(n)
            WHERE (n)-[:DISCUSSED]->(p)

            // Get community/island
            OPTIONAL MATCH (p)-[:PART_OF_ISLAND]->(c:Community)

            RETURN p.name as project_name,
                   p.status as status,
                   p.deadline as deadline,
                   g.description as goal,
                   c.name as island,
                   collect(DISTINCT {
                     title: n.title,
                     summary: n.content_summarized,
                     date: n.created_at
                   })[0..5] as recent_notes,
                   collect(DISTINCT {
                     action: t.action,
                     status: t.status,
                     priority: t.priority
                   }) as tasks,
                   collect(DISTINCT person.name) as key_persons
            """,
            {"project_uuid": project_uuid}
        )
        return await result.single()
```

### 9.4 Micro View: Entities and Episodes

For precise fact retrieval and specific entity queries.

```python
async def micro_search(
    driver: AsyncDriver,
    query: str,
    entity_type: Optional[str] = None,
    include_historical: bool = False
) -> List[Dict[str, Any]]:
    """
    Micro-level retrieval: Get specific Entity facts and Episodes.

    Use for:
    - "When did Sarah change jobs?"
    - "What's John's email address?"
    - "Who reported the bug last Tuesday?"
    """
    temporal_clause = "" if include_historical else "WHERE r.expired_at IS NULL"
    type_clause = f"AND n:{entity_type}" if entity_type else ""

    async with driver.session() as session:
        result = await session.run(
            f"""
            // Vector search for entry point
            CALL db.index.vector.queryNodes('entity_vector', 10, $query_embedding)
            YIELD node as n, score
            WHERE score > 0.6 {type_clause}

            // Get all current relationships
            OPTIONAL MATCH (n)-[r]-(related)
            {temporal_clause}

            RETURN n.uuid as entity_uuid,
                   labels(n)[0] as entity_type,
                   properties(n) as entity_properties,
                   score,
                   collect(DISTINCT {{
                     relationship: type(r),
                     target: properties(related),
                     target_type: labels(related)[0],
                     created_at: r.created_at,
                     expired_at: r.expired_at
                   }}) as relationships
            ORDER BY score DESC
            """,
            {"query_embedding": await get_embedding(query)}
        )
        return await result.data()

async def get_entity_timeline(
    driver: AsyncDriver,
    entity_uuid: str
) -> List[Dict[str, Any]]:
    """Get chronological history of an entity's relationships"""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {uuid: $entity_uuid})-[r]-(related)
            RETURN type(r) as relationship,
                   labels(related)[0] as related_type,
                   related.name as related_name,
                   r.created_at as started,
                   r.expired_at as ended,
                   properties(r) as relationship_props
            ORDER BY r.created_at DESC
            """,
            {"entity_uuid": entity_uuid}
        )
        return await result.data()
```

### 9.5 Automatic Zoom Level Selection

The Researcher agent automatically selects the appropriate zoom level based on query analysis.

```python
class ZoomLevelSelector:
    """Automatically selects appropriate retrieval zoom level"""

    MACRO_INDICATORS = [
        "overview", "summary", "themes", "big picture",
        "main areas", "life", "everything", "all"
    ]

    MESO_INDICATORS = [
        "project", "status", "progress", "discussed",
        "meeting", "notes", "recent", "working on"
    ]

    MICRO_INDICATORS = [
        "who", "what", "when", "where", "exactly",
        "specific", "email", "phone", "address", "date"
    ]

    def select_zoom_level(self, query: str) -> str:
        """
        Analyze query to determine optimal zoom level.

        Returns: 'macro', 'meso', or 'micro'
        """
        query_lower = query.lower()

        # Count indicators
        macro_score = sum(1 for i in self.MACRO_INDICATORS if i in query_lower)
        meso_score = sum(1 for i in self.MESO_INDICATORS if i in query_lower)
        micro_score = sum(1 for i in self.MICRO_INDICATORS if i in query_lower)

        # Question words tend toward micro
        if query.startswith(("Who ", "When ", "What is", "What's")):
            micro_score += 2

        # Determine level
        if macro_score > meso_score and macro_score > micro_score:
            return "macro"
        elif meso_score > micro_score:
            return "meso"
        else:
            return "micro"

    async def search(
        self,
        driver: AsyncDriver,
        graphiti: GraphitiClient,
        query: str,
        captain_uuid: str
    ) -> Dict[str, Any]:
        """Execute search at automatically selected zoom level"""
        level = self.select_zoom_level(query)

        if level == "macro":
            results = await macro_search(driver, captain_uuid)
            return {"level": "macro", "islands": results}

        elif level == "meso":
            results = await meso_search(driver, query)
            return {"level": "meso", "notes_and_projects": results}

        else:  # micro
            # Combine Graphiti search with entity lookup
            facts = await graphiti.search(query, limit=10)
            entities = await micro_search(driver, query)
            return {"level": "micro", "facts": facts, "entities": entities}
```

---

## 10. Community Detection Integration

### 10.1 Knowledge Islands

Communities (Knowledge Islands) are clusters of highly related nodes representing major life themes. They're detected algorithmically and maintained by the Cartographer agent.

```cypher
// Community Node Structure
CREATE (c:Community {
    uuid: 'comm-work-001',
    name: 'Work Island',
    theme: 'professional',
    summary: 'Professional activities, career, and work relationships',
    node_count: 247,
    modularity_score: 0.72,
    detected_at: timestamp(),
    last_updated: timestamp()
})
```

### 10.2 Community Detection via Neo4j GDS

```python
async def detect_communities(driver: AsyncDriver) -> Dict[str, Any]:
    """
    Run Louvain community detection on the knowledge graph.

    Called by Cartographer agent on schedule.
    """
    async with driver.session() as session:
        # Create in-memory graph projection
        await session.run(
            """
            CALL gds.graph.project(
                'klabautermann-graph',
                ['Person', 'Organization', 'Project', 'Note', 'Goal', 'Task', 'Hobby', 'Pet'],
                {
                    WORKS_AT: {orientation: 'UNDIRECTED'},
                    KNOWS: {orientation: 'UNDIRECTED'},
                    MENTIONED_IN: {orientation: 'UNDIRECTED'},
                    PART_OF: {orientation: 'UNDIRECTED'},
                    CONTRIBUTES_TO: {orientation: 'UNDIRECTED'},
                    PRACTICES: {orientation: 'UNDIRECTED'},
                    FAMILY_OF: {orientation: 'UNDIRECTED'},
                    FRIEND_OF: {orientation: 'UNDIRECTED'}
                }
            )
            """
        )

        # Run Louvain algorithm
        result = await session.run(
            """
            CALL gds.louvain.stream('klabautermann-graph')
            YIELD nodeId, communityId
            RETURN gds.util.asNode(nodeId).uuid AS nodeUuid,
                   labels(gds.util.asNode(nodeId))[0] AS nodeType,
                   communityId
            """
        )

        community_assignments = await result.data()

        # Cleanup projection
        await session.run("CALL gds.graph.drop('klabautermann-graph')")

        return community_assignments

async def create_community_nodes(
    driver: AsyncDriver,
    community_assignments: List[Dict[str, Any]]
) -> List[str]:
    """
    Create or update Community nodes from detection results.
    """
    # Group by community
    communities = {}
    for assignment in community_assignments:
        comm_id = assignment['communityId']
        if comm_id not in communities:
            communities[comm_id] = []
        communities[comm_id].append(assignment)

    created_communities = []

    async with driver.session() as session:
        for comm_id, members in communities.items():
            # Analyze community theme based on member types
            theme = await _infer_community_theme(members)

            # Create or update community node
            result = await session.run(
                """
                MERGE (c:Community {external_id: $comm_id})
                ON CREATE SET
                    c.uuid = randomUUID(),
                    c.detected_at = timestamp()
                SET c.name = $name,
                    c.theme = $theme,
                    c.node_count = $node_count,
                    c.last_updated = timestamp()
                RETURN c.uuid as uuid
                """,
                {
                    "comm_id": str(comm_id),
                    "name": f"{theme.title()} Island",
                    "theme": theme,
                    "node_count": len(members)
                }
            )

            record = await result.single()
            community_uuid = record['uuid']
            created_communities.append(community_uuid)

            # Link members to community
            member_uuids = [m['nodeUuid'] for m in members]
            await session.run(
                """
                MATCH (c:Community {uuid: $community_uuid})
                UNWIND $member_uuids as member_uuid
                MATCH (m {uuid: member_uuid})
                MERGE (m)-[:PART_OF_ISLAND]->(c)
                """,
                {"community_uuid": community_uuid, "member_uuids": member_uuids}
            )

    return created_communities

async def _infer_community_theme(members: List[Dict[str, Any]]) -> str:
    """Infer theme based on predominant node types"""
    type_counts = {}
    for m in members:
        node_type = m['nodeType']
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    # Theme inference rules
    if type_counts.get('Organization', 0) + type_counts.get('Project', 0) > len(members) * 0.3:
        return 'work'
    elif type_counts.get('Hobby', 0) > len(members) * 0.2:
        return 'hobbies'
    elif type_counts.get('HealthMetric', 0) > len(members) * 0.2:
        return 'health'
    elif type_counts.get('Pet', 0) > 0:
        return 'family'
    else:
        return 'general'
```

### 10.3 Island Summary Generation

```python
async def generate_island_summary(
    driver: AsyncDriver,
    llm_client,
    community_uuid: str
) -> str:
    """
    Generate human-readable summary of a Knowledge Island.

    Called by Scribe during reflection, delegated from Cartographer.
    """
    async with driver.session() as session:
        # Get island members and their key facts
        result = await session.run(
            """
            MATCH (c:Community {uuid: $community_uuid})<-[:PART_OF_ISLAND]-(member)
            WITH c, member
            ORDER BY member.updated_at DESC
            LIMIT 50

            // Get key facts about members
            OPTIONAL MATCH (member)-[r]-(related)
            WHERE r.expired_at IS NULL

            RETURN c.name as island_name,
                   c.theme as theme,
                   collect(DISTINCT {
                     type: labels(member)[0],
                     name: member.name,
                     relationship: type(r),
                     related_to: related.name
                   })[0..20] as sample_facts
            """,
            {"community_uuid": community_uuid}
        )

        record = await result.single()

    # Generate summary via LLM
    prompt = f"""Summarize this Knowledge Island in 2-3 sentences.

Island: {record['island_name']}
Theme: {record['theme']}
Sample contents: {json.dumps(record['sample_facts'], indent=2)}

Write a concise, informative summary of what this island represents in the Captain's life."""

    response = await llm_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )

    summary = response.content[0].text

    # Store summary back on community node
    async with driver.session() as session:
        await session.run(
            """
            MATCH (c:Community {uuid: $uuid})
            SET c.summary = $summary,
                c.summary_generated_at = timestamp()
            """,
            {"uuid": community_uuid, "summary": summary}
        )

    return summary
```

### 10.4 Researcher Integration

The Researcher agent uses communities for "executive summaries" when responding to broad questions.

```python
class ResearcherWithCommunities:
    """Researcher enhanced with community-aware retrieval"""

    async def search_with_community_context(
        self,
        query: str,
        captain_uuid: str
    ) -> Dict[str, Any]:
        """
        Search that includes community context for broader understanding.
        """
        # Detect if this is a broad vs specific query
        zoom_selector = ZoomLevelSelector()
        level = zoom_selector.select_zoom_level(query)

        results = {
            "zoom_level": level,
            "direct_results": [],
            "community_context": None
        }

        # Always get direct results
        direct = await self.graphiti.search(query, limit=10)
        results["direct_results"] = direct

        # For macro/meso queries, include community context
        if level in ["macro", "meso"]:
            async with self.driver.session() as session:
                # Find which communities the results belong to
                result_uuids = [r.uuid for r in direct]

                comm_result = await session.run(
                    """
                    UNWIND $result_uuids as uuid
                    MATCH (n {uuid: uuid})-[:PART_OF_ISLAND]->(c:Community)
                    RETURN DISTINCT c.name as island, c.summary as summary,
                           count(n) as result_count
                    ORDER BY result_count DESC
                    """,
                    {"result_uuids": result_uuids}
                )

                communities = await comm_result.data()
                results["community_context"] = communities

        return results
```

---

## 11. Parallel Memory for Bard

### 11.1 Separate Memory Space

The Bard of the Bilge maintains a separate memory pattern from task-oriented retrieval. While the Researcher queries facts and entities, the Bard queries narrative episodes and saga progress.

```
┌─────────────────────────────────────────────────────────────────┐
│                    PARALLEL MEMORY PATTERNS                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────┐    ┌─────────────────────────┐    │
│  │  TASK MEMORY            │    │  LORE MEMORY            │    │
│  │  (Researcher)           │    │  (Bard)                 │    │
│  ├─────────────────────────┤    ├─────────────────────────┤    │
│  │ - Entity facts          │    │ - LoreEpisode nodes     │    │
│  │ - Project status        │    │ - Saga progress         │    │
│  │ - Task chains           │    │ - Story continuity      │    │
│  │ - Temporal queries      │    │ - Captain preferences   │    │
│  └─────────────────────────┘    └─────────────────────────┘    │
│                                                                 │
│  Links via: Thread, Person      Links via: Person (Captain)    │
│  Context: Thread-bound          Context: Captain-bound         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 LoreEpisode Retrieval

```python
class LoreMemory:
    """Memory interface for the Bard of the Bilge"""

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def get_active_sagas(self, captain_uuid: str) -> List[Dict[str, Any]]:
        """
        Get all sagas with unfinished chapters for this Captain.

        Note: Queries by Captain (Person), NOT by Thread.
        This enables cross-conversation, cross-channel continuity.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})<-[:TOLD_TO]-(le:LoreEpisode)
                WHERE le.saga_completed = false OR le.saga_completed IS NULL

                // Get the latest chapter for each saga
                WITH le.saga_id as saga_id, max(le.chapter) as max_chapter
                MATCH (captain)<-[:TOLD_TO]-(latest:LoreEpisode {
                    saga_id: saga_id,
                    chapter: max_chapter
                })

                // Check saga age (timeout after 30 days)
                WHERE latest.told_at > timestamp() - 30*24*60*60*1000

                RETURN latest.saga_id as saga_id,
                       latest.saga_name as saga_name,
                       latest.chapter as current_chapter,
                       latest.content as last_content,
                       latest.told_at as last_told,
                       latest.channel as last_channel
                ORDER BY latest.told_at DESC
                """,
                {"captain_uuid": captain_uuid}
            )
            return await result.data()

    async def get_saga_history(
        self,
        captain_uuid: str,
        saga_id: str
    ) -> List[Dict[str, Any]]:
        """Get full history of a specific saga"""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})<-[:TOLD_TO]-(le:LoreEpisode)
                WHERE le.saga_id = $saga_id
                RETURN le.chapter as chapter,
                       le.content as content,
                       le.told_at as told_at,
                       le.channel as channel
                ORDER BY le.chapter ASC
                """,
                {"captain_uuid": captain_uuid, "saga_id": saga_id}
            )
            return await result.data()

    async def add_episode(
        self,
        captain_uuid: str,
        saga_id: str,
        saga_name: str,
        chapter: int,
        content: str,
        channel: str
    ) -> str:
        """
        Add a new episode to a saga.

        Links to Captain (not Thread) for cross-channel continuity.
        """
        episode_uuid = str(uuid.uuid4())

        async with self.driver.session() as session:
            # Create episode and link to Captain
            await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})

                CREATE (le:LoreEpisode {
                    uuid: $episode_uuid,
                    saga_id: $saga_id,
                    saga_name: $saga_name,
                    chapter: $chapter,
                    content: $content,
                    channel: $channel,
                    told_at: timestamp(),
                    created_at: timestamp(),
                    saga_completed: false
                })

                CREATE (le)-[:TOLD_TO]->(captain)

                // Link to previous chapter if exists
                WITH le, captain
                OPTIONAL MATCH (captain)<-[:TOLD_TO]-(prev:LoreEpisode)
                WHERE prev.saga_id = $saga_id
                  AND prev.chapter = $chapter - 1

                FOREACH (p IN CASE WHEN prev IS NOT NULL THEN [prev] ELSE [] END |
                    CREATE (le)-[:EXPANDS_UPON]->(p)
                )
                """,
                {
                    "captain_uuid": captain_uuid,
                    "episode_uuid": episode_uuid,
                    "saga_id": saga_id,
                    "saga_name": saga_name,
                    "chapter": chapter,
                    "content": content,
                    "channel": channel
                }
            )

        return episode_uuid

    async def complete_saga(self, captain_uuid: str, saga_id: str):
        """Mark a saga as completed"""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})<-[:TOLD_TO]-(le:LoreEpisode)
                WHERE le.saga_id = $saga_id
                SET le.saga_completed = true
                """,
                {"captain_uuid": captain_uuid, "saga_id": saga_id}
            )

    async def get_captain_story_preferences(
        self,
        captain_uuid: str
    ) -> Dict[str, Any]:
        """
        Get Captain's story engagement patterns.

        Used by Bard to personalize story selection.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})<-[:TOLD_TO]-(le:LoreEpisode)

                // Count sagas and chapters
                WITH captain,
                     count(DISTINCT le.saga_id) as total_sagas,
                     count(le) as total_chapters

                // Find favorite saga themes (most chapters heard)
                MATCH (captain)<-[:TOLD_TO]-(le2:LoreEpisode)
                WITH captain, total_sagas, total_chapters,
                     le2.saga_id as saga, count(le2) as saga_chapters
                ORDER BY saga_chapters DESC
                LIMIT 3

                RETURN total_sagas,
                       total_chapters,
                       collect({saga: saga, chapters: saga_chapters}) as favorite_sagas
                """,
                {"captain_uuid": captain_uuid}
            )
            return await result.single()

    async def get_recent_lore_for_scribe(
        self,
        captain_uuid: str,
        since_timestamp: float
    ) -> List[Dict[str, Any]]:
        """
        Get lore episodes since last reflection.

        Used by Scribe during midnight reflection to include
        saga progress in the journal.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (captain:Person {uuid: $captain_uuid})<-[:TOLD_TO]-(le:LoreEpisode)
                WHERE le.told_at >= $since_timestamp
                RETURN le.saga_name as saga,
                       le.chapter as chapter,
                       le.content as content,
                       le.channel as channel,
                       le.told_at as told_at
                ORDER BY le.told_at ASC
                """,
                {"captain_uuid": captain_uuid, "since_timestamp": since_timestamp}
            )
            return await result.data()
```

### 11.3 Cross-Channel Saga Continuity

The key difference from task memory: stories follow the **Person** (Captain), not the **Thread**. This enables:

```python
# CLI Session
bard.continue_saga("the-great-maelstrom", chapter=3)
# Captain hears Chapter 3 in CLI

# ... hours later ...

# Telegram Session (same Captain)
active_sagas = await lore_memory.get_active_sagas(captain_uuid)
# Returns: [{"saga_id": "the-great-maelstrom", "chapter": 3, ...}]

# Bard can continue the story in Telegram
bard.continue_saga("the-great-maelstrom", chapter=4)
# Captain hears Chapter 4 in Telegram
```

### 11.4 Integration with Scribe Reflection

```python
async def generate_reflection_with_lore(
    scribe,
    captain_uuid: str,
    day_date: str
) -> str:
    """
    Generate daily reflection that includes lore progress.

    The Scribe weaves saga progress into the journal entry.
    """
    # Get task-based reflection
    task_summary = await scribe.generate_task_summary(captain_uuid, day_date)

    # Get lore progress from parallel memory
    lore_memory = LoreMemory(scribe.driver)
    day_start = datetime.strptime(day_date, "%Y-%m-%d").timestamp() * 1000
    lore_episodes = await lore_memory.get_recent_lore_for_scribe(
        captain_uuid,
        day_start
    )

    if lore_episodes:
        # Generate lore summary
        lore_summary = _format_lore_progress(lore_episodes)

        # Combine into unified reflection
        return f"""{task_summary}

---

**From the Ship's Tales**

{lore_summary}"""

    return task_summary

def _format_lore_progress(episodes: List[Dict[str, Any]]) -> str:
    """Format lore episodes for journal inclusion"""
    saga_progress = {}
    for ep in episodes:
        saga = ep['saga']
        if saga not in saga_progress:
            saga_progress[saga] = []
        saga_progress[saga].append(ep['chapter'])

    lines = []
    for saga, chapters in saga_progress.items():
        if len(chapters) == 1:
            lines.append(f"- Heard Chapter {chapters[0]} of _{saga}_")
        else:
            lines.append(f"- Heard Chapters {min(chapters)}-{max(chapters)} of _{saga}_")

    return "\n".join(lines)
```

### 11.5 Query Pattern Comparison

| Aspect | Task Memory (Researcher) | Lore Memory (Bard) |
|--------|--------------------------|-------------------|
| **Context Anchor** | Thread UUID | Captain UUID |
| **Primary Query** | "What facts relate to X?" | "What story was I telling?" |
| **Temporal Focus** | Point-in-time queries | Narrative continuity |
| **Cross-Channel** | Thread is channel-bound | Stories transcend channels |
| **Relationships** | Entity facts, edges | `[:EXPANDS_UPON]`, `[:TOLD_TO]` |
| **Retrieval Trigger** | User query | Response "salting" (5-10%) |

---

*"The Locker holds all memories, past and present, waiting to guide your voyage."* - Klabautermann
