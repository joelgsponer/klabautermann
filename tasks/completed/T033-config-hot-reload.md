# Implement Config Hot-Reload (Quartermaster)

## Metadata
- **ID**: T033
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: completed
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 4.2
- Related: [AGENTS_EXTENDED.md](../../specs/architecture/AGENTS_EXTENDED.md)

## Dependencies
- [x] T032 - Agent configuration system

## Context
The Quartermaster is a utility agent that watches for configuration file changes and triggers hot-reloads. This enables tuning agent behavior (prompts, models, parameters) without restarting the system. It uses file system watching to detect changes.

## Requirements
- [x] Create `src/klabautermann/config/quartermaster.py`:

### File Watching
- [x] Watch `config/agents/` directory for changes
- [x] Detect file modifications (checksum comparison)
- [x] Debounce rapid changes (wait 500ms)
- [x] Handle file creation and deletion

### Reload Mechanism
- [x] Trigger ConfigManager reload on change
- [x] Notify affected agents of config update
- [x] Validate new config before applying
- [x] Rollback on validation failure

### Agent Notification
- [x] Callback system for config change events
- [x] Per-agent reload callbacks
- [x] Logging of reload events

### Error Handling
- [x] Invalid YAML handling
- [x] Schema validation errors
- [x] Filesystem permission errors

### Status Reporting
- [x] Current config versions
- [x] Last reload timestamps
- [x] Reload success/failure counts

## Acceptance Criteria
- [x] Modifying orchestrator.yaml triggers reload
- [x] Agents receive new config on next request
- [x] Invalid YAML doesn't crash the system
- [x] Reload events logged
- [x] No reload if content unchanged

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

## Development Notes

### Implementation

**Files Created:**
- `src/klabautermann/config/quartermaster.py` - Main Quartermaster implementation with ConfigChangeHandler and ReloadStats
- `tests/unit/test_quartermaster.py` - Comprehensive test suite with 28 tests

**Files Modified:**
- `src/klabautermann/config/__init__.py` - Added exports for Quartermaster, ConfigChangeHandler, ReloadCallback, ReloadStats
- `requirements.txt` - Added watchdog>=3.0.0 dependency

### Decisions Made

1. **Thread-safe event handling**: Watchdog runs in a separate thread, so we use `call_soon_threadsafe` to schedule reloads on the main event loop. This ensures proper async coordination.

2. **Event loop storage**: The Quartermaster stores a reference to the event loop when `start()` is called. This allows the ConfigChangeHandler (which runs in watchdog's thread) to schedule tasks on the correct loop.

3. **Debouncing strategy**: Implemented debouncing using `call_later` with cancellation of pending reloads. This prevents multiple rapid file changes (e.g., from editor autosave) from triggering multiple reloads.

4. **Graceful error handling**: Callbacks that raise exceptions don't prevent other callbacks from running or crash the reload process. All errors are logged with appropriate nautical log levels.

5. **Statistics tracking**: ReloadStats dataclass tracks reload_count, success_count, failure_count, and last_reload timestamp per agent for monitoring and debugging.

### Patterns Established

1. **File system watcher integration**: Pattern for integrating watchdog with asyncio event loops using thread-safe calls.

2. **Callback notification system**: Type-safe callback system using `ReloadCallback = Callable[[str], Awaitable[None]]` for agent notifications.

3. **Debounce pattern**: Cancellable timer handles for debouncing rapid events.

4. **Statistics tracking**: Dataclass-based stats with success/failure counts and timestamps.

### Testing

Created comprehensive test suite with 28 tests covering:
- Initialization and configuration
- Start/stop lifecycle management
- Callback registration (single and multiple)
- Force reload with success/failure scenarios
- Invalid YAML handling
- Statistics tracking
- File system event handling (on_modified, on_created)
- Event filtering (ignoring directories and non-YAML files)
- Debouncing behavior
- End-to-end hot-reload workflow

All tests pass successfully.

### Issues Encountered

**Challenge**: Initial implementation had event loop issues where watchdog's observer thread couldn't properly schedule async tasks.

**Solution**: Implemented thread-safe scheduling using `call_soon_threadsafe` to bridge between watchdog's observer thread and the main asyncio event loop. The Quartermaster stores the event loop reference when `start()` is called, and the handler uses this to schedule reloads safely.

### Integration Pattern

Agents can integrate with hot-reload by:
1. Storing a reference to ConfigManager
2. Registering a callback with Quartermaster during initialization
3. Implementing callback handler to reload config and apply changes

Example:
```python
async def _on_config_change(self, agent_name: str) -> None:
    new_config = self.config_manager.get(agent_name)
    if new_config:
        self._config = new_config
        await self._apply_config()  # Apply new settings
```

### Next Steps

This pattern enables zero-downtime config updates for all agents. Future agents (Ingestor, Researcher, Executor) should follow this pattern for hot-reload support.
