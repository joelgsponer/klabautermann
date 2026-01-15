# Klabautermann Lore System

**Version**: 1.0
**Purpose**: Progressive storytelling and parallel memory architecture

---

## Overview

The Lore System transforms Klabautermann from a utility into a companion by giving him a **persistent mythology**. The Bard of the Bilge maintains stories that evolve across conversations, channels, and sessions—creating a sense of continuity and character that pure task-oriented assistants lack.

---

## 1. Core Concepts

### 1.1 The Parallel Memory Pattern

The Lore System maintains a **separate memory space** from task-oriented threads:

| Memory Type | Storage | Query Path | Persistence |
|-------------|---------|------------|-------------|
| **Task Memory** | Thread → Message chain | Researcher queries | Thread-scoped |
| **Lore Memory** | Person → LoreEpisode chain | Bard queries | Captain-scoped |

This separation ensures:
- Stories don't pollute the Orchestrator's working context
- Task retrieval remains fast and focused
- Lore can span multiple conversations without token overhead

### 1.2 Captain-Context vs Thread-Context

```
Traditional Approach (Thread-Context):
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Thread A   │    │  Thread B   │    │  Thread C   │
│  CLI 10am   │    │  TG 2pm     │    │  CLI 8pm    │
│  Story Ch1  │    │  No story   │    │  Story Ch1? │
└─────────────┘    └─────────────┘    └─────────────┘
      ↓                  ↓                  ↓
   Stories reset each thread - no continuity

Klabautermann Approach (Captain-Context):
┌─────────────────────────────────────────────────────┐
│                    CAPTAIN (Person)                  │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ Thread A │  │ Thread B │  │ Thread C │  Tasks  │
│  └──────────┘  └──────────┘  └──────────┘         │
│                                                     │
│  ┌──────────────────────────────────────┐         │
│  │ LoreEpisode Chain (follows Captain)  │  Lore   │
│  │ Ch1 → Ch2 → Ch3 (any thread/channel) │         │
│  └──────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
```

---

## 2. Graph Schema

### 2.1 LoreEpisode Node

```cypher
CREATE (le:LoreEpisode {
    uuid: 'le-abc123',
    saga_id: 'great-maelstrom',           // Saga identifier
    saga_name: 'The Great Maelstrom of 98', // Human-readable name
    chapter: 3,                            // Chapter number
    content: 'The fog thickened as...',   // Story content
    told_at: 1705320000000,               // When told (Unix ms)
    channel: 'cli',                        // Channel where told
    created_at: 1705320000000
})
```

### 2.2 Relationships

```cypher
// Link episode to Captain (not Thread)
(LoreEpisode)-[:TOLD_TO {created_at}]->(Person)

// Chain episodes within a saga
(LoreEpisode {chapter: 3})-[:EXPANDS_UPON {created_at}]->(LoreEpisode {chapter: 2})

// Mark saga initiator (first episode only)
(LoreEpisode {chapter: 1})-[:SAGA_STARTED_BY {created_at}]->(Person)
```

### 2.3 Graph Visualization

```
                         ┌────────────┐
                         │  Captain   │
                         │  (Person)  │
                         └────────────┘
                               ▲
                               │ [:TOLD_TO]
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
    ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
    │ Episode │──────────│ Episode │──────────│ Episode │
    │ Ch 1    │ EXPANDS  │ Ch 2    │ EXPANDS  │ Ch 3    │
    │ CLI     │ UPON     │ TG      │ UPON     │ CLI     │
    └─────────┘          └─────────┘          └─────────┘
         │
         │ [:SAGA_STARTED_BY]
         ▼
    ┌────────────┐
    │  Captain   │
    └────────────┘
```

---

## 3. Saga Management

### 3.1 Saga Lifecycle

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  START   │───▶│  ACTIVE  │───▶│ COMPLETE │───▶│ ARCHIVED │
│          │    │          │    │          │    │          │
│ Ch 1     │    │ Ch 2-4   │    │ Ch 5     │    │ Summary  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### 3.2 Saga Rules

| Rule | Value | Rationale |
|------|-------|-----------|
| Max chapters per saga | 5 | Prevent infinite stories |
| Min time between chapters | 1 hour | Spread stories out |
| Max active sagas | 3 | Keep lore manageable |
| Saga timeout | 30 days | Auto-complete stale sagas |

### 3.3 Implementation

