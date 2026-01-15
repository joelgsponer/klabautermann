# Klabautermann Graph Ontology

**Version**: 1.0
**Purpose**: Complete schema definition for the temporal knowledge graph

---

## Overview

The Klabautermann ontology defines the structure of the knowledge graph—the types of **nodes** (entities), **relationships** (edges), and **properties** that form the "second brain." This schema is designed for:

1. **Semantic Richness**: Capture the full context of your life (who, what, when, where, why)
2. **Temporal Awareness**: Every fact has a timeline; nothing is ever truly deleted
3. **Query Efficiency**: Indexes and constraints optimized for common access patterns
4. **Agentic Use**: Schema understood by AI agents for extraction and reasoning

---

## 1. Entity Types (Nodes)

### 1.1 Core Entities

#### Person
Human contacts—colleagues, friends, family, acquaintances.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier (UUID v4) |
| `name` | String | Yes | Full name |
| `email` | String | No | Primary email address |
| `phone` | String | No | Phone number |
| `bio` | String | No | Short description / notes |
| `linkedin_url` | String | No | LinkedIn profile URL |
| `twitter_handle` | String | No | Twitter/X handle |
| `avatar_url` | String | No | Profile picture URL |
| `vector_embedding` | Float[] | No | Semantic embedding for similarity search |
| `created_at` | Float | Yes | Unix timestamp of creation |
| `updated_at` | Float | Yes | Unix timestamp of last update |

**Constraints**:
- `uuid` must be unique
- `name` must not be null

**Indexes**:
- Full-text on `name`, `email`
- Vector index on `vector_embedding`

---

#### Organization
Companies, non-profits, clubs, institutions, or any group entity.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Organization name |
| `industry` | String | No | Industry/sector |
| `website` | String | No | Primary website URL |
| `domain` | String | No | Email domain (e.g., "acme.com") |
| `description` | String | No | Brief description |
| `logo_url` | String | No | Logo image URL |
| `vector_embedding` | Float[] | No | Semantic embedding |
| `created_at` | Float | Yes | Creation timestamp |
| `updated_at` | Float | Yes | Last update timestamp |

**Constraints**:
- `uuid` must be unique
- `name` must not be null

---

#### Project
Goal-oriented endeavors with defined scope and (usually) an end date.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Project name |
| `description` | String | No | Project description |
| `status` | String | Yes | One of: `active`, `on_hold`, `completed`, `cancelled` |
| `deadline` | Float | No | Target completion timestamp |
| `priority` | String | No | `high`, `medium`, `low` |
| `vector_embedding` | Float[] | No | Semantic embedding |
| `created_at` | Float | Yes | Creation timestamp |
| `updated_at` | Float | Yes | Last update timestamp |

**Constraints**:
- `uuid` must be unique
- `status` must be one of the allowed values

---

#### Goal
High-level objectives—the "why" behind projects and tasks.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `description` | String | Yes | Goal description |
| `timeframe` | String | No | Target timeframe (e.g., "Q1 2026", "2026") |
| `status` | String | Yes | `active`, `achieved`, `abandoned` |
| `category` | String | No | `personal`, `professional`, `health`, `financial`, etc. |
| `created_at` | Float | Yes | Creation timestamp |
| `updated_at` | Float | Yes | Last update timestamp |

---

#### Task
Atomic actionable items—discrete units of work.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `action` | String | Yes | Task description (verb + object) |
| `status` | String | Yes | `todo`, `in_progress`, `done`, `cancelled` |
| `priority` | String | No | `urgent`, `high`, `medium`, `low` |
| `due_date` | Float | No | Due timestamp |
| `completed_at` | Float | No | Completion timestamp |
| `created_at` | Float | Yes | Creation timestamp |
| `updated_at` | Float | Yes | Last update timestamp |

---

#### Event
Meetings, calls, appointments, or any time-bound occurrence.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `title` | String | Yes | Event title |
| `description` | String | No | Event details |
| `start_time` | Float | Yes | Start timestamp |
| `end_time` | Float | No | End timestamp |
| `location_context` | String | No | Text description of location |
| `is_recurring` | Boolean | No | Whether this is a recurring event |
| `calendar_id` | String | No | External calendar event ID |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Location
Physical places—offices, cafes, cities, addresses.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Location name |
| `address` | String | No | Full address |
| `coordinate` | Point | No | Neo4j Point (latitude, longitude) |
| `place_id` | String | No | Google Maps place ID |
| `type` | String | No | `office`, `home`, `cafe`, `city`, `venue`, etc. |
| `created_at` | Float | Yes | Creation timestamp |

**Special**:
- `coordinate` uses Neo4j's native Point type for geospatial queries

---

#### Note
Knowledge artifacts—thoughts, summaries, captured information.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `title` | String | No | Note title |
| `content` | String | No | Full content (if short) |
| `content_summarized` | String | No | AI-generated summary |
| `content_format` | String | No | `markdown`, `text`, `voice_transcript` |
| `source` | String | No | Where the note came from |
| `vector_embedding` | Float[] | No | Semantic embedding |
| `requires_user_validation` | Boolean | No | Flag for ambiguous content |
| `created_at` | Float | Yes | Creation timestamp |
| `updated_at` | Float | Yes | Last update timestamp |

---

