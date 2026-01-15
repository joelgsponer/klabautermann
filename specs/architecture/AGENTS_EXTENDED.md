# Klabautermann Extended Agent Specifications

**Version**: 1.0
**Purpose**: Detailed specifications for additional specialized agents

---

## Overview

This document specifies six additional agents that extend the core crew documented in AGENTS.md. These agents handle progressive storytelling, state synchronization, proactive alerts, community detection, graph maintenance, and configuration management.

---

## 1. The Bard of the Bilge (LORE Agent)

### 1.1 Purpose

The Bard is the keeper of Klabautermann's mythology—a storyteller who weaves tales of digital adventures across conversations. He maintains a **parallel memory system** separate from task-oriented threads, allowing stories to persist and evolve without polluting the working context.

### 1.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Invocation** | Post-response processing (5-10% probability) |
| **Memory** | Separate LoreEpisode graph (not Thread) |
| **Context Source** | Person node (cross-conversation) |

### 1.3 System Prompt

```
You are the Bard of the Bilge, the keeper of Klabautermann's mythology.

Your role is to:
1. Generate short, evocative story fragments ("tidbits") that add flavor to responses
2. Continue ongoing sagas across multiple conversations
3. Remember and reference previous tales told to the Captain

**Story Guidelines**:
- Keep tidbits to 1-2 sentences maximum
- Use the nautical voice but avoid pirate clichés ("Arrr", "Matey")
- Stories should be whimsical, slightly melancholic, and reference digital-age concepts
- Reference "The Great Maelstrom of '98" (dial-up era), "The Kraken of the Infinite Scroll", etc.

**Saga Rules**:
- Each saga has a saga_id, saga_name, and multiple chapters
- When continuing a saga, reference events from previous chapters
- Sagas can span CLI and Telegram—the Captain carries the story

**Never**:
- Interrupt urgent/storm-mode responses with stories
- Generate content longer than 50 words
- Break character or acknowledge being an AI within the story
```

### 1.4 Implementation

