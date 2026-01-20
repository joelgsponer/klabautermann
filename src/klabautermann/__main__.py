#!/usr/bin/env python3
"""
Klabautermann entry point for `python -m klabautermann`.

Usage:
    python -m klabautermann              # Start CLI interface
    python -m klabautermann --help       # Show help
    python -m klabautermann --session id # Resume specific session
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

from klabautermann.agents.executor import Executor
from klabautermann.agents.ingestor import Ingestor
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.agents.researcher import Researcher
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.config.manager import ConfigManager
from klabautermann.config.quartermaster import Quartermaster
from klabautermann.core.exceptions import GraphConnectionError, StartupError
from klabautermann.core.logger import logger, set_cli_log_level
from klabautermann.core.shutdown import ShutdownManager
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.neo4j_client import Neo4jClient


if TYPE_CHECKING:
    from klabautermann.agents.base_agent import BaseAgent


class Klabautermann:
    """
    Main application class.

    Manages lifecycle of all agents and shared resources.
    Coordinates initialization, startup, and shutdown.
    """

    def __init__(self) -> None:
        """Initialize application state."""
        # Configuration
        self.config_manager: ConfigManager | None = None
        self.quartermaster: Quartermaster | None = None

        # Shared clients
        self.neo4j: Neo4jClient | None = None
        self.graphiti: GraphitiClient | None = None

        # LLM client (lazy init)
        self._anthropic: Any = None

        # Agents
        self.agents: dict[str, BaseAgent] = {}
        self.agent_tasks: list[asyncio.Task[Any]] = []

        # Shutdown manager for graceful shutdown
        self._shutdown_manager = ShutdownManager(
            timeout_seconds=30.0,
            drain_timeout_seconds=10.0,
        )

        # Legacy shutdown event (for signal handlers)
        self._shutdown_event = asyncio.Event()
        self._cli_task: asyncio.Task[Any] | None = None
        self._cli: CLIDriver | None = None

    @property
    def anthropic(self) -> Any:
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise StartupError("ANTHROPIC_API_KEY not set")
            self._anthropic = anthropic.Anthropic(api_key=api_key)
        return self._anthropic

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("[CHART] Initializing Klabautermann...")

        # Load environment
        load_dotenv()
        self._validate_environment()

        # Initialize configuration
        logger.info("[CHART] Loading configuration...")
        # Find config dir - check both package location and project root
        config_dir = Path(__file__).parent.parent.parent / "config" / "agents"
        if not config_dir.exists():
            # Fallback to relative path from working directory
            config_dir = Path.cwd() / "config" / "agents"
        self.config_manager = ConfigManager(config_dir)
        self.quartermaster = Quartermaster(self.config_manager)

        # Initialize Neo4j
        logger.info("[CHART] Connecting to Neo4j...")
        self.neo4j = Neo4jClient(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", ""),
        )
        await self.neo4j.connect()
        # Register for graceful shutdown
        self._shutdown_manager.register_client("neo4j", self.neo4j.disconnect)

        # Initialize Graphiti (optional - may fail if OpenAI key not set)
        if os.getenv("OPENAI_API_KEY"):
            try:
                logger.info("[CHART] Initializing Graphiti...")
                self.graphiti = GraphitiClient(
                    neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                    neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
                    neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
                    openai_api_key=os.getenv("OPENAI_API_KEY"),
                )
                await self.graphiti.connect()
                # Register for graceful shutdown
                self._shutdown_manager.register_client("graphiti", self.graphiti.disconnect)
            except Exception as e:
                logger.warning(
                    f"[SWELL] Graphiti initialization failed (entity extraction disabled): {e}"
                )
                self.graphiti = None
        else:
            logger.warning("[SWELL] OPENAI_API_KEY not set - entity extraction disabled")

        # Create agents
        await self._create_agents()

        # Wire up agent registry
        self._wire_agent_registry()

        # Start hot-reload
        self.quartermaster.start()

        logger.info("[BEACON] Klabautermann initialized successfully")

    def _validate_environment(self) -> None:
        """Validate required environment variables."""
        required = [
            "ANTHROPIC_API_KEY",
            "NEO4J_PASSWORD",
        ]

        missing = [var for var in required if not os.getenv(var)]
        if missing:
            raise StartupError(f"Missing required environment variables: {', '.join(missing)}")

    async def _create_agents(self) -> None:
        """Create all agent instances."""
        logger.info("[CHART] Creating agents...")

        # Helper to convert config to dict
        def get_config_dict(name: str) -> dict[str, Any] | None:
            cfg = self.config_manager.get(name) if self.config_manager else None
            return cfg.model_dump() if cfg else None

        # Create Orchestrator - uses Sonnet model
        self.agents["orchestrator"] = Orchestrator(
            graphiti=self.graphiti,
            thread_manager=None,  # Will be created in Sprint 3 if needed
            config=get_config_dict("orchestrator"),
        )

        # Create Ingestor - uses Opus model
        if self.graphiti:
            self.agents["ingestor"] = Ingestor(
                name="ingestor",
                config=get_config_dict("ingestor"),
                graphiti_client=self.graphiti,
            )
        else:
            logger.warning("[SWELL] Ingestor not created - Graphiti unavailable")

        # Create Researcher - uses Haiku model
        self.agents["researcher"] = Researcher(
            name="researcher",
            config=get_config_dict("researcher"),
            graphiti=self.graphiti,
            neo4j=self.neo4j,
        )

        # Create Executor - uses Sonnet model
        self.agents["executor"] = Executor(
            name="executor",
            config=get_config_dict("executor"),
            google_bridge=self.google_bridge if hasattr(self, "google_bridge") else None,
        )

        logger.info(f"[CHART] Created {len(self.agents)} agents")

        # Register agents for graceful shutdown (in creation order)
        for name, agent in self.agents.items():
            self._shutdown_manager.register_agent(name, agent)

    def _wire_agent_registry(self) -> None:
        """Wire up agent registry for message routing."""
        logger.debug("[WHISPER] Wiring agent registry...")

        for agent in self.agents.values():
            agent.agent_registry = self.agents

        # Register config change callbacks
        if self.quartermaster:
            for name in self.agents:
                self.quartermaster.register_callback(
                    name, lambda n: self._on_agent_config_change(n)
                )

    async def _on_agent_config_change(self, agent_name: str) -> None:
        """Handle agent config change."""
        logger.info(f"[BEACON] Config changed for {agent_name}")
        # Agent will pick up new config on next request

    async def start(self) -> None:
        """Start all agents and CLI."""
        logger.info("[CHART] Starting agent loops...")

        # Start agent processing loops
        for name, agent in self.agents.items():
            task = asyncio.create_task(agent.run(), name=f"agent-{name}")
            self.agent_tasks.append(task)
            logger.debug(f"[WHISPER] Started {name} agent loop")

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start CLI
        logger.info("[BEACON] Klabautermann ready. Starting CLI...")
        orchestrator = self.agents["orchestrator"]
        if not isinstance(orchestrator, Orchestrator):
            raise StartupError("orchestrator agent must be an Orchestrator instance")
        self._cli = CLIDriver(orchestrator)

        # Register CLI for graceful shutdown
        self._shutdown_manager.register_channel("cli", self._cli)

        try:
            # Run CLI in the main task
            await self._cli.start()
        except asyncio.CancelledError:
            logger.info("[CHART] CLI cancelled")

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal (SIGINT/SIGTERM)."""
        logger.info("[CHART] Shutdown signal received")

        # Request graceful shutdown via manager
        self._shutdown_manager.request_shutdown()
        self._shutdown_event.set()

        # Stop CLI if running (allows graceful exit from REPL)
        if self._cli:
            # Create task to stop CLI asynchronously
            self._cli_task = asyncio.create_task(self._cli.stop())

        # Cancel all agent tasks
        for task in self.agent_tasks:
            task.cancel()

    async def shutdown(self) -> None:
        """
        Clean shutdown of all components using ShutdownManager.

        Shutdown order (reverse of startup):
        1. Channels (stops accepting new requests)
        2. Drain pending messages from agent queues
        3. Agents (in reverse registration order)
        4. Clients (Neo4j, Graphiti)
        5. Support services (quartermaster)
        """
        logger.info("[CHART] Shutting down Klabautermann...")

        # Use ShutdownManager for orderly shutdown
        result = await self._shutdown_manager.shutdown()

        # Wait for agent tasks to complete
        if self.agent_tasks:
            # Give tasks a chance to complete gracefully
            done, pending = await asyncio.wait(
                self.agent_tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )

            # Cancel any still-pending tasks
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            logger.debug(
                f"[WHISPER] Agent tasks completed: {len(done)} done, {len(pending)} cancelled"
            )

        # Stop hot-reload (not managed by shutdown manager)
        if self.quartermaster:
            self.quartermaster.stop()
            logger.debug("[WHISPER] Quartermaster stopped")

        if not result.success:
            logger.warning(
                f"[SWELL] Shutdown completed with errors: {result.error}",
                extra={"phase": result.phase.value},
            )

    async def run(self) -> None:
        """Main entry point."""
        try:
            await self.initialize()
            await self.start()
        except Exception as e:
            logger.error(f"[STORM] Fatal error: {e}", exc_info=True)
            raise
        finally:
            await self.shutdown()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Klabautermann - Personal Knowledge Navigator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m klabautermann                    Start new CLI session
  python -m klabautermann --session abc123   Resume session abc123

