# Scribe Agent Implementation

## Metadata
- **ID**: T046
- **Priority**: P1
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.6 (The Scribe)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 5 (Day Nodes)

## Dependencies
- [x] T016 - Base Agent class
- [x] T044 - Scribe Analytics Queries
- [x] T045 - Journal Generation Pipeline
- [x] T042 - Day Node Management

## Context
The Scribe is the "Historian" that generates daily reflections. It runs at midnight, gathers the day's statistics, and creates a JournalEntry node linked to the Day. The journal serves as a high-level summary of activity, written in Klabautermann's distinctive voice.

## Requirements
- [ ] Create `src/klabautermann/agents/scribe.py`:

### Class Structure
- [ ] Inherit from `BaseAgent`
- [ ] Initialize with graph client and config
- [ ] Model: Claude 3 Haiku

### Core Methods
- [ ] `generate_daily_reflection(date: Optional[str] = None) -> str`
  - Default to yesterday's date (for midnight runs)
  - Gather analytics for the day
  - Call journal generation pipeline
  - Create JournalEntry node
  - Link to Day node
  - Return JournalEntry UUID

- [ ] `get_recent_journals(days: int = 7) -> list[dict]`
  - Retrieve recent journal entries
  - Used for context/continuity

### JournalEntry Node Creation
- [ ] `_create_journal_node(date: str, journal: JournalEntry) -> str`
  - Create JournalEntry node with all fields
  - Link to Day via [:OCCURRED_ON]
  - Store analytics snapshot for reference

### Integration with Scheduler
- [ ] Method designed to be called by APScheduler
- [ ] Idempotent: check if journal already exists for date
- [ ] Skip generation if already done (prevent duplicates)

### Configuration
- [ ] Load from `config/agents/scribe.yaml`
- [ ] Configurable generation time (default: midnight)
- [ ] Configurable minimum activity threshold

## Acceptance Criteria
- [ ] Agent inherits from BaseAgent
- [ ] Generates reflection for specified date
- [ ] Creates JournalEntry node in graph
- [ ] Links to correct Day node
- [ ] Idempotent (no duplicate journals)
- [ ] All operations logged with trace_id
- [ ] Unit tests with mocked dependencies

## Implementation Notes

```python
class Scribe(BaseAgent):
    """
    The Scribe - chronicler of the daily voyage.

    Responsibilities:
    1. Run at midnight (scheduled via APScheduler)
    2. Query the day's activity statistics
    3. Generate journal entry with Klabautermann personality
    4. Create JournalEntry node linked to Day
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        graph_client: GraphitiClient,
        driver: AsyncDriver,
        **kwargs
    ):
        super().__init__(name="scribe", config_manager=config_manager, **kwargs)
        self.graph = graph_client
        self.driver = driver
        self.config = self._load_config()

    async def generate_daily_reflection(
        self,
        date: Optional[str] = None
    ) -> Optional[str]:
        """Generate daily reflection journal entry."""
        trace_id = str(uuid.uuid4())

        # Default to yesterday for midnight runs
        if date is None:
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            date = yesterday.strftime("%Y-%m-%d")

        # Check if journal already exists
        if await self._journal_exists(date):
            logger.info(f"[CHART] {trace_id} | Journal already exists for {date}")
            return None

        # Gather analytics
        analytics = await get_daily_analytics(self.driver, date)

        # Check minimum activity threshold
        if analytics.interaction_count < self.config.get("min_interactions", 1):
            logger.info(f"[WHISPER] {trace_id} | Skipping {date}: insufficient activity")
            return None

        # Generate journal
        journal = await generate_journal(analytics)

        # Create node
        journal_uuid = await self._create_journal_node(date, journal, analytics)

        logger.info(f"[BEACON] {trace_id} | Created journal {journal_uuid} for {date}")
        return journal_uuid

    async def _journal_exists(self, date: str) -> bool:
        """Check if journal already exists for date."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (j:JournalEntry)-[:OCCURRED_ON]->(d:Day {date: $date})
                RETURN j.uuid
                """,
                {"date": date}
            )
            return await result.single() is not None

    async def _create_journal_node(
        self,
        date: str,
        journal: JournalEntry,
        analytics: DailyAnalytics
    ) -> str:
        """Create JournalEntry node and link to Day."""
        journal_uuid = str(uuid.uuid4())

        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (d:Day {date: $date})
                CREATE (j:JournalEntry {
                    uuid: $uuid,
                    content: $content,
                    summary: $summary,
                    mood: $mood,
                    forward_look: $forward_look,
                    interaction_count: $interaction_count,
                    tasks_completed: $tasks_completed,
                    new_entities_count: $new_entities_count,
                    generated_at: timestamp()
                })
                CREATE (j)-[:OCCURRED_ON]->(d)
                """,
                {
                    "date": date,
                    "uuid": journal_uuid,
                    "content": journal.content,
                    "summary": journal.summary,
                    "mood": journal.mood,
                    "forward_look": journal.forward_look,
                    "interaction_count": analytics.interaction_count,
                    "tasks_completed": analytics.tasks_completed,
                    "new_entities_count": sum(analytics.new_entities.values())
                }
            )

        return journal_uuid
```

### Config File (config/agents/scribe.yaml)
```yaml
model: claude-3-haiku-20240307
schedule:
  hour: 0
  minute: 0
min_interactions: 1
journal:
  include_highlights: true
  max_content_length: 2000
```
