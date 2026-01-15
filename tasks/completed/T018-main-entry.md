# Create Main Application Entry Point

## Metadata
- **ID**: T018
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 8
- Related: [DEPLOYMENT.md](../../specs/infrastructure/DEPLOYMENT.md)

## Dependencies
- [ ] T002 - Python Dockerfile
- [ ] T004 - Environment configuration
- [ ] T015 - CLI thread persistence
- [ ] T017 - Simple Orchestrator

## Context
The main entry point initializes all components, wires them together, and starts the application. It handles environment loading, connection management, and graceful shutdown.

## Requirements
- [ ] Create `main.py` in project root with:

### Initialization
- [ ] Load environment variables from .env
- [ ] Initialize Neo4j client and verify connection
- [ ] Initialize Graphiti client
- [ ] Initialize Thread Manager
- [ ] Initialize Orchestrator with dependencies
- [ ] Initialize CLI Driver with Orchestrator

### Connection Management
- [ ] Connect to Neo4j before starting
- [ ] Connect to Graphiti before starting
- [ ] Verify all connections healthy

### Main Loop
- [ ] Start CLI driver (blocking)
- [ ] Handle KeyboardInterrupt gracefully

### Shutdown
- [ ] Close all connections on exit
- [ ] Log shutdown message
- [ ] Exit cleanly

## Acceptance Criteria
- [ ] `python main.py` starts the application
- [ ] Missing environment variables cause clear error
- [ ] Neo4j connection failure causes clear error
- [ ] Ctrl+C triggers graceful shutdown
- [ ] All connections closed on exit

## Implementation Notes

```python
#!/usr/bin/env python3
"""
Klabautermann - Personal Knowledge Navigator

Usage: python main.py
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

from klabautermann.core.logger import logger
from klabautermann.core.exceptions import GraphConnectionError
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.thread_manager import ThreadManager
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.channels.cli_driver import CLIDriver


def check_environment() -> dict:
    """Verify required environment variables are set."""
    required = [
        "ANTHROPIC_API_KEY",
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
    ]

    optional = [
        "OPENAI_API_KEY",  # For embeddings
        "LOG_LEVEL",
    ]

    config = {}
    missing = []

    for var in required:
        value = os.getenv(var)
        if not value:
            missing.append(var)
        config[var] = value

    for var in optional:
        config[var] = os.getenv(var)

    if missing:
        logger.error(f"[SHIPWRECK] Missing required environment variables: {missing}")
        logger.error("Copy .env.example to .env and fill in values")
        sys.exit(1)

    return config


async def initialize_components(config: dict) -> tuple:
    """Initialize all application components."""
    logger.info("[CHART] Initializing components...")

    # Neo4j client
    neo4j = Neo4jClient(
        uri=config["NEO4J_URI"],
        username=config["NEO4J_USERNAME"],
        password=config["NEO4J_PASSWORD"],
    )
    await neo4j.connect()

    # Graphiti client
    graphiti = GraphitiClient(
        neo4j_uri=config["NEO4J_URI"],
        neo4j_user=config["NEO4J_USERNAME"],
        neo4j_password=config["NEO4J_PASSWORD"],
        openai_api_key=config.get("OPENAI_API_KEY", ""),
    )
    await graphiti.connect()

    # Thread manager
    thread_manager = ThreadManager(neo4j)

    # Orchestrator
    orchestrator = Orchestrator(
        graphiti=graphiti,
        thread_manager=thread_manager,
    )

    # CLI driver
    cli = CLIDriver(
        orchestrator=orchestrator,
        thread_manager=thread_manager,
    )

    logger.info("[BEACON] All components initialized")

    return neo4j, graphiti, orchestrator, cli


async def shutdown(neo4j, graphiti) -> None:
    """Clean shutdown of all connections."""
    logger.info("[CHART] Shutting down...")

    try:
        if graphiti:
            await graphiti.disconnect()
    except Exception as e:
        logger.warning(f"[SWELL] Graphiti disconnect error: {e}")

    try:
        if neo4j:
            await neo4j.disconnect()
    except Exception as e:
        logger.warning(f"[SWELL] Neo4j disconnect error: {e}")

    logger.info("[BEACON] Shutdown complete")


async def main():
    """Main entry point."""
    # Load environment
    load_dotenv()
    config = check_environment()

    neo4j = None
    graphiti = None

    try:
        # Initialize components
        neo4j, graphiti, orchestrator, cli = await initialize_components(config)

        # Start CLI (blocking)
        await cli.start()

    except GraphConnectionError as e:
        logger.error(f"[SHIPWRECK] Database connection failed: {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("[CHART] Interrupted by user")

    except Exception as e:
        logger.error(f"[SHIPWRECK] Unexpected error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        await shutdown(neo4j, graphiti)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Already handled in main()
```

**Docker Integration**: The Dockerfile should set `ENTRYPOINT ["python", "main.py"]` to run this on container start.