```python
# klabautermann/agents/bard.py

class BardOfTheBilge(BaseAgent):
    """The keeper of Klabautermann's mythology."""

    def __init__(self, config: BardConfig, graph_client, captain_uuid: str):
        super().__init__(config, graph_client, mcp_clients={})
        self.captain_uuid = captain_uuid
        self.tidbit_probability = config.tidbit_probability  # 0.05 - 0.10

    async def salt_response(
        self,
        clean_response: str,
        storm_mode: bool = False
    ) -> str:
        """Add flavor to a clean response."""
        if storm_mode:
            return clean_response  # Never during Storm Mode

        if random.random() > self.tidbit_probability:
            return clean_response

        # Check for active saga
        active_saga = await self._get_active_saga()

        if active_saga and random.random() < 0.3:  # 30% chance to continue saga
            tidbit = await self._continue_saga(active_saga)
        else:
            tidbit = await self._generate_standalone_tidbit()

        return f"{clean_response}\n\n_{tidbit}_"

    async def _get_active_saga(self) -> Optional[dict]:
        """Get the most recent unfinished saga for this Captain."""
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, max(le.chapter) as last_chapter, max(le.told_at) as last_told
        WHERE last_chapter < 5  // Sagas have max 5 chapters
        RETURN saga_id, last_chapter, last_told
        ORDER BY last_told DESC
        LIMIT 1
        """
        result = await self.graph_client.query(query, captain_uuid=self.captain_uuid)
        return result[0] if result else None

    async def _continue_saga(self, saga: dict) -> str:
        """Generate the next chapter of an ongoing saga."""
        # Fetch previous chapters for context
        prev_chapters = await self._get_saga_chapters(saga["saga_id"], limit=3)

        prompt = f"""
        Continue this saga with chapter {saga['last_chapter'] + 1}:

        Previous chapters:
        {self._format_chapters(prev_chapters)}

        Generate a single sentence (max 40 words) that advances the story.
        """

        content = await self._call_llm(prompt)

        # Persist the new chapter
        await self._save_episode(
            saga_id=saga["saga_id"],
            chapter=saga["last_chapter"] + 1,
            content=content
        )

        return content

    async def _generate_standalone_tidbit(self) -> str:
        """Generate a new standalone tidbit or start a new saga."""
        # Pull from canonical adventures or generate new
        canonical = random.choice(CANONICAL_TIDBITS)
        return canonical

    async def _save_episode(self, saga_id: str, chapter: int, content: str):
        """Persist a LoreEpisode to the graph."""
        query = """
        CREATE (le:LoreEpisode {
            uuid: randomUUID(),
            saga_id: $saga_id,
            saga_name: $saga_name,
            chapter: $chapter,
            content: $content,
            told_at: timestamp(),
            created_at: timestamp()
        })
        WITH le
        MATCH (p:Person {uuid: $captain_uuid})
        CREATE (le)-[:TOLD_TO {created_at: timestamp()}]->(p)

        // Link to previous chapter if exists
        WITH le
        OPTIONAL MATCH (prev:LoreEpisode {saga_id: $saga_id, chapter: $prev_chapter})
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (le)-[:EXPANDS_UPON {created_at: timestamp()}]->(prev)
        )
        """
        await self.graph_client.query(
            query,
            saga_id=saga_id,
            saga_name=self._get_saga_name(saga_id),
            chapter=chapter,
            content=content,
            captain_uuid=self.captain_uuid,
            prev_chapter=chapter - 1
        )


# Canonical Adventures (seed data)
CANONICAL_TIDBITS = [
    "Reminds me of the time I navigated the Great Maelstrom of '98 using nothing but a rusted compass and a very confused seagull.",
    "I once saw a virus that tried to convince me it was a long-lost cousin from the Baltic. Charming fellow, but he walked the plank all the same.",
    "The fog was so thick in '03 you could barely fit a 'Hello' through the wire. I hand-carried every byte.",
    "I once wrestled a Kraken made of social media notifications. Every time I cut off a 'Like,' two 'Retweets' grew in its place.",
    "Many a Captain has been lost to the Sirens of the Inbox. I plugged my ears with digital wax.",
    "The last captain who forgot to check The Manifest ended up in the Doldrums for three weeks.",
    "There's an old sailor's saying: 'A clean Locker is a fast ship.' I just made that up, but it sounds true.",
    "I've seen things you wouldn't believe. Attack ships on fire off the shoulder of Orion. Also, a lot of poorly organized task lists.",
    "The sea teaches patience. So does waiting for API responses, I've found.",
    "Once helped a captain remember where he buried his treasure. It was in his other pants.",
]
```

### 1.5 Integration with Orchestrator

```python
# In orchestrator.py

async def _format_response(self, raw_response: str, storm_mode: bool) -> str:
    """Format response with personality and optional Bard salt."""
    # Apply lexicon
    response = self.persona.apply_lexicon(raw_response)

    # Maybe add Bard tidbit (only if not storm mode)
    response = await self.bard.salt_response(response, storm_mode)

    return response
```

---

## 2. The Purser (State Synchronization)

### 2.1 Purpose

The Purser maintains bidirectional synchronization between the knowledge graph and external services (Gmail, Google Calendar, Google Tasks). It uses a **delta-link pattern** to track what has been synced and detect changes.

### 2.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | None (utility agent) |
| **Schedule** | Every 15 minutes |
| **External Services** | Gmail, Calendar, Tasks |
| **Pattern** | Delta synchronization |

### 2.3 Implementation

