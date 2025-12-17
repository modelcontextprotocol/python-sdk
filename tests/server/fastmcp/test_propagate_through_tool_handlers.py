"""Test that propagate_through_tool_handlers attribute correctly bypasses error wrapping."""

import pytest

from mcp import types
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.tools.tool_manager import ToolManager
from mcp.shared.exceptions import McpError, UrlElicitationRequiredError


class TestPropagateThroughToolHandlers:
    """Test the propagate_through_tool_handlers attribute behavior."""

    @pytest.mark.anyio
    async def test_url_elicitation_required_error_propagates(self):
        """Test that UrlElicitationRequiredError propagates through Tool.run() without wrapping."""

        # Create a tool that raises UrlElicitationRequiredError
        async def auth_required_tool() -> str:
            raise UrlElicitationRequiredError(
                [
                    types.ElicitRequestURLParams(
                        mode="url",
                        message="Authorization required",
                        url="https://example.com/auth",
                        elicitationId="auth-001",
                    )
                ]
            )

        tool = Tool.from_function(auth_required_tool)

        # The exception should propagate, not be wrapped as ToolError
        with pytest.raises(UrlElicitationRequiredError) as exc_info:
            await tool.run({})

        # Verify it's the actual exception, not wrapped
        assert isinstance(exc_info.value, UrlElicitationRequiredError)
        assert exc_info.value.propagate_through_tool_handlers is True
        assert exc_info.value.error.code == types.URL_ELICITATION_REQUIRED

    @pytest.mark.anyio
    async def test_custom_mcp_error_without_attribute_is_wrapped(self):
        """Test that a custom McpError without propagate_through_tool_handlers is wrapped."""

        # Create a custom McpError that doesn't propagate
        class CustomMcpError(McpError):
            propagate_through_tool_handlers = False  # Default, but explicit for clarity

            def __init__(self):
                error = types.ErrorData(code=-32000, message="Custom error")
                super().__init__(error)

        async def tool_that_raises_custom_error() -> str:
            raise CustomMcpError()

        tool = Tool.from_function(tool_that_raises_custom_error)

        # The exception should be wrapped as ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.run({})

        # Verify it's wrapped
        assert "Custom error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, CustomMcpError)

    @pytest.mark.anyio
    async def test_custom_mcp_error_with_attribute_propagates(self):
        """Test that a custom McpError with propagate_through_tool_handlers=True propagates."""

        # Create a custom McpError that does propagate
        class PropagatingMcpError(McpError):
            propagate_through_tool_handlers = True

            def __init__(self):
                error = types.ErrorData(code=-32001, message="Propagating error")
                super().__init__(error)

        async def tool_that_raises_propagating_error() -> str:
            raise PropagatingMcpError()

        tool = Tool.from_function(tool_that_raises_propagating_error)

        # The exception should propagate, not be wrapped
        with pytest.raises(PropagatingMcpError) as exc_info:
            await tool.run({})

        # Verify it's not wrapped
        assert isinstance(exc_info.value, PropagatingMcpError)
        assert exc_info.value.propagate_through_tool_handlers is True

    @pytest.mark.anyio
    async def test_normal_exception_still_wrapped(self):
        """Test that normal exceptions (non-McpError) are still wrapped as ToolError."""

        async def tool_that_raises_value_error() -> str:
            raise ValueError("Something went wrong")

        tool = Tool.from_function(tool_that_raises_value_error)

        # Normal exceptions should be wrapped as ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.run({})

        assert "Something went wrong" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, ValueError)

    @pytest.mark.anyio
    async def test_propagates_through_tool_manager(self):
        """Test that propagation works through ToolManager.call_tool()."""

        async def auth_tool() -> str:
            raise UrlElicitationRequiredError(
                [
                    types.ElicitRequestURLParams(
                        mode="url",
                        message="Auth required",
                        url="https://example.com/auth",
                        elicitationId="test-auth",
                    )
                ]
            )

        manager = ToolManager()
        manager.add_tool(auth_tool)

        # Exception should propagate through ToolManager as well
        with pytest.raises(UrlElicitationRequiredError) as exc_info:
            await manager.call_tool("auth_tool", {})

        assert exc_info.value.error.code == types.URL_ELICITATION_REQUIRED


@pytest.mark.anyio
async def test_integration_url_elicitation_propagates_to_jsonrpc():
    """Integration test: Verify UrlElicitationRequiredError becomes JSON-RPC error response."""
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession
    from mcp.shared.memory import create_connected_server_and_client_session

    mcp = FastMCP(name="TestServer")

    @mcp.tool(description="Tool that requires authentication")
    async def secure_tool(ctx: Context[ServerSession, None]) -> str:
        raise UrlElicitationRequiredError(
            [
                types.ElicitRequestURLParams(
                    mode="url",
                    message="Authentication required",
                    url="https://example.com/oauth",
                    elicitationId="oauth-001",
                )
            ]
        )

    async with create_connected_server_and_client_session(mcp._mcp_server) as client_session:
        await client_session.initialize()

        # Should raise McpError with URL_ELICITATION_REQUIRED code
        with pytest.raises(McpError) as exc_info:
            await client_session.call_tool("secure_tool", {})

        # Verify it's a JSON-RPC error response, not a wrapped tool error
        error = exc_info.value.error
        assert error.code == types.URL_ELICITATION_REQUIRED
        assert error.message == "URL elicitation required"
        assert error.data is not None
        assert "elicitations" in error.data
