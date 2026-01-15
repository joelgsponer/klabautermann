#!/usr/bin/env python3
"""
Klabautermann - Personal Knowledge Navigator

A multi-agent system with a temporal knowledge graph for personal knowledge management.
Named after the helpful ship spirit from Germanic folklore.

Usage:
    python main.py                    # Start CLI interface
    python main.py --help             # Show help
    python main.py --session <id>     # Resume specific session

Environment:
    Copy .env.example to .env and configure before running.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def setup_path() -> None:
    """Add src to Python path for imports."""
    src_path = Path(__file__).parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


# Set up path before imports
setup_path()

from dotenv import load_dotenv  # noqa: E402

from klabautermann.core.exceptions import GraphConnectionError  # noqa: E402
from klabautermann.core.logger import logger  # noqa: E402


def check_environment() -> dict[str, str | None]:
    """
    Verify required environment variables are set.

    Returns:
        Configuration dictionary with environment values.

    Raises:
        SystemExit: If required variables are missing.
    """
    required = [
        "ANTHROPIC_API_KEY",
    ]

    # These have defaults but warn if not set
    recommended = [
        ("NEO4J_URI", "bolt://localhost:7687"),
        ("NEO4J_USERNAME", "neo4j"),
        ("NEO4J_PASSWORD", None),  # No default - must be set
    ]

    optional = [
        "OPENAI_API_KEY",  # For embeddings
        "LOG_LEVEL",
    ]

    config: dict[str, str | None] = {}
    missing: list[str] = []

    # Check required
    for var in required:
        value = os.getenv(var)
        if not value:
            missing.append(var)
        config[var] = value

    # Check recommended with defaults
    for var, default in recommended:
        value = os.getenv(var, default)
        if value is None:
            missing.append(var)
        config[var] = value

    # Add optional
    for var in optional:
        config[var] = os.getenv(var)

    if missing:
        logger.error(f"[SHIPWRECK] Missing required environment variables: {missing}")
        logger.error("Copy .env.example to .env and fill in values:")
        logger.error("  cp .env.example .env")
        logger.error("  # Edit .env with your API keys and database credentials")
        sys.exit(1)

    return config


async def initialize_components(
    config: dict[str, str | None],
    session_id: str | None = None,
) -> tuple:
    """
    Initialize all application components.

    Args:
        config: Configuration dictionary from check_environment.
        session_id: Optional session ID to resume.

    Returns:
        Tuple of (neo4j, graphiti, orchestrator, cli).
    """
    from klabautermann.agents.orchestrator import Orchestrator
    from klabautermann.channels.cli_driver import CLIDriver
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient
    from klabautermann.memory.thread_manager import ThreadManager

    logger.info("[CHART] Initializing components...")

    # Neo4j client
    neo4j = Neo4jClient(
        uri=config["NEO4J_URI"],
        username=config["NEO4J_USERNAME"],
        password=config["NEO4J_PASSWORD"],
    )
    await neo4j.connect()

    # Thread manager
    thread_manager = ThreadManager(neo4j)

    # Graphiti client (optional - may fail if OpenAI key not set)
    graphiti: GraphitiClient | None = None
    if config.get("OPENAI_API_KEY"):
        try:
            graphiti = GraphitiClient(
                neo4j_uri=config["NEO4J_URI"],
                neo4j_user=config["NEO4J_USERNAME"],
                neo4j_password=config["NEO4J_PASSWORD"],
                openai_api_key=config["OPENAI_API_KEY"],
            )
            await graphiti.connect()
        except Exception as e:
            logger.warning(
                f"[SWELL] Graphiti initialization failed (entity extraction disabled): {e}"
            )
            graphiti = None
    else:
        logger.warning("[SWELL] OPENAI_API_KEY not set - entity extraction disabled")

    # Orchestrator
    orchestrator = Orchestrator(
        graphiti=graphiti,
        thread_manager=thread_manager,
    )

    # CLI driver with optional session ID
    cli_config = {}
    if session_id:
        cli_config["session_id"] = session_id

    cli = CLIDriver(
        orchestrator=orchestrator,
        config=cli_config,
    )

    logger.info("[BEACON] All components initialized")

    return neo4j, graphiti, orchestrator, cli


async def shutdown(
    neo4j: object | None,
    graphiti: object | None,
) -> None:
    """
    Clean shutdown of all connections.

    Args:
        neo4j: Neo4j client instance.
        graphiti: Graphiti client instance.
    """
    logger.info("[CHART] Shutting down...")

    if graphiti:
        try:
            await graphiti.disconnect()
        except Exception as e:
            logger.warning(f"[SWELL] Graphiti disconnect error: {e}")

    if neo4j:
        try:
            await neo4j.disconnect()
        except Exception as e:
            logger.warning(f"[SWELL] Neo4j disconnect error: {e}")

    logger.info("[BEACON] Shutdown complete")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Klabautermann - Personal Knowledge Navigator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    Start new CLI session
  python main.py --session abc123   Resume session abc123

Environment Variables:
  ANTHROPIC_API_KEY    Required - Claude API key
  NEO4J_URI            Neo4j connection URI (default: bolt://localhost:7687)
  NEO4J_USERNAME       Neo4j username (default: neo4j)
  NEO4J_PASSWORD       Required - Neo4j password
  OPENAI_API_KEY       Optional - For entity extraction
  LOG_LEVEL            Log verbosity (default: INFO)
""",
    )

    parser.add_argument(
        "--session",
        "-s",
        type=str,
        help="Resume a specific session by ID",
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version="Klabautermann v0.1.0",
    )

    return parser.parse_args()


async def main() -> int:
    """
    Main entry point for Klabautermann.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    # Parse arguments
    args = parse_args()

    # Load environment variables from .env file
    load_dotenv()

    # Check environment
    config = check_environment()

    neo4j = None
    graphiti = None

    try:
        # Initialize components
        neo4j, graphiti, orchestrator, cli = await initialize_components(
            config,
            session_id=args.session,
        )

        # Start CLI (blocking)
        await cli.start()

        return 0

    except GraphConnectionError as e:
        logger.error(f"[SHIPWRECK] Database connection failed: {e}")
        logger.error("Make sure Neo4j is running:")
        logger.error("  docker-compose up -d neo4j")
        logger.error("  # Wait for Neo4j to start, then try again")
        return 1

    except KeyboardInterrupt:
        logger.info("[CHART] Interrupted by user")
        return 0

    except Exception as e:
        logger.error(f"[SHIPWRECK] Unexpected error: {e}", exc_info=True)
        return 1

    finally:
        await shutdown(neo4j, graphiti)


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        # Already handled in main()
        sys.exit(0)