#### Resource
External links, files, attachments—anything with a URL or path.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `url` | String | Yes | Resource URL or file path |
| `title` | String | No | Resource title |
| `type` | String | No | `bookmark`, `pdf`, `email`, `image`, `video`, `document` |
| `description` | String | No | Brief description |
| `vector_embedding` | Float[] | No | Semantic embedding |
| `created_at` | Float | Yes | Creation timestamp |

---

### 1.2 Personal Life Entities

#### Hobby
Leisure activities and interests.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Hobby name (e.g., "Rock Climbing", "Piano") |
| `category` | String | No | `sport`, `music`, `craft`, `gaming`, `outdoor`, `creative`, etc. |
| `frequency` | String | No | `daily`, `weekly`, `monthly`, `occasional` |
| `skill_level` | String | No | `beginner`, `intermediate`, `advanced`, `expert` |
| `started_at` | Float | No | When this hobby was started |
| `description` | String | No | Additional notes |
| `created_at` | Float | Yes | Creation timestamp |

---

#### HealthMetric
Wellness and health tracking data points.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `type` | String | Yes | `weight`, `blood_pressure`, `steps`, `sleep`, `mood`, `exercise`, etc. |
| `value` | Float | Yes | Numeric value |
| `unit` | String | Yes | Unit of measurement (kg, bpm, hours, etc.) |
| `secondary_value` | Float | No | For compound metrics (e.g., diastolic in blood pressure) |
| `notes` | String | No | Additional context |
| `recorded_at` | Float | Yes | When the measurement was taken |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Pet
Animal companions.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Pet's name |
| `species` | String | Yes | `dog`, `cat`, `bird`, `fish`, `rabbit`, etc. |
| `breed` | String | No | Specific breed |
| `birthday` | Float | No | Birth date timestamp |
| `adoption_date` | Float | No | When the pet joined the family |
| `notes` | String | No | Personality, preferences, medical notes |
| `avatar_url` | String | No | Pet photo URL |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Milestone
Personal achievements and life events.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Milestone name |
| `description` | String | No | Details about the achievement |
| `category` | String | No | `career`, `education`, `personal`, `relationship`, `health`, `financial` |
| `achieved_at` | Float | Yes | When the milestone was reached |
| `significance` | String | No | `minor`, `moderate`, `major`, `life_changing` |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Routine
Recurring personal activities and habits.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Routine name (e.g., "Morning Run", "Weekly Review") |
| `description` | String | No | What the routine involves |
| `frequency` | String | Yes | `daily`, `weekly`, `monthly`, `weekdays`, `weekends` |
| `time_of_day` | String | No | `morning`, `afternoon`, `evening`, `night` |
| `duration_minutes` | Integer | No | Typical duration |
| `days` | String | No | Specific days (e.g., "Mon,Wed,Fri") |
| `is_active` | Boolean | Yes | Whether routine is currently active |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Preference
Personal likes, dislikes, and preferences.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `category` | String | Yes | `food`, `music`, `travel`, `work_style`, `communication`, etc. |
| `item` | String | Yes | The specific preference (e.g., "Italian food", "Morning meetings") |
| `sentiment` | String | Yes | `likes`, `dislikes`, `prefers`, `avoids` |
| `strength` | Float | No | Preference strength (0.0-1.0) |
| `context` | String | No | When this preference applies |
| `created_at` | Float | Yes | Creation timestamp |

---

#### Community
Knowledge Islands—clusters of highly related nodes representing life themes.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `name` | String | Yes | Island name (e.g., "Work Life", "Family", "Hobbies") |
| `theme` | String | Yes | `professional`, `family`, `social`, `health`, `hobbies`, `finance` |
| `summary` | String | No | High-level description of this knowledge area |
| `node_count` | Integer | No | Number of nodes in this community |
| `detected_at` | Float | No | When community was detected/created |
| `last_updated` | Float | No | Last summary update |
| `created_at` | Float | Yes | Creation timestamp |

**Note**: Communities are created by the Cartographer agent using community detection algorithms.

---

#### LoreEpisode
Story chapters from Klabautermann's adventures (progressive storytelling).

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `saga_id` | String | Yes | Identifier for the saga this belongs to |
| `saga_name` | String | Yes | Human-readable saga name |
| `chapter` | Integer | Yes | Chapter number within the saga |
| `content` | String | Yes | The story content |
| `told_at` | Float | Yes | When this chapter was told |
| `channel` | String | No | Channel where told (`cli`, `telegram`) |
| `created_at` | Float | Yes | Creation timestamp |

**Note**: LoreEpisodes are managed by the Bard of the Bilge agent and form a parallel memory system.

---

### 1.3 System Entities

#### Thread
Conversation threads—containers for messages within a channel.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `external_id` | String | Yes | Platform-specific ID (chat_id, session_id) |
| `channel_type` | String | Yes | `cli`, `telegram`, `discord` |
| `user_id` | String | No | Platform user identifier |
| `status` | String | Yes | `active`, `archiving`, `archived` |
| `created_at` | Float | Yes | Creation timestamp |
| `last_message_at` | Float | Yes | Last message timestamp |

---

#### Message
Individual messages within a thread.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `role` | String | Yes | `user` or `assistant` |
| `content` | String | Yes | Message text |
| `timestamp` | Float | Yes | Message timestamp |
| `metadata` | String | No | JSON string of additional data |

---

