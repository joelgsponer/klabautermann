# Update Main.py for Multi-Agent Startup

## Metadata
- **ID**: T034
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 8
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [ ] T020 - Orchestrator refactor
- [ ] T023 - Ingestor agent
- [ ] T024 - Researcher agent
- [ ] T029 - Executor agent
- [ ] T033 - Config hot-reload

## Context
Sprint 1's `main.py` only starts the simple Orchestrator and CLI. Sprint 2 requires initializing all agents (Orchestrator, Ingestor, Researcher, Executor), wiring up the agent registry for message routing, and setting up the configuration system with hot-reload.

## Requirements
- [ ] Update `main.py` for multi-agent architecture:

### Initialization
- [ ] Initialize shared resources:
  - ConfigManager
  - Neo4j client
  - Graphiti client
  - MCP client
  - LLM client (Anthropic)
- [ ] Create all agent instances
- [ ] Wire up agent registry for message routing
- [ ] Set up Quartermaster for hot-reload

### Agent Lifecycle
- [ ] Start all agent processing loops
- [ ] Graceful shutdown on SIGINT/SIGTERM
- [ ] Clean up resources on exit
- [ ] Health check endpoints (optional)

### Error Handling
- [ ] Handle startup failures gracefully
- [ ] Log initialization progress
- [ ] Validate all dependencies before starting

### Configuration
- [ ] Load from environment (.env)
- [ ] Load agent configs from YAML
- [ ] Validate required credentials

## Acceptance Criteria
- [ ] `main.py` starts all four agents
- [ ] Agent registry correctly wired
- [ ] Ctrl+C triggers graceful shutdown
- [ ] All agents stop cleanly
- [ ] Startup logs show initialization progress

## Implementation Notes

```python
#!/usr/bin/env python3
"""
Klabautermann Main Entry Point

Initializes all agents and starts the multi-agent system.
"""

import asyncio
import os
import signal
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
import anthropic

from klabautermann.core.logger import logger
from klabautermann.core.exceptions import StartupError
from klabautermann.config.manager import ConfigManager
from klabautermann.config.quartermaster import Quartermaster
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.mcp.client import MCPClient
from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge
from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.agents.ingestor import Ingestor
from klabautermann.agents.researcher import Researcher
from klabautermann.agents.executor import Executor
from klabautermann.channels.cli_driver import CLIDriver


class Klabautermann:
    """
    Main application class.

    Manages lifecycle of all agents and shared resources.
    """

    def __init__(self):
        self.config_manager: ConfigManager = None
        self.quartermaster: Quartermaster = None
        self.neo4j: Neo4jClient = None
        self.graphiti: GraphitiClient = None
        self.mcp_client: MCPClient = None
        self.google_bridge: GoogleWorkspaceBridge = None
        self.llm_client: anthropic.Anthropic = None

        self.agents: Dict[str, BaseAgent] = {}
        self.agent_tasks: list[asyncio.Task] = []

        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("[CHART] Initializing Klabautermann...")

        # Load environment
        load_dotenv()
        self._validate_environment()

        # Initialize configuration
        logger.info("[CHART] Loading configuration...")
        self.config_manager = ConfigManager(Path("config/agents"))
        self.quartermaster = Quartermaster(self.config_manager)

        # Initialize clients
        logger.info("[CHART] Connecting to Neo4j...")
        self.neo4j = Neo4jClient(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", ""),
        )
        await self.neo4j.verify_connection()

        logger.info("[CHART] Initializing Graphiti...")
        self.graphiti = GraphitiClient(
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        )
        await self.graphiti.initialize()

        logger.info("[CHART] Initializing MCP client...")
        self.mcp_client = MCPClient()
        self.google_bridge = GoogleWorkspaceBridge(self.mcp_client)

        logger.info("[CHART] Initializing LLM client...")
        self.llm_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

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

        # Orchestrator (Sonnet)
        self.agents["orchestrator"] = Orchestrator(
            name="orchestrator",
            config=self.config_manager.get("orchestrator"),
            graphiti_client=self.graphiti,
            neo4j_client=self.neo4j,
            llm_client=self.llm_client,
        )

        # Ingestor (Haiku)
        self.agents["ingestor"] = Ingestor(
            name="ingestor",
            config=self.config_manager.get("ingestor"),
            graphiti_client=self.graphiti,
            llm_client=self.llm_client,
        )

        # Researcher (Haiku)
        self.agents["researcher"] = Researcher(
            name="researcher",
            config=self.config_manager.get("researcher"),
            graphiti_client=self.graphiti,
            neo4j_client=self.neo4j,
            llm_client=self.llm_client,
        )

        # Executor (Sonnet)
        self.agents["executor"] = Executor(
            name="executor",
            config=self.config_manager.get("executor"),
            google_bridge=self.google_bridge,
            llm_client=self.llm_client,
        )

        logger.info(f"[CHART] Created {len(self.agents)} agents")

    def _wire_agent_registry(self) -> None:
        """Wire up agent registry for message routing."""
        for agent in self.agents.values():
            agent.agent_registry = self.agents

        # Register config change callbacks
        for name in self.agents.keys():
            self.quartermaster.register_callback(
                name,
                lambda n: self._on_agent_config_change(n)
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
        cli = CLIDriver(self.agents["orchestrator"])

        try:
            await cli.run()
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
        if self.google_bridge:
            await self.google_bridge.stop()

        if self.mcp_client:
            await self.mcp_client.stop_all()

        if self.neo4j:
            await self.neo4j.close()

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


async def main():
    """Entry point."""
    app = Klabautermann()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
```

This replaces the Sprint 1 `main.py` with a full multi-agent setup.
