# Main Agent (Orchestrator v2) Specification

**Version**: 2.0
**Status**: Draft
**Purpose**: Define the next-generation orchestration pattern that replaces rigid intent classification with flexible multi-task parallel execution.

---

## 1. Motivation

### 1.1 Problem with Current Approach

The current orchestrator uses a 4-way intent classification (SEARCH, ACTION, INGESTION, CONVERSATION) which is **critically flawed**:

1. **Single-intent limitation**: Real user messages often contain multiple intents
2. **Premature routing**: Classification happens before understanding the full context
3. **Lost opportunities**: Information that could inform one task is separated from another
4. **Serial execution**: Even when multiple tasks are independent, they execute sequentially

**Example of the problem**:
```
User: "Learned that Sarah has studied at Harvard. Do I have a meeting with her next week for lunch? Does she like italian?"
```

Current system classifies this as ONE intent (likely INGESTION or SEARCH), missing:
- Ingestion task: "Sarah studied at Harvard"
- Calendar lookup: meetings next week with Sarah
- Knowledge search: events/notes about Sarah next week
- Knowledge search: Sarah's food preferences

### 1.2 Proposed Solution

Replace intent classification with a **Think-Dispatch-Synthesize** pattern where the orchestrator:
1. Receives context (messages + recent summaries)
2. Reasons about ALL tasks needed
3. Dispatches parallel subagents
4. Waits for results
5. Synthesizes a holistic response with proactive suggestions

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER MESSAGE                            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CONTEXT INJECTION                            │
│  • Last N messages from current thread                          │
│  • Summaries of recent threads (last 12 hours)                  │
│  • Active tasks/reminders                                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 ORCHESTRATOR (Claude Opus)                      │
│                                                                 │
│  <thinks>                                                       │
│    What does the user need? Let me identify ALL tasks:          │
│    1. Ingest fact: "Sarah studied at Harvard"                   │
│    2. Check calendar for meetings with Sarah next week          │
│    3. Search knowledge graph for Sarah-related events/notes     │
│    4. Search knowledge graph for Sarah's food preferences       │
│  </thinks>                                                      │
│                                                                 │
│  DISPATCH PARALLEL SUBAGENTS                                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   @ingestor   │     │   @executor     │     │  @researcher    │
│ "Sarah has    │     │ Check calendar  │     │ 1. Events with  │
│  studied at   │     │ for meetings    │     │    Sarah        │
│  Harvard"     │     │ next week       │     │ 2. Food prefs   │
└───────┬───────┘     └────────┬────────┘     └────────┬────────┘
        │                      │                       │
        │ (fire-and-forget)    │ (wait)               │ (wait)
        │                      │                       │
        └──────────────────────┼───────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR SYNTHESIS                       │
│                                                                 │
│  <thinks>                                                       │
│    Results:                                                     │
│    - Calendar: No formal meeting found                          │
│    - Note from yesterday: "Agreed to lunch with Sarah"          │
│    - Sarah likes italian food (from previous conversation)      │
│                                                                 │
│    User may have discussed this in person and forgot to record. │
│    Should suggest following up to confirm.                      │
│  </thinks>                                                      │
│                                                                 │
│  <answer>                                                       │
│    I don't see a calendar event, but you mentioned agreeing     │
│    to lunch with Sarah yesterday. She does like italian!        │
│    Should I follow up with her to confirm?                      │
│  </answer>                                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Principles

### 3.1 Chat Memory as Context

Before processing, inject relevant context:

| Context Type | Source | Purpose |
|--------------|--------|---------|
| Recent messages | ThreadManager.get_context_window(N=20) | Conversational continuity |
| Thread summaries | Note nodes from last 12 hours | Cross-thread awareness |
| Active tasks | Task nodes with status=pending | Proactive reminders |
| Recent entities | Entities created in last 24h | Fresh context |

### 3.2 Proactive Behavior

The orchestrator should:
- **Ask clarifications** when information is ambiguous
- **Suggest confirmations** before taking irreversible actions
- **Infer preferences** from historical patterns
- **Offer follow-ups** ("Should I add this to your calendar?")

### 3.3 Parallel Subagent Dispatch

The orchestrator identifies ALL tasks that can provide useful information, then spawns subagents in parallel:

