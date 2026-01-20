"""
Unit tests for graceful shutdown management.

Tests the ShutdownManager's ability to coordinate orderly shutdown
of channels, agents, and clients.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

import pytest

from klabautermann.core.shutdown import (
    ShutdownManager,
    ShutdownPhase,
    ShutdownResult,
    ShutdownStatus,
    get_shutdown_manager,
    reset_shutdown_manager,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def shutdown_manager() -> ShutdownManager:
    """Create a fresh shutdown manager."""
    return ShutdownManager(timeout_seconds=5.0, drain_timeout_seconds=2.0)


@pytest.fixture
def mock_channel() -> MagicMock:
    """Create a mock channel."""
    channel = MagicMock()
    channel.stop = AsyncMock()
    return channel


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock agent with inbox."""
    agent = MagicMock()
    agent.stop = AsyncMock()
    agent.inbox = asyncio.Queue()
    return agent


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock client disconnect function."""
    return AsyncMock()


@pytest.fixture(autouse=True)
def reset_global_manager() -> None:
    """Reset global shutdown manager before each test."""
    reset_shutdown_manager()


# =============================================================================
# Test ShutdownStatus
# =============================================================================


class TestShutdownStatus:
    """Tests for ShutdownStatus dataclass."""

    def test_duration_ms_calculation(self) -> None:
        """Test duration calculation in milliseconds."""
        started = datetime(2024, 1, 1, 12, 0, 0, 0)
        completed = datetime(2024, 1, 1, 12, 0, 0, 500000)  # 500ms later

        status = ShutdownStatus(
            component_name="test",
            component_type="agent",
            started_at=started,
            completed_at=completed,
        )

        assert status.duration_ms == 500.0

    def test_duration_ms_none_when_incomplete(self) -> None:
        """Test duration is None when not completed."""
        status = ShutdownStatus(
            component_name="test",
            component_type="agent",
            started_at=datetime.now(),
        )

        assert status.duration_ms is None


# =============================================================================
# Test ShutdownResult
# =============================================================================


class TestShutdownResult:
    """Tests for ShutdownResult dataclass."""

    def test_summary_success(self) -> None:
        """Test summary for successful shutdown."""
        result = ShutdownResult(
            success=True,
            phase=ShutdownPhase.COMPLETE,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            completed_at=datetime(2024, 1, 1, 12, 0, 1),
            component_statuses=[
                ShutdownStatus("channel", "channel", success=True),
                ShutdownStatus("agent", "agent", success=True),
            ],
        )

        summary = result.summary()
        assert "SUCCESS" in summary
        assert "2 components" in summary

    def test_summary_failure(self) -> None:
        """Test summary for failed shutdown."""
        result = ShutdownResult(
            success=False,
            phase=ShutdownPhase.FAILED,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            completed_at=datetime(2024, 1, 1, 12, 0, 1),
            component_statuses=[
                ShutdownStatus("channel", "channel", success=True),
                ShutdownStatus("agent", "agent", success=False),
            ],
        )

        summary = result.summary()
        assert "FAILED" in summary
        assert "agent" in summary


# =============================================================================
# Test ShutdownManager - Registration
# =============================================================================


class TestShutdownRegistration:
    """Tests for component registration."""

    def test_register_channel(
        self, shutdown_manager: ShutdownManager, mock_channel: MagicMock
    ) -> None:
        """Test registering a channel."""
        shutdown_manager.register_channel("cli", mock_channel)

        assert len(shutdown_manager._channels) == 1
        assert shutdown_manager._channels[0][0] == "cli"

    def test_register_agent(self, shutdown_manager: ShutdownManager, mock_agent: MagicMock) -> None:
        """Test registering an agent."""
        shutdown_manager.register_agent("orchestrator", mock_agent)

        assert len(shutdown_manager._agents) == 1
        assert shutdown_manager._agents[0][0] == "orchestrator"

    def test_register_client(
        self, shutdown_manager: ShutdownManager, mock_client: AsyncMock
    ) -> None:
        """Test registering a client."""
        shutdown_manager.register_client("neo4j", mock_client)

        assert len(shutdown_manager._clients) == 1
        assert shutdown_manager._clients[0][0] == "neo4j"

    def test_register_multiple_components(
        self,
        shutdown_manager: ShutdownManager,
        mock_channel: MagicMock,
        mock_agent: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """Test registering multiple components."""
        shutdown_manager.register_channel("cli", mock_channel)
        shutdown_manager.register_agent("orchestrator", mock_agent)
        shutdown_manager.register_agent("ingestor", mock_agent)
        shutdown_manager.register_client("neo4j", mock_client)

        assert len(shutdown_manager._channels) == 1
        assert len(shutdown_manager._agents) == 2
        assert len(shutdown_manager._clients) == 1


# =============================================================================
# Test ShutdownManager - Shutdown Execution
# =============================================================================


class TestShutdownExecution:
    """Tests for shutdown execution."""

    @pytest.mark.asyncio
    async def test_shutdown_empty_manager(self, shutdown_manager: ShutdownManager) -> None:
        """Test shutdown with no registered components."""
        result = await shutdown_manager.shutdown()

        assert result.success is True
        assert result.phase == ShutdownPhase.COMPLETE
        assert len(result.component_statuses) == 0

    @pytest.mark.asyncio
    async def test_shutdown_single_channel(
        self, shutdown_manager: ShutdownManager, mock_channel: MagicMock
    ) -> None:
        """Test shutdown with single channel."""
        shutdown_manager.register_channel("cli", mock_channel)

        result = await shutdown_manager.shutdown()

        assert result.success is True
        mock_channel.stop.assert_called_once()
        assert len(result.component_statuses) == 1
        assert result.component_statuses[0].component_name == "cli"

    @pytest.mark.asyncio
    async def test_shutdown_single_agent(
        self, shutdown_manager: ShutdownManager, mock_agent: MagicMock
    ) -> None:
        """Test shutdown with single agent."""
        shutdown_manager.register_agent("orchestrator", mock_agent)

        result = await shutdown_manager.shutdown()

        assert result.success is True
        mock_agent.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_single_client(
        self, shutdown_manager: ShutdownManager, mock_client: AsyncMock
    ) -> None:
        """Test shutdown with single client."""
        shutdown_manager.register_client("neo4j", mock_client)

        result = await shutdown_manager.shutdown()

        assert result.success is True
        mock_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_order(self, shutdown_manager: ShutdownManager) -> None:
        """Test that shutdown happens in correct order."""
        call_order: list[str] = []

        def make_stop_side_effect(name: str) -> Callable[[], Coroutine[Any, Any, None]]:
            async def _stop() -> None:
                call_order.append(name)

            return _stop

        channel = MagicMock()
        channel.stop = AsyncMock(side_effect=make_stop_side_effect("channel"))

        agent = MagicMock()
        agent.stop = AsyncMock(side_effect=make_stop_side_effect("agent"))
        agent.inbox = asyncio.Queue()

        client = AsyncMock(side_effect=make_stop_side_effect("client"))

        shutdown_manager.register_channel("cli", channel)
        shutdown_manager.register_agent("orchestrator", agent)
        shutdown_manager.register_client("neo4j", client)

        await shutdown_manager.shutdown()

        # Verify channels stop before agents, agents before clients
        channel.stop.assert_called_once()
        agent.stop.assert_called_once()
        client.assert_called_once()

        # Verify order: channel, then agent, then client
        assert call_order == ["channel", "agent", "client"]

    @pytest.mark.asyncio
    async def test_reverse_order_within_category(self, shutdown_manager: ShutdownManager) -> None:
        """Test that components stop in reverse registration order."""
        stop_order: list[str] = []

        def make_stop_side_effect(name: str) -> Callable[[], Coroutine[Any, Any, None]]:
            async def _stop() -> None:
                stop_order.append(name)

            return _stop

        agent1 = MagicMock()
        agent1.stop = AsyncMock(side_effect=make_stop_side_effect("agent1"))
        agent1.inbox = asyncio.Queue()

        agent2 = MagicMock()
        agent2.stop = AsyncMock(side_effect=make_stop_side_effect("agent2"))
        agent2.inbox = asyncio.Queue()

        agent3 = MagicMock()
        agent3.stop = AsyncMock(side_effect=make_stop_side_effect("agent3"))
        agent3.inbox = asyncio.Queue()

        # Register in order: agent1, agent2, agent3
        shutdown_manager.register_agent("agent1", agent1)
        shutdown_manager.register_agent("agent2", agent2)
        shutdown_manager.register_agent("agent3", agent3)

        await shutdown_manager.shutdown()

        # Should stop in reverse: agent3, agent2, agent1
        assert stop_order == ["agent3", "agent2", "agent1"]


# =============================================================================
# Test ShutdownManager - Error Handling
# =============================================================================


class TestShutdownErrorHandling:
    """Tests for error handling during shutdown."""

    @pytest.mark.asyncio
    async def test_component_error_continues_shutdown(
        self, shutdown_manager: ShutdownManager
    ) -> None:
        """Test that shutdown continues after component error."""
        failing_agent = MagicMock()
        failing_agent.stop = AsyncMock(side_effect=RuntimeError("Test error"))
        failing_agent.inbox = asyncio.Queue()

        successful_agent = MagicMock()
        successful_agent.stop = AsyncMock()
        successful_agent.inbox = asyncio.Queue()

        shutdown_manager.register_agent("failing", failing_agent)
        shutdown_manager.register_agent("successful", successful_agent)

        result = await shutdown_manager.shutdown()

        # Both agents should have stop() called
        failing_agent.stop.assert_called_once()
        successful_agent.stop.assert_called_once()

        # Result should indicate partial failure
        assert result.success is False
        failed = [s for s in result.component_statuses if not s.success]
        assert len(failed) == 1
        assert failed[0].component_name == "failing"

    @pytest.mark.asyncio
    async def test_component_timeout(self, shutdown_manager: ShutdownManager) -> None:
        """Test handling of component that times out."""
        # Create manager with very short timeout
        manager = ShutdownManager(timeout_seconds=0.1, drain_timeout_seconds=0.05)

        async def slow_stop() -> None:
            await asyncio.sleep(10.0)  # Much longer than timeout

        slow_agent = MagicMock()
        slow_agent.stop = AsyncMock(side_effect=slow_stop)
        slow_agent.inbox = asyncio.Queue()

        manager.register_agent("slow", slow_agent)

        result = await manager.shutdown()

        # Should have timed out
        timed_out = [s for s in result.component_statuses if s.error and "Timeout" in s.error]
        assert len(timed_out) == 1


# =============================================================================
# Test ShutdownManager - Queue Draining
# =============================================================================


class TestQueueDraining:
    """Tests for queue draining during shutdown."""

    @pytest.mark.asyncio
    async def test_tracks_pending_items(self, shutdown_manager: ShutdownManager) -> None:
        """Test that pending queue items are tracked."""
        agent = MagicMock()
        agent.stop = AsyncMock()
        agent.inbox = asyncio.Queue()

        # Add some items to the queue
        await agent.inbox.put("message1")
        await agent.inbox.put("message2")

        shutdown_manager.register_agent("agent", agent)

        result = await shutdown_manager.shutdown()

        # Should record pending items count
        agent_status = result.component_statuses[0]
        assert agent_status.pending_items == 2

    @pytest.mark.asyncio
    async def test_drain_timeout(self, shutdown_manager: ShutdownManager) -> None:
        """Test that drain times out gracefully."""
        # Create manager with very short drain timeout
        manager = ShutdownManager(timeout_seconds=5.0, drain_timeout_seconds=0.1)

        agent = MagicMock()
        agent.stop = AsyncMock()
        agent.inbox = asyncio.Queue()

        # Add items that won't be consumed
        await agent.inbox.put("message1")

        manager.register_agent("agent", agent)

        # Should complete without hanging
        await manager.shutdown()

        # Shutdown should still succeed (drain timeout is warning, not error)
        assert agent.stop.called


# =============================================================================
# Test ShutdownManager - State Management
# =============================================================================


class TestShutdownState:
    """Tests for shutdown state management."""

    def test_initial_state(self, shutdown_manager: ShutdownManager) -> None:
        """Test initial state of shutdown manager."""
        assert shutdown_manager.shutdown_requested is False
        assert shutdown_manager.current_phase == ShutdownPhase.INITIATED

    def test_request_shutdown(self, shutdown_manager: ShutdownManager) -> None:
        """Test requesting shutdown."""
        shutdown_manager.request_shutdown()

        assert shutdown_manager.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_wait_for_shutdown(self, shutdown_manager: ShutdownManager) -> None:
        """Test waiting for shutdown request."""

        async def request_later() -> None:
            await asyncio.sleep(0.1)
            shutdown_manager.request_shutdown()

        # Start background task to request shutdown
        background_task = asyncio.create_task(request_later())

        # This should complete once shutdown is requested
        await asyncio.wait_for(shutdown_manager.wait_for_shutdown(), timeout=1.0)

        # Cleanup background task
        await background_task

        assert shutdown_manager.shutdown_requested is True


# =============================================================================
# Test Module Functions
# =============================================================================


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_shutdown_manager_singleton(self) -> None:
        """Test that get_shutdown_manager returns singleton."""
        manager1 = get_shutdown_manager()
        manager2 = get_shutdown_manager()

        assert manager1 is manager2

    def test_reset_shutdown_manager(self) -> None:
        """Test resetting the global shutdown manager."""
        manager1 = get_shutdown_manager()
        reset_shutdown_manager()
        manager2 = get_shutdown_manager()

        assert manager1 is not manager2


# =============================================================================
# Test ShutdownPhase
# =============================================================================


class TestShutdownPhase:
    """Tests for ShutdownPhase enum."""

    def test_all_phases_have_values(self) -> None:
        """Test that all phases have string values."""
        for phase in ShutdownPhase:
            assert isinstance(phase.value, str)
            assert len(phase.value) > 0

    def test_phase_progression(self) -> None:
        """Test expected phase values."""
        assert ShutdownPhase.INITIATED.value == "initiated"
        assert ShutdownPhase.CHANNELS_STOPPING.value == "channels_stopping"
        assert ShutdownPhase.DRAINING_QUEUES.value == "draining_queues"
        assert ShutdownPhase.AGENTS_STOPPING.value == "agents_stopping"
        assert ShutdownPhase.CLIENTS_DISCONNECTING.value == "clients_disconnecting"
        assert ShutdownPhase.COMPLETE.value == "complete"
        assert ShutdownPhase.FAILED.value == "failed"


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Integration tests for realistic shutdown scenarios."""

    @pytest.mark.asyncio
    async def test_full_system_shutdown(self, shutdown_manager: ShutdownManager) -> None:
        """Test shutdown of a complete system."""
        # Create mock components
        cli = MagicMock()
        cli.stop = AsyncMock()

        orchestrator = MagicMock()
        orchestrator.stop = AsyncMock()
        orchestrator.inbox = asyncio.Queue()

        ingestor = MagicMock()
        ingestor.stop = AsyncMock()
        ingestor.inbox = asyncio.Queue()

        researcher = MagicMock()
        researcher.stop = AsyncMock()
        researcher.inbox = asyncio.Queue()

        neo4j = AsyncMock()
        graphiti = AsyncMock()

        # Register all components
        shutdown_manager.register_channel("cli", cli)
        shutdown_manager.register_agent("orchestrator", orchestrator)
        shutdown_manager.register_agent("ingestor", ingestor)
        shutdown_manager.register_agent("researcher", researcher)
        shutdown_manager.register_client("graphiti", graphiti)
        shutdown_manager.register_client("neo4j", neo4j)

        # Execute shutdown
        result = await shutdown_manager.shutdown()

        # Verify success
        assert result.success is True
        assert result.phase == ShutdownPhase.COMPLETE
        assert len(result.component_statuses) == 6

        # Verify all components were stopped
        cli.stop.assert_called_once()
        orchestrator.stop.assert_called_once()
        ingestor.stop.assert_called_once()
        researcher.stop.assert_called_once()
        graphiti.assert_called_once()
        neo4j.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_with_pending_messages(self, shutdown_manager: ShutdownManager) -> None:
        """Test shutdown when agents have pending messages."""
        agent = MagicMock()
        consumed_messages: list[Any] = []

        async def stop_and_drain() -> None:
            # Simulate draining messages during stop
            while not agent.inbox.empty():
                msg = await agent.inbox.get()
                consumed_messages.append(msg)

        agent.stop = AsyncMock(side_effect=stop_and_drain)
        agent.inbox = asyncio.Queue()

        # Add pending messages
        await agent.inbox.put({"type": "ingest", "data": "test1"})
        await agent.inbox.put({"type": "ingest", "data": "test2"})

        shutdown_manager.register_agent("agent", agent)

        result = await shutdown_manager.shutdown()

        # Agent should have been stopped
        assert agent.stop.called
        assert result.success is True
