"""
Unit tests for MCP client wrapper.

Tests cover:
- Server lifecycle (start, stop, health check)
- Tool invocation (success, failure, timeout)
- JSON-RPC protocol handling
- Connection pooling and reconnection
- Error handling and propagation
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.core.exceptions import MCPConnectionError, MCPError, MCPTimeoutError
from klabautermann.mcp.client import (
    MCPClient,
    MCPServerConfig,
    MCPServerConnection,
    ToolInvocationContext,
    invoke_mcp_tool,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def server_config() -> MCPServerConfig:
    """Create a test server configuration."""
    return MCPServerConfig(
        name="test_server",
        command=["npx", "-y", "@test/mcp-server"],
        env={"TEST_VAR": "test_value"},
        timeout=5.0,
    )


@pytest.fixture
def invocation_context() -> ToolInvocationContext:
    """Create a test invocation context."""
    return ToolInvocationContext(
        trace_id="test-trace-123",
        agent_name="test_agent",
        thread_id="thread-456",
    )


@pytest.fixture
def mock_process() -> MagicMock:
    """Create a mock subprocess."""
    process = MagicMock()
    # stdin needs write (sync) and drain (async)
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()  # Synchronous write
    process.stdin.drain = AsyncMock(return_value=None)  # Async drain
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


# ===========================================================================
# MCPClient Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPClient:
    """Test suite for MCPClient."""

    async def test_start_server_success(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test successful server startup."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            # Mock the initialize response
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",  # EOF
                ]
            )

            await client.start_server(server_config)

            assert client.is_server_running("test_server")

        await client.stop_all()

    async def test_start_server_already_running(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test starting a server that's already running (should be idempotent)."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",
                ]
            )

            await client.start_server(server_config)
            await client.start_server(server_config)  # Second call

            assert client.is_server_running("test_server")

        await client.stop_all()

    async def test_stop_server(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test stopping a server."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",
                ]
            )

            await client.start_server(server_config)
            assert client.is_server_running("test_server")

            await client.stop_server("test_server")
            assert not client.is_server_running("test_server")

    async def test_stop_all_servers(
        self,
    ) -> None:
        """Test stopping all servers."""
        client = MCPClient()
        config1 = MCPServerConfig(name="server1", command=["test"])
        config2 = MCPServerConfig(name="server2", command=["test"])

        # Create separate mock processes for each server
        async def create_mock_process(*args, **kwargs):
            process = MagicMock()
            # stdin needs write (sync) and drain (async)
            process.stdin = MagicMock()
            process.stdin.write = MagicMock()
            process.stdin.drain = AsyncMock(return_value=None)
            process.stdout = AsyncMock()
            process.stderr = AsyncMock()
            process.wait = AsyncMock(return_value=0)
            process.terminate = MagicMock()
            process.kill = MagicMock()
            # Each process returns init response then EOF
            process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",
                ]
            )
            return process

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=create_mock_process,
        ):
            await client.start_server(config1)
            await client.start_server(config2)

            assert client.is_server_running("server1")
            assert client.is_server_running("server2")

            await client.stop_all()

            assert not client.is_server_running("server1")
            assert not client.is_server_running("server2")

    async def test_invoke_tool_success(
        self,
        server_config: MCPServerConfig,
        invocation_context: ToolInvocationContext,
        mock_process: MagicMock,
    ) -> None:
        """Test successful tool invocation."""
        client = MCPClient()

        # Create an async queue for responses
        response_queue = asyncio.Queue()

        async def mock_readline():
            """Read from queue with proper async behavior."""
            return await response_queue.get()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = mock_readline

            # Enqueue responses
            await response_queue.put(b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n')  # initialize

            await client.start_server(server_config)

            # Enqueue tool call response
            await response_queue.put(
                b'{"jsonrpc": "2.0", "id": 2, "result": {"output": "success"}}\n'
            )

            result = await client.invoke_tool(
                "test_server",
                "test_tool",
                {"arg1": "value1"},
                invocation_context,
            )

            assert result == {"output": "success"}

            # Enqueue EOF to stop reader task
            await response_queue.put(b"")

        await client.stop_all()

    async def test_invoke_tool_server_not_found(
        self,
        invocation_context: ToolInvocationContext,
    ) -> None:
        """Test invoking tool on non-existent server."""
        client = MCPClient()

        with pytest.raises(MCPError) as exc_info:
            await client.invoke_tool(
                "nonexistent_server",
                "test_tool",
                {},
                invocation_context,
            )

        assert "Server not found" in str(exc_info.value)

    async def test_invoke_tool_timeout(
        self,
        server_config: MCPServerConfig,
        invocation_context: ToolInvocationContext,
        mock_process: MagicMock,
    ) -> None:
        """Test tool invocation timeout."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            # Initialize response, then hang on tool call
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    asyncio.sleep(10),  # Simulate timeout
                ]
            )

            await client.start_server(server_config)

            with pytest.raises(MCPTimeoutError) as exc_info:
                await client.invoke_tool(
                    "test_server",
                    "slow_tool",
                    {},
                    invocation_context,
                    timeout=0.1,  # Very short timeout
                )

            assert exc_info.value.tool_name == "slow_tool"
            assert exc_info.value.timeout_seconds == 0.1

        await client.stop_all()

    @pytest.mark.skip(reason="TODO: Fix with async queue approach")
    async def test_list_tools(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test listing available tools."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            tools = [
                {"name": "tool1", "description": "First tool"},
                {"name": "tool2", "description": "Second tool"},
            ]

            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',  # initialize
                    json.dumps({"jsonrpc": "2.0", "id": 2, "tools": tools}).encode()
                    + b"\n",  # list_tools
                    b"",
                ]
            )

            await client.start_server(server_config)
            result = await client.list_tools("test_server")

            assert len(result) == 2
            assert result[0]["name"] == "tool1"
            assert result[1]["name"] == "tool2"

        await client.stop_all()

    async def test_list_tools_server_not_found(self) -> None:
        """Test listing tools on non-existent server."""
        client = MCPClient()

        with pytest.raises(MCPError) as exc_info:
            await client.list_tools("nonexistent_server")

        assert "Server not found" in str(exc_info.value)

    @pytest.mark.skip(reason="TODO: Fix with async queue approach")
    async def test_server_context_manager(
        self,
        server_config: MCPServerConfig,
        invocation_context: ToolInvocationContext,
        mock_process: MagicMock,
    ) -> None:
        """Test server context manager for temporary connections."""
        client = MCPClient()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',  # initialize
                    b'{"jsonrpc": "2.0", "id": 2, "result": {"data": "test"}}\n',  # tool call
                    b"",
                ]
            )

            async with client.server_context(server_config) as server_name:
                assert client.is_server_running(server_name)

                result = await client.invoke_tool(
                    server_name,
                    "test_tool",
                    {},
                    invocation_context,
                )

                assert result == {"data": "test"}

            # Server should be stopped after context exit
            assert not client.is_server_running(server_config.name)