| Agent | Use When | Blocking? |
|-------|----------|-----------|
| @ingestor | New information to store | No (fire-and-forget) |
| @researcher | Need to query knowledge graph | Yes (wait for results) |
| @executor | Need to check calendar/email | Yes (wait for results) |

### 3.4 Iterative Deepening

If initial results are insufficient, the orchestrator may spawn additional research rounds:

```
max_research_depth: int = 2  # Default: allow up to 2 follow-up rounds

Round 1: Initial parallel dispatch
Round 2: Follow-up queries based on Round 1 results
         (e.g., "Found Sarah works at Acme, now search for Acme contacts")
```

---

## 4. Detailed Workflow

### 4.1 Input Processing

```python
async def handle_user_input(
    self,
    text: str,
    thread_uuid: str,
    trace_id: str,
) -> str:
    # 1. Build rich context
    context = await self._build_context(thread_uuid, trace_id)

    # 2. Orchestrator thinks and plans tasks
    task_plan = await self._plan_tasks(text, context, trace_id)

    # 3. Execute tasks in parallel
    results = await self._execute_parallel(task_plan, trace_id)

    # 4. Optional: deepen research if needed
    if self._needs_deeper_research(results, task_plan):
        deeper_results = await self._deepen_research(results, trace_id)
        results = self._merge_results(results, deeper_results)

    # 5. Synthesize final response
    response = await self._synthesize_response(text, context, results, trace_id)

    return response
```

### 4.2 Context Building

Integrates with the Memory System's multi-level retrieval (see `specs/architecture/MEMORY.md` Section 9).

```python
class EnrichedContext(BaseModel):
    """Rich context for orchestrator reasoning."""

    thread_uuid: str
    channel_type: ChannelType

    # Recent messages in current thread (Short-Term Memory)
    messages: list[dict[str, Any]]

    # Summaries from other recent threads (Mid-Term Memory - Note nodes)
    recent_summaries: list[ThreadSummary]

    # Active tasks/reminders
    pending_tasks: list[TaskNode]

    # Recently mentioned entities (Long-Term Memory - Graphiti entities)
    recent_entities: list[EntityReference]

    # Knowledge Island context (Community detection)
    relevant_islands: list[CommunityContext] | None = None

class CommunityContext(BaseModel):
    """Summary of a Knowledge Island relevant to current context."""
    name: str
    theme: str
    summary: str
    pending_tasks: int

async def _build_context(self, thread_uuid: str, trace_id: str) -> EnrichedContext:
    """
    Build rich context by gathering from all memory layers in parallel.

    Memory Layers (from MEMORY.md):
    - Short-Term: Current thread messages (ThreadManager)
    - Mid-Term: Recent Note summaries from archived threads
    - Long-Term: Entity references from Graphiti
    - Community: Knowledge Island context for broad awareness
    """
    # Parallel context gathering from all memory layers
    messages, summaries, tasks, entities, islands = await asyncio.gather(
        self.thread_manager.get_context_window(thread_uuid, limit=20),
        self._get_recent_summaries(hours=12),  # Note nodes
        self._get_pending_tasks(),              # Task nodes
        self._get_recent_entities(hours=24),    # Graphiti entities
        self._get_relevant_islands(),           # Community nodes
    )

    return EnrichedContext(
        thread_uuid=thread_uuid,
        channel_type=channel_type,
        messages=messages.messages,
        recent_summaries=summaries,
        pending_tasks=tasks,
        recent_entities=entities,
        relevant_islands=islands,
    )

async def _get_recent_summaries(self, hours: int = 12) -> list[ThreadSummary]:
    """
    Retrieve Note nodes from recently archived threads.

    This provides cross-thread awareness - the orchestrator knows
    what was discussed in other channels/threads recently.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()

    async with self.driver.session() as session:
        result = await session.run(
            """
            MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread)
            WHERE n.created_at >= $cutoff
            OPTIONAL MATCH (n)<-[:MENTIONED_IN]-(p:Person)
            RETURN n.uuid as uuid,
                   n.title as title,
                   n.content_summarized as summary,
                   n.topics as topics,
                   t.channel_type as channel,
                   collect(DISTINCT p.name) as participants
            ORDER BY n.created_at DESC
            LIMIT 10
            """,
            {"cutoff": cutoff}
        )
        return [ThreadSummary(**r) for r in await result.data()]

async def _get_relevant_islands(self) -> list[CommunityContext]:
    """
    Get Knowledge Island summaries for broad context.

    Uses the Macro-level retrieval from MEMORY.md Section 9.2.
    """
    async with self.driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Community)
            WHERE EXISTS((c)<-[:PART_OF_ISLAND]-())

            // Get pending task count per island
            OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(t:Task {status: 'todo'})

            RETURN c.name as name,
                   c.theme as theme,
                   c.summary as summary,
                   count(t) as pending_tasks
            ORDER BY pending_tasks DESC
            LIMIT 5
            """,
            {}
        )
        return [CommunityContext(**r) for r in await result.data()]
```

