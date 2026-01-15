# Archivist Agent Skeleton

## Metadata
- **ID**: T040
- **Priority**: P0
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.5 (The Archivist)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 3 (Thread Management)

## Dependencies
- [x] T016 - Base Agent class
- [x] T036 - Cooldown Detection Query
- [x] T037 - Thread Status Lifecycle
- [x] T038 - Thread Summary Models
- [x] T039 - LLM Summarization Pipeline

## Context
The Archivist is the "Janitor" that maintains the knowledge graph. It scans for inactive threads, summarizes them, and prunes original messages. This task creates the agent class that orchestrates the archival pipeline, connecting all the pieces built in previous tasks.

## Requirements
- [ ] Create `src/klabautermann/agents/archivist.py`:

### Class Structure
- [ ] Inherit from `BaseAgent`
- [ ] Initialize with graph client, config, and optional thread_manager
- [ ] Model: Claude 3 Haiku (cost-effective for summarization)

### Core Methods
- [ ] `scan_for_inactive_threads() -> list[str]`
  - Call cooldown detection query
  - Return list of thread UUIDs ready for archival

- [ ] `archive_thread(thread_uuid: str) -> Optional[str]`
  - Mark thread as archiving (with lock)
  - Fetch all messages
  - Call summarization pipeline
  - Create Note node from summary
  - Link Note to Thread and Day
  - Prune messages
  - Mark thread as archived
  - Return Note UUID on success, None on failure

- [ ] `process_archival_queue() -> int`
  - Get inactive threads
  - Archive each one sequentially
  - Return count of successfully archived threads

### Integration Points
- [ ] `_fetch_thread_messages(thread_uuid: str) -> list[dict]`
  - Use ThreadManager.get_full_thread()

- [ ] `_create_summary_note(thread_uuid: str, summary: ThreadSummary) -> str`
  - Delegate to graph queries (T041)

- [ ] `_prune_messages(thread_uuid: str) -> None`
  - Delegate to message pruning (T043)

### Error Handling
- [ ] If archival fails mid-process, reactivate thread
- [ ] Log all archival attempts with trace_id
- [ ] Never leave thread in inconsistent state

### Configuration
- [ ] Load from `config/agents/archivist.yaml`
- [ ] Configurable cooldown_minutes (default: 60)
- [ ] Configurable max_threads_per_scan (default: 10)

## Acceptance Criteria
- [ ] Agent inherits from BaseAgent
- [ ] Can scan for inactive threads
- [ ] Can archive a single thread (stub graph operations)
- [ ] Handles archival failures gracefully
- [ ] Reactivates thread on failure
- [ ] All operations logged with trace_id
- [ ] Unit tests with mocked dependencies

## Implementation Notes

```python
class Archivist(BaseAgent):
    """
    The Archivist - keeper of The Locker's long-term memory.

    Responsibilities:
    1. Scan for inactive threads (60+ minutes cooldown)
    2. Summarize threads into Note nodes
    3. Prune original messages after archival
    4. Detect and flag entity duplicates
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        graph_client: GraphitiClient,
        thread_manager: ThreadManager,
        **kwargs
    ):
        super().__init__(name="archivist", config_manager=config_manager, **kwargs)
        self.graph = graph_client
        self.thread_manager = thread_manager
        self.config = self._load_config()

    async def archive_thread(self, thread_uuid: str) -> Optional[str]:
        """Archive a single thread, returning Note UUID on success."""
        trace_id = str(uuid.uuid4())

        # 1. Mark as archiving (atomic lock)
        if not await self.thread_manager.mark_archiving(thread_uuid):
            logger.info(f"[CHART] {trace_id} | Thread {thread_uuid} not available for archival")
            return None

        try:
            # 2. Fetch all messages
            messages = await self.thread_manager.get_full_thread(thread_uuid)
            if not messages:
                logger.warning(f"[SWELL] {trace_id} | Thread {thread_uuid} has no messages")
                await self.thread_manager.reactivate_thread(thread_uuid)
                return None

            # 3. Summarize
            summary = await summarize_thread(messages)

            # 4. Create Note node
            note_uuid = await self._create_summary_note(thread_uuid, summary, trace_id)

            # 5. Mark archived and link summary
            await self.thread_manager.mark_archived(thread_uuid, note_uuid)

            # 6. Prune messages (after successful archival)
            await self._prune_messages(thread_uuid)

            logger.info(f"[BEACON] {trace_id} | Archived thread {thread_uuid} -> Note {note_uuid}")
            return note_uuid

        except Exception as e:
            logger.error(f"[STORM] {trace_id} | Archival failed for {thread_uuid}: {e}")
            await self.thread_manager.reactivate_thread(thread_uuid)
            return None
```

### Config File (config/agents/archivist.yaml)
```yaml
model: claude-3-haiku-20240307
cooldown_minutes: 60
max_threads_per_scan: 10
summarization:
  max_message_length: 1000
  include_timestamps: true
```
