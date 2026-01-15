"""
Unit tests for the Quartermaster config hot-reload system.

Tests cover file watching, debouncing, callback notifications,
statistics tracking, and error handling.
"""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from klabautermann.config.manager import ConfigManager
from klabautermann.config.quartermaster import (
    ConfigChangeHandler,
    Quartermaster,
    ReloadStats,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory with sample YAML files."""
    config_dir = tmp_path / "agents"
    config_dir.mkdir()

    # Create orchestrator.yaml
    orchestrator_config = {
        "model": {"primary": "claude-sonnet-4-20250514", "temperature": 0.7},
        "personality": {"name": "klabautermann", "wit_level": 0.3},
    }
    (config_dir / "orchestrator.yaml").write_text(yaml.dump(orchestrator_config))

    # Create ingestor.yaml
    ingestor_config = {
        "model": {"primary": "claude-haiku-4-20250514"},
        "extraction": {"confidence_threshold": 0.8},
    }
    (config_dir / "ingestor.yaml").write_text(yaml.dump(ingestor_config))

    return config_dir


@pytest.fixture
def config_manager(temp_config_dir):
    """Create ConfigManager with temp config directory."""
    return ConfigManager(temp_config_dir)


@pytest.fixture
def quartermaster(config_manager):
    """Create Quartermaster instance."""
    return Quartermaster(config_manager)


# ===========================================================================
# Initialization Tests
# ===========================================================================


def test_quartermaster_init(config_manager, temp_config_dir):
    """Test Quartermaster initialization."""
    qm = Quartermaster(config_manager)
    assert qm.config_manager is config_manager
    assert qm.config_dir == temp_config_dir
    assert qm.debounce_ms == 500  # default
    assert not qm.is_running
    assert qm._observer is None


def test_quartermaster_init_custom_debounce(config_manager):
    """Test Quartermaster with custom debounce delay."""
    qm = Quartermaster(config_manager, debounce_ms=1000)
    assert qm.debounce_ms == 1000


def test_quartermaster_init_custom_config_dir(config_manager, tmp_path):
    """Test Quartermaster with custom config directory."""
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    qm = Quartermaster(config_manager, config_dir=custom_dir)
    assert qm.config_dir == custom_dir


# ===========================================================================
# Start/Stop Tests
# ===========================================================================


def test_quartermaster_start(quartermaster, temp_config_dir):
    """Test starting the Quartermaster."""
    quartermaster.start()
    assert quartermaster.is_running
    assert quartermaster._observer is not None
    quartermaster.stop()


def test_quartermaster_start_already_running(quartermaster):
    """Test starting when already running."""
    quartermaster.start()
    assert quartermaster.is_running

    # Should handle gracefully
    quartermaster.start()
    assert quartermaster.is_running

    quartermaster.stop()


def test_quartermaster_start_missing_directory(config_manager, tmp_path):
    """Test starting with non-existent config directory."""
    missing_dir = tmp_path / "missing"
    qm = Quartermaster(config_manager, config_dir=missing_dir)

    # Should handle gracefully and not start
    qm.start()
    assert not qm.is_running


def test_quartermaster_stop(quartermaster):
    """Test stopping the Quartermaster."""
    quartermaster.start()
    assert quartermaster.is_running

    quartermaster.stop()
    assert not quartermaster.is_running
    assert quartermaster._observer is None


def test_quartermaster_stop_not_running(quartermaster):
    """Test stopping when not running."""
    assert not quartermaster.is_running
    quartermaster.stop()  # Should handle gracefully


# ===========================================================================
# Callback Registration Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_register_callback(quartermaster):
    """Test callback registration."""
    callback = AsyncMock()
    quartermaster.register_callback("orchestrator", callback)

    assert "orchestrator" in quartermaster._callbacks
    assert callback in quartermaster._callbacks["orchestrator"]


@pytest.mark.asyncio
async def test_register_multiple_callbacks(quartermaster):
    """Test registering multiple callbacks for same agent."""
    callback1 = AsyncMock()
    callback2 = AsyncMock()

    quartermaster.register_callback("orchestrator", callback1)
    quartermaster.register_callback("orchestrator", callback2)

    callbacks = quartermaster._callbacks["orchestrator"]
    assert len(callbacks) == 2
    assert callback1 in callbacks
    assert callback2 in callbacks


# ===========================================================================
# Reload Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_force_reload_success(quartermaster, temp_config_dir):
    """Test force reload with successful config change."""
    # Modify config file
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"primary": "claude-opus-4-5-20251101", "temperature": 0.9}}
    config_file.write_text(yaml.dump(new_config))

    # Force reload
    success = await quartermaster.force_reload("orchestrator")
    assert success

    # Verify config changed
    new_cfg = quartermaster.config_manager.get("orchestrator")
    assert new_cfg.model.primary == "claude-opus-4-5-20251101"
    assert new_cfg.model.temperature == 0.9


@pytest.mark.asyncio
async def test_force_reload_with_callback(quartermaster, temp_config_dir):
    """Test force reload triggers callback."""
    callback = AsyncMock()
    quartermaster.register_callback("orchestrator", callback)

    # Modify config
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.8}}
    config_file.write_text(yaml.dump(new_config))

    # Force reload
    await quartermaster.force_reload("orchestrator")

    # Verify callback was called
    callback.assert_called_once_with("orchestrator")


@pytest.mark.asyncio
async def test_force_reload_multiple_callbacks(quartermaster, temp_config_dir):
    """Test force reload triggers all registered callbacks."""
    callback1 = AsyncMock()
    callback2 = AsyncMock()
    quartermaster.register_callback("orchestrator", callback1)
    quartermaster.register_callback("orchestrator", callback2)

    # Modify config
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.8}}
    config_file.write_text(yaml.dump(new_config))

    # Force reload
    await quartermaster.force_reload("orchestrator")

    # Both callbacks should be invoked
    callback1.assert_called_once_with("orchestrator")
    callback2.assert_called_once_with("orchestrator")


@pytest.mark.asyncio
async def test_force_reload_callback_exception(quartermaster, temp_config_dir, caplog):
    """Test force reload handles callback exceptions gracefully."""
    # Create callback that raises exception
    callback = AsyncMock(side_effect=ValueError("Callback error"))
    quartermaster.register_callback("orchestrator", callback)

    # Modify config
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.8}}
    config_file.write_text(yaml.dump(new_config))

    # Force reload should succeed despite callback failure
    success = await quartermaster.force_reload("orchestrator")
    assert success

    # Verify error was logged
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_force_reload_no_change(quartermaster):
    """Test force reload when config hasn't changed."""
    # Reload without changing file
    await quartermaster.force_reload("orchestrator")

    # Stats should show reload but no success (no change)
    stats = quartermaster.get_stats("orchestrator")
    assert stats is not None
    assert stats.reload_count > 0


@pytest.mark.asyncio
async def test_force_reload_invalid_yaml(quartermaster, temp_config_dir):
    """Test force reload with invalid YAML."""
    # Write invalid YAML
    config_file = temp_config_dir / "orchestrator.yaml"
    config_file.write_text("invalid: yaml: content: [")

    # Reload should fail gracefully
    await quartermaster.force_reload("orchestrator")

    # Stats should show failure
    stats = quartermaster.get_stats("orchestrator")
    assert stats is not None
    assert stats.failure_count > 0


@pytest.mark.asyncio
async def test_reload_all(quartermaster, temp_config_dir):
    """Test reloading all configs."""
    # Modify both config files
    (temp_config_dir / "orchestrator.yaml").write_text(
        yaml.dump({"model": {"temperature": 0.8}})
    )
    (temp_config_dir / "ingestor.yaml").write_text(
        yaml.dump({"model": {"temperature": 0.9}})
    )

    # Reload all
    results = await quartermaster.reload_all()

    assert "orchestrator" in results
    assert "ingestor" in results


# ===========================================================================
# Statistics Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_reload_stats_tracking(quartermaster, temp_config_dir):
    """Test statistics tracking for reloads."""
    # Perform multiple reloads
    config_file = temp_config_dir / "orchestrator.yaml"

    for i in range(3):
        new_config = {"model": {"temperature": 0.5 + i * 0.1}}
        config_file.write_text(yaml.dump(new_config))
        await quartermaster.force_reload("orchestrator")

    stats = quartermaster.get_stats("orchestrator")
    assert stats is not None
    assert stats.reload_count == 3
    assert stats.success_count == 3
    assert stats.failure_count == 0
    assert stats.last_reload is not None


@pytest.mark.asyncio
async def test_reload_stats_failure_tracking(quartermaster, temp_config_dir):
    """Test statistics tracking for failed reloads."""
    config_file = temp_config_dir / "orchestrator.yaml"

    # Write invalid YAML
    config_file.write_text("invalid: yaml: [")
    await quartermaster.force_reload("orchestrator")

    stats = quartermaster.get_stats("orchestrator")
    assert stats is not None
    assert stats.reload_count == 1
    assert stats.failure_count == 1
    assert stats.success_count == 0


def test_get_stats_nonexistent_agent(quartermaster):
    """Test getting stats for agent with no reloads."""
    stats = quartermaster.get_stats("nonexistent")
    assert stats is None


@pytest.mark.asyncio
async def test_get_all_stats(quartermaster, temp_config_dir):
    """Test getting all statistics."""
    # Reload multiple agents
    (temp_config_dir / "orchestrator.yaml").write_text(
        yaml.dump({"model": {"temperature": 0.8}})
    )
    (temp_config_dir / "ingestor.yaml").write_text(
        yaml.dump({"model": {"temperature": 0.9}})
    )

    await quartermaster.force_reload("orchestrator")
    await quartermaster.force_reload("ingestor")

    all_stats = quartermaster.get_all_stats()
    assert "orchestrator" in all_stats
    assert "ingestor" in all_stats
    assert isinstance(all_stats["orchestrator"], ReloadStats)
    assert isinstance(all_stats["ingestor"], ReloadStats)


# ===========================================================================
# File System Event Handler Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_config_change_handler_on_modified(quartermaster, temp_config_dir):
    """Test file modification event handling."""
    callback = AsyncMock()
    quartermaster.register_callback("orchestrator", callback)

    # Set the event loop (normally done by start())
    quartermaster._loop = asyncio.get_running_loop()

    handler = ConfigChangeHandler(quartermaster, debounce_ms=100)

    # Simulate file modification event
    class FakeEvent:
        is_directory = False
        src_path = str(temp_config_dir / "orchestrator.yaml")

    # Modify file
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.99}}
    config_file.write_text(yaml.dump(new_config))

    handler.on_modified(FakeEvent())

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Callback should have been invoked
    callback.assert_called_once_with("orchestrator")


