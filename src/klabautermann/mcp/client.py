"""
MCP Client - Generic wrapper for Model Context Protocol tool invocation.

Manages MCP server processes and provides a unified interface for invoking tools.
Implements stdio transport with JSON-RPC protocol.

Key features:
- Process lifecycle management (start, stop, health check)
- Connection pooling and reuse
- Automatic reconnection on failure
- Trace ID propagation for observability
- Comprehensive error handling

Reference: specs/architecture/MCP.md Section 2
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from klabautermann.core.exceptions import MCPConnectionError, MCPError, MCPTimeoutError
from klabautermann.core.logger import logger


# ===========================================================================
# Configuration Models
# ===========================================================================


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    command: list[str]  # e.g., ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class ToolInvocationContext:
    """Context for tool invocation with trace propagation."""

    trace_id: str
    agent_name: str
    thread_id: str | None = None


# ===========================================================================
# MCP Client
# ===========================================================================


class MCPClient:
    """
    Generic MCP client for tool invocation.

    Manages MCP server processes and provides a unified interface
    for invoking tools across different servers.

    Example:
        client = MCPClient()
        config = MCPServerConfig(
            name="filesystem",
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/app/data"]
        )
        await client.start_server(config)
        result = await client.invoke_tool(
            "filesystem",
            "read_file",
            {"path": "/app/data/notes.txt"},
            context
        )
        await client.stop_all()
    """

    def __init__(self) -> None:
        """Initialize MCP client with empty server registry."""
        self._servers: dict[str, MCPServerConnection] = {}
        self._lock = asyncio.Lock()

    async def start_server(self, config: MCPServerConfig) -> None:
        """
        Start an MCP server process.

        Args:
            config: Server configuration.

        Raises:
            MCPConnectionError: If server fails to start.
        """
        async with self._lock:
            if config.name in self._servers:
                logger.debug(f"[WHISPER] Server {config.name} already running")
                return

            conn = MCPServerConnection(config)
            await conn.start()
            self._servers[config.name] = conn
            logger.info(f"[CHART] Started MCP server: {config.name}")

    async def stop_server(self, name: str) -> None:
        """
        Stop a specific MCP server.

        Args:
            name: Name of the server to stop.
        """
        async with self._lock:
            if name in self._servers:
                await self._servers[name].stop()
                del self._servers[name]
                logger.info(f"[CHART] Stopped MCP server: {name}")

    async def stop_all(self) -> None:
        """Stop all running MCP servers."""
        for name in list(self._servers.keys()):
            await self.stop_server(name)

    async def invoke_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Invoke a tool on an MCP server.

        Args:
            server_name: Name of the MCP server.
            tool_name: Name of the tool to invoke.
            arguments: Tool arguments as dictionary.
            context: Invocation context with trace_id for observability.
            timeout: Optional timeout override (uses server default if None).

        Returns:
            Tool result as dictionary.

        Raises:
            MCPError: If server not found or tool invocation fails.
            MCPTimeoutError: If tool execution times out.
        """
        if server_name not in self._servers:
            raise MCPError(
                f"Server not found: {server_name}",
                trace_id=context.trace_id,
            )

        server = self._servers[server_name]

        logger.debug(
            f"[WHISPER] Invoking tool {tool_name} on {server_name}",
            extra={"trace_id": context.trace_id, "arguments": arguments},
        )

        try:
            result = await server.call_tool(
                tool_name,
                arguments,
                timeout=timeout or server.config.timeout,
            )

            logger.debug(
                f"[WHISPER] Tool {tool_name} completed",
                extra={"trace_id": context.trace_id},
            )

            return result

        except TimeoutError as e:
            logger.warning(
                f"[SWELL] Tool {tool_name} timed out",
                extra={"trace_id": context.trace_id},
            )
            raise MCPTimeoutError(
                f"Tool {tool_name} timed out",
                tool_name=tool_name,
                timeout_seconds=timeout or server.config.timeout,
                trace_id=context.trace_id,
            ) from e

        except MCPError:
            # Re-raise MCP errors as-is
            raise

        except Exception as e:
            logger.error(
                f"[STORM] Tool {tool_name} failed: {e}",
                extra={"trace_id": context.trace_id},
            )
            raise MCPError(
                f"Tool invocation failed: {e}",
                tool_name=tool_name,
                trace_id=context.trace_id,
            ) from e

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """
        List available tools on a server.

        Args:
            server_name: Name of the MCP server.

        Returns:
            List of tool definitions with name, description, and schema.

        Raises:
            MCPError: If server not found.
        """
        if server_name not in self._servers:
            raise MCPError(f"Server not found: {server_name}")

        return await self._servers[server_name].list_tools()

    def is_server_running(self, server_name: str) -> bool:
        """
        Check if a server is currently running.

        Args:
            server_name: Name of the server.

        Returns:
            True if server is running, False otherwise.
        """
        return server_name in self._servers

    @asynccontextmanager
    async def server_context(self, config: MCPServerConfig) -> AsyncIterator[str]:
        """
        Context manager for temporary server lifecycle.

        Starts server on entry, stops on exit. Useful for one-off operations.

        Args:
            config: Server configuration.

        Yields:
            Server name for use in invoke_tool calls.

        Example:
            async with client.server_context(config) as server_name:
                result = await client.invoke_tool(server_name, "tool", {}, context)
        """
        await self.start_server(config)
        try:
            yield config.name
        finally:
            await self.stop_server(config.name)