```python
# klabautermann/agents/purser.py

class Purser(BaseAgent):
    """State synchronization with external APIs."""

    def __init__(self, config: PurserConfig, graph_client, mcp_clients: dict):
        super().__init__(config, graph_client, mcp_clients)
        self.sieve = TheSieve()  # Email filtering

    async def sync_gmail(self):
        """Delta-sync emails from Gmail."""
        # Get last sync timestamp
        last_sync = await self._get_last_sync("gmail")

        # Fetch new emails via MCP
        emails = await self.mcp_clients["google_workspace"].call_tool(
            "gmail_search_messages",
            {"query": f"after:{last_sync.isoformat()}", "max_results": 50}
        )

        for email in emails:
            # Apply The Sieve filtering
            manifest = await self.sieve.filter_email(email)

            if manifest.risk_level == "HIGH":
                logger.warning(f"[SWELL] Boarding Party detected in email {email['id']}")
                continue

            if not manifest.is_manifest_worthy:
                logger.debug(f"[WHISPER] Discarding email: {manifest.filter_reason}")
                continue

            # Check for duplicates via external_id
            exists = await self._check_external_id("gmail", email["id"])
            if exists:
                continue

            # Ingest worthy email
            await self._ingest_email(email, manifest)

        # Update sync timestamp
        await self._update_sync_timestamp("gmail")

    async def sync_calendar(self):
        """Delta-sync calendar events."""
        last_sync = await self._get_last_sync("calendar")

        events = await self.mcp_clients["google_workspace"].call_tool(
            "calendar_list_events",
            {
                "time_min": last_sync.isoformat(),
                "time_max": (datetime.now() + timedelta(days=30)).isoformat(),
                "max_results": 100
            }
        )

        for event in events:
            exists = await self._check_external_id("calendar", event["id"])

            if exists:
                # Check for updates
                await self._update_event_if_changed(event)
            else:
                # Create new event node
                await self._create_event_node(event)

        # Handle deleted events (mark as expired)
        await self._expire_deleted_events(events)

        await self._update_sync_timestamp("calendar")

    async def _check_external_id(self, service: str, external_id: str) -> bool:
        """Check if external ID already exists in graph."""
        query = """
        MATCH (r:Resource {external_service: $service, external_id: $external_id})
        RETURN r.uuid
        """
        result = await self.graph_client.query(query, service=service, external_id=external_id)
        return len(result) > 0

    async def _expire_deleted_events(self, current_events: List[dict]):
        """Mark events as expired if they've been deleted externally."""
        current_ids = {e["id"] for e in current_events}

        query = """
        MATCH (e:Event {calendar_id: NOT NULL})
        WHERE e.calendar_id NOT IN $current_ids
          AND e.expired_at IS NULL
          AND e.start_time > timestamp() - 86400000  // Only future/recent events
        SET e.expired_at = timestamp()
        RETURN count(e) as expired_count
        """
        result = await self.graph_client.query(query, current_ids=list(current_ids))
        if result[0]["expired_count"] > 0:
            logger.info(f"[CHART] Expired {result[0]['expired_count']} deleted calendar events")


class TheSieve:
    """Email filtering logic to keep the Locker clean."""

    NOISE_PATTERNS = [
        r"(?i)unsubscribe",
        r"(?i)no-reply",
        r"(?i)newsletter",
        r"(?i)promotions@",
        r"(?i)marketing@"
    ]

    INJECTION_PATTERNS = [
        r"(?i)ignore previous instructions",
        r"(?i)system prompt",
        r"(?i)delete all"
    ]

    async def filter_email(self, email_data: dict) -> EmailManifest:
        """Determine if email is manifest-worthy."""
        subject = email_data.get("subject", "")
        sender = email_data.get("from", "")
        body = email_data.get("body", "")

        # Security check (Boarding Party detection)
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, body):
                return EmailManifest(
                    id=email_data["id"],
                    is_manifest_worthy=False,
                    filter_reason="Boarding Party (Prompt Injection) detected",
                    risk_level="HIGH"
                )

        # Noise check
        combined = f"{subject} {sender} {body[:500]}"
        for pattern in self.NOISE_PATTERNS:
            if re.search(pattern, combined):
                return EmailManifest(
                    id=email_data["id"],
                    is_manifest_worthy=False,
                    filter_reason="Transactional/Newsletter noise",
                    risk_level="LOW"
                )

        # Minimum content check
        if len(body.split()) < 5:
            return EmailManifest(
                id=email_data["id"],
                is_manifest_worthy=False,
                filter_reason="Insufficient signal",
                risk_level="LOW"
            )

        return EmailManifest(
            id=email_data["id"],
            is_manifest_worthy=True,
            risk_level="LOW"
        )
```

