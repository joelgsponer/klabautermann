"""
Unit tests for Filesystem Bridge.

Tests the MCP-based filesystem operations using mocking.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.core.exceptions import MCPError
from klabautermann.mcp.client import ToolInvocationContext
from klabautermann.mcp.filesystem import FilesystemBridge, FilesystemConfig


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def context():
    """Create a test invocation context."""
    return ToolInvocationContext(
        trace_id="test-trace-123",
        agent_name="test-agent",
        thread_id="thread-456",
    )


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client."""
    with patch("klabautermann.mcp.filesystem.MCPClient") as mock_class:
        mock_client = MagicMock()
        mock_client.start_server = AsyncMock()
        mock_client.stop_all = AsyncMock()
        mock_client.invoke_tool = AsyncMock()
        mock_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def bridge(mock_mcp_client):
    """Create a FilesystemBridge with mock client."""
    config = FilesystemConfig(allowed_paths=["/app/data", "/app/attachments"])
    return FilesystemBridge(config)


# ===========================================================================
# Configuration Tests
# ===========================================================================


class TestFilesystemConfig:
    """Test FilesystemConfig initialization."""

    def test_default_config(self):
        """Test default configuration uses current directory."""
        config = FilesystemConfig()
        assert len(config.allowed_paths) == 1
        assert config.allowed_paths[0] == str(Path.cwd().resolve())

    def test_custom_allowed_paths(self):
        """Test custom allowed paths are resolved to absolute."""
        config = FilesystemConfig(allowed_paths=["/tmp", "/home/user"])
        assert "/tmp" in config.allowed_paths
        assert "/home/user" in config.allowed_paths

    def test_relative_paths_resolved(self, tmp_path):
        """Test relative paths are converted to absolute."""
        config = FilesystemConfig(allowed_paths=["./data"])
        # All paths should be absolute
        for path in config.allowed_paths:
            assert Path(path).is_absolute()

    def test_timeout_default(self):
        """Test default timeout value."""
        config = FilesystemConfig()
        assert config.timeout == 30.0

    def test_custom_timeout(self):
        """Test custom timeout configuration."""
        config = FilesystemConfig(timeout=60.0)
        assert config.timeout == 60.0


# ===========================================================================
# Lifecycle Tests
# ===========================================================================