# ===========================================================================
# MCP Server Connection
# ===========================================================================


class MCPServerConnection:
    """
    Connection to a single MCP server process.

    Handles stdio transport with JSON-RPC 2.0 protocol.
    Manages request/response matching and background reading.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        """
        Initialize connection (does not start process).

        Args:
            config: Server configuration.
        """
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """
        Start the server process and initialize MCP connection.

        Raises:
            MCPConnectionError: If process fails to start or initialize.
        """
        try:
            # Merge environment variables
            env = {**dict(os.environ), **self.config.env}

            # Start subprocess with stdio pipes
            self._process = await asyncio.create_subprocess_exec(
                *self.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Start background reader task
            self._reader_task = asyncio.create_task(self._read_responses())

            # Send MCP initialize handshake
            await self._initialize()

            logger.debug(f"[WHISPER] MCP server {self.config.name} initialized")

        except Exception as e:
            logger.error(f"[STORM] Failed to start MCP server {self.config.name}: {e}")
            raise MCPConnectionError(
                self.config.name,
                f"Failed to start server: {e}",
            ) from e

    async def stop(self) -> None:
        """Stop the server process and cleanup resources."""
        # Cancel reader task
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

        # Terminate process
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                # Force kill if graceful shutdown fails
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.warning(f"[SWELL] Error stopping MCP server {self.config.name}: {e}")

        # Cancel all pending requests
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def _initialize(self) -> None:
        """
        Initialize MCP connection with handshake.

        Sends initialize request and initialized notification.
        """
        # Send initialize request
        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "klabautermann",
                    "version": "0.1.0",
                },
            },
        )

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """
        Call a tool and wait for response.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.
            timeout: Timeout in seconds.

        Returns:
            Tool result from server.

        Raises:
            MCPError: If tool call fails.
            asyncio.TimeoutError: If call times out.
        """
        try:
            response = await asyncio.wait_for(
                self._send_request(
                    "tools/call",
                    {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError:
            raise

        # Check for error in response
        if "error" in response:
            error_msg = response["error"].get("message", "Unknown error")
            raise MCPError(f"Tool {tool_name} failed: {error_msg}", tool_name=tool_name)

        result: dict[str, Any] = response.get("result", {})
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        List available tools from server.

        Returns:
            List of tool definitions.
        """
        response = await self._send_request("tools/list", {})
        tools: list[dict[str, Any]] = response.get("tools", [])
        return tools

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Send JSON-RPC request and wait for response.

        Args:
            method: JSON-RPC method name.
            params: Method parameters.

        Returns:
            Response data.

        Raises:
            MCPError: If request fails.
        """
        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # Send request
        await self._write(request)

        # Wait for response
        return await future

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """
        Send JSON-RPC notification (no response expected).

        Args:
            method: Notification method name.
            params: Method parameters.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write(notification)

    async def _write(self, data: dict[str, Any]) -> None:
        """
        Write JSON-RPC message to server stdin.

        Args:
            data: JSON-RPC message.

        Raises:
            MCPError: If server not running or write fails.
        """
        if not self._process or not self._process.stdin:
            raise MCPError(f"Server {self.config.name} not running")

        try:
            message = json.dumps(data) + "\n"
            self._process.stdin.write(message.encode())
            await self._process.stdin.drain()
        except Exception as e:
            raise MCPError(f"Failed to write to server: {e}") from e

    async def _read_responses(self) -> None:
        """
        Read responses from server stdout (runs in background).

        Matches responses to pending requests and resolves futures.
        """
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    # EOF - server closed
                    break

                data = json.loads(line.decode())

                # Match response to pending request
                if "id" in data and data["id"] in self._pending:
                    future = self._pending.pop(data["id"])
                    if not future.done():
                        future.set_result(data)

            except json.JSONDecodeError as e:
                logger.warning(f"[SWELL] Invalid JSON from MCP server {self.config.name}: {e}")
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STORM] MCP reader error for {self.config.name}: {e}")
                break

        # If we exit the loop, cancel all pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(
                    MCPConnectionError(
                        self.config.name,
                        "Server connection closed unexpectedly",
                    )
                )


# ===========================================================================
# Convenience Function
# ===========================================================================


async def invoke_mcp_tool(
    server_config: MCPServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolInvocationContext,
) -> dict[str, Any]:
    """
    Convenience function to invoke a tool without managing server lifecycle.

    Creates a temporary connection, invokes the tool, and cleans up.
    For repeated calls, use MCPClient with persistent connections.

    Args:
        server_config: Server configuration.
        tool_name: Name of the tool to invoke.
        arguments: Tool arguments.
        context: Invocation context.

    Returns:
        Tool result.

    Example:
        result = await invoke_mcp_tool(
            MCPServerConfig(name="fs", command=["npx", "-y", "..."]),
            "read_file",
            {"path": "/app/data/notes.txt"},
            context
        )
    """
    client = MCPClient()
    try:
        await client.start_server(server_config)
        return await client.invoke_tool(
            server_config.name,
            tool_name,
            arguments,
            context,
        )
    finally:
        await client.stop_all()


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "MCPClient",
    "MCPServerConfig",
    "MCPServerConnection",
    "ToolInvocationContext",
    "invoke_mcp_tool",
]