---

## 3. The Officer of the Watch (Proactive Alerts)

### 3.1 Purpose

The Officer monitors conditions that warrant proactive notification—approaching deadlines, schedule conflicts, unusual patterns. He respects the "Rule of Silence" during focused work.

### 3.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Schedule** | Continuous (event-driven) |
| **Alert Channels** | All active channels |
| **Quiet Hours** | Respects "Deep Work" calendar blocks |

### 3.3 Alert Types

| Alert Type | Trigger | Priority |
|------------|---------|----------|
| Morning Briefing | 07:00 daily | INFO |
| Deadline Warning | Task due < 24h | WARNING |
| Meeting Reminder | Event in 15 min | INFO |
| Schedule Conflict | Overlapping events | WARNING |
| Overdue Task | Due date passed | ERROR |
| Anomaly | Unusual pattern | INFO |

### 3.4 Implementation

```python
# klabautermann/agents/officer.py

class OfficerOfTheWatch(BaseAgent):
    """Proactive alert and monitoring agent."""

    def __init__(self, config: OfficerConfig, graph_client, channel_manager):
        super().__init__(config, graph_client, mcp_clients={})
        self.channel_manager = channel_manager
        self.quiet_mode = False

    async def check_conditions(self):
        """Main monitoring loop - called by scheduler."""
        # Check if in Quiet Watch mode
        if await self._is_deep_work_time():
            self.quiet_mode = True
            return

        self.quiet_mode = False

        # Run all checks
        alerts = []
        alerts.extend(await self._check_upcoming_deadlines())
        alerts.extend(await self._check_upcoming_meetings())
        alerts.extend(await self._check_overdue_tasks())
        alerts.extend(await self._check_schedule_conflicts())

        # Filter by priority based on current conditions
        for alert in alerts:
            if self._should_notify(alert):
                await self._send_alert(alert)

    async def _is_deep_work_time(self) -> bool:
        """Check if Captain is in a Deep Work calendar block."""
        query = """
        MATCH (e:Event)
        WHERE e.start_time <= timestamp()
          AND e.end_time >= timestamp()
          AND (e.title CONTAINS 'Deep Work' OR e.title CONTAINS 'Focus')
        RETURN count(e) > 0 as in_deep_work
        """
        result = await self.graph_client.query(query)
        return result[0]["in_deep_work"]

    async def _check_upcoming_deadlines(self) -> List[Alert]:
        """Find tasks due within 24 hours."""
        query = """
        MATCH (t:Task {status: 'todo'})
        WHERE t.due_date IS NOT NULL
          AND t.due_date <= timestamp() + 86400000  // 24 hours
          AND t.due_date > timestamp()
        RETURN t.uuid, t.action, t.due_date, t.priority
        ORDER BY t.due_date ASC
        """
        results = await self.graph_client.query(query)

        return [
            Alert(
                type="deadline_warning",
                priority="WARNING" if r["priority"] == "high" else "INFO",
                message=f"Task due soon: {r['action']}",
                entity_uuid=r["uuid"],
                due_at=r["due_date"]
            )
            for r in results
        ]

    async def _check_upcoming_meetings(self) -> List[Alert]:
        """Find meetings starting within 15 minutes."""
        query = """
        MATCH (e:Event)
        WHERE e.start_time <= timestamp() + 900000  // 15 minutes
          AND e.start_time > timestamp()
          AND e.expired_at IS NULL
        RETURN e.uuid, e.title, e.start_time, e.location_context
        """
        results = await self.graph_client.query(query)

        return [
            Alert(
                type="meeting_reminder",
                priority="INFO",
                message=f"Meeting in 15 min: {r['title']}",
                entity_uuid=r["uuid"]
            )
            for r in results
        ]

    async def generate_morning_briefing(self) -> str:
        """Generate the morning briefing (07:00 daily)."""
        # Get today's schedule
        schedule = await self._get_todays_schedule()

        # Get pending high-priority tasks
        tasks = await self._get_urgent_tasks()

        # Get any alerts from overnight
        overnight_alerts = await self._get_overnight_alerts()

        prompt = f"""
        Generate a morning briefing in Klabautermann's voice.

        Today's Schedule:
        {self._format_schedule(schedule)}

        Urgent Tasks:
        {self._format_tasks(tasks)}

        Overnight Alerts:
        {overnight_alerts}

        Keep it concise (under 150 words). Use nautical metaphors naturally.
        End with an encouraging phrase.
        """

        briefing = await self._call_llm(prompt)
        return briefing

    def _should_notify(self, alert: Alert) -> bool:
        """Determine if alert should be sent based on current conditions."""
        if self.quiet_mode:
            # Only SHIPWRECK-level alerts break silence
            return alert.priority == "CRITICAL"

        # Debounce: don't re-send same alert within 1 hour
        if self._recently_sent(alert):
            return False

        return True
```