#### Day
Calendar day nodes forming the "temporal spine."

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `date` | String | Yes | ISO date (YYYY-MM-DD) |
| `day_of_week` | String | No | Monday, Tuesday, etc. |
| `is_weekend` | Boolean | No | Weekend flag |
| `is_holiday` | Boolean | No | Holiday flag |

**Note**: Day nodes are created automatically when events or journal entries are linked.

---

#### JournalEntry
Daily reflections generated by the Scribe agent.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `uuid` | String | Yes | Unique identifier |
| `content` | String | Yes | Journal content (Klabautermann voice) |
| `summary` | String | No | One-line summary |
| `interaction_count` | Integer | No | Number of interactions that day |
| `new_entities_count` | Integer | No | New nodes created |
| `tasks_completed` | Integer | No | Tasks marked done |
| `generated_at` | Float | Yes | Generation timestamp |

---

## 2. Relationship Types (Edges)

### 2.1 Professional Context

#### WORKS_AT
Links a Person to their Organization (employer).

```cypher
(Person)-[:WORKS_AT {title, department, created_at, expired_at}]->(Organization)
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `title` | String | No | Job title |
| `department` | String | No | Department name |
| `created_at` | Float | Yes | When employment started |
| `expired_at` | Float | No | When employment ended (null = current) |

**Temporal**: Yes—tracks job history

---

#### REPORTS_TO
Hierarchical relationship between Persons.

```cypher
(Person)-[:REPORTS_TO {created_at, expired_at}]->(Person)
```

**Temporal**: Yes—tracks reporting structure changes

---

#### AFFILIATED_WITH
Non-employment relationship with Organization (advisor, board member, investor).

```cypher
(Person)-[:AFFILIATED_WITH {role, created_at, expired_at}]->(Organization)
```

---

### 2.2 Action Hierarchy

#### CONTRIBUTES_TO
Links Projects to Goals—the "why" connection.

```cypher
(Project)-[:CONTRIBUTES_TO {weight, created_at}]->(Goal)
```

| Property | Type | Description |
|----------|------|-------------|
| `weight` | Float | Contribution strength (0.0-1.0) |

---

#### PART_OF
Links Tasks to Projects, or sub-projects to parent projects.

```cypher
(Task)-[:PART_OF {created_at}]->(Project)
(Project)-[:PART_OF {created_at}]->(Project)
```

---

#### SUBTASK_OF
Links Tasks to parent Tasks.

```cypher
(Task)-[:SUBTASK_OF]->(Task)
```

---

#### BLOCKS
Indicates Task A blocks Task B from proceeding.

```cypher
(Task)-[:BLOCKS {reason, created_at}]->(Task)
```

---

#### DEPENDS_ON
Indicates Task A depends on Task B completing first.

```cypher
(Task)-[:DEPENDS_ON {reason, created_at}]->(Task)
```

---

#### ASSIGNED_TO
Links Tasks to responsible Persons.

```cypher
(Task)-[:ASSIGNED_TO {created_at}]->(Person)
```

---

### 2.3 Spatial Context

#### HELD_AT
Links Events to Locations.

```cypher
(Event)-[:HELD_AT]->(Location)
```

---

#### LOCATED_IN
Person's home or office location.

```cypher
(Person)-[:LOCATED_IN {type, created_at, expired_at}]->(Location)
```

| Property | Type | Description |
|----------|------|-------------|
| `type` | String | `home`, `office`, `current` |

**Temporal**: Yes—tracks location changes

---

#### CREATED_AT_LOCATION
Where a Note was created.

```cypher
(Note)-[:CREATED_AT_LOCATION]->(Location)
```

---

### 2.4 Knowledge Linking

#### REFERENCES
Note or Resource references another Resource.

```cypher
(Note)-[:REFERENCES]->(Resource)
(Resource)-[:REFERENCES]->(Resource)
```

---

#### SUMMARIZES
Note summarizes an Event or Thread.

```cypher
(Note)-[:SUMMARIZES]->(Event)
(Note)-[:SUMMARY_OF]->(Thread)
```

---

#### MENTIONED_IN
Person or Organization mentioned in a Note or Event.

```cypher
(Person)-[:MENTIONED_IN]->(Note)
(Organization)-[:MENTIONED_IN]->(Event)
```

---

#### DISCUSSED
Event discussed a Project, Task, or Goal.

```cypher
(Event)-[:DISCUSSED]->(Project)
(Event)-[:DISCUSSED]->(Task)
(Event)-[:DISCUSSED]->(Goal)
```

---

### 2.5 Event Context

#### ATTENDED
Person attended an Event.

```cypher
(Person)-[:ATTENDED {role}]->(Event)
```

| Property | Type | Description |
|----------|------|-------------|
| `role` | String | `organizer`, `attendee`, `speaker`, `observer` |

---

#### ORGANIZED_BY
Event organized by a Person or Organization.

```cypher
(Event)-[:ORGANIZED_BY]->(Person)
(Event)-[:ORGANIZED_BY]->(Organization)
```

---

### 2.6 Information Lineage

#### VERSION_OF
Resource is a version of another Resource (for tracking edits).

```cypher
(Resource)-[:VERSION_OF {version_number}]->(Resource)
```

---

#### REPLIES_TO
Message or Note is a reply to another.

```cypher
(Note)-[:REPLIES_TO]->(Note)
```

---

#### ATTACHED_TO
Resource attached to an Event or Note.

```cypher
(Resource)-[:ATTACHED_TO]->(Event)
(Resource)-[:ATTACHED_TO]->(Note)
```

---

### 2.7 Interpersonal Context

#### KNOWS
Person knows another Person (general relationship).

```cypher
(Person)-[:KNOWS {context, strength, created_at}]->(Person)
```

| Property | Type | Description |
|----------|------|-------------|
| `context` | String | How they know each other |
| `strength` | Float | Relationship strength (0.0-1.0) |

---

#### INTRODUCED_BY
How two Persons met.

```cypher
(Person)-[:INTRODUCED_BY]->(Person)
```

---

### 2.8 Family & Personal Relationships

#### FAMILY_OF
Generic family relationship between Persons.

```cypher
(Person)-[:FAMILY_OF {role, created_at}]->(Person)
```

| Property | Type | Description |
|----------|------|-------------|
| `role` | String | `spouse`, `parent`, `child`, `sibling`, `grandparent`, `cousin`, `in-law` |

---

#### SPOUSE_OF
Marriage or partnership relationship.

```cypher
(Person)-[:SPOUSE_OF {married_at, created_at, expired_at}]->(Person)
```

| Property | Type | Description |
|----------|------|-------------|
| `married_at` | Float | Wedding/partnership date |

**Temporal**: Yes—tracks relationship status changes

---

#### PARENT_OF
Parent-child relationship.

```cypher
(Person)-[:PARENT_OF {created_at}]->(Person)
```

---

#### CHILD_OF
Child-parent relationship (inverse of PARENT_OF).

```cypher
(Person)-[:CHILD_OF {created_at}]->(Person)
```

---

#### SIBLING_OF
Sibling relationship.

```cypher
(Person)-[:SIBLING_OF {created_at}]->(Person)
```

---

#### FRIEND_OF
Friendship between Persons.

```cypher
(Person)-[:FRIEND_OF {since, how_met, strength, created_at, expired_at}]->(Person)
```

| Property | Type | Description |
|----------|------|-------------|
| `since` | Float | When friendship began |
| `how_met` | String | Context of meeting |
| `strength` | Float | Closeness (0.0-1.0) |

**Temporal**: Yes—friendships can drift apart

---

### 2.9 Personal Life Relationships

#### PRACTICES
Person engages in a Hobby.

```cypher
(Person)-[:PRACTICES {since, frequency, skill_level, created_at, expired_at}]->(Hobby)
```

| Property | Type | Description |
|----------|------|-------------|
| `since` | Float | When they started |
| `frequency` | String | How often they practice |
| `skill_level` | String | Current proficiency |

**Temporal**: Yes—hobbies can be picked up and dropped

---

#### INTERESTED_IN
Person has interest in a Topic or subject.

```cypher
(Person)-[:INTERESTED_IN {strength, since, created_at}]->(Topic)
```

---

#### PREFERS
Person has a stated preference.

```cypher
(Person)-[:PREFERS {created_at}]->(Preference)
```

---

#### OWNS
Person owns a Pet.

```cypher
(Person)-[:OWNS {since, created_at, expired_at}]->(Pet)
```

**Temporal**: Yes—pet ownership changes

---

#### CARES_FOR
Person cares for a Pet (may not be owner).

```cypher
(Person)-[:CARES_FOR {role, created_at}]->(Pet)
```

| Property | Type | Description |
|----------|------|-------------|
| `role` | String | `owner`, `caretaker`, `sitter` |

---

#### RECORDED
Person recorded a health metric.

```cypher
(Person)-[:RECORDED {created_at}]->(HealthMetric)
```

---

#### ACHIEVES
Person achieved a milestone.

```cypher
(Person)-[:ACHIEVES {created_at}]->(Milestone)
```

---

#### FOLLOWS_ROUTINE
Person follows a routine.

```cypher
(Person)-[:FOLLOWS_ROUTINE {started_at, streak, created_at, expired_at}]->(Routine)
```

| Property | Type | Description |
|----------|------|-------------|
| `started_at` | Float | When routine started |
| `streak` | Integer | Current streak count |

**Temporal**: Yes—routines can be started and stopped

---

### 2.10 Community (Knowledge Islands)

#### PART_OF_ISLAND
Links any node to its Knowledge Island (Community).

```cypher
(Person)-[:PART_OF_ISLAND {weight, detected_at}]->(Community)
(Project)-[:PART_OF_ISLAND {weight, detected_at}]->(Community)
(Note)-[:PART_OF_ISLAND {weight, detected_at}]->(Community)
(Hobby)-[:PART_OF_ISLAND {weight, detected_at}]->(Community)
```

| Property | Type | Description |
|----------|------|-------------|
| `weight` | Float | Membership strength (0.0-1.0) |
| `detected_at` | Float | When this membership was detected |

**Note**: Created by the Cartographer agent during community detection.

---

### 2.11 Lore System (Progressive Storytelling)

#### EXPANDS_UPON
Links LoreEpisode chapters in a saga chain.

```cypher
(LoreEpisode)-[:EXPANDS_UPON {created_at}]->(LoreEpisode)
```

**Note**: Creates a linked list of story chapters within a saga.

---

#### TOLD_TO
Links a LoreEpisode to the Captain (Person) it was told to.

```cypher
(LoreEpisode)-[:TOLD_TO {created_at}]->(Person)
```

**Note**: Links stories to the Person (not Thread) for cross-conversation continuity.

---

#### SAGA_STARTED_BY
Indicates who initiated a saga.

```cypher
(LoreEpisode)-[:SAGA_STARTED_BY {created_at}]->(Person)
```

**Note**: Only the first episode of a saga has this relationship.

---

### 2.12 Thread Management

#### CONTAINS
Thread contains Messages.

```cypher
(Thread)-[:CONTAINS]->(Message)
```

---

#### PRECEDES
Sequential linking of Messages within a Thread.

```cypher
(Message)-[:PRECEDES]->(Message)
```

**Note**: Enables efficient "last N messages" queries via chain traversal.

---

#### SUMMARY_OF
Note is a summary of a Thread.

```cypher
(Note)-[:SUMMARY_OF]->(Thread)
```

---

### 2.9 Temporal Spine

#### OCCURRED_ON
Links time-bound entities to their Day.

```cypher
(Event)-[:OCCURRED_ON]->(Day)
(JournalEntry)-[:OCCURRED_ON]->(Day)
(Note)-[:OCCURRED_ON]->(Day)
```

---

### 2.10 Tagging & Categorization

#### TAGGED_WITH
Generic tagging relationship for flexible categorization.

```cypher
(Note)-[:TAGGED_WITH]->(Tag)
(Project)-[:TAGGED_WITH]->(Tag)
(Resource)-[:TAGGED_WITH]->(Tag)
```

**Tag Node**:
| Property | Type | Description |
|----------|------|-------------|
| `name` | String | Tag name (e.g., "AI", "Q1-2026", "urgent") |

---

## 3. Temporal Modeling

### 3.1 Bi-Temporal Pattern

Every temporal relationship has two timestamps:

| Property | Description |
|----------|-------------|
| `created_at` | When the relationship became true (valid time) |
| `expired_at` | When the relationship stopped being true (null = still valid) |

### 3.2 Time-Travel Queries

Query the state of the graph at a specific point in time:

```cypher
// Who did Sarah work for on 2025-06-15?
MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT]->(o:Organization)
WHERE r.created_at <= datetime('2025-06-15').epochMillis
  AND (r.expired_at IS NULL OR r.expired_at > datetime('2025-06-15').epochMillis)
