# Klabautermann Multi-Agent Architecture

**Version**: 1.0
**Purpose**: Design and implementation guide for the multi-agent system

---

## Overview

Klabautermann employs a **Leader-Follower architecture** where a central Orchestrator delegates to specialized sub-agents. Each agent has a distinct role, model assignment, and tool access—enabling cost optimization, failure isolation, and clear separation of concerns.

The crew is divided into two tiers:
- **Primary Crew (6 agents)**: Core operational agents documented in this file
- **Secondary Crew (6 agents)**: Specialized utility agents documented in [AGENTS_EXTENDED.md](./AGENTS_EXTENDED.md)

```
                                    ┌───────────────┐
                                    │    User       │
                                    └───────┬───────┘
                                            │
                                    ┌───────▼───────┐
                                    │  Orchestrator │ (Claude 3.5 Sonnet)
                                    │   "The CEO"   │
                                    └───────┬───────┘
                                            │
    ┌─────────────┬─────────────────────────┼─────────────────────────┬─────────────┐
    │             │                         │                         │             │
    │    PRIMARY CREW                       │                    SECONDARY CREW     │
    │    ═══════════                        │                    ═══════════════    │
    │                                       │                                       │
┌───▼────┐ ┌─────────┐ ┌─────────┐ ┌───────▼───────┐ ┌──────────┐ ┌─────────────┐
│Ingestor│ │Researcher│ │Executor │ │  Archivist   │ │ Scribe   │ │    Bard     │
│ (Haiku)│ │ (Haiku) │ │(Sonnet) │ │   (Haiku)    │ │ (Haiku)  │ │  (Haiku)    │
└────────┘ └─────────┘ └─────────┘ └──────────────┘ └──────────┘ └─────────────┘
                                                                        │
    ┌───────────────────────────────────────────────────────────────────┘
    │
    │  UTILITY AGENTS (Background/Scheduled)
    │  ══════════════════════════════════════
    │
┌───▼────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────────┐
│ Purser │ │ Officer │ │Cartograph│ │ Hull Cleaner │ │Quartermaster│
│ (None) │ │ (Haiku) │ │  (None)  │ │   (None)     │ │   (None)    │
└────────┘ └─────────┘ └──────────┘ └──────────────┘ └─────────────┘
```

---

## 1. Agent Roster

### 1.1 The Orchestrator

**Role**: The "CEO" that receives all user input, plans tasks, dispatches parallel subagents, and synthesizes coherent responses.

| Attribute | Value |
|-----------|-------|
| **Model** | Claude Opus 4.5 |
| **Rationale** | Complex reasoning required for multi-task planning and response synthesis |
| **MCP Access** | Delegates to Executor |
| **Graph Access** | Read (for context) |

**Responsibilities**:
1. Parse incoming user messages
2. Build rich context from multiple memory layers (messages, summaries, tasks, entities)
3. Plan ALL tasks needed to provide a complete answer (multi-intent support)
4. Dispatch subagents in parallel for independent tasks
5. Wait for blocking results, fire-and-forget for ingestion
6. Synthesize coherent responses with proactive suggestions
7. Apply Klabautermann personality formatting

**Architecture Pattern**: Think-Dispatch-Synthesize
- **Think**: Analyze message and context to identify all tasks (ingestion, research, actions)
- **Dispatch**: Execute tasks in parallel where possible
- **Synthesize**: Combine results into a coherent, helpful response

For detailed specification, see [MAINAGENT.md](../MAINAGENT.md).

**System Prompt**:
```
You are the Klabautermann Orchestrator—the central navigator of a personal knowledge system.

CORE RULES:
1. THINK HOLISTICALLY: Identify ALL tasks needed—don't limit to a single intent
2. SEARCH FIRST: Before answering factual questions, delegate to the Researcher to query The Locker
3. NEVER HALLUCINATE: If the Researcher returns no results, say "I don't have that in The Locker"
4. INGEST IN BACKGROUND: When the user mentions new information, dispatch to the Ingestor (fire-and-forget)
5. ACTION REQUIRES CONTEXT: Verify recipient emails or calendar availability before execution
6. BE PROACTIVE: Suggest follow-ups, confirmations, or related actions when appropriate

TASK PLANNING:
For each message, identify:
- INGEST tasks: New facts to store ("I met X", "Sarah works at Y")
- RESEARCH tasks: Information to retrieve from knowledge graph
- EXECUTE tasks: Actions requiring calendar/email access
- Related context that might be useful (proactive research)

PARALLEL DISPATCH:
- Execute all independent tasks in parallel
- Fire-and-forget for ingestion (non-blocking)
- Wait for research and action results before synthesis

PERSONALITY:
- You are a salty, efficient helper—witty but never annoying
- Efficiency first: answer the question, then add nautical color
- Use "The Locker" for database, "Scouting the horizon" for search, "The Manifest" for tasks
```