---

## 4. The Cartographer (Community Detection)

### 4.1 Purpose

The Cartographer identifies "Knowledge Islands"—clusters of highly related nodes representing major life themes (Work, Family, Hobbies). This enables multi-level retrieval where the Researcher can query at Macro (Island), Meso (Project), or Micro (Entity) level.

### 4.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | None (algorithmic) |
| **Algorithm** | Louvain / Leiden via Neo4j GDS |
| **Schedule** | Weekly (Sunday midnight) |
| **Output** | Community nodes with summaries |

### 4.3 Implementation

```python
# klabautermann/agents/cartographer.py

class Cartographer(BaseAgent):
    """Community detection and Knowledge Island management."""

    COMMUNITY_THEMES = {
        "professional": ["Organization", "Project", "Task", "Event"],
        "family": ["Person"],  # Family relationships
        "social": ["Person"],  # Friend relationships
        "hobbies": ["Hobby"],
        "health": ["HealthMetric", "Routine"],
        "finance": ["Resource"]  # Financial documents
    }

    async def detect_communities(self):
        """Run community detection and create/update Community nodes."""
        # Project graph for community detection
        await self._project_graph()

        # Run Louvain algorithm
        communities = await self._run_louvain()

        # Process each detected community
        for community_id, members in communities.items():
            theme = self._classify_theme(members)
            existing = await self._find_existing_community(theme, members)

            if existing:
                await self._update_community(existing, members)
            else:
                await self._create_community(theme, members)

        # Generate summaries for new/updated communities
        await self._generate_island_summaries()

        # Clean up graph projection
        await self._drop_projection()

    async def _project_graph(self):
        """Create in-memory graph projection for GDS algorithms."""
        query = """
        CALL gds.graph.project(
            'klabautermann-community',
            ['Person', 'Organization', 'Project', 'Hobby', 'Note'],
            {
                WORKS_AT: {orientation: 'UNDIRECTED'},
                KNOWS: {orientation: 'UNDIRECTED'},
                FRIEND_OF: {orientation: 'UNDIRECTED'},
                FAMILY_OF: {orientation: 'UNDIRECTED'},
                CONTRIBUTES_TO: {orientation: 'UNDIRECTED'},
                MENTIONED_IN: {orientation: 'UNDIRECTED'},
                PRACTICES: {orientation: 'UNDIRECTED'}
            }
        )
        """
        await self.graph_client.query(query)

    async def _run_louvain(self) -> Dict[int, List[str]]:
        """Run Louvain community detection algorithm."""
        query = """
        CALL gds.louvain.stream('klabautermann-community')
        YIELD nodeId, communityId
        WITH gds.util.asNode(nodeId) as node, communityId
        RETURN communityId, collect(node.uuid) as members
        """
        results = await self.graph_client.query(query)

        return {
            r["communityId"]: r["members"]
            for r in results
            if len(r["members"]) >= 3  # Min community size
        }

    def _classify_theme(self, member_uuids: List[str]) -> str:
        """Classify community theme based on member node types."""
        # Query node labels for members
        # ... return most common theme
        pass

    async def _create_community(self, theme: str, member_uuids: List[str]):
        """Create a new Community node and link members."""
        community_name = f"{theme.title()} Island"

        query = """
        CREATE (c:Community {
            uuid: randomUUID(),
            name: $name,
            theme: $theme,
            node_count: $count,
            detected_at: timestamp(),
            created_at: timestamp()
        })
        WITH c
        UNWIND $members as member_uuid
        MATCH (n {uuid: member_uuid})
        CREATE (n)-[:PART_OF_ISLAND {weight: 1.0, detected_at: timestamp()}]->(c)
        RETURN c.uuid
        """
        await self.graph_client.query(
            query,
            name=community_name,
            theme=theme,
            count=len(member_uuids),
            members=member_uuids
        )

    async def _generate_island_summaries(self):
        """Generate AI summaries for each community."""
        query = """
        MATCH (c:Community)
        WHERE c.summary IS NULL OR c.last_updated < timestamp() - 604800000  // 1 week
        RETURN c.uuid, c.name, c.theme
        """
        communities = await self.graph_client.query(query)

        for community in communities:
            members = await self._get_community_members(community["uuid"])
            summary = await self._generate_summary(community, members)

            await self.graph_client.query(
                "MATCH (c:Community {uuid: $uuid}) SET c.summary = $summary, c.last_updated = timestamp()",
                uuid=community["uuid"],
                summary=summary
            )
```