class TestFilesystemBridgeLifecycle:
    """Test bridge initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_server(self, bridge, mock_mcp_client):
        """Test starting creates MCP server with correct config."""
        await bridge.start()

        mock_mcp_client.start_server.assert_called_once()
        config = mock_mcp_client.start_server.call_args[0][0]
        assert config.name == "filesystem"
        assert "npx" in config.command
        assert "@modelcontextprotocol/server-filesystem" in config.command
        assert "/app/data" in config.command
        assert "/app/attachments" in config.command

    @pytest.mark.asyncio
    async def test_start_idempotent(self, bridge, mock_mcp_client):
        """Test starting multiple times is safe."""
        await bridge.start()
        await bridge.start()

        assert mock_mcp_client.start_server.call_count == 1

    @pytest.mark.asyncio
    async def test_stop_stops_server(self, bridge, mock_mcp_client):
        """Test stopping stops the MCP server."""
        await bridge.start()
        await bridge.stop()

        mock_mcp_client.stop_all.assert_called_once()
        assert bridge._started is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self, bridge, mock_mcp_client):
        """Test stopping without starting is safe."""
        await bridge.stop()

        mock_mcp_client.stop_all.assert_not_called()


# ===========================================================================
# Read Operations Tests
# ===========================================================================


class TestReadOperations:
    """Test file read operations."""

    @pytest.mark.asyncio
    async def test_read_file_success(self, bridge, mock_mcp_client, context):
        """Test successful file read."""
        mock_mcp_client.invoke_tool.return_value = {"content": [{"text": "Hello, World!"}]}

        content = await bridge.read_file("/app/data/test.txt", context)

        assert content == "Hello, World!"
        mock_mcp_client.invoke_tool.assert_called_once_with(
            "filesystem",
            "read_file",
            {"path": "/app/data/test.txt"},
            context,
        )

    @pytest.mark.asyncio
    async def test_read_file_auto_starts(self, bridge, mock_mcp_client, context):
        """Test read_file auto-starts the server."""
        mock_mcp_client.invoke_tool.return_value = {"content": [{"text": "content"}]}

        await bridge.read_file("/app/data/test.txt", context)

        mock_mcp_client.start_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_file_bytes_validates_path(self, bridge, mock_mcp_client, context):
        """Test read_file_bytes validates path against allowed paths."""
        with pytest.raises(MCPError, match="Path not allowed"):
            await bridge.read_file_bytes("/etc/passwd", context)

    @pytest.mark.asyncio
    async def test_read_file_bytes_success(self, bridge, mock_mcp_client, context, tmp_path):
        """Test successful binary file read."""
        # Create a test file
        test_file = tmp_path / "data" / "test.bin"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_bytes(b"\x00\x01\x02\x03")

        # Configure bridge with tmp_path
        bridge.config.allowed_paths = [str(tmp_path)]

        data = await bridge.read_file_bytes(str(test_file), context)

        assert data == b"\x00\x01\x02\x03"


# ===========================================================================
# Write Operations Tests
# ===========================================================================


class TestWriteOperations:
    """Test file write operations."""

    @pytest.mark.asyncio
    async def test_write_file_success(self, bridge, mock_mcp_client, context):
        """Test successful file write."""
        mock_mcp_client.invoke_tool.return_value = {}

        await bridge.write_file("/app/data/output.txt", "test content", context)

        mock_mcp_client.invoke_tool.assert_called_once_with(
            "filesystem",
            "write_file",
            {"path": "/app/data/output.txt", "content": "test content"},
            context,
        )

    @pytest.mark.asyncio
    async def test_write_file_bytes_validates_path(self, bridge, mock_mcp_client, context):
        """Test write_file_bytes validates path against allowed paths."""
        with pytest.raises(MCPError, match="Path not allowed"):
            await bridge.write_file_bytes("/etc/passwd", b"data", context)

    @pytest.mark.asyncio
    async def test_write_file_bytes_success(self, bridge, mock_mcp_client, context, tmp_path):
        """Test successful binary file write."""
        # Configure bridge with tmp_path
        bridge.config.allowed_paths = [str(tmp_path)]

        test_file = tmp_path / "output.bin"
        await bridge.write_file_bytes(str(test_file), b"\x00\x01\x02\x03", context)

        assert test_file.read_bytes() == b"\x00\x01\x02\x03"

    @pytest.mark.asyncio
    async def test_write_file_bytes_creates_directories(
        self, bridge, mock_mcp_client, context, tmp_path
    ):
        """Test write_file_bytes creates parent directories."""
        bridge.config.allowed_paths = [str(tmp_path)]

        test_file = tmp_path / "nested" / "dirs" / "output.bin"
        await bridge.write_file_bytes(str(test_file), b"data", context)

        assert test_file.exists()
        assert test_file.read_bytes() == b"data"


# ===========================================================================
# Directory Operations Tests
# ===========================================================================


class TestDirectoryOperations:
    """Test directory operations."""

    @pytest.mark.asyncio
    async def test_list_directory(self, bridge, mock_mcp_client, context):
        """Test listing directory contents."""
        mock_mcp_client.invoke_tool.return_value = {
            "content": [{"text": "[DIR] subdir\n[FILE] file.txt"}]
        }

        entries = await bridge.list_directory("/app/data", context)

        assert len(entries) == 2
        assert entries[0]["name"] == "subdir"
        assert entries[0]["type"] == "directory"
        assert entries[1]["name"] == "file.txt"
        assert entries[1]["type"] == "file"

    @pytest.mark.asyncio
    async def test_create_directory(self, bridge, mock_mcp_client, context):
        """Test creating a directory."""
        mock_mcp_client.invoke_tool.return_value = {}

        await bridge.create_directory("/app/data/new_folder", context)

        mock_mcp_client.invoke_tool.assert_called_once_with(
            "filesystem",
            "create_directory",
            {"path": "/app/data/new_folder"},
            context,
        )


# ===========================================================================
# File Operations Tests
# ===========================================================================


class TestFileOperations:
    """Test file manipulation operations."""

    @pytest.mark.asyncio
    async def test_move_file(self, bridge, mock_mcp_client, context):
        """Test moving a file."""
        mock_mcp_client.invoke_tool.return_value = {}

        await bridge.move_file("/app/data/old.txt", "/app/data/new.txt", context)

        mock_mcp_client.invoke_tool.assert_called_once_with(
            "filesystem",
            "move_file",
            {"source": "/app/data/old.txt", "destination": "/app/data/new.txt"},
            context,
        )

    @pytest.mark.asyncio
    async def test_get_file_info(self, bridge, mock_mcp_client, context):
        """Test getting file metadata."""
        mock_mcp_client.invoke_tool.return_value = {
            "content": [{"text": "size: 1024\nmodified: 2024-01-15T10:00:00"}]
        }

        info = await bridge.get_file_info("/app/data/test.txt", context)

        assert "size" in info
        assert "modified" in info
        mock_mcp_client.invoke_tool.assert_called_once_with(
            "filesystem",
            "get_file_info",
            {"path": "/app/data/test.txt"},
            context,
        )


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_read_file_propagates_mcp_error(self, bridge, mock_mcp_client, context):
        """Test that MCP errors are propagated."""
        mock_mcp_client.invoke_tool.side_effect = MCPError("File not found")

        with pytest.raises(MCPError, match="File not found"):
            await bridge.read_file("/app/data/missing.txt", context)

    @pytest.mark.asyncio
    async def test_write_file_bytes_handles_os_error(
        self, bridge, mock_mcp_client, context, tmp_path
    ):
        """Test that OS errors during binary write are handled."""
        bridge.config.allowed_paths = [str(tmp_path)]

        # Try to write to a directory path (should fail)
        with pytest.raises(MCPError, match="Failed to write file"):
            await bridge.write_file_bytes(str(tmp_path), b"data", context)
