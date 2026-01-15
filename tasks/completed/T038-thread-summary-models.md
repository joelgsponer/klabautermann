# Thread Summary Pydantic Models

## Metadata
- **ID**: T038
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: completed
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

## Development Notes

### Implementation

**Files Modified:**
- `/home/klabautermann/klabautermann3/src/klabautermann/core/models.py`
  - Added `ActionStatus` enum with values: PENDING, COMPLETED, MENTIONED
  - Added `ConflictResolution` enum with values: EXPIRE_OLD, KEEP_BOTH, USER_REVIEW, IGNORE_NEW
  - Added `ActionItem` model with confidence validation (0.0-1.0)
  - Added `ExtractedFact` model with confidence validation (0.0-1.0)
  - Added `FactConflict` model with default resolution of USER_REVIEW
  - Added `ThreadSummary` model with complete archival output structure
  - Updated `__all__` exports to include all new models in alphabetical order

**Files Created:**
- `/home/klabautermann/klabautermann3/tests/unit/test_models.py`
  - 30 comprehensive unit tests covering all new models
  - Tests for enum values and string conversion
  - Tests for model instantiation (minimal and full)
  - Tests for dict instantiation (LLM output compatibility)
  - Tests for confidence validation (valid and invalid ranges)
  - Tests for JSON serialization/deserialization
  - Tests for default values
  - Tests for nested model validation
  - Real-world example test with realistic Archivist output

### Decisions Made

1. **Confidence Validation**: Used Pydantic's `@field_validator` decorator with explicit range checking for better error messages, matching the pattern established in `IntentClassification`.

2. **Default Values**:
   - `ActionItem.status` defaults to `PENDING` (most common case)
   - `ActionItem.confidence` defaults to 0.8 (reasonable default)
   - `ExtractedFact.confidence` defaults to 0.8 (same as ActionItem)
   - `FactConflict.resolution` defaults to `USER_REVIEW` (safest option)
   - All list fields in `ThreadSummary` use `Field(default_factory=list)` to avoid mutable default issues

3. **Enum Design**: Both enums inherit from `str, Enum` to ensure JSON serialization works correctly and values match spec strings.

4. **Model Organization**: Placed all thread summarization models together in a dedicated section before Action Execution Models for logical grouping.

### Patterns Established

1. **Confidence Field Pattern**: All models with confidence fields use:
   ```python
   confidence: float = Field(ge=0.0, le=1.0, default=0.8)

   @field_validator("confidence")
   @classmethod
   def validate_confidence(cls, v: float) -> float:
       if not 0.0 <= v <= 1.0:
           raise ValueError("Confidence must be between 0.0 and 1.0")
       return v
   ```

2. **Enum String Inheritance**: All enums use `str, Enum` pattern for JSON compatibility.

3. **Default Factories**: List fields use `Field(default_factory=list)` to avoid mutable defaults.

4. **Comprehensive Testing**: Test coverage includes:
   - Enum values and string conversion
   - Minimal and full instantiation
   - Dict instantiation (LLM compatibility)
   - Validation edge cases
   - JSON serialization/deserialization
   - Nested model validation
   - Real-world examples

### Testing

All 30 unit tests pass:
```
tests/unit/test_models.py::TestActionStatus (2 tests)
tests/unit/test_models.py::TestConflictResolution (2 tests)
tests/unit/test_models.py::TestActionItem (8 tests)
tests/unit/test_models.py::TestExtractedFact (6 tests)
tests/unit/test_models.py::TestFactConflict (4 tests)
tests/unit/test_models.py::TestThreadSummary (8 tests)
```

Test command: `uv run pytest tests/unit/test_models.py -v --tb=short`

### Issues Encountered

None. Implementation was straightforward following established patterns in the codebase.

### Integration Points

These models are ready for use by:
1. **Archivist Agent** (T039) - Will use `ThreadSummary` as LLM response model
2. **Thread Manager** - Already exists, will consume these models during archival
3. **Future Conflict Resolution UI** - Can use `FactConflict` model directly

### Next Steps

The models are complete and tested. Next recommended tasks:
- **T039**: Archivist Agent Implementation (depends on these models)
- **T040**: Thread Archival Pipeline (will use ThreadSummary)