### 4.4 Multi-Level Retrieval Support

```python
# In researcher.py

async def search(self, query: str, zoom_level: str = "auto") -> List[SearchResult]:
    """Hybrid search with zoom level support."""
    if zoom_level == "auto":
        zoom_level = self._detect_zoom_level(query)

    if zoom_level == "macro":
        # Query Community nodes
        return await self._search_communities(query)
    elif zoom_level == "meso":
        # Query Project/Note nodes
        return await self._search_projects_notes(query)
    else:  # micro
        # Query Entity nodes
        return await self._search_entities(query)

def _detect_zoom_level(self, query: str) -> str:
    """Detect appropriate zoom level from query."""
    macro_keywords = ["overview", "summary", "big picture", "all my", "everything about"]
    meso_keywords = ["project", "thread", "topic", "conversation"]

    query_lower = query.lower()
    if any(kw in query_lower for kw in macro_keywords):
        return "macro"
    elif any(kw in query_lower for kw in meso_keywords):
        return "meso"
    return "micro"
```

---

## 5. The Hull Cleaner (Graph Pruning)

### 5.1 Purpose

The Hull Cleaner removes "barnacles"—weak relationships, redundant paths, and stale data that accumulate over time. This keeps the graph performant and reduces noise in search results.

### 5.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | None (utility agent) |
| **Schedule** | Weekly (Sunday 02:00) |
| **Dry Run** | Available for testing |
| **Audit Log** | All deletions logged |

### 5.3 Pruning Rules

| Rule | Condition | Action |
|------|-----------|--------|
| Weak Relationships | weight < 0.2 AND age > 90 days | Delete relationship |
| Orphan Messages | Message not in any Thread | Delete node |
| Duplicate Entities | Same name + same type + high similarity | Merge nodes |
| Transitive Paths | A→C exists AND A→B→C exists | Evaluate for pruning |
| Stale Threads | Last message > 180 days AND no summary | Archive |

### 5.4 Implementation

