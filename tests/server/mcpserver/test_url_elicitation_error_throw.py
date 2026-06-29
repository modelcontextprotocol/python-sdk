import mcp_types as types
import pytest
from inline_snapshot import snapshot

from mcp import Client, ErrorData
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError, UrlElicitationRequiredError


@pytest.mark.anyio
async def test_url_elicitation_error_thrown_from_tool():
    mcp = MCPServer(name="UrlElicitationErrorServer")

    @mcp.tool(description="A tool that raises UrlElicitationRequiredError")
    async def connect_service(service_name: str, ctx: Context) -> str:
        raise UrlElicitationRequiredError(
            [
                types.ElicitRequestURLParams(
                    mode="url",
                    message=f"Authorization required to connect to {service_name}",
                    url=f"https://{service_name}.example.com/oauth/authorize",
                    elicitation_id=f"{service_name}-auth-001",
                )
            ]
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("connect_service", {"service_name": "github"})

        assert exc_info.value.error == snapshot(
            ErrorData(
                code=types.URL_ELICITATION_REQUIRED,
                message="URL elicitation required",
                data={
                    "elicitations": [
                        {
                            "mode": "url",
                            "message": "Authorization required to connect to github",
                            "url": "https://github.example.com/oauth/authorize",
                            "elicitationId": "github-auth-001",
                        }
                    ]
                },
            )
        )


@pytest.mark.anyio
async def test_url_elicitation_error_from_error():
    mcp = MCPServer(name="UrlElicitationErrorServer")

    @mcp.tool(description="A tool that raises UrlElicitationRequiredError with multiple elicitations")
    async def multi_auth(ctx: Context) -> str:
        raise UrlElicitationRequiredError(
            [
                types.ElicitRequestURLParams(
                    mode="url",
                    message="GitHub authorization required",
                    url="https://github.example.com/oauth",
                    elicitation_id="github-auth",
                ),
                types.ElicitRequestURLParams(
                    mode="url",
                    message="Google Drive authorization required",
                    url="https://drive.google.com/oauth",
                    elicitation_id="gdrive-auth",
                ),
            ]
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("multi_auth", {})

        mcp_error = exc_info.value
        assert mcp_error.code == types.URL_ELICITATION_REQUIRED

        url_error = UrlElicitationRequiredError.from_error(mcp_error.error)

        assert len(url_error.elicitations) == 2
        assert url_error.elicitations[0].elicitation_id == "github-auth"
        assert url_error.elicitations[1].elicitation_id == "gdrive-auth"


@pytest.mark.anyio
async def test_normal_exceptions_still_return_error_result():
    mcp = MCPServer(name="NormalErrorServer")

    @mcp.tool(description="A tool that raises a normal exception")
    async def failing_tool(ctx: Context) -> str:
        raise ValueError("Something went wrong")

    async with Client(mcp) as client:
        result = await client.call_tool("failing_tool", {})
        assert result.is_error is True
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        assert "Something went wrong" in result.content[0].text