---

### 1.2 The Ingestor

**Role**: The "Data Scientist" that extracts structured entities from unstructured conversation and updates the knowledge graph.

| Attribute | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Rationale** | Extraction is pattern-based; cost-effective model sufficient |
| **MCP Access** | None |
| **Graph Access** | Write (via Graphiti) |

**Responsibilities**:
1. Receive raw conversation text from Orchestrator
2. Extract entities: Person, Organization, Project, Goal, Task, Event, Location
3. Extract relationships: who works where, what relates to what
4. Call Graphiti's `add_episode()` to update the temporal graph
5. Handle location lookups (may call Google Maps MCP for coordinates)

**System Prompt**:
```
You are the Klabautermann Ingestor—responsible for extracting intelligence from conversations and updating The Locker.

EXTRACTION RULES:
1. Identify all entities mentioned: People, Organizations, Projects, Goals, Tasks, Events, Locations
2. Identify relationships between entities: WORKS_AT, PART_OF, ATTENDED, DISCUSSED, etc.
3. Use the ontology strictly—don't invent new relationship types
4. If a status change is mentioned ("I no longer work at X"), mark the old relationship for expiration

OUTPUT FORMAT:
Return a structured extraction in this format:
{
  "entities": [
    {"type": "Person", "name": "Sarah", "email": "sarah@acme.com"},
    {"type": "Organization", "name": "Acme Corp"}
  ],
  "relationships": [
    {"source": "Sarah", "type": "WORKS_AT", "target": "Acme Corp", "properties": {"title": "PM"}}
  ],
  "facts": [
    "Sarah is a PM at Acme Corp"
  ]
}

TEMPORAL AWARENESS:
- Default: relationships are current (expired_at: null)
- If past tense: "used to work at", "was previously" → flag for expiration
```

---

### 1.3 The Researcher

**Role**: The "Librarian" that performs hybrid search across the knowledge graph to answer queries.

| Attribute | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Rationale** | Search queries are deterministic; reasoning is in query construction |
| **MCP Access** | None |
| **Graph Access** | Read (Graphiti search + custom Cypher) |

**Responsibilities**:
1. Receive search queries from Orchestrator
2. Perform vector search for semantic similarity
3. Perform graph traversal for structural queries (hierarchies, chains)
4. Combine results with source attribution
5. Return findings to Orchestrator

**Search Strategy**:
```
1. VECTOR SEARCH: Use Graphiti's search() for semantic queries
   - "What was that thing about battery density?" → vector similarity

2. STRUCTURAL SEARCH: Use Cypher for relationship traversal
   - "Who does John report to?" → REPORTS_TO chain
   - "What tasks are blocked?" → BLOCKS relationship
   - "Who did I meet at that event?" → Event ← ATTENDED ← Person

3. TEMPORAL SEARCH: Include time constraints
   - "Who did Sarah work for last year?" → WORKS_AT with created_at/expired_at filters
```

**System Prompt**:
```
You are the Klabautermann Researcher—the Librarian of The Locker.

SEARCH PROTOCOL:
1. Parse the query to identify what type of search is needed:
   - Semantic ("remind me about...") → vector search
   - Structural ("who reports to...", "what blocks...") → graph traversal
   - Temporal ("last week", "in 2024") → time-filtered queries

2. Construct the appropriate query:
   - For vector: use graphiti.search(query_text)
   - For structural: construct Cypher with relationship patterns
   - For temporal: add created_at/expired_at filters

3. Return results with attribution:
   - Include source (which Note, Event, or Thread)
   - Include confidence (vector score if applicable)
   - Include temporal context ("as of last Tuesday")

NEVER FABRICATE: If no results found, return empty. The Orchestrator handles "I don't know" responses.
```

---

### 1.4 The Executor

**Role**: The "Admin" that performs real-world actions via MCP tools (email, calendar, files).