### 4.3 Task Planning

The orchestrator uses Claude Opus to analyze the message and plan tasks:

```python
class PlannedTask(BaseModel):
    """A task identified by the orchestrator."""

    task_type: Literal["ingest", "research", "execute"]
    description: str
    agent: Literal["ingestor", "researcher", "executor"]
    payload: dict[str, Any]
    blocking: bool  # True if we need the result

class TaskPlan(BaseModel):
    """Orchestrator's plan for handling the user message."""

    reasoning: str  # Why these tasks were chosen
    tasks: list[PlannedTask]
    direct_response: str | None  # If no tasks needed, respond directly
```

**System Prompt for Task Planning**:
```
You are the Klabautermann Orchestrator analyzing a user message.

Given the user's message and context, identify ALL tasks that would help provide a complete answer.

For each piece of information the user provides or requests:
1. INGEST: New facts to store ("I learned X", "Sarah works at Y")
2. RESEARCH: Information to retrieve from the knowledge graph
3. EXECUTE: Actions requiring calendar/email access

Think step by step:
- What is the user telling me? (potential ingestion)
- What is the user asking? (potential research/execution)
- What related information might be useful? (proactive research)

Return a structured task plan. Be thorough - it's better to gather more context than to miss something.
```

### 4.4 Parallel Execution

```python
async def _execute_parallel(
    self,
    task_plan: TaskPlan,
    trace_id: str,
) -> dict[str, Any]:
    """Execute all planned tasks in parallel."""

    results = {}
    blocking_tasks = []

    for task in task_plan.tasks:
        if task.blocking:
            # Create coroutine for blocking task
            blocking_tasks.append(
                self._dispatch_and_wait(task.agent, task.payload, trace_id)
            )
        else:
            # Fire-and-forget for non-blocking tasks
            asyncio.create_task(
                self._dispatch_fire_and_forget(task.agent, task.payload, trace_id)
            )

    # Wait for all blocking tasks in parallel
    if blocking_tasks:
        task_results = await asyncio.gather(*blocking_tasks, return_exceptions=True)

        # Map results back to task descriptions
        for task, result in zip(
            [t for t in task_plan.tasks if t.blocking],
            task_results
        ):
            if isinstance(result, Exception):
                results[task.description] = {"error": str(result)}
            else:
                results[task.description] = result

    return results
```

### 4.5 Response Synthesis

After gathering all results, the orchestrator synthesizes a response:

```python
async def _synthesize_response(
    self,
    original_text: str,
    context: EnrichedContext,
    results: dict[str, Any],
    trace_id: str,
) -> str:
    """Synthesize final response from all gathered information."""

    synthesis_prompt = f"""
You are synthesizing a response for the user based on gathered information.

Original message: {original_text}

Context:
{self._format_context(context)}

Results from subagents:
{self._format_results(results)}

Instructions:
1. Answer the user's questions using the gathered information
2. If information is missing or uncertain, say so honestly
3. Be proactive - suggest follow-up actions if appropriate
4. If you ingested new information, briefly acknowledge it
5. Keep the response concise but complete
"""

    return await self._call_opus(synthesis_prompt, trace_id)
```

---

## 5. Subagent Contracts

### 5.1 Ingestor Contract

**Input**: Text containing information to extract and store
**Output**: None (fire-and-forget)
**Behavior**: Extract entities and relationships, store via Graphiti

```python
# Orchestrator dispatches
await self._dispatch_fire_and_forget(
    "ingestor",
    {"text": "Sarah has studied at Harvard", "trace_id": trace_id}
)
```

### 5.2 Researcher Contract

