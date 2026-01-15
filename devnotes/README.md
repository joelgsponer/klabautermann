# Klabautermann Development Notes

Team knowledge repository for insights, decisions, and patterns discovered during development.

## Directory Structure

```
devnotes/
├── shipwright/   # The Shipwright (PM) - sprint status, decisions, blockers
├── carpenter/    # The Carpenter (Backend) - agent patterns, async gotchas
├── navigator/    # The Navigator (Graph) - schema migrations, query patterns
├── alchemist/    # The Alchemist (ML) - prompt iterations, extraction quality
├── engineer/     # The Engineer (DevOps) - docker setup, monitoring, incidents
├── helmsman/     # The Helmsman (Full-Stack) - component design, API contracts
├── scout/        # The Scout (Mobile) - RN patterns, offline sync
├── purser/       # The Purser (Integration) - MCP tools, OAuth flows
├── inspector/    # The Inspector (QA) - test coverage, golden scenarios
├── watchman/     # The Watchman (Security) - threat model, Sieve rules
└── chronicler/   # The Chronicler (Docs) - changelog, terminology
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
  Shipwright creates devnotes/shipwright/sprint-XX-plan.md

During Sprint:
  Each crew member updates their learnings.md

Sprint End:
  Shipwright creates devnotes/shipwright/sprint-XX-retro.md
  Crew archives resolved blockers
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
| Current sprint status | `shipwright/sprint-*.md` |
| Known issues with Neo4j | `navigator/blockers.md` |
| Async patterns to follow | `carpenter/learnings.md` |
| Security concerns | `watchman/threat-model.md` |

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