@pytest.mark.asyncio
async def test_config_change_handler_on_created(quartermaster, temp_config_dir):
    """Test file creation event handling."""
    callback = AsyncMock()
    quartermaster.register_callback("newagent", callback)

    # Set the event loop (normally done by start())
    quartermaster._loop = asyncio.get_running_loop()

    handler = ConfigChangeHandler(quartermaster, debounce_ms=100)

    # Create new config file
    new_config_file = temp_config_dir / "newagent.yaml"
    new_config = {"model": {"temperature": 0.7}}
    new_config_file.write_text(yaml.dump(new_config))

    # Simulate file creation event
    class FakeEvent:
        is_directory = False
        src_path = str(new_config_file)

    handler.on_created(FakeEvent())

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Callback should have been invoked
    callback.assert_called_once_with("newagent")


def test_config_change_handler_ignores_directories(quartermaster):
    """Test handler ignores directory events."""
    handler = ConfigChangeHandler(quartermaster)

    class FakeEvent:
        is_directory = True
        src_path = "/some/dir"

    # Should not raise or schedule reload
    handler.on_modified(FakeEvent())
    assert len(handler._pending_reloads) == 0


def test_config_change_handler_ignores_non_yaml(quartermaster, temp_config_dir):
    """Test handler ignores non-YAML files."""
    handler = ConfigChangeHandler(quartermaster)

    class FakeEvent:
        is_directory = False
        src_path = str(temp_config_dir / "readme.txt")

    # Should not schedule reload
    handler.on_modified(FakeEvent())
    assert len(handler._pending_reloads) == 0


