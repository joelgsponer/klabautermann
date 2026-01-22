"""
Filesystem Bridge - MCP server integration for local file operations.

Wraps the @modelcontextprotocol/server-filesystem MCP server to provide
secure, sandboxed file operations within configured allowed paths.

Reference: specs/architecture/MCP.md Section 3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from klabautermann.core.exceptions import MCPError
from klabautermann.core.logger import logger
from klabautermann.mcp.client import MCPClient, MCPServerConfig, ToolInvocationContext


# ===========================================================================
# Configuration
# ===========================================================================


@dataclass
class FilesystemConfig:
    """
    Configuration for filesystem MCP server.

    Attributes:
        allowed_paths: List of directories the server can access.
                      Files outside these paths will be rejected.
        timeout: Timeout for filesystem operations in seconds.
    """

    allowed_paths: list[str] = field(default_factory=list)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate and resolve allowed paths."""
        if not self.allowed_paths:
            # Default to current working directory
            self.allowed_paths = [str(Path.cwd())]

        # Resolve all paths to absolute
        self.allowed_paths = [str(Path(p).resolve()) for p in self.allowed_paths]


# ===========================================================================
# Filesystem Bridge
# ===========================================================================


class FilesystemBridge:
    """
    Bridge to filesystem operations via MCP server.

    Provides sandboxed file read/write operations through the
    @modelcontextprotocol/server-filesystem MCP server.

    Example:
        config = FilesystemConfig(allowed_paths=["/app/data", "/app/attachments"])
        bridge = FilesystemBridge(config)
        await bridge.start()

        # Read a file
        content = await bridge.read_file("/app/data/notes.txt", context)

        # Write a file
        await bridge.write_file("/app/attachments/report.pdf", data, context)

        await bridge.stop()

    Security:
        - Only paths within allowed_paths can be accessed
        - Attempts to escape via symlinks or .. are blocked by the MCP server
    """

    SERVER_NAME = "filesystem"

    def __init__(self, config: FilesystemConfig | None = None) -> None:
        """
        Initialize the filesystem bridge.

        Args:
            config: Filesystem configuration. If None, uses defaults.
        """
        self.config = config or FilesystemConfig()
        self._client = MCPClient()
        self._started = False

    async def start(self) -> None:
        """
        Start the filesystem MCP server.

        Raises:
            MCPError: If server fails to start.
        """
        if self._started:
            return

        # Build MCP server config
        # The filesystem server expects allowed directories as arguments
        command = [
            "npx",
            "-y",
            "@modelcontextprotocol/server-filesystem",
            *self.config.allowed_paths,
        ]

        server_config = MCPServerConfig(
            name=self.SERVER_NAME,
            command=command,
            timeout=self.config.timeout,
        )

        await self._client.start_server(server_config)
        self._started = True

        logger.info(
            "[CHART] Filesystem MCP server started",
            extra={"allowed_paths": self.config.allowed_paths},
        )

    async def stop(self) -> None:
        """Stop the filesystem MCP server."""
        if self._started:
            await self._client.stop_all()
            self._started = False
            logger.info("[CHART] Filesystem MCP server stopped")

    async def read_file(
        self,
        path: str,
        context: ToolInvocationContext,
    ) -> str:
        """
        Read a text file's contents.

        Args:
            path: Absolute path to the file (must be within allowed_paths)
            context: Invocation context with trace_id

        Returns:
            File contents as string

        Raises:
            MCPError: If read fails or path is not allowed
        """
        await self.start()

        result = await self._client.invoke_tool(
            self.SERVER_NAME,
            "read_file",
            {"path": path},
            context,
        )

        # MCP server returns content in result
        content: str = result.get("content", [{}])[0].get("text", "")

        logger.debug(
            f"[WHISPER] File read: {path}",
            extra={"trace_id": context.trace_id, "size": len(content)},
        )

        return content

    async def read_file_bytes(
        self,
        path: str,
        context: ToolInvocationContext,
    ) -> bytes:
        """
        Read a binary file's contents.

        Args:
            path: Absolute path to the file (must be within allowed_paths)
            context: Invocation context with trace_id

        Returns:
            File contents as bytes

        Raises:
            MCPError: If read fails or path is not allowed
        """
        # For binary files, we read directly since MCP server may not handle binary well
        await self.start()

        # Validate path is within allowed paths
        resolved_path = str(Path(path).resolve())
        if not any(resolved_path.startswith(ap) for ap in self.config.allowed_paths):
            raise MCPError(
                f"Path not allowed: {path}",
                trace_id=context.trace_id,
            )

        try:
            data = Path(path).read_bytes()

            logger.debug(
                f"[WHISPER] Binary file read: {path}",
                extra={"trace_id": context.trace_id, "size": len(data)},
            )

            return data
        except OSError as e:
            raise MCPError(
                f"Failed to read file: {e}",
                trace_id=context.trace_id,
            ) from e

    async def write_file(
        self,
        path: str,
        content: str,
        context: ToolInvocationContext,
    ) -> None:
        """
        Write text content to a file.

        Args:
            path: Absolute path to the file (must be within allowed_paths)
            content: Text content to write
            context: Invocation context with trace_id

        Raises:
            MCPError: If write fails or path is not allowed
        """
        await self.start()

        await self._client.invoke_tool(
            self.SERVER_NAME,
            "write_file",
            {"path": path, "content": content},
            context,
        )

        logger.info(
            f"[BEACON] File written: {path}",
            extra={"trace_id": context.trace_id, "size": len(content)},
        )

    async def write_file_bytes(
        self,
        path: str,
        data: bytes,
        context: ToolInvocationContext,
    ) -> None:
        """
        Write binary data to a file.

        Args:
            path: Absolute path to the file (must be within allowed_paths)
            data: Binary data to write
            context: Invocation context with trace_id

        Raises:
            MCPError: If write fails or path is not allowed
        """
        await self.start()

        # Validate path is within allowed paths
        resolved_path = str(Path(path).resolve())
        if not any(resolved_path.startswith(ap) for ap in self.config.allowed_paths):
            raise MCPError(
                f"Path not allowed: {path}",
                trace_id=context.trace_id,
            )

        try:
            # Ensure directory exists
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_path.write_bytes(data)

            logger.info(
                f"[BEACON] Binary file written: {path}",
                extra={"trace_id": context.trace_id, "size": len(data)},
            )
        except OSError as e:
            raise MCPError(
                f"Failed to write file: {e}",
                trace_id=context.trace_id,
            ) from e

    async def list_directory(
        self,
        path: str,
        context: ToolInvocationContext,
    ) -> list[dict[str, Any]]:
        """
        List contents of a directory.

        Args:
            path: Absolute path to the directory (must be within allowed_paths)
            context: Invocation context with trace_id

        Returns:
            List of entries with name, type (file/directory), and size

        Raises:
            MCPError: If listing fails or path is not allowed
        """
        await self.start()

        result = await self._client.invoke_tool(
            self.SERVER_NAME,
            "list_directory",
            {"path": path},
            context,
        )

        # Parse result - MCP server returns entries in content
        entries: list[dict[str, Any]] = []
        content = result.get("content", [])
        if content and isinstance(content[0].get("text"), str):
            # Parse text listing into structured data
            for line in content[0]["text"].strip().split("\n"):
                if line:
                    # Format: [DIR] name or [FILE] name (size)
                    if line.startswith("[DIR]"):
                        name = line[6:].strip()
                        entries.append({"name": name, "type": "directory", "size": 0})
                    elif line.startswith("[FILE]"):
                        # Extract name and optional size
                        parts = line[7:].strip()
                        name = parts.split(" (")[0] if " (" in parts else parts
                        entries.append({"name": name, "type": "file", "size": 0})

        logger.debug(
            f"[WHISPER] Directory listed: {path}",
            extra={"trace_id": context.trace_id, "entries": len(entries)},
        )

        return entries

    async def create_directory(
        self,
        path: str,
        context: ToolInvocationContext,
    ) -> None:
        """
        Create a directory (including parent directories).

        Args:
            path: Absolute path for the new directory (must be within allowed_paths)
            context: Invocation context with trace_id

        Raises:
            MCPError: If creation fails or path is not allowed
        """
        await self.start()

        await self._client.invoke_tool(
            self.SERVER_NAME,
            "create_directory",
            {"path": path},
            context,
        )

        logger.info(
            f"[BEACON] Directory created: {path}",
            extra={"trace_id": context.trace_id},
        )

    async def move_file(
        self,
        source: str,
        destination: str,
        context: ToolInvocationContext,
    ) -> None:
        """
        Move or rename a file.

        Args:
            source: Source file path (must be within allowed_paths)
            destination: Destination path (must be within allowed_paths)
            context: Invocation context with trace_id

        Raises:
            MCPError: If move fails or paths are not allowed
        """
        await self.start()

        await self._client.invoke_tool(
            self.SERVER_NAME,
            "move_file",
            {"source": source, "destination": destination},
            context,
        )

        logger.info(
            f"[BEACON] File moved: {source} -> {destination}",
            extra={"trace_id": context.trace_id},
        )

    async def get_file_info(
        self,
        path: str,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        """
        Get file metadata (size, modified time, etc.).

        Args:
            path: Absolute path to the file (must be within allowed_paths)
            context: Invocation context with trace_id

        Returns:
            Dict with file metadata (size, modified, created, is_file, is_directory)

        Raises:
            MCPError: If path is not allowed or doesn't exist
        """
        await self.start()

        result = await self._client.invoke_tool(
            self.SERVER_NAME,
            "get_file_info",
            {"path": path},
            context,
        )

        # Parse result
        info: dict[str, Any] = {}
        content = result.get("content", [])
        if content and isinstance(content[0].get("text"), str):
            # Parse the text response into structured data
            text = content[0]["text"]
            for line in text.strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    info[key.strip().lower().replace(" ", "_")] = value.strip()

        logger.debug(
            f"[WHISPER] File info: {path}",
            extra={"trace_id": context.trace_id},
        )

        return info


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "FilesystemBridge",
    "FilesystemConfig",
]
