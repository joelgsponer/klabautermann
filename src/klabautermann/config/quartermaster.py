"""
The Quartermaster: Configuration hot-reload manager for Klabautermann.

Watches config files for changes and triggers reloads with agent notifications.
Provides debouncing, validation, and statistics tracking.

Reference: specs/architecture/AGENTS.md Section 4.2
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from klabautermann.config.manager import ConfigManager
from klabautermann.core.logger import logger


# ===========================================================================
# Types and Models
# ===========================================================================


@dataclass
class ReloadStats:
    """Statistics for config reloads."""

    last_reload: datetime | None = None
    reload_count: int = 0
    success_count: int = 0
    failure_count: int = 0


ReloadCallback = Callable[[str], Awaitable[None]]


# ===========================================================================
# File System Event Handler
# ===========================================================================


class ConfigChangeHandler(FileSystemEventHandler):
    """
    Watchdog handler for config file changes.

    Implements debouncing to avoid triggering multiple reloads
    during rapid file modifications (e.g., editor autosave).

    Note: This runs in watchdog's observer thread, so we use
    call_soon_threadsafe to schedule reloads on the event loop.
    """

    def __init__(self, quartermaster: Quartermaster, debounce_ms: float = 500) -> None:
        """
        Initialize the handler.

        Args:
            quartermaster: Quartermaster instance to notify.
            debounce_ms: Debounce delay in milliseconds.
        """
        self.quartermaster = quartermaster
        self._pending_reloads: dict[str, asyncio.TimerHandle] = {}
        self._debounce_ms = debounce_ms

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".yaml"):
            return

        agent_name = Path(event.src_path).stem
        self._schedule_reload(agent_name)

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle file creation."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".yaml"):
            return

        agent_name = Path(event.src_path).stem
        self._schedule_reload(agent_name)

    def _schedule_reload(self, agent_name: str) -> None:
        """
        Schedule a debounced reload.

        Cancels any pending reload for the same agent to avoid duplicates.
        Uses call_soon_threadsafe since watchdog calls this from a different thread.

        Args:
            agent_name: Agent whose config changed.
        """
        loop = self.quartermaster._loop
        if loop is None:
            logger.warning("[SWELL] No event loop available for Quartermaster reload scheduling")
            return

        # Schedule on the event loop (thread-safe)
        loop.call_soon_threadsafe(self._schedule_on_loop, agent_name)

    def _schedule_on_loop(self, agent_name: str) -> None:
        """
        Schedule reload on the event loop.

        Must be called from the event loop thread.

        Args:
            agent_name: Agent whose config changed.
        """
        loop = self.quartermaster._loop
        if loop is None:
            return

        # Cancel pending reload for this agent
        if agent_name in self._pending_reloads:
            self._pending_reloads[agent_name].cancel()

        # Schedule new reload
        handle = loop.call_later(
            self._debounce_ms / 1000,
            lambda: asyncio.create_task(self.quartermaster._do_reload(agent_name)),
        )
        self._pending_reloads[agent_name] = handle


# ===========================================================================
# Quartermaster
# ===========================================================================


class Quartermaster:
    """
    The Quartermaster: manages configuration hot-reload.

    Watches config files for changes and triggers reloads with validation.
    Notifies registered agents when their configuration changes.
    Tracks reload statistics and handles rollback on failure.

    Usage:
        config_manager = ConfigManager(Path("config/agents"))
        quartermaster = Quartermaster(config_manager)
        quartermaster.register_callback("orchestrator", my_callback)
        quartermaster.start()
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        config_dir: Path | None = None,
        debounce_ms: float = 500,
    ) -> None:
        """
        Initialize the Quartermaster.

        Args:
            config_manager: ConfigManager instance to reload.
            config_dir: Directory to watch (default: config_manager.config_dir).
            debounce_ms: Debounce delay in milliseconds (default: 500).
        """
        self.config_manager = config_manager
        self.config_dir = config_dir or config_manager.config_dir
        self.debounce_ms = debounce_ms

        self._observer: Observer | None = None
        self._callbacks: dict[str, list[ReloadCallback]] = {}
        self._stats: dict[str, ReloadStats] = {}
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def register_callback(
        self,
        agent_name: str,
        callback: ReloadCallback,
    ) -> None:
        """
        Register a callback for config changes.

        The callback will be invoked asynchronously when the agent's
        config file changes and reloads successfully.

        Args:
            agent_name: Agent to watch.
            callback: Async callback to invoke on change.
        """
        if agent_name not in self._callbacks:
            self._callbacks[agent_name] = []
        self._callbacks[agent_name].append(callback)

        logger.debug(
            f"[WHISPER] Registered reload callback for {agent_name}",
            extra={"agent_name": agent_name},
        )

    def start(self) -> None:
        """Start watching for config changes."""
        if self._running:
            logger.warning("[SWELL] Quartermaster already running")
            return

        if not self.config_dir.exists():
            logger.warning(
                f"[SWELL] Config directory {self.config_dir} does not exist. "
                "Quartermaster will not watch for changes."
            )
            return

        # Store the current event loop
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "[SWELL] No running event loop when starting Quartermaster. "
                "Hot-reload may not work correctly."
            )
            self._loop = None

        handler = ConfigChangeHandler(self, debounce_ms=self.debounce_ms)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.config_dir), recursive=False)
        self._observer.start()
        self._running = True

        logger.info(
            f"[CHART] Quartermaster watching {self.config_dir}",
            extra={"config_dir": str(self.config_dir)},
        )

    def stop(self) -> None:
        """Stop watching for config changes."""
        if not self._running:
            return

        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        self._running = False
        self._loop = None

        logger.info("[CHART] Quartermaster stopped")

    async def _do_reload(self, agent_name: str) -> None:
        """
        Execute reload for an agent.

        Validates the new config before applying. On validation failure,
        keeps the old config and logs the error.

        Args:
            agent_name: Agent to reload.
        """
        stats = self._stats.setdefault(agent_name, ReloadStats())
        stats.reload_count += 1

        try:
            # Attempt reload (ConfigManager validates internally)
            changed = self.config_manager.reload(agent_name)

            if changed:
                logger.info(
                    f"[BEACON] Config reloaded for {agent_name}",
                    extra={"agent_name": agent_name},
                )

                # Invoke callbacks
                callbacks = self._callbacks.get(agent_name, [])
                for callback in callbacks:
                    try:
                        await callback(agent_name)
                    except Exception as e:
                        logger.error(
                            f"[STORM] Callback failed for {agent_name}: {e}",
                            extra={"agent_name": agent_name},
                            exc_info=True,
                        )

                stats.success_count += 1
            else:
                logger.debug(
                    f"[WHISPER] No changes for {agent_name}",
                    extra={"agent_name": agent_name},
                )

        except Exception as e:
            stats.failure_count += 1
            logger.error(
                f"[STORM] Failed to reload {agent_name}: {e}",
                extra={"agent_name": agent_name},
                exc_info=True,
            )
            # Config manager automatically rolls back on validation failure

        finally:
            stats.last_reload = datetime.now()

    async def force_reload(self, agent_name: str) -> bool:
        """
        Force reload of an agent's config.

        Bypasses debouncing and triggers immediate reload.

        Args:
            agent_name: Agent to reload.

        Returns:
            True if reload succeeded, False otherwise.
        """
        try:
            await self._do_reload(agent_name)
            return True
        except Exception as e:
            logger.error(
                f"[STORM] Force reload failed for {agent_name}: {e}",
                extra={"agent_name": agent_name},
                exc_info=True,
            )
            return False

    async def reload_all(self) -> dict[str, bool]:
        """
        Force reload all configs.

        Useful for batch updates or manual refresh.

        Returns:
            Dict mapping agent name to success status.
        """
        results = {}
        for agent_name in self.config_manager.agent_names:
            results[agent_name] = await self.force_reload(agent_name)
        return results

    def get_stats(self, agent_name: str) -> ReloadStats | None:
        """
        Get reload statistics for an agent.

        Args:
            agent_name: Agent name.

        Returns:
            ReloadStats or None if no reloads have occurred.
        """
        return self._stats.get(agent_name)

    def get_all_stats(self) -> dict[str, ReloadStats]:
        """
        Get all reload statistics.

        Returns:
            Dict mapping agent name to ReloadStats.
        """
        return dict(self._stats)

    @property
    def is_running(self) -> bool:
        """Check if Quartermaster is running."""
        return self._running


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "ConfigChangeHandler",
    "Quartermaster",
    "ReloadCallback",
    "ReloadStats",
]