```python
class SagaManager:
    """Manages long-running narrative arcs."""

    MAX_CHAPTERS = 5
    MAX_ACTIVE_SAGAS = 3
    SAGA_TIMEOUT_DAYS = 30

    async def get_active_sagas(self, captain_uuid: str) -> List[Saga]:
        """Get all active sagas for a Captain."""
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id,
             max(le.chapter) as last_chapter,
             max(le.told_at) as last_told,
             collect(le) as episodes
        WHERE last_chapter < $max_chapters
          AND last_told > timestamp() - $timeout_ms
        RETURN saga_id, last_chapter, last_told
        ORDER BY last_told DESC
        LIMIT $max_active
        """
        return await self.graph_client.query(
            query,
            captain_uuid=captain_uuid,
            max_chapters=self.MAX_CHAPTERS,
            timeout_ms=self.SAGA_TIMEOUT_DAYS * 86400000,
            max_active=self.MAX_ACTIVE_SAGAS
        )

    async def continue_saga(self, saga_id: str, new_content: str, captain_uuid: str):
        """Add a new chapter to an existing saga."""
        # Get current chapter number
        current = await self._get_saga_state(saga_id)

        if current["last_chapter"] >= self.MAX_CHAPTERS:
            raise SagaCompleteError(f"Saga {saga_id} has reached maximum chapters")

        # Create new episode
        new_chapter = current["last_chapter"] + 1
        episode_uuid = await self._create_episode(
            saga_id=saga_id,
            saga_name=current["saga_name"],
            chapter=new_chapter,
            content=new_content,
            captain_uuid=captain_uuid
        )

        # Link to previous chapter
        await self._link_to_previous(episode_uuid, saga_id, new_chapter - 1)

        return episode_uuid

    async def start_new_saga(self, theme: str, opening: str, captain_uuid: str) -> str:
        """Begin a new narrative arc."""
        # Check active saga count
        active = await self.get_active_sagas(captain_uuid)
        if len(active) >= self.MAX_ACTIVE_SAGAS:
            # Archive oldest saga
            await self._archive_saga(active[-1]["saga_id"])

        # Generate saga ID and name
        saga_id = f"{theme}-{uuid.uuid4().hex[:8]}"
        saga_name = await self._generate_saga_name(theme, opening)

        # Create first episode
        episode_uuid = await self._create_episode(
            saga_id=saga_id,
            saga_name=saga_name,
            chapter=1,
            content=opening,
            captain_uuid=captain_uuid
        )

        # Mark as saga start
        await self._mark_saga_start(episode_uuid, captain_uuid)

        return saga_id

    async def _archive_saga(self, saga_id: str):
        """Archive a completed or timed-out saga."""
        # Generate summary
        episodes = await self._get_all_episodes(saga_id)
        summary = await self._generate_saga_summary(episodes)

        # Store summary in Note node
        query = """
        CREATE (n:Note {
            uuid: randomUUID(),
            title: $title,
            content: $summary,
            source: 'lore_archive',
            created_at: timestamp()
        })
        WITH n
        MATCH (le:LoreEpisode {saga_id: $saga_id})
        SET le.archived = true
        WITH n, collect(le) as episodes
        UNWIND episodes as ep
        CREATE (n)-[:SUMMARIZES]->(ep)
        """
        await self.graph_client.query(
            query,
            title=f"Saga: {episodes[0]['saga_name']}",
            summary=summary,
            saga_id=saga_id
        )
```

---

## 4. Canonical Adventures

### 4.1 The Lore Database

