# Klabautermann Development Notes

Team knowledge repository for insights, decisions, and patterns discovered during development.

## Directory Structure

```
devnotes/
├── pm/           # Project Manager - sprint status, decisions, blockers
├── backend/      # Backend Engineer - agent patterns, async gotchas
├── graph/        # Graph Engineer - schema migrations, query patterns
├── ml/           # ML Engineer - prompt iterations, extraction quality
├── devops/       # DevOps Engineer - docker setup, monitoring, incidents
├── fullstack/    # Full-Stack Engineer - component design, API contracts
├── mobile/       # Mobile Engineer - RN patterns, offline sync
├── integration/  # Integration Engineer - MCP tools, OAuth flows
├── qa/           # QA Engineer - test coverage, golden scenarios
├── security/     # Security Engineer - threat model, Sieve rules
└── docs/         # Tech Writer - changelog, terminology
```

## Conventions

### File Naming

- Use kebab-case: `sprint-01-status.md`, `query-patterns.md`
- Date-prefixed for time-sensitive notes: `2025-01-15-incident-report.md`
- Use descriptive names that indicate content type

### Standard Files Per Directory

Each role directory should maintain:

| File | Purpose |
|------|---------|
| `decisions.md` | Key decisions with rationale |
| `learnings.md` | Gotchas, patterns, tips discovered |
| `blockers.md` | Current blockers and dependencies |

### Note Structure

```markdown
# Title

**Date**: YYYY-MM-DD
**Author**: [Role]
**Status**: Draft | Active | Archived

## Context

Why this note exists.

## Content

The actual information.

## Related

- Links to specs, code, other notes
```

### Cross-References

- Link to specs: `See [AGENTS.md](../specs/architecture/AGENTS.md)`
- Link to code: `Implementation at `src/agents/orchestrator.py:142``
- Link to other notes: `Related: [async-gotchas.md](../backend/async-gotchas.md)`

## Workflow

### During Development

1. **Before starting**: Check role's `blockers.md` for known issues
2. **While working**: Note gotchas in `learnings.md`
3. **Decisions**: Document in `decisions.md` with rationale
4. **After completion**: Update `blockers.md` if resolved

### Sprint Cycle

```
Sprint Start:
  PM creates devnotes/pm/sprint-XX-plan.md

During Sprint:
  Each engineer updates their learnings.md

Sprint End:
  PM creates devnotes/pm/sprint-XX-retro.md
  Engineers archive resolved blockers
```

### Handoffs

When handing off work between roles:

1. Author creates handoff note in their directory
2. Note includes: context, state, blockers, next steps
3. Receiving role acknowledges in their blockers.md

## Quick Reference

### Finding Information

| Question | Look In |
|----------|---------|
| Why did we choose X? | `*/decisions.md` |
| Current sprint status | `pm/sprint-*.md` |
| Known issues with Neo4j | `graph/blockers.md` |
| Async patterns to follow | `backend/learnings.md` |
| Security concerns | `security/threat-model.md` |

### Creating Notes

```bash
# Create a new learning note
echo "# Topic\n\n**Date**: $(date +%Y-%m-%d)\n**Author**: [Role]\n\n## Context\n\n## Details\n" > devnotes/[role]/topic.md
```

## Integration with Specs

Devnotes complement the formal specs in `specs/`:

| Specs | Devnotes |
|-------|----------|
| What to build | How we built it |
| Requirements | Implementation insights |
| Architecture | Gotchas and patterns |
| Formal | Informal |

Keep specs authoritative; use devnotes for working knowledge.
