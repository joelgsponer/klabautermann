# Update Documentation for v2

## Metadata
- **ID**: T067
- **Priority**: P2
- **Category**: maintenance
- **Effort**: S
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T060 - Migrate to v2 (after migration is complete)

## Context
Update all relevant documentation to reflect the new orchestrator v2 architecture. This ensures the codebase documentation stays in sync with implementation.

## Requirements
- [ ] Update AGENTS.md Section 1.1 (Orchestrator) to reflect v2
- [ ] Update PROGRESS.md with v2 completion notes
- [ ] Add MAINAGENT.md to Related Specifications in AGENTS.md
- [ ] Update system prompt documentation if changed
- [ ] Update architecture diagrams if needed
- [ ] Add v2 notes to NEWS.md (user-visible change)

## Acceptance Criteria
- [ ] AGENTS.md describes Think-Dispatch-Synthesize pattern
- [ ] AGENTS.md removes/deprecates intent classification description
- [ ] PROGRESS.md shows orchestrator v2 as completed
- [ ] NEWS.md has entry for improved multi-intent handling
- [ ] No outdated references to v1 workflow in docs

## Implementation Notes
Key updates to AGENTS.md:

**Section 1.1 - The Orchestrator**:
- Change from "classifies intent" to "plans tasks"
- Add description of parallel subagent dispatch
- Reference MAINAGENT.md for detailed spec

**System Prompt** (if changed):
- Update the system prompt shown in docs
- Reflect task planning instead of intent classification

**NEWS.md entry**:
```markdown
## [Unreleased]

### Improved
- Multi-intent message handling: Orchestrator now identifies and handles
  multiple intents in a single message (e.g., "Learned X. What about Y?")
- Parallel subagent execution for faster responses
- Richer context injection with cross-thread awareness
```
