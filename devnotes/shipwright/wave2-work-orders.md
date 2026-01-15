# Wave 2 Work Orders

**Sprint:** 2 - Multi-Agent Architecture
**Date:** 2026-01-15
**Status:** In Progress

These work orders define the scope for each subagent working on Wave 2 tasks.
Each can be executed in parallel as they have no inter-dependencies.

---

## Work Order 1: T023 - Ingestor Agent (carpenter)

### Task
Implement the Ingestor agent that extracts entities and relationships from conversation.

### File to Create
`/home/klabautermann/klabautermann3/src/klabautermann/agents/ingestor.py`

### Key Requirements
1. Inherit from `BaseAgent` in `base_agent.py`
2. Use Claude Haiku for cost-effective extraction
3. Extract entities: Person, Organization, Project, Goal, Task, Event, Location
4. Extract relationships: WORKS_AT, PART_OF, CONTRIBUTES_TO, ATTENDED, HELD_AT, BLOCKS
5. Detect temporal markers ("used to", "previously") for historical relationships
6. Write to graph via GraphitiClient.add_episode()
7. Fire-and-forget pattern - never block, log errors gracefully

### Patterns to Follow
- See `orchestrator.py` for agent structure
- See `models.py` for `AgentMessage` structure
- Use structured Pydantic models for extraction output
- All async, trace_id propagation
- Nautical logging: [WHISPER], [CHART], [BEACON], [SWELL], [STORM]

### Tests to Create
`/home/klabautermann/klabautermann3/tests/unit/test_ingestor.py`

### Acceptance Criteria
- "I met Sarah from Acme" extracts Person + Organization + WORKS_AT
- "Sarah (sarah@acme.com) is a PM" captures email and title
- "I used to work at Google" flags for expiration
- Extraction errors logged but don't crash agent

### Invocation
```
claude --agent carpenter "Implement T023: Ingestor Agent per /home/klabautermann/klabautermann3/tasks/in-progress/T023-ingestor-agent.md"
```

---

## Work Order 2: T024 - Researcher Agent (carpenter)

### Task
Implement the Researcher agent that performs hybrid search across the knowledge graph.

### File to Create
`/home/klabautermann/klabautermann3/src/klabautermann/agents/researcher.py`

### Key Requirements
1. Inherit from `BaseAgent` in `base_agent.py`
2. Classify query type: SEMANTIC, STRUCTURAL, TEMPORAL, HYBRID
3. Vector search via GraphitiClient.search()
4. Graph traversal via Neo4j Cypher queries
5. Temporal filtering with created_at/expired_at
6. NEVER fabricate results - empty response if nothing found
7. Return results with source attribution and confidence scores

### Patterns to Follow
- See `orchestrator.py` for agent structure
- See `graphiti_client.py` for search interface
- Use `SearchResult` model from `models.py`
- All async, trace_id propagation
- Pattern matching for query classification

### Tests to Create
`/home/klabautermann/klabautermann3/tests/unit/test_researcher.py`

### Acceptance Criteria
- "Who is Sarah?" returns Person node with properties
- "Who does Sarah work for?" traverses WORKS_AT relationship
- "What did I do last week?" filters by time range
- Empty results return gracefully (no fabrication)

### Interface for T025
Define these search method signatures for navigator (T025):
- `_semantic_search(query, trace_id) -> SearchResponse`
- `_structural_search(query, trace_id) -> SearchResponse`
- `_temporal_search(query, trace_id) -> SearchResponse`
- `_hybrid_search(query, trace_id) -> SearchResponse`

### Invocation
```
claude --agent carpenter "Implement T024: Researcher Agent per /home/klabautermann/klabautermann3/tasks/in-progress/T024-researcher-agent.md"
```

---

## Work Order 3: T026 - MCP Client Wrapper (purser)

### Task
Create the MCP client infrastructure for tool invocation.

### Files to Create
- `/home/klabautermann/klabautermann3/src/klabautermann/mcp/client.py`
- Add MCP exceptions to `core/exceptions.py`

### Key Requirements
1. Manage MCP server processes (start, stop, health check)
2. Generic `invoke_tool()` method for any MCP tool
3. JSON-RPC communication over stdio
4. Timeout handling (default 30s)
5. Trace ID propagation and logging
6. Support multiple concurrent servers

### Technical Details
- MCP uses JSON-RPC 2.0 over stdin/stdout
- Servers started via `npx -y @modelcontextprotocol/server-*` commands
- Initialize with handshake: `initialize` + `notifications/initialized`
- Tool calls: `tools/call` method
- Tool listing: `tools/list` method

### Exceptions to Add
```python
class MCPError(KlabautermannError):
    """MCP tool invocation failed."""
    pass

class MCPTimeoutError(MCPError):
    """MCP tool timed out."""
    pass
```

### Tests to Create
`/home/klabautermann/klabautermann3/tests/unit/test_mcp_client.py`

### Acceptance Criteria
- MCP server can be started and stopped cleanly
- Tool invocation works with proper arguments
- Errors from tools are caught and formatted
- Timeout triggers graceful failure
- All invocations logged with trace ID

### Invocation
```
claude --agent purser "Implement T026: MCP Client Wrapper per /home/klabautermann/klabautermann3/tasks/in-progress/T026-mcp-client-wrapper.md"
```

---

## Work Order 4: T033 - Config Hot-Reload (carpenter)

### Task
Implement the Quartermaster file watcher for config hot-reload.

### File to Create
`/home/klabautermann/klabautermann3/src/klabautermann/config/quartermaster.py`

### Key Requirements
1. Watch `config/agents/` directory for file changes
2. Use watchdog library for file system events
3. Debounce rapid changes (500ms)
4. Trigger ConfigManager.reload() on change
5. Notify agents via callback system
6. Track reload statistics

### Dependencies
- T032 ConfigManager (COMPLETED) - already exists in `config/manager.py`
- Add `watchdog>=3.0.0` to requirements.txt

### Patterns to Follow
- Use existing ConfigManager checksum detection
- Callback registration per agent
- Graceful error handling for invalid YAML

### Tests to Create
`/home/klabautermann/klabautermann3/tests/unit/test_quartermaster.py`

### Acceptance Criteria
- Modifying orchestrator.yaml triggers reload
- Invalid YAML doesn't crash the system
- Reload events logged
- No reload if content unchanged

### Invocation
```
claude --agent carpenter "Implement T033: Config Hot-Reload per /home/klabautermann/klabautermann3/tasks/in-progress/T033-config-hot-reload.md"
```

---

## Coordination Notes

### Handoff to Wave 3
When T024 (Researcher) completes, notify navigator to start T025 (Hybrid Search Queries).
The Researcher defines the interface; navigator implements the Cypher query library.

When T026 (MCP Client) completes, purser can proceed with:
- T027 (OAuth Bootstrap)
- T028 (Google Workspace Bridge)

### Completion Checklist
Each task requires:
- [ ] Implementation code
- [ ] Unit tests (all passing)
- [ ] Development notes in task file
- [ ] Move task to `tasks/completed/`
- [ ] Update `PROGRESS.md`

---

*"Fair winds and following seas to the crew."* - The Shipwright