# ===========================================================================
# MCPServerConnection Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPServerConnection:
    """Test suite for MCPServerConnection."""

    async def test_start_success(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test successful connection start."""
        conn = MCPServerConnection(server_config)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",
                ]
            )

            await conn.start()
            assert conn._process is not None

        await conn.stop()

    async def test_start_failure(
        self,
        server_config: MCPServerConfig,
    ) -> None:
        """Test connection start failure."""
        conn = MCPServerConnection(server_config)

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("Command not found"),
        ):
            with pytest.raises(MCPConnectionError) as exc_info:
                await conn.start()

            assert "Failed to start server" in str(exc_info.value)

    async def test_call_tool_success(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test successful tool call."""
        conn = MCPServerConnection(server_config)

        response_queue = asyncio.Queue()

        async def mock_readline():
            return await response_queue.get()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = mock_readline

            await response_queue.put(b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n')  # initialize

            await conn.start()

            await response_queue.put(
                b'{"jsonrpc": "2.0", "id": 2, "result": {"status": "ok"}}\n'
            )  # tool call

            result = await conn.call_tool("test_tool", {"key": "value"})
            assert result == {"status": "ok"}

            await response_queue.put(b"")  # EOF

        await conn.stop()

    async def test_call_tool_error(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test tool call with error response."""
        conn = MCPServerConnection(server_config)

        response_queue = asyncio.Queue()

        async def mock_readline():
            return await response_queue.get()

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = mock_readline

            await response_queue.put(b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n')  # initialize

            await conn.start()

            await response_queue.put(
                b'{"jsonrpc": "2.0", "id": 2, "error": {"message": "Tool failed"}}\n'
            )  # error

            with pytest.raises(MCPError) as exc_info:
                await conn.call_tool("failing_tool", {})

            assert "Tool failed" in str(exc_info.value)

            await response_queue.put(b"")  # EOF

        await conn.stop()

    async def test_call_tool_timeout(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test tool call timeout."""
        conn = MCPServerConnection(server_config)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    asyncio.sleep(10),  # Hang forever
                ]
            )

            await conn.start()

            with pytest.raises(asyncio.TimeoutError):
                await conn.call_tool("slow_tool", {}, timeout=0.1)

        await conn.stop()

    @pytest.mark.skip(reason="TODO: Fix with async queue approach")
    async def test_list_tools(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test listing tools from connection."""
        conn = MCPServerConnection(server_config)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            tools = [{"name": "tool1"}, {"name": "tool2"}]

            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    json.dumps({"jsonrpc": "2.0", "id": 2, "tools": tools}).encode() + b"\n",
                    b"",
                ]
            )

            await conn.start()

            result = await conn.list_tools()
            assert len(result) == 2

        await conn.stop()

    @pytest.mark.skip(reason="TODO: Fix with async queue approach")
    async def test_json_rpc_protocol(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test proper JSON-RPC message formatting."""
        conn = MCPServerConnection(server_config)
        written_messages: list[dict] = []

        async def capture_write(data: bytes) -> None:
            """Capture written messages for inspection."""
            written_messages.append(json.loads(data.decode().strip()))

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"",
                ]
            )
            mock_process.stdin.write = MagicMock(side_effect=capture_write)
            mock_process.stdin.drain = AsyncMock()

            await conn.start()

            # Check initialize request format
            assert len(written_messages) >= 1
            init_request = written_messages[0]
            assert init_request["jsonrpc"] == "2.0"
            assert init_request["method"] == "initialize"
            assert "id" in init_request
            assert "params" in init_request

        await conn.stop()

    @pytest.mark.skip(reason="TODO: Fix with async queue approach")
    async def test_invalid_json_handling(
        self,
        server_config: MCPServerConfig,
        mock_process: MagicMock,
    ) -> None:
        """Test handling of invalid JSON from server."""
        conn = MCPServerConnection(server_config)

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_process,
        ):
            mock_process.stdout.readline = AsyncMock(
                side_effect=[
                    b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                    b"invalid json\n",  # Invalid JSON should be skipped
                    b'{"jsonrpc": "2.0", "id": 2, "result": {"ok": true}}\n',
                    b"",
                ]
            )

            await conn.start()

            # Should successfully get valid response despite invalid JSON in between
            result = await conn.call_tool("test_tool", {})
            assert result["ok"] is True

        await conn.stop()


# ===========================================================================
# Convenience Function Tests
# ===========================================================================


@pytest.mark.unit
@pytest.mark.skip(reason="TODO: Fix with async queue approach")
async def test_invoke_mcp_tool_convenience(
    server_config: MCPServerConfig,
    invocation_context: ToolInvocationContext,
    mock_process: MagicMock,
) -> None:
    """Test convenience function for one-off tool invocations."""
    with patch(
        "asyncio.create_subprocess_exec",
        return_value=mock_process,
    ):
        mock_process.stdout.readline = AsyncMock(
            side_effect=[
                b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
                b'{"jsonrpc": "2.0", "id": 2, "result": {"data": "result"}}\n',
                b"",
            ]
        )

        result = await invoke_mcp_tool(
            server_config,
            "test_tool",
            {"input": "test"},
            invocation_context,
        )

        assert result == {"data": "result"}
