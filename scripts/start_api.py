#!/usr/bin/env python3
"""
Start the Klabautermann API server.

This script initializes the full Klabautermann stack (orchestrator, graphiti, etc.)
and runs the FastAPI WebSocket server for external clients like the Go TUI.

Usage:
    python scripts/start_api.py [--host HOST] [--port PORT]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


async def main(host: str, port: int) -> None:
    """Initialize and run the API server."""
    import os

    import uvicorn

    from klabautermann.agents.orchestrator import Orchestrator
    from klabautermann.api.server import app, set_orchestrator
    from klabautermann.config.manager import ConfigManager
    from klabautermann.core.logger import logger
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient
    from klabautermann.memory.thread_manager import ThreadManager

    logger.info("[CHART] Starting Klabautermann API server...")

    # Load configuration
    config_dir = Path(__file__).parent.parent / "config" / "agents"
    config_manager = ConfigManager(config_dir)

    # Initialize Neo4j client for thread management
    neo4j_client = Neo4jClient(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    try:
        await neo4j_client.connect()
        thread_manager = ThreadManager(neo4j_client)
        logger.info("[BEACON] Thread management enabled")
    except Exception as e:
        logger.warning(f"[SWELL] Neo4j connection failed: {e}")
        thread_manager = None
        neo4j_client = None

    # Initialize Graphiti client
    graphiti_client = GraphitiClient()
    try:
        await graphiti_client.connect()
    except Exception as e:
        logger.warning(f"[SWELL] Graphiti connection failed: {e}")
        graphiti_client = None

    # Initialize orchestrator
    orchestrator_config = config_manager.get("orchestrator")
    orchestrator = Orchestrator(
        graphiti=graphiti_client,
        thread_manager=thread_manager,
        config=orchestrator_config.model_dump() if orchestrator_config else {},
    )

    # Register orchestrator with API
    set_orchestrator(orchestrator)

    logger.info(f"[BEACON] API server starting on {host}:{port}")

    # Run uvicorn server
    server_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)

    try:
        await server.serve()
    finally:
        if graphiti_client:
            await graphiti_client.disconnect()
        if neo4j_client:
            await neo4j_client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Klabautermann API server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port))
