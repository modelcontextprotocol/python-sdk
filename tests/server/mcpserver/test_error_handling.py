"""Tests for MCPServer raise-based error handling.

Validates that MCPServer handlers support a consistent raise-based error pattern:
- ToolError → CallToolResult(is_error=True) with the user's message
- ResourceError / PromptError → MCPError (JSON-RPC error) with the user's message
- MCPError → re-raised as-is (protocol-level error)
- Unexpected exceptions → sanitized message (no internal detail leakage)
"""

import pytest

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import PromptError, ResourceError, ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, TextContent

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Tool error handling
# ---------------------------------------------------------------------------


class TestToolErrorHandling:
    async def test_tool_error_reaches_client(self) -> None:
        """User raises ToolError → client sees CallToolResult(is_error=True) with exact message."""
        mcp = MCPServer()

        @mcp.tool()
        def fail_tool() -> str:
            raise ToolError("invalid input")

        async with Client(mcp) as client:
            result = await client.call_tool("fail_tool", {})
            assert result.is_error is True
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "invalid input" in content.text

    async def test_unexpected_exception_does_not_leak(self) -> None:
        """Plain exception should NOT leak internal details to client."""
        mcp = MCPServer()

        @mcp.tool()
        def secret_fail() -> str:
            raise RuntimeError("secret database password is hunter2")

        async with Client(mcp) as client:
            result = await client.call_tool("secret_fail", {})
            assert result.is_error is True
            content = result.content[0]
            assert isinstance(content, TextContent)
            # Internal details must not reach the client
            assert "hunter2" not in content.text
            assert "secret_fail" in content.text

    async def test_mcp_error_from_tool_becomes_jsonrpc_error(self) -> None:
        """MCPError raised in a tool → JSON-RPC error (not CallToolResult)."""
        mcp = MCPServer()

        @mcp.tool()
        def protocol_fail() -> str:
            raise MCPError(code=INVALID_PARAMS, message="bad params")

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="bad params"):
                await client.call_tool("protocol_fail", {})


# ---------------------------------------------------------------------------
# Resource error handling
# ---------------------------------------------------------------------------


class TestResourceErrorHandling:
    async def test_resource_error_reaches_client(self) -> None:
        """User raises ResourceError → client sees MCPError with the user's message."""
        mcp = MCPServer()

        @mcp.resource("resource://guarded")
        def guarded_resource() -> str:
            raise ResourceError("access denied")

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="access denied"):
                await client.read_resource("resource://guarded")

    async def test_unexpected_resource_error_does_not_leak(self) -> None:
        """Plain exception from resource should NOT leak internal details."""
        mcp = MCPServer()

        @mcp.resource("resource://broken")
        def broken_resource() -> str:
            raise RuntimeError("secret internal state")

        async with Client(mcp) as client:
            with pytest.raises(MCPError) as exc_info:
                await client.read_resource("resource://broken")
            # Internal details must not reach the client
            assert "secret internal state" not in exc_info.value.message
            assert "resource://broken" in exc_info.value.message

    async def test_unknown_resource_error(self) -> None:
        """Reading a non-existent resource → MCPError."""
        mcp = MCPServer()

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="Unknown resource"):
                await client.read_resource("resource://nonexistent")


# ---------------------------------------------------------------------------
# Prompt error handling
# ---------------------------------------------------------------------------


class TestPromptErrorHandling:
    async def test_prompt_error_reaches_client(self) -> None:
        """User raises PromptError → client sees MCPError with the user's message."""
        mcp = MCPServer()

        @mcp.prompt()
        def bad_prompt() -> str:
            raise PromptError("invalid context")

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="invalid context"):
                await client.get_prompt("bad_prompt")

    async def test_unknown_prompt_error(self) -> None:
        """Getting a non-existent prompt → MCPError."""
        mcp = MCPServer()

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="Unknown prompt"):
                await client.get_prompt("nonexistent")

    async def test_missing_prompt_args_error(self) -> None:
        """Missing required prompt arguments → MCPError."""
        mcp = MCPServer()

        @mcp.prompt()
        def greeting(name: str) -> str:  # pragma: no cover
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="Missing required arguments"):
                await client.get_prompt("greeting")
