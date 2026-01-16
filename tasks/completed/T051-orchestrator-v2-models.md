# Orchestrator v2 Pydantic Models

## Metadata
- **ID**: T051
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.2, 4.3
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)

## Dependencies
- None (foundational task)

## Context
Define the Pydantic models required for the new orchestrator v2 workflow. These models are the data structures that flow through the Think-Dispatch-Synthesize pattern.

## Requirements
- [x] Create `EnrichedContext` model with all memory layer fields
- [x] Create `CommunityContext` model for Knowledge Island summaries
- [x] Create `PlannedTask` model for individual task definitions
- [x] Create `TaskPlan` model for orchestrator's task plan output
- [x] Add proper type hints and Field descriptions
- [x] Ensure JSON serialization works for LLM prompts

## Acceptance Criteria
- [x] All models pass Pydantic validation
- [x] Models can be instantiated with sample data
- [x] Models serialize to JSON correctly
- [x] Models are importable from `klabautermann.core.models`

## Implementation Notes
Add to `src/klabautermann/core/models.py`. Follow existing patterns (e.g., `ThreadContext`, `AgentMessage`).

```python
# Key models to add:
class EnrichedContext(BaseModel):
    thread_uuid: str
    channel_type: ChannelType
    messages: list[dict[str, Any]]
    recent_summaries: list[ThreadSummary]
    pending_tasks: list[TaskNode]
    recent_entities: list[EntityReference]
    relevant_islands: list[CommunityContext] | None = None

class CommunityContext(BaseModel):
    name: str
    theme: str
    summary: str
    pending_tasks: int

class PlannedTask(BaseModel):
    task_type: Literal["ingest", "research", "execute"]
    description: str
    agent: Literal["ingestor", "researcher", "executor"]
    payload: dict[str, Any]
    blocking: bool

class TaskPlan(BaseModel):
    reasoning: str
    tasks: list[PlannedTask]
    direct_response: str | None = None
```

## Development Notes

### Implementation

**Files Modified:**
- `/home/klabautermann/klabautermann3/src/klabautermann/core/models.py`
  - Added `Literal` to imports (required for task_type and agent field validation)
  - Added 5 new Pydantic models for Orchestrator v2 workflow
  - Updated `__all__` export list with new models

**Files Created:**
- `/home/klabautermann/klabautermann3/tests/unit/test_v2_models.py`
  - Comprehensive test suite with 19 test cases covering all models
  - Tests for validation, serialization, defaults, and integration

### Models Created

1. **CommunityContext** - Knowledge Island summaries for broad context awareness
   - Fields: name, theme, summary, pending_tasks (default 0)
   - Used in EnrichedContext.relevant_islands

2. **EntityReference** - Lightweight entity references from Graphiti
   - Fields: uuid, name, entity_type, created_at
   - Provides recent entity context without full entity details

3. **EnrichedContext** - Rich context integrating all memory layers
   - Replaces simple ThreadContext in Orchestrator v2
   - Integrates Short/Mid/Long-Term memory plus Community detection
   - Fields: thread_uuid, channel_type, messages, recent_summaries, pending_tasks, recent_entities, relevant_islands

4. **PlannedTask** - Individual task definition for dispatch
   - Fields: task_type (Literal), description, agent (Literal), payload, blocking
   - Supports validation of task_type ("ingest", "research", "execute")
   - Supports validation of agent ("ingestor", "researcher", "executor")
   - Default blocking=True (wait for result before synthesis)

5. **TaskPlan** - Complete orchestrator plan from Think phase
   - Fields: reasoning, tasks (list), direct_response (optional)
   - Empty task list defaults to [] for convenience
   - Supports direct response when no task execution needed

### Decisions Made

1. **Field Descriptions**: Added comprehensive docstrings and Field descriptions for better LLM prompt generation and developer clarity

2. **Default Values**:
   - `CommunityContext.pending_tasks` defaults to 0
   - `PlannedTask.blocking` defaults to True (safer default - wait for results)
   - `TaskPlan.tasks` defaults to empty list
   - `EnrichedContext.relevant_islands` is optional (None by default)

3. **Validation**: Used Literal types for task_type and agent fields to ensure only valid values are accepted, preventing runtime errors

4. **Model Placement**: Added models in a new section "Orchestrator v2 Models" before Action Execution Models to keep related models together

### Patterns Established

1. **Comprehensive Docstrings**: All models include multi-line docstrings explaining purpose, usage, and spec references
2. **Memory Layer Integration**: EnrichedContext clearly documents which fields map to which memory layers (Short/Mid/Long-Term/Community)
3. **Field Comments**: Inline comments on key fields explain their purpose
4. **Validation**: Literal types used for enum-like string fields instead of Python Enum (simpler for LLM interaction)

### Testing

Created comprehensive test suite with 19 tests:
- **Model Instantiation**: Valid data creates models correctly
- **Default Values**: Optional fields and defaults work as expected
- **JSON Serialization**: All models serialize/deserialize correctly
- **Validation**: Literal fields reject invalid values (task_type, agent)
- **Integration**: Models work together in realistic scenarios

All tests pass:
```
19 passed in 0.12s
```

Verified no regression in existing tests:
- `test_config_manager.py`: 22 passed
- `test_intent_classification.py`: 19 passed

### Issues Encountered

None. Implementation was straightforward following existing patterns in models.py.