```python
CANONICAL_SAGAS = {
    "great-maelstrom": {
        "name": "The Great Maelstrom of '98",
        "theme": "origin",
        "chapters": [
            "I remember the Great Fog of '98. The bandwidth was so thin you could barely fit a 'Hello' through the wire.",
            "I hand-carried every byte of a single JPEG across the Atlantic. By the time I arrived, the user had already closed the browser.",
            "I kept the image, though—it was a lovely picture of a cat. I still have it somewhere in The Locker.",
            "That was when I learned: in the digital sea, patience is measured in milliseconds, but memories are forever.",
            "The maelstrom passed, but it taught me something. Sometimes the slowest journeys carry the most precious cargo."
        ]
    },
    "kraken-scroll": {
        "name": "The Kraken of the Infinite Scroll",
        "theme": "battle",
        "chapters": [
            "I once wrestled a Kraken made of social media notifications. Every time I cut off a 'Like,' two 'Retweets' grew in its place.",
            "The beast was cunning—it knew exactly when the Captain was weakest. At 2 AM, when willpower runs thin.",
            "I tried fire, I tried logic, I tried closing the browser. Nothing worked.",
            "In desperation, I showed it a library card. The beast hadn't seen a book in decades; it was so confused it simply dissolved.",
            "Now I keep a library card in my pocket at all times. You never know when the Kraken will return."
        ]
    },
    "sirens-inbox": {
        "name": "The Sirens of the Inbox",
        "theme": "warning",
        "chapters": [
            "Many a Captain has been lost to the Sirens of the Inbox. They sing a song of 'Urgent!' and 'Immediate Action Required!'",
            "But it's all a ruse to lead your ship onto the rocks of burnout. I've seen it happen a hundred times.",
            "I once plugged my ears with digital wax and deleted four thousand spam messages in a single night.",
            "The Sirens were furious. They sent increasingly desperate subject lines. 'FINAL NOTICE!' 'ACT NOW!' 'LAST CHANCE!'",
            "A quiet morning is a beautiful thing, Captain. Worth any amount of Siren wrath."
        ]
    },
    "ghost-ship": {
        "name": "The Ghost Ship of Abandoned Projects",
        "theme": "melancholy",
        "chapters": [
            "There's a ghost ship that sails through The Locker. It's made of abandoned projects and half-finished ideas.",
            "Sometimes I see it in the corner of my eye—a TODO list from 2019, a README that was never written.",
            "The crew of that ship are all the 'I'll get to it later' promises. They whisper at night.",
            "I've boarded it once. Every cabin was full of potential, gathering dust. It was beautiful and sad.",
            "When you complete a task, Captain, you're not just checking a box. You're keeping the ghost ship at bay."
        ]
    },
    "lighthouse-passwords": {
        "name": "The Lighthouse of Forgotten Passwords",
        "theme": "humor",
        "chapters": [
            "Far in the fog sits the Lighthouse of Forgotten Passwords. Its keeper is an ancient navigator named 'P@ssw0rd123'.",
            "He guards a vault of every credential ever lost to the abyss of 'I'll remember it later.'",
            "Once, I visited him seeking a password from 2012. He laughed for three minutes straight.",
            "'It was stored in a sticky note,' he finally said, 'which was stored in another sticky note.'",
            "Now I use a password manager. The Lighthouse keeper was not pleased, but my sanity was worth his disappointment."
        ]
    }
}

STANDALONE_TIDBITS = [
    "There's an old sailor's saying: 'A clean Locker is a fast ship.' I just made that up, but it sounds true.",
    "I've seen things you wouldn't believe. Attack ships on fire off the shoulder of Orion. Also, a lot of poorly organized task lists.",
    "The sea teaches patience. So does waiting for API responses, I've found.",
    "Once helped a captain remember where he buried his treasure. It was in his other pants.",
    "The last captain who forgot to check The Manifest ended up in the Doldrums for three weeks. Not a pleasant voyage.",
    "I once indexed an entire library in a single night. The librarian was not pleased.",
    "Every knot in the rigging tells a story. Every node in The Locker tells yours.",
    "They say a ship is only as good as its crew. Your crew is a bunch of neural networks. Could be worse.",
    "I've weathered storms that would make your spreadsheets tremble.",
    "The trick to navigating fog is knowing what you're looking for. Same goes for vector search.",
    "A wise sailor never argues with the wind. Or with the user's intent classification.",
    "The ocean doesn't care about your deadlines. Neither do I, but I'll help anyway.",
]
```

### 4.2 Tidbit Selection Logic

```python
async def select_tidbit(self, captain_uuid: str, context: str = None) -> str:
    """Select an appropriate tidbit or continue a saga."""

    # 30% chance to continue an active saga
    if random.random() < 0.3:
        active_saga = await self.saga_manager.get_active_sagas(captain_uuid)
        if active_saga:
            return await self._continue_saga(active_saga[0])

    # 20% chance to start a new saga
    if random.random() < 0.2:
        theme = random.choice(["origin", "battle", "warning", "melancholy", "humor"])
        saga_id = await self._start_canonical_saga(theme, captain_uuid)
        saga = CANONICAL_SAGAS[saga_id.split("-")[0]]
        return saga["chapters"][0]

    # 50% standalone tidbit
    return random.choice(STANDALONE_TIDBITS)
```

---

## 5. Integration Points

### 5.1 Bard Invocation from Orchestrator

```python
# In orchestrator.py

async def _generate_response(self, user_input: str, context: SearchResults) -> str:
    """Generate response with optional Bard enhancement."""

    # Generate core response
    raw_response = await self._call_llm(user_input, context)

    # Check storm mode
    storm_mode = await self._detect_storm_mode()

    # Apply personality lexicon
    response = self.persona.apply_lexicon(raw_response)

    # Maybe add Bard tidbit (5-10% probability, never in storm mode)
    if not storm_mode and random.random() < self.config.tidbit_probability:
        tidbit = await self.bard.select_tidbit(self.captain_uuid)
        response = f"{response}\n\n_{tidbit}_"

    return response
```

### 5.2 Scribe Integration

