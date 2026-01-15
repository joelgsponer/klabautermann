# Create MCP Client Wrapper

## Metadata
- **ID**: T026
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @integration-engineer

## Specs
- Primary: [MCP_INTEGRATION.md](../../specs/architecture/MCP_INTEGRATION.md) (if exists)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4

## Dependencies
- [x] T008 - Logging system
- [x] T012 - Custom exceptions

## Context
MCP (Model Context Protocol) provides standardized tool integration. Agents don't call external APIs directly - they invoke MCP tools through a generic wrapper. This task creates the core MCP client infrastructure that manages server processes, invokes tools, and handles responses.

## Requirements
- [ ] Create `src/klabautermann/mcp/client.py`:

### Server Process Management
- [ ] Start MCP server processes (npx commands)
- [ ] Manage server lifecycle (start, health check, restart)
- [ ] Handle server crashes gracefully
- [ ] Support multiple concurrent servers

### Tool Invocation
- [ ] Generic `invoke_tool()` method
- [ ] Tool name and arguments validation
- [ ] Request/response serialization (JSON-RPC)
- [ ] Timeout handling

### Response Handling
- [ ] Parse tool results
- [ ] Handle errors from tools
- [ ] Format responses for agent consumption

### Connection Management
- [ ] Stdio transport (stdin/stdout communication)
- [ ] Connection pooling (reuse server processes)
- [ ] Automatic reconnection on failure

### Context Propagation
- [ ] Pass trace_id through tool calls
- [ ] Log all tool invocations
- [ ] Track tool execution metrics

## Acceptance Criteria
- [ ] MCP server can be started and stopped cleanly
- [ ] Tool invocation works with proper arguments
- [ ] Errors from tools are caught and formatted
- [ ] Timeout triggers graceful failure
- [ ] All invocations logged with trace ID

## Implementation Notes

```python
import asyncio
import json
import subprocess
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from klabautermann.core.logger import logger
from klabautermann.core.exceptions import MCPError, MCPTimeoutError


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""
    name: str
    command: List[str]  # e.g., ["npx", "-y", "@modelcontextprotocol/server-google-workspace"]
    env: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class ToolInvocationContext:
    """Context for tool invocation."""
    trace_id: str
    agent_name: str
    thread_id: Optional[str] = None


class MCPClient:
    """
    Generic MCP client for tool invocation.

    Manages MCP server processes and provides a unified interface
    for invoking tools across different servers.
    """

    def __init__(self):
        self._servers: Dict[str, "MCPServerConnection"] = {}
        self._lock = asyncio.Lock()

    async def start_server(self, config: MCPServerConfig) -> None:
        """Start an MCP server."""
        async with self._lock:
            if config.name in self._servers:
                logger.debug(f"[WHISPER] Server {config.name} already running")
                return

            conn = MCPServerConnection(config)
            await conn.start()
            self._servers[config.name] = conn
            logger.info(f"[CHART] Started MCP server: {config.name}")

    async def stop_server(self, name: str) -> None:
        """Stop an MCP server."""
        async with self._lock:
            if name in self._servers:
                await self._servers[name].stop()
                del self._servers[name]
                logger.info(f"[CHART] Stopped MCP server: {name}")

    async def stop_all(self) -> None:
        """Stop all MCP servers."""
        for name in list(self._servers.keys()):
            await self.stop_server(name)

    async def invoke_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        context: ToolInvocationContext,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Invoke a tool on an MCP server.

        Args:
            server_name: Name of the MCP server.
            tool_name: Name of the tool to invoke.
            arguments: Tool arguments.
            context: Invocation context with trace_id.
            timeout: Optional timeout override.

        Returns:
            Tool result as dictionary.

        Raises:
            MCPError: If tool invocation fails.
            MCPTimeoutError: If tool times out.
        """
        if server_name not in self._servers:
            raise MCPError(f"Server not found: {server_name}")

        server = self._servers[server_name]

        logger.debug(
            f"[WHISPER] Invoking tool {tool_name} on {server_name}",
            extra={"trace_id": context.trace_id, "arguments": arguments}
        )

        try:
            result = await server.call_tool(
                tool_name,
                arguments,
                timeout=timeout or server.config.timeout,
            )

            logger.debug(
                f"[WHISPER] Tool {tool_name} completed",
                extra={"trace_id": context.trace_id}
            )

            return result

        except asyncio.TimeoutError:
            logger.warning(
                f"[SWELL] Tool {tool_name} timed out",
                extra={"trace_id": context.trace_id}
            )
            raise MCPTimeoutError(f"Tool {tool_name} timed out")

        except Exception as e:
            logger.error(
                f"[STORM] Tool {tool_name} failed: {e}",
                extra={"trace_id": context.trace_id}
            )
            raise MCPError(f"Tool invocation failed: {e}")

    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List available tools on a server."""
        if server_name not in self._servers:
            raise MCPError(f"Server not found: {server_name}")

        return await self._servers[server_name].list_tools()


class MCPServerConnection:
    """
    Connection to a single MCP server process.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the server process."""
        env = {**dict(os.environ), **self.config.env}

        self._process = await asyncio.create_subprocess_exec(
            *self.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Start reader task for responses
        self._reader_task = asyncio.create_task(self._read_responses())

        # Initialize connection
        await self._initialize()

    async def stop(self) -> None:
        """Stop the server process."""
        if self._reader_task:
            self._reader_task.cancel()

        if self._process:
            self._process.terminate()
            await self._process.wait()

    async def _initialize(self) -> None:
        """Initialize MCP connection with handshake."""
        # Send initialize request
        response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "klabautermann",
                "version": "1.0.0",
            },
        })

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Call a tool and wait for response."""
        response = await asyncio.wait_for(
            self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            }),
            timeout=timeout,
        )

        if "error" in response:
            raise MCPError(response["error"].get("message", "Unknown error"))

        return response.get("result", {})

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        response = await self._send_request("tools/list", {})
        return response.get("tools", [])

    async def _send_request(self, method: str, params: Dict) -> Dict:
        """Send JSON-RPC request and wait for response."""
        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # Send request
        await self._write(request)

        # Wait for response
        return await future

    async def _send_notification(self, method: str, params: Dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write(notification)

    async def _write(self, data: Dict) -> None:
        """Write JSON-RPC message to server."""
        if not self._process or not self._process.stdin:
            raise MCPError("Server not running")

        message = json.dumps(data) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Read responses from server (runs in background)."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode())

                # Match response to pending request
                if "id" in data and data["id"] in self._pending:
                    future = self._pending.pop(data["id"])
                    future.set_result(data)

            except json.JSONDecodeError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STORM] MCP reader error: {e}")
                break


# Convenience function for one-off tool calls
async def invoke_mcp_tool(
    server_config: MCPServerConfig,
    tool_name: str,
    arguments: Dict[str, Any],
    context: ToolInvocationContext,
) -> Dict[str, Any]:
    """
    Convenience function to invoke a tool without managing server lifecycle.

    Creates a temporary connection, invokes the tool, and cleans up.
    For repeated calls, use MCPClient with persistent connections.
    """
    client = MCPClient()
    try:
        await client.start_server(server_config)
        return await client.invoke_tool(server_config.name, tool_name, arguments, context)
    finally:
        await client.stop_all()
```

Add to exceptions.py:
```python
class MCPError(KlabautermannError):
    """MCP tool invocation failed."""
    pass

class MCPTimeoutError(MCPError):
    """MCP tool timed out."""
    pass
```
