"""
Unit tests for V2 rollback mechanism (T077).

Tests the ability to switch between v1 (intent-based) and v2 (Think-Dispatch-Synthesize)
workflows via the use_v2_workflow config flag.
"""

from unittest.mock import AsyncMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator


class TestV2RollbackMechanism:
    """Tests for v1/v2 workflow routing based on config flag."""

    @pytest.fixture
    def base_config(self) -> dict:
        """Base configuration with v2 workflow enabled (default)."""
        return {
            "use_v2_workflow": True,
            "model": {
                "primary": "claude-sonnet-4-20250514",
            },
        }

    @pytest.fixture
    def orchestrator_v2(self, base_config: dict) -> Orchestrator:
        """Create orchestrator with v2 workflow enabled."""
        return Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=base_config,
        )

    @pytest.fixture
    def orchestrator_v1(self, base_config: dict) -> Orchestrator:
        """Create orchestrator with v1 workflow enabled (rollback mode)."""
        config = base_config.copy()
        config["use_v2_workflow"] = False
        return Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_v2_routes_to_handle_user_input_v2(self, orchestrator_v2: Orchestrator) -> None:
        """When use_v2_workflow is True, routes to handle_user_input_v2."""
        # Mock the v2 handler
        with patch.object(
            orchestrator_v2, "handle_user_input_v2", new_callable=AsyncMock
        ) as mock_v2:
            mock_v2.return_value = "v2 response"

            result = await orchestrator_v2.handle_user_input(
                thread_id="test-thread-123",
                text="Tell me about Project Alpha",
                trace_id="test-trace",
            )

            # Assert v2 handler was called
            mock_v2.assert_called_once()
            call_kwargs = mock_v2.call_args.kwargs
            assert call_kwargs["text"] == "Tell me about Project Alpha"
            assert call_kwargs["thread_uuid"] == "test-thread-123"
            assert call_kwargs["trace_id"] == "test-trace"
            assert result == "v2 response"

    @pytest.mark.asyncio
    async def test_v1_routes_to_handle_user_input_v1(self, orchestrator_v1: Orchestrator) -> None:
        """When use_v2_workflow is False, routes to _handle_user_input_v1."""
        # Mock the v1 handler
        with patch.object(
            orchestrator_v1, "_handle_user_input_v1", new_callable=AsyncMock
        ) as mock_v1:
            mock_v1.return_value = "v1 response"

            result = await orchestrator_v1.handle_user_input(
                thread_id="test-thread-456",
                text="Who is John?",
                context=None,
                trace_id="test-trace",
            )

            # Assert v1 handler was called
            mock_v1.assert_called_once()
            call_kwargs = mock_v1.call_args.kwargs
            assert call_kwargs["text"] == "Who is John?"
            assert call_kwargs["thread_id"] == "test-thread-456"
            assert call_kwargs["context"] is None
            assert call_kwargs["trace_id"] == "test-trace"
            assert result == "v1 response"

    @pytest.mark.asyncio
    async def test_config_flag_defaults_to_v2_when_missing(self) -> None:
        """When use_v2_workflow is not in config, defaults to True (v2)."""
        orchestrator = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config={},  # Empty config, no use_v2_workflow flag
        )

        with patch.object(orchestrator, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "default v2"

            await orchestrator.handle_user_input(
                thread_id="test-thread",
                text="test message",
            )

            # Should default to v2
            mock_v2.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_flag_defaults_to_v2_when_config_is_none(self) -> None:
        """When config is None, defaults to True (v2)."""
        orchestrator = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=None,
        )

        with patch.object(orchestrator, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "default v2"

            await orchestrator.handle_user_input(
                thread_id="test-thread",
                text="test message",
            )

            # Should default to v2
            mock_v2.assert_called_once()

    @pytest.mark.asyncio
    async def test_runtime_config_reload_switches_workflow(self) -> None:
        """Config change takes effect at runtime without restart."""
        config = {"use_v2_workflow": True}
        orchestrator = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config,
        )

        # First call should use v2
        with patch.object(orchestrator, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "v2 response"

            result1 = await orchestrator.handle_user_input(
                thread_id="test-thread",
                text="first message",
            )

            assert result1 == "v2 response"
            mock_v2.assert_called_once()

        # Change config to v1
        config["use_v2_workflow"] = False

        # Second call should use v1
        with patch.object(orchestrator, "_handle_user_input_v1", new_callable=AsyncMock) as mock_v1:
            mock_v1.return_value = "v1 response"

            result2 = await orchestrator.handle_user_input(
                thread_id="test-thread",
                text="second message",
            )

            assert result2 == "v1 response"
            mock_v1.assert_called_once()

    @pytest.mark.asyncio
    async def test_v2_logs_workflow_version(self, orchestrator_v2: Orchestrator) -> None:
        """Using v2 workflow logs [CHART] indicator."""
        with patch.object(
            orchestrator_v2, "handle_user_input_v2", new_callable=AsyncMock
        ) as mock_v2:
            mock_v2.return_value = "v2 response"

            with patch("klabautermann.agents.orchestrator.logger") as mock_logger:
                await orchestrator_v2.handle_user_input(
                    thread_id="test-thread",
                    text="test message",
                    trace_id="test-trace",
                )

                # Check that logger.info was called with v2 workflow message
                calls = list(mock_logger.info.call_args_list)
                assert any(
                    "[CHART] Using v2 workflow" in str(call) for call in calls
                ), "Expected [CHART] log for v2 workflow"

    @pytest.mark.asyncio
    async def test_v1_logs_workflow_version(self, orchestrator_v1: Orchestrator) -> None:
        """Using v1 workflow logs [CHART] indicator."""
        with patch.object(
            orchestrator_v1, "_handle_user_input_v1", new_callable=AsyncMock
        ) as mock_v1:
            mock_v1.return_value = "v1 response"

            with patch("klabautermann.agents.orchestrator.logger") as mock_logger:
                await orchestrator_v1.handle_user_input(
                    thread_id="test-thread",
                    text="test message",
                    trace_id="test-trace",
                )

                # Check that logger.info was called with v1 workflow message
                calls = list(mock_logger.info.call_args_list)
                assert any(
                    "[CHART] Using v1 workflow" in str(call) for call in calls
                ), "Expected [CHART] log for v1 workflow"

    @pytest.mark.asyncio
    async def test_v1_and_v2_workflows_coexist(self) -> None:
        """Both v1 and v2 workflows can be instantiated and used."""
        config_v1 = {"use_v2_workflow": False}
        config_v2 = {"use_v2_workflow": True}

        orch_v1 = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config_v1,
        )

        orch_v2 = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config_v2,
        )

        # Both should work independently
        with patch.object(orch_v1, "_handle_user_input_v1", new_callable=AsyncMock) as mock_v1:
            mock_v1.return_value = "v1 response"
            result_v1 = await orch_v1.handle_user_input(
                thread_id="thread-1",
                text="message 1",
            )
            assert result_v1 == "v1 response"

        with patch.object(orch_v2, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "v2 response"
            result_v2 = await orch_v2.handle_user_input(
                thread_id="thread-2",
                text="message 2",
            )
            assert result_v2 == "v2 response"

    @pytest.mark.asyncio
    async def test_trace_id_generation_works_for_both_workflows(self) -> None:
        """Trace ID is generated if not provided, for both workflows."""
        config_v1 = {"use_v2_workflow": False}
        config_v2 = {"use_v2_workflow": True}

        orch_v1 = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config_v1,
        )

        orch_v2 = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config_v2,
        )

        # v1 should generate trace_id
        with patch.object(orch_v1, "_handle_user_input_v1", new_callable=AsyncMock) as mock_v1:
            mock_v1.return_value = "v1 response"

            await orch_v1.handle_user_input(
                thread_id="thread-1",
                text="message 1",
                # trace_id not provided
            )

            # Check that trace_id was generated (starts with "orch-")
            call_kwargs = mock_v1.call_args.kwargs
            assert "trace_id" in call_kwargs
            assert call_kwargs["trace_id"].startswith("orch-")

        # v2 should generate trace_id
        with patch.object(orch_v2, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "v2 response"

            await orch_v2.handle_user_input(
                thread_id="thread-2",
                text="message 2",
                # trace_id not provided
            )

            # Check that trace_id was generated (starts with "orch-")
            call_kwargs = mock_v2.call_args.kwargs
            assert "trace_id" in call_kwargs
            assert call_kwargs["trace_id"].startswith("orch-")


class TestPerformanceImpact:
    """Tests to ensure no performance impact from routing check."""

    @pytest.mark.asyncio
    async def test_routing_check_adds_negligible_overhead(self) -> None:
        """Config flag check adds negligible overhead."""
        import time

        config = {"use_v2_workflow": True}
        orchestrator = Orchestrator(
            graphiti=None,
            thread_manager=None,
            neo4j_client=None,
            config=config,
        )

        with patch.object(orchestrator, "handle_user_input_v2", new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "response"

            # Measure time for 100 routing checks
            start = time.perf_counter()
            for _ in range(100):
                await orchestrator.handle_user_input(
                    thread_id="thread",
                    text="test",
                )
            end = time.perf_counter()

            # Each routing decision should take < 1ms (being very conservative)
            avg_time_ms = ((end - start) / 100) * 1000
            # Most of the time is in the mocked call, but routing should be negligible
            # We're really just checking that it doesn't blow up
            assert avg_time_ms < 100  # Very generous upper bound
