# Thread Summary Pydantic Models

## Metadata
- **ID**: T038
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.5 (Archivist output format)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Note node schema

## Dependencies
- [x] T005 - Pydantic models foundation

## Context
The Archivist extracts structured information from thread conversations. These Pydantic models define what the LLM must return, ensuring consistent output that can be reliably stored in the graph. The models also enable validation before graph writes.

## Requirements
- [ ] Add models to `src/klabautermann/core/models.py`:

### ThreadSummary Model
- [ ] Main container for summarization output:
  ```python
  class ThreadSummary(BaseModel):
      summary: str  # 2-3 sentence overview
      topics: list[str]  # Main topics discussed
      action_items: list[ActionItem]  # Extracted tasks
      new_facts: list[ExtractedFact]  # Facts to add to graph
      conflicts: list[FactConflict]  # Detected contradictions
      participants: list[str]  # Names mentioned
      sentiment: str  # overall, positive, negative, neutral, mixed
  ```

### ActionItem Model
- [ ] Task/action extracted from conversation:
  ```python
  class ActionItem(BaseModel):
      action: str  # What needs to be done
      assignee: Optional[str] = None  # Who should do it
      status: ActionStatus  # pending, completed, mentioned
      due_date: Optional[str] = None  # If mentioned
      confidence: float = Field(ge=0.0, le=1.0, default=0.8)
  ```

### ActionStatus Enum
- [ ] Status of action items:
  ```python
  class ActionStatus(str, Enum):
      PENDING = "pending"
      COMPLETED = "completed"
      MENTIONED = "mentioned"  # Reference to existing task
  ```

### ExtractedFact Model
- [ ] New information to add to graph:
  ```python
  class ExtractedFact(BaseModel):
      entity: str  # Entity name
      entity_type: str  # Person, Organization, Project, etc.
      fact: str  # The fact statement
      confidence: float = Field(ge=0.0, le=1.0, default=0.8)
  ```

### FactConflict Model
- [ ] Contradiction with existing data:
  ```python
  class FactConflict(BaseModel):
      existing_fact: str  # What's currently in the graph
      new_fact: str  # What the conversation states
      entity: str  # Which entity is affected
      resolution: ConflictResolution  # How to resolve
  ```

### ConflictResolution Enum
- [ ] How to handle contradictions:
  ```python
  class ConflictResolution(str, Enum):
      EXPIRE_OLD = "expire_old"  # Mark old fact as expired
      KEEP_BOTH = "keep_both"  # Both might be valid
      USER_REVIEW = "user_review"  # Flag for human decision
      IGNORE_NEW = "ignore_new"  # Keep existing, discard new
  ```

## Acceptance Criteria
- [ ] All models have proper type hints
- [ ] All models have docstrings
- [ ] Confidence fields have 0.0-1.0 validation
- [ ] Models can be instantiated from dict (for LLM output parsing)
- [ ] Models can be serialized to JSON
- [ ] Unit tests for model validation

## Implementation Notes

The models should work with instructor-style LLM extraction:
```python
summary = await client.chat.completions.create(
    model="claude-3-haiku-20240307",
    response_model=ThreadSummary,
    messages=[{"role": "user", "content": prompt}]
)
```

Export all new models from `core/models.py` and consider grouping them:
```python
# Thread summarization models
__all__ = [
    # ... existing exports ...
    "ThreadSummary",
    "ActionItem",
    "ActionStatus",
    "ExtractedFact",
    "FactConflict",
    "ConflictResolution",
]
```
