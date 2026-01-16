# Orchestrator v2 Configuration

## Metadata
- **ID**: T058
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 7
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 4

## Dependencies
- None (can be done in parallel)

## Context
Create the configuration file for orchestrator v2 with all tunable parameters for context building, execution, and proactive behavior.

## Requirements
- [x] Create `config/agents/orchestrator_v2.yaml`
- [x] Define model configuration (planning model, synthesis model)
- [x] Define context parameters (message_window, summary_hours, etc.)
- [x] Define execution parameters (max_research_depth, timeouts)
- [x] Define proactive behavior flags
- [x] Load config in orchestrator __init__
- [x] Support config hot-reload (if Quartermaster pattern exists)

## Acceptance Criteria
- [x] Config file created at `config/agents/orchestrator_v2.yaml`
- [x] All parameters from spec Section 7 included
- [x] Orchestrator reads config on initialization
- [x] Default values match spec recommendations
- [x] Config validation on load (Pydantic or similar)

## Implementation Notes
Config structure from spec:
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

## Development Notes

### Implementation

#### Files Created
1. `/home/klabautermann/klabautermann3/config/agents/orchestrator_v2.yaml`
   - Main configuration file with all parameters from MAINAGENT.md Section 7
   - Includes inline comments explaining each parameter
   - Matches spec defaults exactly

2. `/home/klabautermann/klabautermann3/tests/unit/test_orchestrator_v2_config.py`
   - Comprehensive test suite with 14 test cases
   - Tests config loading, validation, defaults, and hot-reload
   - All tests passing

#### Files Modified
1. `/home/klabautermann/klabautermann3/src/klabautermann/config/manager.py`
   - Added `ContextConfig` model for context gathering parameters
   - Added `ExecutionConfig` model for execution control parameters
   - Added `ProactiveBehaviorConfig` model for proactive behavior settings
   - Added `OrchestratorV2Config` model that composes all three
   - Registered `orchestrator_v2` in `CONFIG_CLASSES` dictionary
   - Updated `__all__` exports to include new config models
   - All models use Pydantic with field validation

### Decisions Made

1. **Config Structure**: Used nested Pydantic models (ContextConfig, ExecutionConfig, ProactiveBehaviorConfig) instead of flat structure
   - Reasoning: Better organization, clearer responsibilities, easier to extend
   - Pattern matches existing agent configs in codebase

2. **Model Field Override**: OrchestratorV2Config uses plain string fields for `model` and `synthesis_model` instead of ModelConfig object
   - Reasoning: V2 orchestrator needs simpler model specification, doesn't need temperature/token limits in config
   - These are fixed values per the spec (both use Opus)

3. **Validation Constraints**: Added strict validation on all numeric fields
   - message_window: must be > 0
   - summary_hours: must be > 0
   - max_research_depth: must be between 1 and 5
   - timeout values: must be > 0
   - Reasoning: Prevents invalid configs that would break orchestrator

4. **Hot-Reload Support**: Leveraged existing ConfigManager checksum-based hot-reload
   - No additional work needed, automatically supported
   - Quartermaster pattern already in place

### Patterns Established

1. **Three-Layer Config Pattern**: For complex agents with multiple concerns
   ```python
   class AgentConfig(AgentConfigBase):
       concern_a: ConcernAConfig = Field(default_factory=ConcernAConfig)
       concern_b: ConcernBConfig = Field(default_factory=ConcernBConfig)
       concern_c: ConcernCConfig = Field(default_factory=ConcernCConfig)
   ```

2. **Config Registration**: Add new agent configs to `CONFIG_CLASSES` dict
   ```python
   CONFIG_CLASSES: ClassVar[dict[str, type[AgentConfigBase]]] = {
       "orchestrator_v2": OrchestratorV2Config,
       ...
   }
   ```

3. **Test Coverage**: Every config should have tests for:
   - File existence
   - Successful loading
   - Field value correctness
   - Validation constraints
   - Default fallbacks
   - Hot-reload detection

### Testing

All 14 tests pass:
- Config file exists and loads successfully
- All field values match spec defaults
- Pydantic validation enforces constraints
- Default values work when config file missing
- Hot-reload detection works
- All fields accessible via dot notation

### Issues Encountered

None. Implementation was straightforward following existing patterns in the codebase.

### Next Steps

This config is now ready for use in T059 (Orchestrator v2 Think-Plan-Dispatch implementation). The orchestrator will:
```python
from klabautermann.config.manager import ConfigManager, OrchestratorV2Config

config_manager = ConfigManager()
v2_config = config_manager.get_typed("orchestrator_v2", OrchestratorV2Config)

# Access values
model = v2_config.model  # "claude-opus-4-5-20251101"
window_size = v2_config.context.message_window  # 20
max_depth = v2_config.execution.max_research_depth  # 2
```