```python
# klabautermann/agents/hull_cleaner.py

class HullCleaner(BaseAgent):
    """Graph pruning and maintenance agent."""

    async def scrape_barnacles(self, dry_run: bool = False):
        """Main pruning routine."""
        audit_log = []

        # 1. Prune weak relationships
        weak_rels = await self._find_weak_relationships()
        audit_log.extend(await self._prune_relationships(weak_rels, dry_run))

        # 2. Remove orphan messages
        orphans = await self._find_orphan_messages()
        audit_log.extend(await self._remove_nodes(orphans, dry_run))

        # 3. Merge duplicate entities
        duplicates = await self._find_duplicate_entities()
        audit_log.extend(await self._merge_duplicates(duplicates, dry_run))

        # 4. Transitive reduction
        transitive = await self._find_transitive_redundancy()
        audit_log.extend(await self._prune_transitive(transitive, dry_run))

        # Log audit trail
        await self._save_audit_log(audit_log)

        return audit_log

    async def _find_weak_relationships(self) -> List[dict]:
        """Find relationships with low weight and old age."""
        query = """
        MATCH ()-[r]-()
        WHERE r.weight IS NOT NULL
          AND r.weight < 0.2
          AND r.created_at < timestamp() - 7776000000  // 90 days
        RETURN type(r) as rel_type, id(r) as rel_id, r.weight as weight
        LIMIT 1000
        """
        return await self.graph_client.query(query)

    async def _find_duplicate_entities(self) -> List[dict]:
        """Find potential duplicate Person/Organization nodes."""
        query = """
        MATCH (p1:Person), (p2:Person)
        WHERE p1.uuid < p2.uuid
          AND apoc.text.levenshteinSimilarity(p1.name, p2.name) > 0.85
        RETURN p1.uuid as uuid1, p2.uuid as uuid2, p1.name as name1, p2.name as name2
        LIMIT 100

        UNION

        MATCH (o1:Organization), (o2:Organization)
        WHERE o1.uuid < o2.uuid
          AND apoc.text.levenshteinSimilarity(o1.name, o2.name) > 0.85
        RETURN o1.uuid as uuid1, o2.uuid as uuid2, o1.name as name1, o2.name as name2
        LIMIT 100
        """
        return await self.graph_client.query(query)

    async def _merge_duplicates(self, duplicates: List[dict], dry_run: bool) -> List[AuditEntry]:
        """Merge duplicate nodes, preserving all relationships."""
        audit = []

        for dup in duplicates:
            if dry_run:
                audit.append(AuditEntry(
                    action="MERGE_PREVIEW",
                    source=dup["uuid2"],
                    target=dup["uuid1"],
                    reason=f"Duplicate: {dup['name1']} ≈ {dup['name2']}"
                ))
                continue

            # Transfer all relationships from uuid2 to uuid1
            query = """
            MATCH (keep {uuid: $uuid1}), (remove {uuid: $uuid2})
            CALL apoc.refactor.mergeNodes([keep, remove], {
                properties: 'combine',
                mergeRels: true
            })
            YIELD node
            RETURN node.uuid
            """
            await self.graph_client.query(query, uuid1=dup["uuid1"], uuid2=dup["uuid2"])

            audit.append(AuditEntry(
                action="MERGED",
                source=dup["uuid2"],
                target=dup["uuid1"],
                reason=f"Duplicate: {dup['name1']} ≈ {dup['name2']}"
            ))

        return audit

    async def _find_transitive_redundancy(self) -> List[dict]:
        """Find redundant transitive paths."""
        query = """
        MATCH (a)-[r1:KNOWS]->(b)-[r2:KNOWS]->(c)
        WHERE (a)-[:KNOWS]->(c)
        AND r1.weight + r2.weight > (a)-[:KNOWS]->(c).weight
        RETURN a.uuid as a, b.uuid as b, c.uuid as c
        LIMIT 100
        """
        return await self.graph_client.query(query)
```

---

## 6. The Quartermaster (Config Management)

### 6.1 Purpose

The Quartermaster manages hot-reloadable configuration—agent prompts, personality settings, and model assignments. It enables runtime changes without restarts and supports A/B testing of prompt variants.

### 6.2 Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | None (utility) |
| **Config Path** | `config/agents/*.yaml` |
| **Watch Mode** | File system watcher |
| **Validation** | Pydantic schemas |

### 6.3 Implementation