RETURN o.name
```

### 3.3 Relationship Updates

When a relationship changes, don't delete—expire and create new:

```cypher
// Sarah changed jobs
// Step 1: Expire old relationship
MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT {expired_at: null}]->(o:Organization {name: 'Acme'})
SET r.expired_at = timestamp()

// Step 2: Create new relationship
MATCH (p:Person {name: 'Sarah'}), (o:Organization {name: 'NewCo'})
CREATE (p)-[:WORKS_AT {title: 'VP Engineering', created_at: timestamp(), expired_at: null}]->(o)
```

---

## 4. Database Setup

### 4.1 Constraints

```cypher
// Uniqueness constraints (also create implicit indexes)
CREATE CONSTRAINT person_uuid IF NOT EXISTS FOR (p:Person) REQUIRE p.uuid IS UNIQUE;
CREATE CONSTRAINT organization_uuid IF NOT EXISTS FOR (o:Organization) REQUIRE o.uuid IS UNIQUE;
CREATE CONSTRAINT project_uuid IF NOT EXISTS FOR (p:Project) REQUIRE p.uuid IS UNIQUE;
CREATE CONSTRAINT goal_uuid IF NOT EXISTS FOR (g:Goal) REQUIRE g.uuid IS UNIQUE;
CREATE CONSTRAINT task_uuid IF NOT EXISTS FOR (t:Task) REQUIRE t.uuid IS UNIQUE;
CREATE CONSTRAINT event_uuid IF NOT EXISTS FOR (e:Event) REQUIRE e.uuid IS UNIQUE;
CREATE CONSTRAINT location_uuid IF NOT EXISTS FOR (l:Location) REQUIRE l.uuid IS UNIQUE;
CREATE CONSTRAINT note_uuid IF NOT EXISTS FOR (n:Note) REQUIRE n.uuid IS UNIQUE;
CREATE CONSTRAINT resource_uuid IF NOT EXISTS FOR (r:Resource) REQUIRE r.uuid IS UNIQUE;
CREATE CONSTRAINT thread_uuid IF NOT EXISTS FOR (t:Thread) REQUIRE t.uuid IS UNIQUE;
CREATE CONSTRAINT message_uuid IF NOT EXISTS FOR (m:Message) REQUIRE m.uuid IS UNIQUE;
CREATE CONSTRAINT day_date IF NOT EXISTS FOR (d:Day) REQUIRE d.date IS UNIQUE;
CREATE CONSTRAINT journal_uuid IF NOT EXISTS FOR (j:JournalEntry) REQUIRE j.uuid IS UNIQUE;

