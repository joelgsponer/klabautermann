# Klabautermann Task Management

> **See also**: [CONTRIBUTING.md](../CONTRIBUTING.md) for workflow | [PROGRESS.md](../PROGRESS.md) for current state

## Directory Structure

```
tasks/
├── pending/          # Tasks ready to be worked on
├── in-progress/      # Currently being implemented
├── completed/        # Done tasks (archived)
└── blocked/          # Tasks waiting on dependencies
```

## Task File Format

Each task is a markdown file with the following structure:

```markdown
# Task Title

## Metadata
- **ID**: TXXX
- **Priority**: P0|P1|P2|P3
- **Category**: core|channel|skill|subagent|workflow|maintenance|performance|file|ui|deployment
- **Effort**: S|M|L|XL
- **Status**: pending|in-progress|blocked|completed

## Specs
- Primary: [spec-file.md](../docs/specs/spec-file.md)
- Related: [other-spec.md](../docs/specs/other-spec.md), ...

## Dependencies
- [ ] TXXX - Dependency task title

## Context
Brief explanation of why this task matters and how it fits into the system.

## Requirements
- [ ] Requirement 1
- [ ] Requirement 2

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Implementation Notes
Technical guidance or constraints.

## Development Notes (Added After Completion)
Document what was actually built, decisions made, patterns established.
```

**Important**: When completing a task, add a `## Development Notes` section documenting:
- Files created/modified
- Decisions made during implementation
- Patterns established for future tasks
- Testing approach
- Any issues encountered

This helps future workers understand what was done and why.

## Priority Levels

| Priority | Description | Examples |
|----------|-------------|----------|
| P0 | Foundation - Must be done first | Core infrastructure, MCP setup |
| P1 | Critical - Core functionality | Entity CRUD, basic skills |
| P2 | Important - Full feature set | Advanced skills, workflows |
| P3 | Enhancement - Nice to have | Optimization, polish |