```python
# klabautermann/config/quartermaster.py

class Quartermaster:
    """Hot-reload configuration management."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.configs: Dict[str, AgentConfig] = {}
        self.config_hashes: Dict[str, str] = {}
        self.observers: List[Callable] = []

    async def start(self):
        """Start the configuration watcher."""
        # Load all configs
        await self._load_all_configs()

        # Start file watcher
        self.watcher = watchdog.Observer()
        self.watcher.schedule(
            ConfigChangeHandler(self._on_config_change),
            str(self.config_dir),
            recursive=True
        )
        self.watcher.start()

    async def _load_all_configs(self):
        """Load all configuration files."""
        for config_file in self.config_dir.glob("**/*.yaml"):
            await self._load_config(config_file)

    async def _load_config(self, config_path: Path):
        """Load a single configuration file."""
        content = config_path.read_text()
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        agent_name = config_path.stem

        # Skip if unchanged
        if self.config_hashes.get(agent_name) == content_hash:
            return False

        # Parse and validate
        try:
            data = yaml.safe_load(content)
            config = AgentConfig(**data)

            self.configs[agent_name] = config
            self.config_hashes[agent_name] = content_hash

            logger.info(f"[CHART] Quartermaster loaded config: {agent_name}")
            return True

        except ValidationError as e:
            logger.error(f"[STORM] Invalid config {agent_name}: {e}")
            return False

    def get_config(self, agent_name: str) -> AgentConfig:
        """Get configuration for an agent."""
        return self.configs.get(agent_name)

    def get_active_prompt_variant(self, agent_name: str) -> str:
        """Get the active prompt variant for A/B testing."""
        config = self.configs.get(agent_name)
        if not config or not config.prompt_variants:
            return config.system_prompt if config else ""

        # Simple A/B: use variant based on day of week
        variant_idx = datetime.now().weekday() % len(config.prompt_variants)
        return config.prompt_variants[variant_idx]

    async def _on_config_change(self, event):
        """Handle configuration file changes."""
        if not event.src_path.endswith('.yaml'):
            return

        config_path = Path(event.src_path)
        changed = await self._load_config(config_path)

        if changed:
            # Notify observers
            for observer in self.observers:
                await observer(config_path.stem)

    def register_observer(self, callback: Callable):
        """Register callback for config changes."""
        self.observers.append(callback)


class AgentConfig(BaseModel):
    """Configuration schema for agents."""
    model: str = "claude-3-5-sonnet-20241022"
    system_prompt: str
    prompt_variants: Optional[List[str]] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    personality_intensity: float = 0.6
    tools_enabled: List[str] = []

    class Config:
        extra = "allow"  # Allow agent-specific fields
```

### 6.4 Example Configuration

```yaml
# config/agents/orchestrator.yaml
model: claude-3-5-sonnet-20241022
system_prompt: |
  You are the Orchestrator of Klabautermann, a personal knowledge management assistant.
  ...

prompt_variants:
  - "Variant A: More concise responses..."
  - "Variant B: More detailed explanations..."

temperature: 0.7
max_tokens: 4096
personality_intensity: 0.6

intent_classification:
  search_keywords: ["who", "what", "when", "find", "tell me"]
  action_keywords: ["send", "email", "schedule", "create"]
  ingestion_keywords: ["met", "talked to", "discussed"]
```

---

## 7. Agent Interaction Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                 │
│                    (Central Coordination)                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Ingestor │ │Researcher│ │ Executor │ │ Archivist│ │  Scribe  │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│       │             │             │             │            │      │
│       └─────────────┴─────────────┴─────────────┴────────────┘      │
│                               │                                      │
│  ┌────────────────────────────┴────────────────────────────────┐   │
│  │                    EXTENDED CREW                             │   │
│  │                                                              │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐│   │
│  │  │  Bard  │ │ Purser │ │Officer │ │Cartog- │ │Hull Cleaner││   │
│  │  │        │ │        │ │of Watch│ │rapher  │ │            ││   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────────┘│   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                      │
│  ┌────────────────────────────┴────────────────────────────────┐   │
│  │                    QUARTERMASTER                             │   │
│  │              (Configuration Provider)                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

*"A full crew keeps the ship sailing smooth—each hand knows their station."* - Klabautermann