@pytest.mark.asyncio
async def test_config_change_handler_debouncing(quartermaster, temp_config_dir):
    """Test debouncing prevents multiple rapid reloads."""
    callback = AsyncMock()
    quartermaster.register_callback("orchestrator", callback)

    # Set the event loop (normally done by start())
    quartermaster._loop = asyncio.get_running_loop()

    handler = ConfigChangeHandler(quartermaster, debounce_ms=200)

    class FakeEvent:
        is_directory = False
        src_path = str(temp_config_dir / "orchestrator.yaml")

    # Modify config file
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.95}}
    config_file.write_text(yaml.dump(new_config))

    # Trigger multiple rapid events
    handler.on_modified(FakeEvent())
    await asyncio.sleep(0.05)
    handler.on_modified(FakeEvent())
    await asyncio.sleep(0.05)
    handler.on_modified(FakeEvent())

    # Wait for debounce + processing
    await asyncio.sleep(0.4)

    # Callback should be called only once due to debouncing
    callback.assert_called_once_with("orchestrator")


# ===========================================================================
# Integration Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_end_to_end_hot_reload(quartermaster, temp_config_dir):
    """Test end-to-end hot reload workflow."""
    # Register callback
    reloaded = []

    async def track_reload(agent_name: str) -> None:
        reloaded.append(agent_name)

    quartermaster.register_callback("orchestrator", track_reload)

    # Start watching
    quartermaster.start()

    # Give observer time to start
    await asyncio.sleep(0.2)

    # Modify config file
    config_file = temp_config_dir / "orchestrator.yaml"
    new_config = {"model": {"temperature": 0.88}}
    config_file.write_text(yaml.dump(new_config))

    # Wait for file system event + debounce + processing
    # File system events can be slow, especially in containers
    await asyncio.sleep(2.0)

    # Stop watching
    quartermaster.stop()

    # Verify reload occurred
    assert "orchestrator" in reloaded

    # Verify config was updated
    updated_config = quartermaster.config_manager.get("orchestrator")
    assert updated_config.model.temperature == 0.88


@pytest.mark.asyncio
async def test_reload_stats_structure(quartermaster):
    """Test ReloadStats dataclass structure."""
    stats = ReloadStats()
    assert stats.last_reload is None
    assert stats.reload_count == 0
    assert stats.success_count == 0
    assert stats.failure_count == 0

    # Update stats
    from datetime import datetime

    stats.last_reload = datetime.now()
    stats.reload_count = 5
    stats.success_count = 4
    stats.failure_count = 1

    assert stats.last_reload is not None
    assert stats.reload_count == 5
    assert stats.success_count == 4
    assert stats.failure_count == 1