// Personal Life entity constraints
CREATE CONSTRAINT hobby_uuid IF NOT EXISTS FOR (h:Hobby) REQUIRE h.uuid IS UNIQUE;
CREATE CONSTRAINT healthmetric_uuid IF NOT EXISTS FOR (h:HealthMetric) REQUIRE h.uuid IS UNIQUE;
CREATE CONSTRAINT pet_uuid IF NOT EXISTS FOR (p:Pet) REQUIRE p.uuid IS UNIQUE;
CREATE CONSTRAINT milestone_uuid IF NOT EXISTS FOR (m:Milestone) REQUIRE m.uuid IS UNIQUE;
CREATE CONSTRAINT routine_uuid IF NOT EXISTS FOR (r:Routine) REQUIRE r.uuid IS UNIQUE;
CREATE CONSTRAINT preference_uuid IF NOT EXISTS FOR (p:Preference) REQUIRE p.uuid IS UNIQUE;
CREATE CONSTRAINT community_uuid IF NOT EXISTS FOR (c:Community) REQUIRE c.uuid IS UNIQUE;
CREATE CONSTRAINT loreepisode_uuid IF NOT EXISTS FOR (le:LoreEpisode) REQUIRE le.uuid IS UNIQUE;

// Property existence constraints
CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS NOT NULL;
CREATE CONSTRAINT thread_status IF NOT EXISTS FOR (t:Thread) REQUIRE t.status IS NOT NULL;
CREATE CONSTRAINT hobby_name IF NOT EXISTS FOR (h:Hobby) REQUIRE h.name IS NOT NULL;
CREATE CONSTRAINT pet_name IF NOT EXISTS FOR (p:Pet) REQUIRE p.name IS NOT NULL;
CREATE CONSTRAINT routine_name IF NOT EXISTS FOR (r:Routine) REQUIRE r.name IS NOT NULL;
CREATE CONSTRAINT community_name IF NOT EXISTS FOR (c:Community) REQUIRE c.name IS NOT NULL;
CREATE CONSTRAINT loreepisode_saga IF NOT EXISTS FOR (le:LoreEpisode) REQUIRE le.saga_id IS NOT NULL;
```

### 4.2 Indexes

```cypher
// Full-text search indexes
CREATE FULLTEXT INDEX person_search IF NOT EXISTS FOR (p:Person) ON EACH [p.name, p.email, p.bio];
CREATE FULLTEXT INDEX org_search IF NOT EXISTS FOR (o:Organization) ON EACH [o.name, o.description];
CREATE FULLTEXT INDEX note_search IF NOT EXISTS FOR (n:Note) ON EACH [n.title, n.content_summarized];
CREATE FULLTEXT INDEX project_search IF NOT EXISTS FOR (p:Project) ON EACH [p.name, p.description];