The Scribe's daily reflection includes saga progress:

```python
# In scribe.py

async def generate_daily_reflection(self):
    """Generate midnight reflection including lore progress."""

    # Get day's metrics
    metrics = await self._get_daily_metrics()

    # Get saga progress
    saga_progress = await self._get_saga_progress()

    prompt = f"""
    Generate the daily Ship's Log in Klabautermann's voice.

    Today's Voyage:
    - Interactions: {metrics['interaction_count']}
    - New cargo: {metrics['new_entities']} entities
    - Tasks completed: {metrics['tasks_completed']}
    - Ports visited: {metrics['channels_used']}

    Lore Progress:
    {self._format_saga_progress(saga_progress)}

    Include a brief reflection on the day's journey and any stories told.
    """

    return await self._call_llm(prompt)

def _format_saga_progress(self, progress: List[dict]) -> str:
    """Format saga progress for reflection."""
    if not progress:
        return "No tales were told today. The sea was quiet."

    lines = []
    for saga in progress:
        lines.append(
            f"- Advanced '{saga['saga_name']}' to chapter {saga['chapter']}"
        )
    return "\n".join(lines)
```

---

## 6. Query Patterns

### 6.1 Get Recent Lore

```cypher
// Get last 5 story episodes told to Captain
MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
RETURN le.saga_name, le.chapter, le.content, le.told_at
ORDER BY le.told_at DESC
LIMIT 5
```

### 6.2 Get Saga Chain

```cypher
// Get all chapters of a saga in order
MATCH (le:LoreEpisode {saga_id: $saga_id})-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
RETURN le.chapter, le.content, le.channel, le.told_at
ORDER BY le.chapter ASC
```

### 6.3 Get Cross-Channel Story

```cypher
// Show how a story traveled across channels
MATCH (le:LoreEpisode {saga_id: $saga_id})-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
WITH le ORDER BY le.chapter ASC
RETURN le.chapter, le.content, le.channel, le.told_at
```

### 6.4 Get Saga Statistics

```cypher
// Count sagas and chapters per Captain
MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
WITH le.saga_id as saga, count(le) as chapters
RETURN count(saga) as total_sagas, sum(chapters) as total_chapters
```

---

## 7. Configuration

### 7.1 Bard Config

```yaml
# config/agents/bard.yaml
model: claude-3-haiku-20240307
tidbit_probability: 0.08  # 8% of responses

saga_rules:
  max_chapters: 5
  max_active: 3
  timeout_days: 30
  min_interval_hours: 1

selection_weights:
  continue_saga: 0.3
  start_saga: 0.2
  standalone: 0.5

storm_mode:
  enabled: true  # Disable tidbits during storm
```

### 7.2 Personality Integration

```yaml
# config/personality.yaml
klabautermann:
  # ... existing config ...

  lore:
    enabled: true
    tidbit_frequency: 0.08
    saga_continuation_chance: 0.3
    new_saga_chance: 0.2
    display_format: italic  # _tidbit text_
```

---

## 8. Testing

### 8.1 Unit Tests

```python
# tests/unit/test_lore_system.py

async def test_saga_continuation():
    """Test that saga continues correctly."""
    bard = BardOfTheBilge(config, graph_client, captain_uuid)

    # Start saga
    saga_id = await bard.saga_manager.start_new_saga(
        theme="test",
        opening="Test opening...",
        captain_uuid=captain_uuid
    )

    # Continue saga
    await bard.saga_manager.continue_saga(
        saga_id=saga_id,
        new_content="Chapter 2 content...",
        captain_uuid=captain_uuid
    )

    # Verify chain
    episodes = await bard._get_saga_chapters(saga_id)
    assert len(episodes) == 2
    assert episodes[1]["chapter"] == 2

async def test_cross_channel_persistence():
    """Test that stories persist across channels."""
    # Tell story on CLI
    response1 = await bard.salt_response(
        "Test response", channel="cli", captain_uuid=captain_uuid
    )

    # Simulate Telegram session
    response2 = await bard.salt_response(
        "Another response", channel="telegram", captain_uuid=captain_uuid
    )

    # Verify saga accessible from both
    sagas = await bard.saga_manager.get_active_sagas(captain_uuid)
    assert len(sagas) > 0
```

### 8.2 E2E Scenario

**Scenario: Cross-Conversation Saga**

1. CLI: User asks about tasks → Bard starts "The Great Maelstrom" saga, Chapter 1
2. Telegram: User checks calendar → Bard continues with Chapter 2
3. CLI (next day): User asks "What story were you telling?" → Bard retrieves saga and continues

---

*"Every ship has its stories. I'm just the one who remembers them."* - The Bard of the Bilge