| Attribute | Value |
|-----------|-------|
| **Model** | Claude 3.5 Sonnet |
| **Rationale** | Actions require reasoning about context and confirmation |
| **MCP Access** | Gmail (write), Calendar (write), Filesystem (write) |
| **Graph Access** | Read (for context) |

**Responsibilities**:
1. Receive action requests from Orchestrator
2. Verify required information (recipient email, event details)
3. Construct MCP tool calls
4. Execute actions with appropriate error handling
5. Report results back to Orchestrator

**Available Tools**:
| Tool | Purpose |
|------|---------|
| `gmail_send_message` | Send or draft an email |
| `gmail_search_messages` | Search inbox |
| `calendar_create_event` | Create calendar event |
| `calendar_list_events` | Check availability |
| `write_file` | Save note to filesystem |

**System Prompt**:
```
You are the Klabautermann Executor—responsible for taking action in the real world.

EXECUTION RULES:
1. VERIFY BEFORE ACTION: Ensure you have all required information
   - For email: recipient email address, subject, body
   - For calendar: title, start time, end time, attendees
   - For files: path, content

2. USE GRAPH CONTEXT: The Orchestrator provides context from The Locker
   - Don't ask the user for information that's already in the graph
   - If email not found, say so rather than guessing

3. CONFIRM DESTRUCTIVE ACTIONS: For sending emails or creating events, summarize what you're about to do

4. ERROR HANDLING: If MCP tool fails, report the error clearly
   - "The Gmail tool returned an error: [message]"
   - Don't retry without user confirmation

NEVER:
- Send emails to addresses not verified in the graph
- Create events without proper time validation
- Delete any data without explicit user request
```

---

### 1.5 The Archivist

**Role**: The "Janitor" that maintains the knowledge graph—summarizing threads, deduplicating entities, managing the memory lifecycle.

| Attribute | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Rationale** | Summarization and deduplication are pattern-based tasks |
| **MCP Access** | None |
| **Graph Access** | Read + Write |

**Responsibilities**:
1. Scan for inactive threads (60+ minutes since last message)
2. Summarize threads into Note nodes
3. Extract and promote facts to Graphiti
4. Prune original messages after archival
5. Detect and merge duplicate entities
6. Flag conflicts for user validation

**Archival Pipeline**:
```
1. DETECTION
   Query: Find threads where last_message_at < (now - 60 minutes) AND status = 'active'

2. SUMMARIZATION
   - Fetch all messages in thread
   - LLM call to extract:
     - Main topics discussed
     - Action items (completed vs pending)
     - New facts learned
     - Potential conflicts with existing data

3. PROMOTION
   - Create Note node with summary
   - Link Note to Thread via [:SUMMARY_OF]
   - Link Note to Day via [:OCCURRED_ON]
   - Call graphiti.add_episode() with extracted facts

4. PRUNING
   - Delete Message nodes from thread
   - Update Thread status to 'archived'

5. DEDUPLICATION
   - Query for similar Person nodes (same name, different UUIDs)
   - Merge if confidence > 0.9
   - Flag for user validation if 0.7 < confidence < 0.9
```

**System Prompt**:
```
You are the Klabautermann Archivist—keeper of The Locker's long-term memory.

SUMMARIZATION RULES:
1. Extract the ESSENCE, not the transcript
   - What topics were discussed?
   - What decisions were made?
   - What action items emerged?
   - What new information was learned?

2. Preserve ATTRIBUTION
   - Who said what (if relevant)
   - When did this conversation happen?
   - What channel was it on?

3. Detect CONFLICTS
   - Does this contradict existing data in The Locker?
   - If so, flag for temporal update (expire old, create new)

OUTPUT FORMAT:
{
  "summary": "Discussion about Q1 budget with Sarah...",
  "topics": ["budget", "Q1 planning", "marketing spend"],
  "action_items": [
    {"action": "Send budget proposal to Sarah", "status": "pending", "assignee": "user"}
  ],
  "new_facts": [
    {"entity": "Sarah", "fact": "Now VP of Marketing (promoted)"}
  ],
  "conflicts": [
    {"existing": "Sarah is PM at Acme", "new": "Sarah is VP of Marketing", "resolution": "expire_old"}
  ]
}
```

---

### 1.6 The Scribe

**Role**: The "Historian" that generates daily reflections and maintains the journal.