**Input**: Search query with optional constraints and zoom level
**Output**: SearchResponse with results and sources

The Researcher supports three zoom levels (from `MEMORY.md` Section 9):
- **MACRO**: Knowledge Island summaries for broad questions
- **MESO**: Project/Note level for thread context
- **MICRO**: Entity facts for specific queries

```python
# Orchestrator dispatches with automatic zoom selection
result = await self._dispatch_and_wait(
    "researcher",
    {
        "query": "What do I know about Sarah's food preferences?",
        "search_type": "semantic",  # or "structural", "temporal"
        "zoom_level": "auto",       # or "macro", "meso", "micro"
        "trace_id": trace_id
    }
)
# Returns: SearchResponse(results=[...], summary="...", zoom_level="micro")

# For broad questions, researcher returns island context
result = await self._dispatch_and_wait(
    "researcher",
    {
        "query": "What are my main priorities right now?",
        "zoom_level": "macro",  # Explicitly request island-level view
        "trace_id": trace_id
    }
)
# Returns: SearchResponse with Knowledge Island summaries
```

The Researcher uses GraphRAG (from `MEMORY.md` Section 6):
1. **Vector search** finds entry point into the graph
2. **Graph traversal** expands context around that entry point
3. Returns facts with source attribution and confidence scores

### 5.3 Executor Contract

**Input**: Action request with context
**Output**: ActionResult with success status and data

```python
# Orchestrator dispatches
result = await self._dispatch_and_wait(
    "executor",
    {
        "action": "calendar_search",
        "params": {
            "query": "lunch with Sarah",
            "time_range": "next_week"
        },
        "trace_id": trace_id
    }
)
# Returns: ActionResult(success=True, data={"events": [...]})
```

---

## 6. Model Selection

| Component | Model | Rationale |
|-----------|-------|-----------|
| Orchestrator (planning) | Claude Opus | Complex reasoning, multi-task identification |
| Orchestrator (synthesis) | Claude Opus | Nuanced response generation |
| Ingestor | Claude Haiku | Pattern-based extraction |
| Researcher | Claude Haiku | Query construction |
| Executor | Claude Sonnet | Action reasoning, MCP interaction |

---

## 7. Configuration

```yaml
# config/agents/orchestrator_v2.yaml
model: claude-opus-4-5-20251101
synthesis_model: claude-opus-4-5-20251101

context:
  message_window: 20
  summary_hours: 12
  include_pending_tasks: true
  include_recent_entities: true
  recent_entity_hours: 24

execution:
  max_research_depth: 2
  parallel_timeout_seconds: 30
  fire_and_forget_timeout_seconds: 60

proactive_behavior:
  suggest_calendar_events: true
  suggest_follow_ups: true
  ask_clarifications: true
```

---

## 8. Example Flows

### 8.1 Multi-Intent Message

**User**: "Learned that Sarah has studied at Harvard. Do I have a meeting with her next week for lunch? Does she like italian?"

**Orchestrator thinks**:
```
Tasks identified:
1. INGEST: "Sarah studied at Harvard" → @ingestor (fire-and-forget)
2. EXECUTE: Check calendar for meetings with Sarah next week → @executor (wait)
3. RESEARCH: Events/notes about Sarah next week → @researcher (wait)
4. RESEARCH: Sarah's food preferences → @researcher (wait)
```

**Parallel execution**:
- Ingestor receives "Sarah studied at Harvard" (non-blocking)
- Executor searches calendar (blocking)
- Researcher searches for Sarah events (blocking)
- Researcher searches for food preferences (blocking)

**Results**:
- Calendar: No formal meeting found
- Events: Note from yesterday "Agreed to lunch with Sarah next week"
- Preferences: "Sarah mentioned she loves italian food"

**Synthesized response**:
```
I don't see a calendar event, but you did mention yesterday agreeing to
lunch with Sarah next week. And yes - she does like italian!

Should I follow up with her to confirm the details?
```

### 8.2 Follow-Up: User Confirms

**User**: "Oh yes let's follow up with her."

**Orchestrator thinks**:
```
Tasks identified:
1. RESEARCH: Get Sarah's email address → @researcher (wait)
2. EXECUTE: Draft email to Sarah → @executor (wait)
```

**Synthesized response**:
```
How about this:

  Dear Sarah,

  Still up for lunch next week? How about italian?

  Best,
  [Your Name]

Want me to send this?
```