// Temporal indexes for time-travel queries
CREATE INDEX works_at_temporal IF NOT EXISTS FOR ()-[r:WORKS_AT]-() ON (r.created_at, r.expired_at);
CREATE INDEX located_in_temporal IF NOT EXISTS FOR ()-[r:LOCATED_IN]-() ON (r.created_at, r.expired_at);

// Message traversal optimization
CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp);

// Thread status for archival queries
CREATE INDEX thread_status IF NOT EXISTS FOR (t:Thread) ON (t.status, t.last_message_at);

// Task status for task management
CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status, t.due_date);

// Spatial index for location queries
CREATE POINT INDEX location_coords IF NOT EXISTS FOR (l:Location) ON (l.coordinate);

// Personal Life indexes
CREATE INDEX hobby_category IF NOT EXISTS FOR (h:Hobby) ON (h.category);
CREATE INDEX healthmetric_type IF NOT EXISTS FOR (h:HealthMetric) ON (h.type, h.recorded_at);
CREATE INDEX pet_species IF NOT EXISTS FOR (p:Pet) ON (p.species);
CREATE INDEX milestone_category IF NOT EXISTS FOR (m:Milestone) ON (m.category, m.achieved_at);
CREATE INDEX routine_frequency IF NOT EXISTS FOR (r:Routine) ON (r.frequency, r.is_active);
CREATE INDEX preference_category IF NOT EXISTS FOR (p:Preference) ON (p.category, p.sentiment);

// Community/Island indexes
CREATE INDEX community_theme IF NOT EXISTS FOR (c:Community) ON (c.theme);
CREATE FULLTEXT INDEX community_search IF NOT EXISTS FOR (c:Community) ON EACH [c.name, c.summary];

// Lore System indexes
CREATE INDEX loreepisode_saga IF NOT EXISTS FOR (le:LoreEpisode) ON (le.saga_id, le.chapter);
CREATE INDEX loreepisode_told IF NOT EXISTS FOR (le:LoreEpisode) ON (le.told_at);

