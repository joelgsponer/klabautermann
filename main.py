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
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any


# Set up path before imports
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from dotenv import load_dotenv  # noqa: E402

from klabautermann.agents.archivist import Archivist  # noqa: E402
from klabautermann.agents.executor import Executor  # noqa: E402
from klabautermann.agents.ingestor import Ingestor  # noqa: E402
from klabautermann.agents.orchestrator import Orchestrator  # noqa: E402
from klabautermann.agents.researcher import Researcher  # noqa: E402
from klabautermann.agents.scribe import Scribe  # noqa: E402
from klabautermann.channels.cli_driver import CLIDriver  # noqa: E402
from klabautermann.config.manager import ConfigManager  # noqa: E402
from klabautermann.config.quartermaster import Quartermaster  # noqa: E402
from klabautermann.core.exceptions import GraphConnectionError, StartupError  # noqa: E402
from klabautermann.core.logger import logger  # noqa: E402
from klabautermann.memory.graphiti_client import GraphitiClient  # noqa: E402
from klabautermann.memory.neo4j_client import Neo4jClient  # noqa: E402
from klabautermann.memory.thread_manager import ThreadManager  # noqa: E402
from klabautermann.utils.scheduler import (  # noqa: E402
    create_scheduler,
    register_scheduled_jobs,
    shutdown_scheduler,
    start_scheduler,
)


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
        self.thread_manager: ThreadManager | None = None
        self.google_bridge: Any = None

        # LLM client (lazy init)
        self._anthropic: Any = None

        # Agents
        self.agents: dict[str, BaseAgent] = {}
        self.agent_tasks: list[asyncio.Task[Any]] = []

        # Scheduler
        self.scheduler: Any = None

        # Shutdown coordination
        self._shutdown_event = asyncio.Event()
        self._cli_task: asyncio.Task[Any] | None = None

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
        config_dir = Path(__file__).parent / "config" / "agents"
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

        # Initialize ThreadManager (for thread/message persistence)
        logger.info("[CHART] Initializing ThreadManager...")
        self.thread_manager = ThreadManager(self.neo4j)

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
            except Exception as e:
                logger.warning(
                    f"[SWELL] Graphiti initialization failed (entity extraction disabled): {e}"
                )
                self.graphiti = None
        else:
            logger.warning("[SWELL] OPENAI_API_KEY not set - entity extraction disabled")

        # Initialize Google Workspace Bridge (optional - for Gmail/Calendar access)
        self.google_bridge = None
        if os.getenv("GOOGLE_REFRESH_TOKEN"):
            try:
                from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge

                logger.info("[CHART] Initializing Google Workspace Bridge...")
                self.google_bridge = GoogleWorkspaceBridge()
                await self.google_bridge.start()
                logger.info("[BEACON] Google Workspace Bridge connected")
            except Exception as e:
                logger.warning(
                    f"[SWELL] Google Workspace initialization failed (email/calendar disabled): {e}"
                )
                self.google_bridge = None
        else:
            logger.warning("[SWELL] GOOGLE_REFRESH_TOKEN not set - email/calendar disabled")

        # Create agents
        await self._create_agents()

        # Wire up agent registry
        self._wire_agent_registry()

        # Initialize scheduler
        logger.info("[CHART] Setting up scheduler...")
        self._initialize_scheduler()

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
            thread_manager=self.thread_manager,
            config=get_config_dict("orchestrator"),
        )

        # Create Ingestor - passes cleaned text to Graphiti for extraction
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

        # Create Archivist - summarizes and archives inactive threads
        self.agents["archivist"] = Archivist(
            name="archivist",
            config=get_config_dict("archivist"),
            thread_manager=self.thread_manager,
            neo4j_client=self.neo4j,
        )

        # Create Scribe - generates daily reflections/journal entries
        self.agents["scribe"] = Scribe(
            name="scribe",
            config=get_config_dict("scribe"),
            neo4j_client=self.neo4j,
        )

        logger.info(f"[CHART] Created {len(self.agents)} agents")

    def _wire_agent_registry(self) -> None:
        """Wire up agent registry for message routing."""
        logger.debug("[WHISPER] Wiring agent registry...")

        for agent in self.agents.values():
            agent.agent_registry = self.agents

        # Register config change callbacks
        for name in self.agents:
            self.quartermaster.register_callback(name, lambda n: self._on_agent_config_change(n))

    def _initialize_scheduler(self) -> None:
        """Initialize and configure the scheduler for periodic jobs."""
        # Load scheduler configuration
        scheduler_config = self._load_scheduler_config()

        # Create scheduler
        job_store = scheduler_config.get("job_store", "memory")
        timezone = scheduler_config.get("timezone", "UTC")
        sqlite_path = scheduler_config.get("sqlite_path", "data/jobs.sqlite")

        self.scheduler = create_scheduler(
            job_store=job_store,
            timezone=timezone,
            sqlite_path=sqlite_path,
        )

        # Register scheduled jobs
        register_scheduled_jobs(self.scheduler, self.agents, scheduler_config)

        logger.debug("[WHISPER] Scheduler configured and ready")

    def _load_scheduler_config(self) -> dict[str, Any]:
        """Load scheduler configuration from YAML."""
        config_file = Path(__file__).parent / "config" / "scheduler.yaml"

        if not config_file.exists():
            logger.warning("[SWELL] scheduler.yaml not found, using defaults")
            return {}

        try:
            import yaml

            with config_file.open() as f:
                config = yaml.safe_load(f) or {}
            logger.debug("[WHISPER] Loaded scheduler config")
            return config
        except Exception as e:
            logger.warning(f"[SWELL] Failed to load scheduler config: {e}")
            return {}

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

        # Start scheduler for periodic jobs
        if self.scheduler:
            await start_scheduler(self.scheduler)

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start CLI
        logger.info("[BEACON] Klabautermann ready. Starting CLI...")
        cli = CLIDriver(self.agents["orchestrator"])

        try:
            # Run CLI in the main task
            await cli.start()
        except asyncio.CancelledError:
            logger.info("[CHART] CLI cancelled")

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info("[CHART] Shutdown signal received")
        self._shutdown_event.set()

        # Cancel all agent tasks
        for task in self.agent_tasks:
            task.cancel()

    async def shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("[CHART] Shutting down Klabautermann...")

        # Stop scheduler (waits for running jobs to complete)
        if self.scheduler:
            await shutdown_scheduler(self.scheduler)

        # Stop agents
        for name, agent in self.agents.items():
            await agent.stop()
            logger.debug(f"[WHISPER] Stopped {name}")

        # Wait for tasks to complete
        if self.agent_tasks:
            await asyncio.gather(*self.agent_tasks, return_exceptions=True)

        # Stop hot-reload
        if self.quartermaster:
            self.quartermaster.stop()

        # Close clients
        if self.graphiti:
            try:
                await self.graphiti.disconnect()
            except Exception as e:
                logger.warning(f"[SWELL] Graphiti disconnect error: {e}")

        if self.neo4j:
            try:
                await self.neo4j.disconnect()
            except Exception as e:
                logger.warning(f"[SWELL] Neo4j disconnect error: {e}")

        logger.info("[BEACON] Klabautermann shutdown complete")

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
  python main.py                    Start new CLI session
  python main.py --session abc123   Resume session abc123

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