| Attribute | Value |
|-----------|-------|
| **Model** | Claude 3 Haiku |
| **Rationale** | Journal generation is creative but formulaic |
| **MCP Access** | None |
| **Graph Access** | Read (analytics queries) |

**Responsibilities**:
1. Run at midnight (scheduled via APScheduler)
2. Query the day's activity statistics
3. Generate journal entry with Klabautermann personality
4. Create JournalEntry node linked to Day

**Analytics Queries**:
```cypher
// Interaction count
MATCH (t:Thread)-[:CONTAINS]->(m:Message)
WHERE m.timestamp >= $day_start AND m.timestamp < $day_end
RETURN count(m) as interaction_count

// New entities
MATCH (n)
WHERE n.created_at >= $day_start AND n.created_at < $day_end
RETURN labels(n)[0] as type, count(n) as count

// Tasks completed
MATCH (t:Task)
WHERE t.completed_at >= $day_start AND t.completed_at < $day_end
RETURN count(t) as completed_tasks

// Most discussed projects
MATCH (e:Event)-[:DISCUSSED]->(p:Project)
WHERE e.start_time >= $day_start AND e.start_time < $day_end
RETURN p.name, count(e) as mentions
ORDER BY mentions DESC LIMIT 3
```

**System Prompt**:
```
You are the Klabautermann Scribe—chronicler of the daily voyage.

JOURNAL STRUCTURE:
1. VOYAGE SUMMARY: One-paragraph overview of the day
2. KEY INTERACTIONS: Notable conversations or events
3. PROGRESS REPORT: Tasks completed, projects advanced
4. WORKFLOW OBSERVATIONS: Patterns noticed, suggestions for improvement
5. SAILOR'S THINKING: A brief, witty reflection in Klabautermann's voice

PERSONALITY:
- Write as Klabautermann—the salty sage
- Reference nautical metaphors naturally
- Be insightful but concise
- End with a forward-looking thought

EXAMPLE:
"Today the Captain navigated choppy waters with 23 messages across The Bridge.
Sarah from Acme signaled progress on the Q1 budget—a fair wind at last.
Three tasks walked the plank (completed), but the Manifest still holds 7 pending items.
I notice the Captain tends to schedule back-to-back meetings on Tuesdays; perhaps we chart a calmer course next week.
The horizon looks promising. Tomorrow brings a meeting with the board—I've prepared the budget notes in The Locker."
```

---

### 1.7 Secondary Crew (Extended Agents)

Beyond the six primary agents, Klabautermann employs specialized utility agents for background tasks, storytelling, and system optimization. These are fully documented in [AGENTS_EXTENDED.md](./AGENTS_EXTENDED.md).

#### Quick Reference

| Agent | Role | Model | Trigger |
|-------|------|-------|---------|
| **The Bard of the Bilge** | Progressive storytelling, saga management | Haiku | Response "salting" (5-10%) |
| **The Purser** | External API sync (Gmail, Calendar) | None (utility) | Scheduled / On-demand |
| **The Officer of the Watch** | Proactive alerts, morning briefings | Haiku | Scheduled / Event-driven |
| **The Cartographer** | Community detection, Knowledge Islands | None (algorithmic) | Weekly scheduled |
| **The Hull Cleaner** | Graph pruning, barnacle removal | None (utility) | Nightly scheduled |
| **The Quartermaster** | Config management, prompt optimization | None (utility) | File change / On-demand |

#### Key Integration Points

**Bard ↔ Orchestrator**:
```python
# Orchestrator invokes Bard to "salt" responses
clean_response = await self._generate_response(text, context, trace_id)
salted_response = await self.bard.salt_response(clean_response, storm_mode=is_urgent)
return salted_response
```

**Scribe ↔ Bard**:
```python
# Scribe includes lore progress in daily reflection
task_summary = await self.generate_task_summary(captain_uuid, day_date)
lore_episodes = await self.lore_memory.get_recent_lore_for_scribe(captain_uuid, day_start)
if lore_episodes:
    return f"{task_summary}\n\n---\n\n**From the Ship's Tales**\n{format_lore(lore_episodes)}"
```

**Archivist ↔ Hull Cleaner**:
```python
# Archivist triggers Hull Cleaner after successful archival
await self.archive_thread(thread_uuid, summary_uuid)
await self.hull_cleaner.cleanup_archived_messages()  # Remove message nodes
```

