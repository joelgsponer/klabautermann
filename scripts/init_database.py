#!/usr/bin/env python3
"""
Initialize Klabautermann Neo4j database schema.

Creates all constraints, indexes, and vector indexes defined in the ontology.
This script is idempotent - safe to run multiple times.

Usage:
    python scripts/init_database.py
    # or
    make init-db
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ClientError

from klabautermann.core.logger import logger
from klabautermann.core.ontology import CONSTRAINTS, ENTERPRISE_CONSTRAINTS, INDEXES, VECTOR_INDEXES


async def verify_connection(driver: AsyncGraphDatabase.driver) -> bool:
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


async def get_db_version(driver: AsyncGraphDatabase.driver) -> str:
    """Get Neo4j database version."""
    try:
        async with driver.session() as session:
            result = await session.run("CALL dbms.components() YIELD name, versions RETURN versions[0] as version")
            record = await result.single()
            return record["version"] if record else "unknown"
    except Exception:
        return "unknown"


async def create_constraints(driver: AsyncGraphDatabase.driver) -> tuple[int, int]:
    """Create all schema constraints. Returns (created, existing) counts."""
    created = 0
    existing = 0

    async with driver.session() as session:
        for constraint in CONSTRAINTS:
            try:
                await session.run(constraint)
                logger.info(f"[CHART] Created constraint: {constraint[:60]}...")
                created += 1
            except ClientError as e:
                if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                    logger.debug(f"[WHISPER] Constraint exists: {constraint[:60]}...")
                    existing += 1
                else:
                    logger.error(f"[STORM] Failed to create constraint: {e}")
                    raise
            except Exception as e:
                logger.error(f"[STORM] Unexpected error creating constraint: {e}")
                raise

    return created, existing


async def create_enterprise_constraints(driver: AsyncGraphDatabase.driver) -> tuple[int, int, bool]:
    """
    Try to create Enterprise-only constraints.

    Returns (created, skipped, is_enterprise) - skipped if running Community Edition.
    """
    created = 0
    skipped = 0
    is_enterprise = True

    async with driver.session() as session:
        for constraint in ENTERPRISE_CONSTRAINTS:
            try:
                await session.run(constraint)
                logger.info(f"[CHART] Created constraint: {constraint[:60]}...")
                created += 1
            except Exception as e:
                error_msg = str(e)
                if "already exists" in error_msg.lower() or "equivalent" in error_msg.lower():
                    logger.debug(f"[WHISPER] Constraint exists: {constraint[:60]}...")
                    created += 1  # Count as success - it exists
                elif "Enterprise Edition" in error_msg or "PROPERTY EXISTENCE" in error_msg:
                    # Community Edition - skip all remaining enterprise constraints
                    is_enterprise = False
                    skipped = len(ENTERPRISE_CONSTRAINTS)
                    logger.info("[CHART] Neo4j Community Edition detected - skipping property existence constraints")
                    break
                else:
                    logger.warning(f"[SWELL] Could not create constraint: {e}")
                    skipped += 1

    return created, skipped, is_enterprise


async def create_indexes(driver: AsyncGraphDatabase.driver) -> tuple[int, int]:
    """Create all schema indexes. Returns (created, existing) counts."""
    created = 0
    existing = 0

    async with driver.session() as session:
        for index in INDEXES:
            try:
                await session.run(index)
                logger.info(f"[CHART] Created index: {index[:60]}...")
                created += 1
            except ClientError as e:
                if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                    logger.debug(f"[WHISPER] Index exists: {index[:60]}...")
                    existing += 1
                else:
                    logger.error(f"[STORM] Failed to create index: {e}")
                    raise
            except Exception as e:
                logger.error(f"[STORM] Unexpected error creating index: {e}")
                raise

    return created, existing


async def create_vector_indexes(driver: AsyncGraphDatabase.driver) -> tuple[int, int]:
    """Create vector indexes for semantic search. Returns (created, existing) counts."""
    created = 0
    existing = 0

    async with driver.session() as session:
        for index in VECTOR_INDEXES:
            try:
                # Clean up the multiline index definition
                clean_index = " ".join(index.split())
                await session.run(clean_index)
                logger.info(f"[CHART] Created vector index: {clean_index[:60]}...")
                created += 1
            except ClientError as e:
                if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                    logger.debug(f"[WHISPER] Vector index exists: {index[:60]}...")
                    existing += 1
                else:
                    # Vector indexes may not be supported on all Neo4j editions
                    logger.warning(f"[SWELL] Could not create vector index: {e}")
            except Exception as e:
                logger.warning(f"[SWELL] Vector index creation skipped: {e}")

    return created, existing


async def show_schema_summary(driver: AsyncGraphDatabase.driver) -> None:
    """Display summary of current schema."""
    async with driver.session() as session:
        # Count constraints
        result = await session.run("SHOW CONSTRAINTS")
        constraints = await result.data()
        constraint_count = len(constraints)

        # Count indexes
        result = await session.run("SHOW INDEXES")
        indexes = await result.data()
        index_count = len(indexes)

        logger.info(f"[BEACON] Schema summary: {constraint_count} constraints, {index_count} indexes")


async def main() -> int:
    """Main entry point for database initialization."""
    # Load environment variables
    load_dotenv()

    # Get Neo4j configuration
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    if not password:
        logger.error("[SHIPWRECK] NEO4J_PASSWORD environment variable not set")
        return 1

    logger.info(f"[CHART] Initializing database at {uri}")

    # Create driver
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    try:
        # Verify connection
        if not await verify_connection(driver):
            return 1

        # Get database version
        version = await get_db_version(driver)
        logger.info(f"[CHART] Neo4j version: {version}")

        # Create constraints
        logger.info("[CHART] Creating constraints...")
        c_created, c_existing = await create_constraints(driver)
        logger.info(f"[BEACON] Constraints: {c_created} created, {c_existing} already existed")

        # Try Enterprise-only constraints (gracefully skip on Community Edition)
        logger.info("[CHART] Checking for Enterprise constraints...")
        e_created, e_skipped, is_enterprise = await create_enterprise_constraints(driver)
        if is_enterprise:
            logger.info(f"[BEACON] Enterprise constraints: {e_created} created")
        else:
            logger.info(f"[BEACON] Enterprise constraints: skipped ({e_skipped} require Enterprise Edition)")

        # Create indexes
        logger.info("[CHART] Creating indexes...")
        i_created, i_existing = await create_indexes(driver)
        logger.info(f"[BEACON] Indexes: {i_created} created, {i_existing} already existed")

        # Create vector indexes
        logger.info("[CHART] Creating vector indexes...")
        v_created, v_existing = await create_vector_indexes(driver)
        logger.info(f"[BEACON] Vector indexes: {v_created} created, {v_existing} already existed")

        # Show summary
        await show_schema_summary(driver)

        logger.info("[BEACON] Database initialization complete!")
        return 0

    except Exception as e:
        logger.error(f"[SHIPWRECK] Database initialization failed: {e}")
        return 1

    finally:
        await driver.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
