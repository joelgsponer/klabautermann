# Add Thread Persistence to CLI

## Metadata
- **ID**: T015
- **Priority**: P1
- **Category**: channel
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CHANNELS.md](../../specs/architecture/CHANNELS.md)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)

## Dependencies
- [ ] T011 - Thread manager
- [ ] T014 - CLI driver

## Context
For the Orchestrator to maintain conversational context, messages must be persisted to the graph. This task enhances the CLI driver to use the Thread Manager for storing and retrieving conversation history.

## Requirements
- [ ] Enhance `CLIDriver` in `src/klabautermann/channels/cli_driver.py`:

### On Start
- [ ] Call `thread_manager.get_or_create_thread()` to initialize thread
- [ ] Load existing context window if thread exists (session recovery)
- [ ] Pass thread context to orchestrator

### On Message
- [ ] Store user message via `thread_manager.add_message()`
- [ ] Store assistant response via `thread_manager.add_message()`
- [ ] Update thread's last_message_at

### Context Window
- [ ] Before calling orchestrator, load context window
- [ ] Pass context to orchestrator for response generation
- [ ] Context window size: 15-20 messages (configurable)

### Session Persistence
- [ ] Option to resume previous session (by session ID)
- [ ] Default: create new session each time

## Acceptance Criteria
- [ ] Messages appear in Neo4j as Message nodes
- [ ] Messages linked to Thread via [:CONTAINS]
- [ ] Messages linked via [:PRECEDES] chain
- [ ] Restart CLI, ask "what did I just say?" - agent remembers (if same session)
- [ ] New session starts fresh context

## Implementation Notes

```python
class CLIDriver(BaseChannel):
    """Enhanced CLI driver with thread persistence."""

    def __init__(
        self,
        orchestrator: Any,
        thread_manager: ThreadManager,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(orchestrator, config)
        self.thread_manager = thread_manager
        self.session_id = config.get("session_id") or str(uuid.uuid4())
        self._thread: Optional[ThreadNode] = None
        self._running = False

    async def start(self) -> None:
        """Start CLI with thread initialization."""
        self._running = True

        # Initialize or recover thread
        self._thread = await self.thread_manager.get_or_create_thread(
            external_id=self.get_thread_id(),
            channel_type=self.channel_type,
        )

        # Check if resuming existing thread
        context = await self.thread_manager.get_context_window(
            self._thread.uuid,
            limit=5,  # Just peek at recent
        )
        if context.message_count > 0:
            print(f"Resuming session with {context.message_count} previous messages.\n")

        self._print_welcome()
        await self._run_loop()

    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Process message with persistence."""
        trace_id = str(uuid.uuid4())

        # Store user message
        await self.thread_manager.add_message(
            thread_uuid=self._thread.uuid,
            role="user",
            content=content,
            trace_id=trace_id,
        )

        # Load context window
        context = await self.thread_manager.get_context_window(
            self._thread.uuid,
            limit=self.config.get("context_window_size", 15),
            trace_id=trace_id,
        )

        # Get response from orchestrator
        response = await self.orchestrator.handle_user_input(
            thread_id=thread_id,
            text=content,
            context=context,
            trace_id=trace_id,
        )

        # Store assistant response
        await self.thread_manager.add_message(
            thread_uuid=self._thread.uuid,
            role="assistant",
            content=response,
            trace_id=trace_id,
        )

        return response
```

Configuration options to support:
```python
config = {
    "session_id": None,  # Generate new if not provided
    "context_window_size": 15,  # Messages to include in context
}
```

Test by verifying graph state:
```cypher
MATCH (t:Thread {channel_type: 'cli'})-[:CONTAINS]->(m:Message)
RETURN t.external_id, m.role, m.content, m.timestamp
ORDER BY m.timestamp
```
