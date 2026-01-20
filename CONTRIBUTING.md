# Contributing to Klabautermann

Thank you for your interest in contributing to Klabautermann!

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Git

### Development Setup

```bash
# Clone the repository
git clone https://github.com/joelgsponer/klabautermann.git
cd klabautermann

# Create virtual environment
make venv
source .venv/bin/activate

# Install development dependencies
make dev

# Copy environment template
cp .env.example .env
# Edit .env with your API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY)

# Start Neo4j
make docker-up

# Initialize database schema
make init-db

# Verify setup
make check
```

### Common Commands

| Command | Description |
|---------|-------------|
| `make run` | Start the CLI |
| `make test` | Run all tests |
| `make test-fast` | Run tests in parallel |
| `make lint` | Run linter (ruff) |
| `make type-check` | Run type checker (mypy) |
| `make format` | Format code |
| `make check` | Run all quality checks |

---

## Code Style

### Ruff Configuration

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Check for issues
make lint

# Auto-format code
make format
```

Key style rules:
- Line length: 100 characters
- Import ordering: isort-compatible (first-party: `klabautermann`)
- Python target: 3.11+

### Type Hints

All functions should have type hints:

```python
# Good
async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
    ...

# Bad
async def process_message(self, msg):
    ...
```

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `ThreadManager`)
- **Functions/Methods**: `snake_case` (e.g., `get_context_window`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`)
- **Private**: Prefix with `_` (e.g., `_internal_method`)

---

## Pull Request Process

### 1. Create a Branch

```bash
# Feature
git checkout -b feat/description

# Bug fix
git checkout -b fix/description

# Documentation
git checkout -b docs/description

# Tests
git checkout -b test/description
```

### 2. Make Changes

- Follow existing code patterns
- Write tests for new functionality
- Update documentation if needed
- Run `make check` before committing

### 3. Commit Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types**: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

**Examples**:
```
feat(researcher): Add temporal search support

- Add _execute_temporal_search method
- Add TimeRange parsing from queries
- Add tests for temporal queries
```

```
fix(cli): Handle ANSI escape codes in non-color terminals
```

### 4. Push and Create PR

```bash
git push -u origin your-branch

# Create PR via GitHub CLI
gh pr create --base dev --title "feat: Description" --body "..."
```

### 5. PR Requirements

- [ ] All tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] Type checking passes (`make type-check`)
- [ ] Documentation updated if needed
- [ ] Conventional commit format

---

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