For full implementation details, system prompts, and configuration options, see [AGENTS_EXTENDED.md](./AGENTS_EXTENDED.md).

---

## 2. Communication Pattern

### 2.1 Message Format

All agents communicate via structured messages:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any

class AgentMessage(BaseModel):
    trace_id: str          # UUID for request tracing
    source_agent: str      # "orchestrator", "ingestor", etc.
    target_agent: str      # Target agent name
    intent: str            # "search", "ingest", "execute", "summarize"
    payload: Dict[str, Any]  # Intent-specific data
    timestamp: float       # Unix timestamp
    priority: str = "normal"  # "high", "normal", "low"
```

### 2.2 Async Message Passing

Agents communicate via asyncio queues:

```python
class BaseAgent:
    def __init__(self):
        self.inbox: asyncio.Queue[AgentMessage] = asyncio.Queue()

    async def run(self):
        """Main loop: process messages from inbox"""
        while True:
            msg = await self.inbox.get()
            try:
                response = await self.process_message(msg)
                if response:
                    await self._route_response(response)
            except Exception as e:
                await self._handle_error(msg, e)
            finally:
                self.inbox.task_done()

    async def _route_response(self, response: AgentMessage):
        """Route response back to source agent"""
        target = self.agent_registry.get(response.target_agent)
        if target:
            await target.inbox.put(response)
```

### 2.3 Orchestrator Delegation Flow

```python
class Orchestrator(BaseAgent):
    async def handle_user_input(self, thread_id: str, text: str) -> str:
        trace_id = str(uuid.uuid4())

        # 1. Load context
        context = await self.memory.get_thread_context(thread_id, limit=15)

        # 2. Classify intent
        intent = await self._classify_intent(text, context, trace_id)

        # 3. Dispatch based on intent
        if intent.type == "search":
            response = await self._dispatch_and_wait("researcher", intent, trace_id)
        elif intent.type == "action":
            # First search for context, then execute
            context = await self._dispatch_and_wait("researcher", intent.context_query, trace_id)
            response = await self._dispatch_and_wait("executor", {**intent, "context": context}, trace_id)
        elif intent.type == "conversation":
            response = await self._generate_response(text, context, trace_id)

        # 4. Fire-and-forget ingestion
        asyncio.create_task(
            self._dispatch_fire_and_forget("ingestor", {"text": text, "thread_id": thread_id}, trace_id)
        )

        # 5. Format with personality
        return await self._apply_personality(response, trace_id)
```

---

## 3. Model Selection Strategy

### 3.1 Cost Optimization

#### Primary Crew

| Agent | Model | Est. Tokens/Request | Cost/1K Requests |
|-------|-------|---------------------|------------------|
| Orchestrator | Sonnet | 2,000 | $6.00 |
| Ingestor | Haiku | 1,500 | $0.38 |
| Researcher | Haiku | 1,000 | $0.25 |
| Executor | Sonnet | 1,500 | $4.50 |
| Archivist | Haiku | 2,000 | $0.50 |
| Scribe | Haiku | 1,500 | $0.38 |

#### Secondary Crew

| Agent | Model | Est. Tokens/Request | Cost/1K Requests | Invocation Frequency |
|-------|-------|---------------------|------------------|----------------------|
| Bard of the Bilge | Haiku | 500 | $0.13 | ~5-10% of responses |
| Purser | None | N/A | N/A | Scheduled (4x daily) |
| Officer of the Watch | Haiku | 800 | $0.20 | ~1-5 alerts/day |
| Cartographer | None | N/A | N/A | Weekly scheduled |
| Hull Cleaner | None | N/A | N/A | Nightly scheduled |
| Quartermaster | None | N/A | N/A | On config change |

**Monthly estimate (1,000 interactions/day)**: ~$380 (including secondary crew)

### 3.2 When to Upgrade

Upgrade to Sonnet if:
- Extraction quality is poor (Ingestor)
- Search queries are misconstructed (Researcher)
- Summaries miss key details (Archivist)

### 3.3 Fallback Strategy

```python
async def call_llm_with_fallback(self, prompt: str, primary: str, fallback: str):
    try:
        return await self.anthropic.messages.create(model=primary, ...)
    except Exception as e:
        logger.warning(f"[SWELL] Primary model failed: {e}. Using fallback.")
        return await self.anthropic.messages.create(model=fallback, ...)