// Family relationship temporal indexes
CREATE INDEX spouse_temporal IF NOT EXISTS FOR ()-[r:SPOUSE_OF]-() ON (r.created_at, r.expired_at);
CREATE INDEX friend_temporal IF NOT EXISTS FOR ()-[r:FRIEND_OF]-() ON (r.created_at, r.expired_at);
CREATE INDEX practices_temporal IF NOT EXISTS FOR ()-[r:PRACTICES]-() ON (r.created_at, r.expired_at);
```

### 4.3 Vector Indexes (for Graphiti)

```cypher
// Vector similarity search (HNSW algorithm)
CREATE VECTOR INDEX person_vector IF NOT EXISTS FOR (p:Person) ON (p.vector_embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX note_vector IF NOT EXISTS FOR (n:Note) ON (n.vector_embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX resource_vector IF NOT EXISTS FOR (r:Resource) ON (r.vector_embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}};
```

---

## 5. Common Query Patterns

### 5.1 Get Current Employer

```cypher
MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
WHERE r.expired_at IS NULL
RETURN o.name as employer, r.title as title
```

### 5.2 Get Thread Context (Rolling Window)

```cypher
MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
WITH m ORDER BY m.timestamp DESC LIMIT $limit
WITH collect(m) as messages
UNWIND reverse(messages) as msg
RETURN msg.role, msg.content, msg.timestamp
ORDER BY msg.timestamp ASC
```

### 5.3 Find Related People

```cypher
MATCH (p:Person {uuid: $person_uuid})-[:ATTENDED]->(e:Event)<-[:ATTENDED]-(other:Person)
WHERE other.uuid <> $person_uuid
RETURN other.name, count(e) as shared_events
ORDER BY shared_events DESC
LIMIT 10
```

### 5.4 Get Blocked Tasks

```cypher
MATCH (t:Task {status: 'todo'})-[:BLOCKS]->(blocker)
RETURN t.action as blocked_task, blocker.action as blocked_by
```

### 5.5 Semantic Search with Graph Context

```cypher
// First: vector search finds relevant Notes
// Then: graph traversal adds context
CALL db.index.vector.queryNodes('note_vector', 5, $query_embedding)
YIELD node, score
MATCH (node)-[:MENTIONED_IN]-(p:Person)
OPTIONAL MATCH (node)-[:DISCUSSED]-(proj:Project)
RETURN node.title, node.content_summarized, collect(p.name) as people, collect(proj.name) as projects, score
ORDER BY score DESC
```

---

## 6. Pydantic Model Mapping

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class NodeLabel(str, Enum):
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
    # Personal Life Entities
    HOBBY = "Hobby"
    HEALTH_METRIC = "HealthMetric"
    PET = "Pet"
    MILESTONE = "Milestone"
    ROUTINE = "Routine"
    PREFERENCE = "Preference"
    COMMUNITY = "Community"
    LORE_EPISODE = "LoreEpisode"
    # System Entities
    THREAD = "Thread"
    MESSAGE = "Message"
    DAY = "Day"
    JOURNAL_ENTRY = "JournalEntry"
    TAG = "Tag"

class RelationType(str, Enum):
    # Professional Context
    WORKS_AT = "WORKS_AT"
    REPORTS_TO = "REPORTS_TO"
    AFFILIATED_WITH = "AFFILIATED_WITH"
    # Action Hierarchy
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    PART_OF = "PART_OF"
    SUBTASK_OF = "SUBTASK_OF"
    BLOCKS = "BLOCKS"
    DEPENDS_ON = "DEPENDS_ON"
    ASSIGNED_TO = "ASSIGNED_TO"
    # Spatial Context
    HELD_AT = "HELD_AT"
    LOCATED_IN = "LOCATED_IN"
    CREATED_AT_LOCATION = "CREATED_AT_LOCATION"
    # Knowledge Linking
    REFERENCES = "REFERENCES"
    SUMMARIZES = "SUMMARIZES"
    SUMMARY_OF = "SUMMARY_OF"
    MENTIONED_IN = "MENTIONED_IN"
    DISCUSSED = "DISCUSSED"
    # Event Context
    ATTENDED = "ATTENDED"
    ORGANIZED_BY = "ORGANIZED_BY"
    # Information Lineage
    VERSION_OF = "VERSION_OF"
    REPLIES_TO = "REPLIES_TO"
    ATTACHED_TO = "ATTACHED_TO"
    # Interpersonal Context
    KNOWS = "KNOWS"
    INTRODUCED_BY = "INTRODUCED_BY"
    # Family & Personal Relationships
    FAMILY_OF = "FAMILY_OF"
    SPOUSE_OF = "SPOUSE_OF"
    PARENT_OF = "PARENT_OF"
    CHILD_OF = "CHILD_OF"
    SIBLING_OF = "SIBLING_OF"
    FRIEND_OF = "FRIEND_OF"
    # Personal Life
    PRACTICES = "PRACTICES"
    INTERESTED_IN = "INTERESTED_IN"
    PREFERS = "PREFERS"
    OWNS = "OWNS"
    CARES_FOR = "CARES_FOR"
    RECORDED = "RECORDED"
    ACHIEVES = "ACHIEVES"
    FOLLOWS_ROUTINE = "FOLLOWS_ROUTINE"
    # Community (Knowledge Islands)
    PART_OF_ISLAND = "PART_OF_ISLAND"
    # Lore System
    EXPANDS_UPON = "EXPANDS_UPON"
    TOLD_TO = "TOLD_TO"
    SAGA_STARTED_BY = "SAGA_STARTED_BY"
    # Thread Management
    CONTAINS = "CONTAINS"
    PRECEDES = "PRECEDES"
    # Temporal Spine
    OCCURRED_ON = "OCCURRED_ON"
    # Categorization
    TAGGED_WITH = "TAGGED_WITH"

class PersonNode(BaseModel):
    uuid: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None
    created_at: float
    updated_at: float

class WorksAtRelation(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    created_at: float
    expired_at: Optional[float] = None

# Personal Life Models

class HobbyNode(BaseModel):
    uuid: str
    name: str
    category: Optional[str] = None
    frequency: Optional[str] = None
    skill_level: Optional[str] = None
    created_at: float

class PetNode(BaseModel):
    uuid: str
    name: str
    species: str
    breed: Optional[str] = None
    birthday: Optional[float] = None
    created_at: float

class MilestoneNode(BaseModel):
    uuid: str
    name: str
    category: Optional[str] = None
    achieved_at: float
    significance: Optional[str] = None
    created_at: float

class RoutineNode(BaseModel):
    uuid: str
    name: str
    frequency: str
    time_of_day: Optional[str] = None
    is_active: bool = True
    created_at: float

class PreferenceNode(BaseModel):
    uuid: str
    category: str
    item: str
    sentiment: str  # likes, dislikes, prefers, avoids
    strength: Optional[float] = None
    created_at: float

class CommunityNode(BaseModel):
    uuid: str
    name: str
    theme: str
    summary: Optional[str] = None
    node_count: Optional[int] = None
    created_at: float

class LoreEpisodeNode(BaseModel):
    uuid: str
    saga_id: str
    saga_name: str
    chapter: int
    content: str
    told_at: float
    channel: Optional[str] = None
    created_at: float

# Personal Relationship Models

class FamilyOfRelation(BaseModel):
    role: str  # spouse, parent, child, sibling, etc.
    created_at: float

class FriendOfRelation(BaseModel):
    since: Optional[float] = None
    how_met: Optional[str] = None
    strength: Optional[float] = None
    created_at: float
    expired_at: Optional[float] = None

class PracticesRelation(BaseModel):
    since: Optional[float] = None
    frequency: Optional[str] = None
    skill_level: Optional[str] = None
    created_at: float
    expired_at: Optional[float] = None
```

---

## 7. Agent Instructions

When instructing agents on ontology usage, include:

```
📝 DATABASE SCHEMA INSTRUCTIONS

When extracting entities and relationships, strictly use the following taxonomy:

**Core Nodes**: Person, Organization, Project, Goal, Task, Event, Location, Note, Resource

**Personal Life Nodes**: Hobby, HealthMetric, Pet, Milestone, Routine, Preference

**System Nodes**: Community, LoreEpisode, Thread, Message, Day, JournalEntry

**Professional Relationships**:
- Use WORKS_AT for employment (with title property)
- Use REPORTS_TO for hierarchical relationships
- Use AFFILIATED_WITH for non-employment organizational ties

**Action Relationships**:
- Use CONTRIBUTES_TO for Project → Goal links
- Use PART_OF for Task → Project links
- Use BLOCKS/DEPENDS_ON for task dependencies
- Use ASSIGNED_TO for task ownership

**Personal Life Relationships**:
- Use FAMILY_OF for family connections (with role: spouse, parent, child, sibling)
- Use FRIEND_OF for friendships
- Use PRACTICES for Person → Hobby links
- Use OWNS for Person → Pet links
- Use RECORDED for Person → HealthMetric links
- Use ACHIEVES for Person → Milestone links
- Use FOLLOWS_ROUTINE for Person → Routine links
- Use PREFERS for Person → Preference links

**Event Relationships**:
- Use ATTENDED for Person → Event links
- Use HELD_AT for Event → Location links
- Use DISCUSSED for Event → Project/Task/Goal links

**Knowledge Relationships**:
- Use MENTIONED_IN for Person/Org → Note/Event links
- Use PART_OF_ISLAND for entity → Community links

**Lore Relationships** (Bard only):
- Use EXPANDS_UPON for LoreEpisode chains
- Use TOLD_TO for LoreEpisode → Person links

**Temporal Rule**: If a relationship is described as "former," "previous," or "past," set the `expired_at` property. Never delete historical data.

**Property Standards**:
- All UUIDs must be UUID v4 format
- All timestamps are Unix epoch (float)
- Names should be title-cased ("Sarah Johnson", not "sarah johnson")
- Email addresses should be lowercase
- Family roles should be lowercase ("spouse", "parent", "child")
```

---

## 8. Example Queries: Personal Life

### 8.1 Get Family Members

```cypher
MATCH (p:Person {uuid: $person_uuid})-[r:FAMILY_OF]->(family:Person)
RETURN family.name, r.role
```

### 8.2 Get Active Hobbies

```cypher
MATCH (p:Person {uuid: $person_uuid})-[r:PRACTICES]->(h:Hobby)
WHERE r.expired_at IS NULL
RETURN h.name, h.category, r.skill_level
```

### 8.3 Get Health Trends

```cypher
MATCH (p:Person {uuid: $person_uuid})-[:RECORDED]->(hm:HealthMetric {type: $metric_type})
WHERE hm.recorded_at >= $start_date
RETURN hm.value, hm.recorded_at
ORDER BY hm.recorded_at ASC
```

### 8.4 Get Knowledge Island Summary

```cypher
MATCH (c:Community {name: $island_name})
OPTIONAL MATCH (n)-[:PART_OF_ISLAND]->(c)
RETURN c.summary, c.theme, count(n) as member_count
```

### 8.5 Get Saga Progress

```cypher
MATCH (le:LoreEpisode {saga_id: $saga_id})-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
RETURN le.chapter, le.content, le.told_at
ORDER BY le.chapter ASC
```

### 8.6 Get Routine Streaks

```cypher
MATCH (p:Person {uuid: $person_uuid})-[r:FOLLOWS_ROUTINE {expired_at: null}]->(rt:Routine)
WHERE rt.is_active = true
RETURN rt.name, rt.frequency, r.streak
ORDER BY r.streak DESC
```

---

*"Every fact in The Locker has its place and time—whether it be work or play."* - Klabautermann