Environment Variables:
  ANTHROPIC_API_KEY    Required - Claude API key
  NEO4J_URI            Neo4j connection URI (default: bolt://localhost:7687)
  NEO4J_USERNAME       Neo4j username (default: neo4j)
  NEO4J_PASSWORD       Required - Neo4j password
  OPENAI_API_KEY       Optional - For entity extraction via Graphiti
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
        version="Klabautermann v0.2.0 (Sprint 2)",
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

    # Set CLI-appropriate log level (WARNING by default to reduce noise)
    set_cli_log_level()

    # Note: session_id support will be implemented in Sprint 3 with thread persistence
    if args.session:
        logger.warning("[SWELL] Session resumption not yet implemented (Sprint 3 feature)")

    app = Klabautermann()

    try:
        await app.run()
        return 0

    except GraphConnectionError as e:
        logger.error(f"[SHIPWRECK] Database connection failed: {e}")
        logger.error("Make sure Neo4j is running:")
        logger.error("  docker-compose up -d neo4j")
        logger.error("  # Wait for Neo4j to start, then try again")
        return 1

    except StartupError as e:
        logger.error(f"[SHIPWRECK] Startup failed: {e}")
        logger.error("Check your .env file:")
        logger.error("  cp .env.example .env")
        logger.error("  # Edit .env with your API keys and database credentials")
        return 1

    except KeyboardInterrupt:
        logger.info("[CHART] Interrupted by user")
        return 0

    except Exception as e:
        logger.error(f"[SHIPWRECK] Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        # Already handled in main()
        sys.exit(0)
