# Create Database Initialization Script

## Metadata
- **ID**: T007
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @graph-engineer

## Specs
- Primary: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) Section 4
- Related: [DEPLOYMENT.md](../../specs/infrastructure/DEPLOYMENT.md)

## Dependencies
- [ ] T006 - Ontology constants (for constraint/index definitions)

## Context
The database initialization script sets up the Neo4j schema with all required constraints and indexes. This script must be idempotent (safe to run multiple times) and validate the connection before attempting schema changes.

## Requirements
- [ ] Create `scripts/init_database.py` with:
  - [ ] Connection validation (check Neo4j is accessible)
  - [ ] Create all uniqueness constraints from ONTOLOGY.md
  - [ ] Create all property existence constraints
  - [ ] Create all full-text indexes
  - [ ] Create all temporal relationship indexes
  - [ ] Create vector indexes (for Graphiti/embeddings)
  - [ ] Create spatial index for Location coordinates
  - [ ] Report progress with nautical logging
  - [ ] Handle existing constraints/indexes gracefully (idempotent)

## Acceptance Criteria
- [ ] Script runs without error on fresh database
- [ ] Script runs without error on already-initialized database
- [ ] `SHOW CONSTRAINTS` in Neo4j Browser shows all constraints
- [ ] `SHOW INDEXES` in Neo4j Browser shows all indexes
- [ ] Script logs progress using nautical format
- [ ] Script exits with error code if Neo4j unreachable

## Implementation Notes

```python
#!/usr/bin/env python3
"""
Initialize Klabautermann Neo4j database schema.

Usage: python scripts/init_database.py
"""
import asyncio
import os
import sys

from neo4j import AsyncGraphDatabase

# Import constraints and indexes from ontology
from klabautermann.core.ontology import CONSTRAINTS, INDEXES
from klabautermann.core.logger import logger


async def verify_connection(driver):
    """Verify Neo4j connection is working."""
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 as ping")
            await result.single()
            logger.info("[BEACON] Neo4j connection verified")
            return True
    except Exception as e:
        logger.error(f"[SHIPWRECK] Neo4j connection failed: {e}")
        return False


async def create_constraints(driver):
    """Create all schema constraints."""
    async with driver.session() as session:
        for constraint in CONSTRAINTS:
            try:
                await session.run(constraint)
                logger.info(f"[CHART] Created constraint: {constraint[:50]}...")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"[CHART] Constraint exists: {constraint[:50]}...")
                else:
                    logger.error(f"[STORM] Failed: {constraint[:50]}... - {e}")
                    raise


async def create_indexes(driver):
    """Create all schema indexes."""
    # Similar pattern to constraints
    pass


async def main():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    if not password:
        logger.error("[SHIPWRECK] NEO4J_PASSWORD not set")
        sys.exit(1)

    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    try:
        if not await verify_connection(driver):
            sys.exit(1)

        await create_constraints(driver)
        await create_indexes(driver)

        logger.info("[BEACON] Database initialization complete")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Note: Vector indexes require specific syntax and dimension configuration - see ONTOLOGY.md Section 4.3.