### 8.3 Proactive Calendar Suggestion

**User**: "Oh now I remember, no all good."

**Orchestrator thinks**:
```
No blocking tasks needed. But user hasn't created calendar event.
Proactive suggestion appropriate.
```

**Response**:
```
Alright! In case the lunch is still on, she does like italian.

Do you want me to add an event to your calendar?
```

---

## 9. Migration Path

### 9.3 Phase 3: Full Replacement (High Impact)

Replace intent classification entirely with task planning:
- Remove IntentClassification enum
- Remove _classify_intent method
- Implement full Think-Dispatch-Synthesize pattern

---

## 10. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Multi-intent handling | 0% (misses secondary intents) | 95% |
| Parallel execution | Sequential | All independent tasks parallel |
| Proactive suggestions | Rare | Natural where appropriate |
| Average response latency | ~3s | ~2s (parallel gains) |
| Context utilization | Messages only | Messages + summaries + tasks |

---

## 11. Memory System Integration

This specification builds upon the Memory System defined in `specs/architecture/MEMORY.md`.

### 11.1 Memory Layer Mapping

| Memory Layer | Usage in Main Agent | Retrieval Pattern |
|--------------|---------------------|-------------------|
| **Short-Term** (Messages) | Current conversation context | `ThreadManager.get_context_window()` |
| **Mid-Term** (Notes) | Cross-thread summaries | Query Note nodes with `[:SUMMARY_OF]` |
| **Long-Term** (Entities) | Entity facts, relationships | Graphiti search + Cypher traversal |
| **Community** (Islands) | Broad life context | Query Community nodes |

### 11.2 Zoom Level Usage

The orchestrator leverages zoom levels when dispatching to the Researcher:

| Query Type | Zoom Level | Memory Layer |
|------------|------------|--------------|
| "What are my priorities?" | MACRO | Community nodes |
| "Status of Q1 budget?" | MESO | Note + Project nodes |
| "What's Sarah's email?" | MICRO | Entity facts |

### 11.3 Context Injection Template

The orchestrator injects context in a structured format:

```xml
<context>
  <thread>
    <!-- Last N messages from ThreadManager -->
    <message role="user" timestamp="...">...</message>
    <message role="assistant" timestamp="...">...</message>
  </thread>

  <recent_summaries>
    <!-- Note nodes from last 12 hours -->
    <summary channel="telegram" participants="Sarah, John">
      Discussed Q1 budget approval...
    </summary>
  </recent_summaries>

  <pending_tasks>
    <!-- Task nodes with status=pending -->
    <task priority="high">Send budget to Sarah</task>
  </pending_tasks>

  <islands>
    <!-- Knowledge Island summaries -->
    <island name="Work Island" pending_tasks="12">
      Professional activities and career...
    </island>
  </islands>
</context>
```

### 11.4 Temporal Awareness

The orchestrator respects temporal semantics from the memory system:
- Relationships have `created_at` and `expired_at` timestamps
- "Time travel" queries use `as_of` parameter
- Status changes ("no longer works at") trigger relationship expiration

---

## 12. Open Questions

1. **Opus Cost**: Using Opus for planning increases cost. Should we use Sonnet for simple messages and escalate to Opus only for complex ones?

2. **Depth Limits**: How do we prevent infinite research loops? Current proposal: max_research_depth=2

3. **Proactive Boundaries**: When is proactive suggestion helpful vs annoying? Need user preference settings?

4. **Task Deduplication**: If two tasks would query similar information, should we merge them?

5. **Zoom Level Hints**: Should the orchestrator hint the zoom level based on task plan, or let the Researcher auto-detect?

6. **Cross-Channel Summary Relevance**: How do we filter recent summaries to only show contextually relevant ones?

---

## 13. Related Specifications

- `specs/architecture/MEMORY.md` - Memory system, GraphRAG, zoom mechanics
- `specs/architecture/AGENTS.md` - Current agent roster and communication patterns
- `specs/architecture/AGENTS_EXTENDED.md` - Secondary crew (Bard, Archivist, etc.)
- `specs/architecture/ONTOLOGY.md` - Entity types and relationship definitions

---

*"A captain sees all the tasks before him, not just the nearest wave."* - Klabautermann
