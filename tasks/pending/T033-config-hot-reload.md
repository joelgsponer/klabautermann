# Implement Config Hot-Reload (Quartermaster)

## Metadata
- **ID**: T033
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 4.2
- Related: [AGENTS_EXTENDED.md](../../specs/architecture/AGENTS_EXTENDED.md)

## Dependencies
- [ ] T032 - Agent configuration system

## Context
The Quartermaster is a utility agent that watches for configuration file changes and triggers hot-reloads. This enables tuning agent behavior (prompts, models, parameters) without restarting the system. It uses file system watching to detect changes.

## Requirements
- [ ] Create `src/klabautermann/config/quartermaster.py`:

### File Watching
- [ ] Watch `config/agents/` directory for changes
- [ ] Detect file modifications (checksum comparison)
- [ ] Debounce rapid changes (wait 500ms)
- [ ] Handle file creation and deletion

### Reload Mechanism
- [ ] Trigger ConfigManager reload on change
- [ ] Notify affected agents of config update
- [ ] Validate new config before applying
- [ ] Rollback on validation failure

### Agent Notification
- [ ] Callback system for config change events
- [ ] Per-agent reload callbacks
- [ ] Logging of reload events

### Error Handling
- [ ] Invalid YAML handling
- [ ] Schema validation errors
- [ ] Filesystem permission errors

### Status Reporting
- [ ] Current config versions
- [ ] Last reload timestamps
- [ ] Reload success/failure counts

## Acceptance Criteria
- [ ] Modifying orchestrator.yaml triggers reload
- [ ] Agents receive new config on next request
- [ ] Invalid YAML doesn't crash the system
- [ ] Reload events logged
- [ ] No reload if content unchanged

## Implementation Notes

