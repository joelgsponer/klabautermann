# Set Up Project Directory Structure

## Metadata
- **ID**: T003
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- None (foundational task)

## Context
A well-organized project structure is essential for maintainability. The structure must support the multi-agent architecture with clear separation between agents, channels, memory, and core utilities.

## Requirements
- [ ] Create the following directory structure:
```
src/
  klabautermann/
    __init__.py
    core/
      __init__.py
      models.py       (Pydantic models)
      ontology.py     (Graph schema constants)
      logger.py       (Logging system)
      exceptions.py   (Custom exceptions)
    agents/
      __init__.py
      base_agent.py   (Abstract base)
      orchestrator.py (Main agent)
    channels/
      __init__.py
      base_channel.py (Abstract interface)
      cli_driver.py   (CLI implementation)
    memory/
      __init__.py
      graphiti_client.py
      neo4j_client.py
      thread_manager.py
    mcp/
      __init__.py
      client.py       (Future: MCP wrapper)
    utils/
      __init__.py
      retry.py        (Retry decorator)
scripts/
  __init__.py
  init_database.py
config/
  agents/           (Agent YAML configs)
tests/
  __init__.py
  unit/
  integration/
  e2e/
  conftest.py
```
- [ ] Create `pyproject.toml` with project metadata
- [ ] Create `requirements.txt` with initial dependencies
- [ ] Update `.gitignore` (if not done in T004)

## Acceptance Criteria
- [ ] All directories exist with `__init__.py` files
- [ ] `pyproject.toml` contains project metadata and tool config
- [ ] `from klabautermann.core import models` imports successfully
- [ ] Project structure matches the architecture in AGENTS.md

## Implementation Notes

Initial dependencies for `requirements.txt`:
```
# Core
pydantic>=2.0
anthropic>=0.18
graphiti-core>=0.3

# Database
neo4j>=5.0

# Async
asyncio
aiofiles

# Utilities
tenacity
python-dotenv
pyyaml

# Development
pytest
pytest-asyncio
ruff
mypy
```

The `pyproject.toml` should include Ruff and Mypy configuration as specified in CODING_STANDARDS.md.
