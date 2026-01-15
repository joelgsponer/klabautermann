# Contributing to Klabautermann

## Task Workflow

### 1. Select a Task

```
tasks/pending/      → Available tasks
tasks/in-progress/  → Currently being worked on
tasks/completed/    → Finished tasks
tasks/blocked/      → Waiting on dependencies
```

**Priority**: Check `PROGRESS.md` → P0 tasks first → Verify dependencies

### 2. Gather Context

Before starting, read:
1. **Task file** - dependencies, linked specs, requirements, acceptance criteria
2. **Spec files** - ALL specs listed in the task (`specs/` directory)
3. **Completed dependency tasks** - implementation notes and patterns established
4. **PROGRESS.md** - recent decisions, blockers, patterns
5. **Existing code** - match patterns in `src/klabautermann/`
6.   Makefile  - understand commands available

### 3. Work on Task

```bash
mv tasks/pending/TXXX-task-name.md tasks/in-progress/
```

Update status in file to `in-progress`. Follow these principles:
- Match existing code patterns
- Keep changes minimal and focused
- Write tests for new functionality
- Maintain documentation

### 4. Complete Task

Add `## Development Notes` section documenting:
- **Implementation**: Files created/modified
- **Decisions Made**: Why you chose this approach
- **Patterns Established**: For future tasks to follow
- **Testing**: What tests were added
- **Issues Encountered**: Blockers or workarounds

Then:
```bash
mv tasks/in-progress/TXXX-task-name.md tasks/completed/
```

Update status to `completed`, update `PROGRESS.md` with completion and next recommended tasks.

### 5. Update User-Facing Docs

- **README.md**: Always keep updated
- **NEWS.md**: Only for user-visible changes (new features, improvements, bug fixes users would notice). Not for refactoring, tests, or internal tooling.

---

## Testing

**CRITICAL: Tests define what code SHOULD do. If tests fail, fix the CODE, not the tests.**

### Test-First Workflow

1. Read the spec
2. Write tests (they should fail)
3. Write code to make tests pass
4. Refactor while keeping tests green

### Guidelines

- Test behavior, not implementation
- Clear names: `test_question_triggers_ai_response` not `test_handler_works`
- One concept per test
- **Never pollute production graph with test data**

See `specs/quality/TESTING.md` for detailed testing protocol.

---

## Git Practices

### Commit Format

```
TXXX: Brief description

- Detail 1
- Detail 2
```

### Rules

- **Commit frequently** - logical units of work, not waiting for task completion
- **Atomic commits** - one thing per commit
- **Verify first** - run `make check` before committing
- **Explain why** - use commit body for non-obvious reasoning

---

## Handling Blockers

1. Document under `## Blockers` in task file
2. Move to `tasks/blocked/`
3. Update `PROGRESS.md` with details
4. Create new task if blocker needs its own work

---

## Reference Hierarchy

When stuck, check in order:
1. Task file → Requirements
2. Spec files → Detailed specifications
3. PROGRESS.md → Recent decisions
4. Completed tasks → Implementation examples
5. Makefile → Available commands

---

## Code Documentation

### Self-Documenting Code
- Variable and function names should be self-explanatory
- Verbose names are acceptable when they add clarity
- Code structure should reveal intent

### Comments
- **Why, not what**: Explain reasoning, not mechanics
- **Avoid obvious**: `# increment counter` adds nothing
- **Document gotchas**: Non-obvious behavior, edge cases, workarounds

```python
# GOOD - explains why
# Neo4j requires explicit transaction for batch operations over 1000 nodes
async with session.begin_transaction() as tx:

# BAD - restates the code
# Create a new person entity
person = PersonEntity(name=name)
```

### Docstrings
- Required for public APIs and complex functions
- Use Google-style format
- Include type hints in signatures, not docstrings

```python
async def extract_entities(text: str, context: ThreadContext) -> list[Entity]:
    """Extract named entities from conversation text.

    Args:
        text: Raw conversation text to analyze.
        context: Thread context for disambiguation.

    Returns:
        Extracted entities with confidence scores.

    Raises:
        ExtractionError: If LLM returns unparseable output.
    """
```

## Development Environment

- Use Docker containers for reproducibility (also testing, development)
- System should work out of the box everywhere
- Maintain a comprehensive Makefile (always keep updated)