```python
import asyncio
from pathlib import Path
from typing import Dict, Callable, Awaitable, Optional
from dataclasses import dataclass, field
from datetime import datetime
import hashlib

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from klabautermann.config.manager import ConfigManager
from klabautermann.core.logger import logger


@dataclass
class ReloadStats:
    """Statistics for config reloads."""
    last_reload: Optional[datetime] = None
    reload_count: int = 0
    success_count: int = 0
    failure_count: int = 0


ReloadCallback = Callable[[str], Awaitable[None]]


class ConfigChangeHandler(FileSystemEventHandler):
    """
    Watchdog handler for config file changes.
    """

    def __init__(self, quartermaster: "Quartermaster"):
        self.quartermaster = quartermaster
        self._pending_reloads: Dict[str, asyncio.TimerHandle] = {}
        self._debounce_ms = 500

    def on_modified(self, event):
        """Handle file modification."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".yaml"):
            return

        agent_name = Path(event.src_path).stem
        self._schedule_reload(agent_name)

    def on_created(self, event):
        """Handle file creation."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".yaml"):
            return

        agent_name = Path(event.src_path).stem
        self._schedule_reload(agent_name)

    def _schedule_reload(self, agent_name: str) -> None:
        """Schedule a debounced reload."""
        # Cancel pending reload for this agent
        if agent_name in self._pending_reloads:
            self._pending_reloads[agent_name].cancel()

        # Schedule new reload
        loop = asyncio.get_event_loop()
        handle = loop.call_later(
            self._debounce_ms / 1000,
            lambda: asyncio.create_task(self.quartermaster._do_reload(agent_name))
        )
        self._pending_reloads[agent_name] = handle


class Quartermaster:
    """
    The Quartermaster: manages configuration hot-reload.

    Watches config files for changes and triggers reloads.
    Notifies agents when their configuration changes.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        config_dir: Optional[Path] = None,
    ):
        """
        Initialize the Quartermaster.

        Args:
            config_manager: ConfigManager instance to reload.
            config_dir: Directory to watch (default: config_manager.config_dir).
        """
        self.config_manager = config_manager
        self.config_dir = config_dir or config_manager.config_dir

        self._observer: Optional[Observer] = None
        self._callbacks: Dict[str, list[ReloadCallback]] = {}
        self._stats: Dict[str, ReloadStats] = {}
        self._running = False

    def register_callback(
        self,
        agent_name: str,
        callback: ReloadCallback,
    ) -> None:
        """
        Register a callback for config changes.

        Args:
            agent_name: Agent to watch.
            callback: Async callback to invoke on change.
        """
        if agent_name not in self._callbacks:
            self._callbacks[agent_name] = []
        self._callbacks[agent_name].append(callback)

    def start(self) -> None:
        """Start watching for config changes."""
        if self._running:
            return

        handler = ConfigChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.config_dir), recursive=False)
        self._observer.start()
        self._running = True

        logger.info(f"[CHART] Quartermaster watching {self.config_dir}")

    def stop(self) -> None:
        """Stop watching for config changes."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        self._running = False

        logger.info("[CHART] Quartermaster stopped")

    async def _do_reload(self, agent_name: str) -> None:
        """Execute reload for an agent."""
        stats = self._stats.setdefault(agent_name, ReloadStats())
        stats.reload_count += 1

        try:
            # Attempt reload
            changed = self.config_manager.reload(agent_name)

            if changed:
                logger.info(f"[BEACON] Config reloaded for {agent_name}")

                # Invoke callbacks
                callbacks = self._callbacks.get(agent_name, [])
                for callback in callbacks:
                    try:
                        await callback(agent_name)
                    except Exception as e:
                        logger.error(
                            f"[STORM] Callback failed for {agent_name}: {e}"
                        )

                stats.success_count += 1
            else:
                logger.debug(f"[WHISPER] No changes for {agent_name}")

        except Exception as e:
            stats.failure_count += 1
            logger.error(f"[STORM] Failed to reload {agent_name}: {e}")

        stats.last_reload = datetime.now()

    async def force_reload(self, agent_name: str) -> bool:
        """
        Force reload of an agent's config.

        Args:
            agent_name: Agent to reload.

        Returns:
            True if reload succeeded.
        """
        try:
            self.config_manager.reload(agent_name)
            await self._do_reload(agent_name)
            return True
        except Exception as e:
            logger.error(f"[STORM] Force reload failed: {e}")
            return False

    async def reload_all(self) -> Dict[str, bool]:
        """
        Force reload all configs.

        Returns:
            Dict mapping agent name to success status.
        """
        results = {}
        for agent_name in self.config_manager.agent_names:
            results[agent_name] = await self.force_reload(agent_name)
        return results

    def get_stats(self, agent_name: str) -> Optional[ReloadStats]:
        """Get reload statistics for an agent."""
        return self._stats.get(agent_name)

    def get_all_stats(self) -> Dict[str, ReloadStats]:
        """Get all reload statistics."""
        return dict(self._stats)


# Integration with agents:

class BaseAgentWithConfig(BaseAgent):
    """
    Base agent with config hot-reload support.
    """

    def __init__(
        self,
        name: str,
        config_manager: ConfigManager,
        quartermaster: Optional[Quartermaster] = None,
    ):
        self.config_manager = config_manager
        self._config = config_manager.get(name)

        # Register for hot-reload
        if quartermaster:
            quartermaster.register_callback(name, self._on_config_change)

    async def _on_config_change(self, agent_name: str) -> None:
        """Handle config change notification."""
        new_config = self.config_manager.get(agent_name)
        if new_config:
            self._config = new_config
            logger.info(f"[BEACON] {self.name} config updated")
            await self._apply_config()

    async def _apply_config(self) -> None:
        """Apply new configuration. Override in subclasses."""
        pass

    @property
    def config(self):
        """Current configuration."""
        return self._config
```

Add to requirements.txt:
```
watchdog>=3.0.0
```

Usage in main.py:
```python
# Initialize config
config_manager = ConfigManager(Path("config/agents"))
quartermaster = Quartermaster(config_manager)

# Create agents with config support
orchestrator = Orchestrator(
    config_manager=config_manager,
    quartermaster=quartermaster,
)

# Start watching
quartermaster.start()
```