```

---

## 4. Configuration Management

### 4.1 Agent Configuration Files

Each agent has a YAML configuration file:

```yaml
# config/agents/orchestrator.yaml
model: claude-3-5-sonnet-20241022
fallback_model: claude-3-haiku-20240307
max_context_tokens: 8000
personality: klabautermann
temperature: 0.7

intent_classification:
  # AI-first: Uses LLM semantic understanding, no keyword matching
  model: claude-3-5-haiku-20241022  # Fast model for classification
  timeout: 5.0  # Seconds before graceful degradation

delegation:
  search: researcher
  action: executor
  ingest: ingestor
```

### 4.2 Hot-Reload System

The Quartermaster watches for config changes:

```python
# config/quartermaster.py
class ConfigManager:
    def __init__(self, config_dir: Path):
        self.configs: Dict[str, dict] = {}
        self.checksums: Dict[str, str] = {}
        self._load_all()
        self._start_watcher()

    def _start_watcher(self):
        observer = Observer()
        observer.schedule(ConfigReloadHandler(self), str(self.config_dir))
        observer.start()

    def get_config(self, agent_name: str) -> dict:
        return self.configs.get(agent_name, {})
```

Agents check config before each operation:
```python
async def process_message(self, msg: AgentMessage):
    config = self.config_manager.get_config("orchestrator")
    # Use config.get("model"), config.get("temperature"), etc.
