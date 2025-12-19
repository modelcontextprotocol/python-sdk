"""Test that UrlElicitationRequiredError is properly propagated as MCP error."""

import pytest

from mcp import types
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError, UrlElicitationRequiredError
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.mark.anyio
async def test_url_elicitation_error_thrown_from_tool():
    """Test that UrlElicitationRequiredError raised from a tool is received as McpError by client."""
    mcp = FastMCP(name="UrlElicitationErrorServer")

    @mcp.tool(description="A tool that raises UrlElicitationRequiredError")
    async def connect_service(service_name: str, ctx: Context[ServerSession, None]) -> str:
        # This tool cannot proceed without authorization
        raise UrlElicitationRequiredError(
            [
                types.ElicitRequestURLParams(
                    mode="url",
                    message=f"Authorization required to connect to {service_name}",
                    url=f"https://{service_name}.example.com/oauth/authorize",
                    elicitationId=f"{service_name}-auth-001",
                )
            ]
        )

    async with create_connected_server_and_client_session(mcp._mcp_server) as client_session:
        await client_session.initialize()

        # Call the tool - it should raise McpError with URL_ELICITATION_REQUIRED code
        with pytest.raises(McpError) as exc_info:
            await client_session.call_tool("connect_service", {"service_name": "github"})

        # Verify the error details
        error = exc_info.value.error
        assert error.code == types.URL_ELICITATION_REQUIRED
        assert error.message == "URL elicitation required"

        # Verify the error data contains elicitations
        assert error.data is not None
        assert "elicitations" in error.data
        elicitations = error.data["elicitations"]
        assert len(elicitations) == 1
        assert elicitations[0]["mode"] == "url"
        assert elicitations[0]["url"] == "https://github.example.com/oauth/authorize"
        assert elicitations[0]["elicitationId"] == "github-auth-001"


@pytest.mark.anyio
async def test_url_elicitation_error_from_error():
    """Test that client can reconstruct UrlElicitationRequiredError from McpError."""
    mcp = FastMCP(name="UrlElicitationErrorServer")

    @mcp.tool(description="A tool that raises UrlElicitationRequiredError with multiple elicitations")
    async def multi_auth(ctx: Context[ServerSession, None]) -> str:
        raise UrlElicitationRequiredError(
            [
                types.ElicitRequestURLParams(
                    mode="url",
                    message="GitHub authorization required",
                    url="https://github.example.com/oauth",
                    elicitationId="github-auth",
                ),
                types.ElicitRequestURLParams(
                    mode="url",
                    message="Google Drive authorization required",
                    url="https://drive.google.com/oauth",
                    elicitationId="gdrive-auth",
                ),
            ]
        )

    async with create_connected_server_and_client_session(mcp._mcp_server) as client_session:
        await client_session.initialize()

        # Call the tool and catch the error
        with pytest.raises(McpError) as exc_info:
            await client_session.call_tool("multi_auth", {})

        # Reconstruct the typed error
        mcp_error = exc_info.value
        assert mcp_error.error.code == types.URL_ELICITATION_REQUIRED

        url_error = UrlElicitationRequiredError.from_error(mcp_error.error)

        # Verify the reconstructed error has both elicitations
        assert len(url_error.elicitations) == 2
        assert url_error.elicitations[0].elicitationId == "github-auth"
        assert url_error.elicitations[1].elicitationId == "gdrive-auth"


@pytest.mark.anyio
async def test_normal_exceptions_still_return_error_result():
    """Test that normal exceptions still return CallToolResult with isError=True."""
    mcp = FastMCP(name="NormalErrorServer")

    @mcp.tool(description="A tool that raises a normal exception")
    async def failing_tool(ctx: Context[ServerSession, None]) -> str:
        raise ValueError("Something went wrong")

    async with create_connected_server_and_client_session(mcp._mcp_server) as client_session:
        await client_session.initialize()

        # Normal exceptions should be returned as error results, not McpError
        result = await client_session.call_tool("failing_tool", {})
        assert result.isError is True
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        assert "Something went wrong" in result.content[0].text
