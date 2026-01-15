# Conflict Detection in Summaries

## Metadata
- **ID**: T048
- **Priority**: P2
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: alchemist

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.5 (Archivist conflict detection)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 2 (Temporal queries)

## Dependencies
- [x] T038 - Thread Summary Models (FactConflict model)
- [x] T039 - LLM Summarization Pipeline
- [x] T010 - Neo4j client

## Context
When the Archivist summarizes a thread, it may discover information that contradicts existing facts in the graph. For example, if Sarah's employer changes or a project status is updated. This task implements conflict detection by comparing extracted facts against current graph state.

## Requirements
- [ ] Extend summarization pipeline in `src/klabautermann/agents/summarization.py`:

### Conflict Detection
- [ ] `detect_conflicts(facts: list[ExtractedFact], driver: AsyncDriver) -> list[FactConflict]`
  - For each extracted fact, query current state
  - Compare new fact with existing
  - Generate FactConflict if mismatch detected

### Conflict Types to Detect
- [ ] Employment changes: Person WORKS_AT changed
- [ ] Project status: status differs from graph
- [ ] Task completion: marked done vs graph state
- [ ] Relationship changes: KNOWS, REPORTS_TO changes

### Conflict Resolution
- [ ] Automatic: EXPIRE_OLD for clear temporal updates
- [ ] User review: Ambiguous conflicts flagged
- [ ] Record resolution action in Note

### Integration with Archivist
- [ ] Call conflict detection after summarization
- [ ] Add conflicts to ThreadSummary
- [ ] Flag Note for user validation if conflicts detected
- [ ] Apply automatic resolutions (expire old relationships)

## Acceptance Criteria
- [ ] Employment changes detected and flagged
- [ ] Temporal updates expire old relationships
- [ ] Ambiguous conflicts flagged for review
- [ ] Conflicts included in summary output
- [ ] Note marked requires_user_validation when needed
- [ ] Unit tests with graph fixtures

## Implementation Notes

```python
async def detect_conflicts(
    facts: list[ExtractedFact],
    driver: AsyncDriver
) -> list[FactConflict]:
    """
    Compare extracted facts against current graph state.
    Returns list of detected conflicts.
    """
    conflicts = []

    for fact in facts:
        if fact.entity_type == "Person":
            conflict = await _check_person_conflicts(fact, driver)
            if conflict:
                conflicts.append(conflict)
        elif fact.entity_type == "Project":
            conflict = await _check_project_conflicts(fact, driver)
            if conflict:
                conflicts.append(conflict)

    return conflicts


async def _check_person_conflicts(
    fact: ExtractedFact,
    driver: AsyncDriver
) -> Optional[FactConflict]:
    """Check for conflicts with Person facts."""

    # Check employment changes
    if "works at" in fact.fact.lower() or "joined" in fact.fact.lower():
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (p:Person)
                WHERE toLower(p.name) = toLower($name)
                OPTIONAL MATCH (p)-[r:WORKS_AT {expired_at: null}]->(o:Organization)
                RETURN p.uuid as person_uuid, o.name as current_employer
                """,
                {"name": fact.entity}
            )
            record = await result.single()

            if record and record["current_employer"]:
                # Extract new employer from fact
                new_employer = _extract_employer_from_fact(fact.fact)
                if new_employer and new_employer.lower() != record["current_employer"].lower():
                    return FactConflict(
                        existing_fact=f"{fact.entity} works at {record['current_employer']}",
                        new_fact=fact.fact,
                        entity=fact.entity,
                        resolution=ConflictResolution.EXPIRE_OLD
                    )

    return None


def _extract_employer_from_fact(fact_text: str) -> Optional[str]:
    """Extract organization name from employment fact."""
    # Simple extraction - could be enhanced with NLP
    patterns = [
        r"works at (\w+(?:\s+\w+)*)",
        r"joined (\w+(?:\s+\w+)*)",
        r"now at (\w+(?:\s+\w+)*)"
    ]
    import re
    for pattern in patterns:
        match = re.search(pattern, fact_text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


async def apply_conflict_resolutions(
    conflicts: list[FactConflict],
    driver: AsyncDriver
) -> int:
    """Apply automatic conflict resolutions. Returns count applied."""
    applied = 0

    for conflict in conflicts:
        if conflict.resolution == ConflictResolution.EXPIRE_OLD:
            # Expire the old relationship
            success = await _expire_old_relationship(conflict, driver)
            if success:
                applied += 1

    return applied


async def _expire_old_relationship(
    conflict: FactConflict,
    driver: AsyncDriver
) -> bool:
    """Expire old relationship for temporal update."""
    # This is a simplified version - real implementation
    # would need to parse the conflict to find the relationship
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Person)-[r:WORKS_AT {expired_at: null}]->(o:Organization)
            WHERE toLower(p.name) = toLower($entity)
            SET r.expired_at = timestamp()
            RETURN count(r) as expired
            """,
            {"entity": conflict.entity}
        )
        record = await result.single()
        return record["expired"] > 0 if record else False
```

### Testing Strategy
Create fixtures with:
- Person with current employer
- Summary that mentions new employer
- Verify conflict detected and resolution applied
- Test ambiguous cases flagged for review