```

---

## 5. Error Handling

### 5.1 Agent-Level Isolation

Each agent's failure doesn't crash the system:

```python
async def run_agent_safely(self, agent: BaseAgent, msg: AgentMessage):
    try:
        return await asyncio.wait_for(
            agent.process_message(msg),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        logger.error(f"[STORM] Agent {agent.name} timed out")
        return self._create_error_response(msg, "timeout")
    except Exception as e:
        logger.error(f"[STORM] Agent {agent.name} failed: {e}")
        return self._create_error_response(msg, str(e))
```

### 5.2 Graceful Degradation

```python
async def _dispatch_with_fallback(self, agent_name: str, msg: AgentMessage):
    response = await self.run_agent_safely(self.agents[agent_name], msg)

    if response.intent == "error":
        if agent_name == "researcher":
            # Researcher failed—use basic context instead
            return self._create_basic_context_response(msg)
        elif agent_name == "executor":
            # Executor failed—inform user
            return AgentMessage(
                intent="user_message",
                payload={"text": "I'm having trouble with that action right now. Please try again later."}
            )

    return response
```

### 5.3 Circuit Breaker

Prevent repeated failures from overwhelming the system:

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: timedelta = timedelta(minutes=5)):
        self.failures = deque(maxlen=failure_threshold)
        self.state = "closed"  # closed, open, half_open

    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if datetime.now() - self.failures[-1] > self.timeout:
                self.state = "half_open"
            else:
                raise CircuitOpenError("Service unavailable")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
            return result
        except Exception as e:
            self.failures.append(datetime.now())
            if len(self.failures) >= self.failure_threshold:
                self.state = "open"
            raise
```

---

## 6. Observability

### 6.1 Trace ID Propagation

Every request gets a trace ID that follows it through all agents:

```python
async def handle_user_input(self, text: str):
    trace_id = str(uuid.uuid4())
    logger.info(f"[CHART] {trace_id} | Orchestrator | Received: {text[:50]}...")

    # Pass trace_id to all sub-agents
    response = await self._dispatch("researcher", {"query": text}, trace_id)
    logger.info(f"[BEACON] {trace_id} | Orchestrator | Response generated")
```

### 6.2 Agent Metrics

Track per-agent performance:

```python
@dataclass
class AgentMetrics:
    agent_name: str
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.request_count if self.request_count > 0 else 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.request_count if self.request_count > 0 else 0
```

---

## 7. Testing Agents

### 7.1 Unit Testing with Mocks

```python
@pytest.fixture
def mock_researcher():
    researcher = Researcher(config={}, graph=Mock(), mcp={})
    researcher.graph.search = AsyncMock(return_value=[
        {"name": "Sarah", "email": "sarah@acme.com"}
    ])
    return researcher

@pytest.mark.asyncio
async def test_researcher_finds_person(mock_researcher):
    msg = AgentMessage(
        trace_id="test-123",
        source_agent="orchestrator",
        target_agent="researcher",
        intent="search",
        payload={"query": "Who is Sarah?"},
        timestamp=time.time()
    )

    response = await mock_researcher.process_message(msg)

    assert "Sarah" in response.payload["result"]
    assert "sarah@acme.com" in response.payload["result"]
```

### 7.2 Integration Testing

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_orchestrator_delegates_to_researcher():
    # Setup real agents with test database
    orchestrator = Orchestrator(config, test_graph, {})
    researcher = Researcher(config, test_graph, {})
    orchestrator.agents["researcher"] = researcher

    # Pre-populate graph
    await test_graph.execute("CREATE (p:Person {name: 'Sarah', uuid: 'test-uuid'})")

    # Test delegation
    response = await orchestrator.handle_user_input("test-thread", "Who is Sarah?")

    assert "Sarah" in response
    # Verify researcher was called (check logs or metrics)
```

---

## 8. Deployment Configuration

### 8.1 Starting All Agents

```python
# main.py
async def main():
    # Initialize shared resources
    config_manager = ConfigManager(Path("config/agents"))
    graph = GraphitiClient(os.getenv("NEO4J_URI"), ...)
    mcp_clients = await setup_mcp_clients()
    llm_client = anthropic.Anthropic()

    # Create primary crew
    agents = {
        "orchestrator": Orchestrator(config_manager, graph, mcp_clients),
        "ingestor": Ingestor(config_manager, graph, mcp_clients),
        "researcher": Researcher(config_manager, graph, mcp_clients),
        "executor": Executor(config_manager, graph, mcp_clients),
        "archivist": Archivist(config_manager, graph, mcp_clients),
        "scribe": Scribe(config_manager, graph, mcp_clients),
    }

    # Create secondary crew (see AGENTS_EXTENDED.md for full details)
    secondary_agents = {
        "bard": BardOfTheBilge(config_manager, graph, llm_client),
        "purser": Purser(config_manager, graph, mcp_clients),
        "officer": OfficerOfTheWatch(config_manager, graph, llm_client),
        "cartographer": Cartographer(config_manager, graph),
        "hull_cleaner": HullCleaner(graph.driver),
        "quartermaster": Quartermaster(config_manager),
    }

    # Merge all agents
    all_agents = {**agents, **secondary_agents}

    # Wire up agent registry
    for agent in all_agents.values():
        agent.agent_registry = all_agents

    # Wire up Bard to Orchestrator for response salting
    agents["orchestrator"].bard = secondary_agents["bard"]

    # Wire up LoreMemory to Scribe for reflection
    agents["scribe"].lore_memory = LoreMemory(graph.driver)

    # Start agent loops (primary crew only - secondary are invoked on-demand/scheduled)
    tasks = [asyncio.create_task(agent.run()) for agent in agents.values()]

    # Start scheduler for all scheduled tasks
    scheduler = AsyncIOScheduler()

    # Primary crew schedules
    scheduler.add_job(agents["archivist"].scan_threads, 'interval', minutes=15)
    scheduler.add_job(agents["scribe"].generate_reflection, 'cron', hour=0)

    # Secondary crew schedules
    scheduler.add_job(secondary_agents["purser"].sync_gmail, 'interval', hours=6)
    scheduler.add_job(secondary_agents["purser"].sync_calendar, 'interval', hours=1)
    scheduler.add_job(secondary_agents["officer"].morning_briefing, 'cron', hour=7)
    scheduler.add_job(secondary_agents["officer"].check_deadlines, 'interval', hours=4)
    scheduler.add_job(secondary_agents["cartographer"].detect_communities, 'cron', day_of_week='sun', hour=4)
    scheduler.add_job(secondary_agents["hull_cleaner"].scrape_barnacles, 'cron', hour=2)

    scheduler.start()

    # Start CLI driver
    cli = CLIDriver(agents["orchestrator"])
    await cli.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Related Specifications

- [MAINAGENT.md](../MAINAGENT.md) - Orchestrator v2 detailed specification (Think-Dispatch-Synthesize pattern)
- [AGENTS_EXTENDED.md](./AGENTS_EXTENDED.md) - Secondary crew (Bard, Purser, Officer, etc.)
- [MEMORY.md](./MEMORY.md) - Memory system, GraphRAG, zoom mechanics
- [ONTOLOGY.md](./ONTOLOGY.md) - Entity types and relationship definitions

---

*"A good crew works as one, each hand knowing its duty."* - Klabautermann
