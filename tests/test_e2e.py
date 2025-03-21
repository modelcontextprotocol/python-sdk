from collections.abc import AsyncGenerator

import pytest

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.server import FastMCP

params = StdioServerParameters(command="uv", args=["run", __file__])


def server() -> FastMCP:
    mcp = FastMCP("Echo")

    @mcp.resource("echo://{message}")
    def echo_resource(message: str) -> str:
        """Echo a message as a resource"""
        return f"Resource echo: {message}"

    @mcp.tool()
    def echo_tool(message: str) -> str:
        """Echo a message as a tool"""
        return f"Tool echo: {message}"

    @mcp.prompt()
    def echo_prompt(message: str) -> str:
        """Create an echo prompt"""
        return f"Please process this message: {message}"

    return mcp


@pytest.fixture
async def mcp_client_session() -> AsyncGenerator[ClientSession, None]:
    async with stdio_client(params) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


@pytest.mark.anyio
async def test_list_resource_templates(mcp_client_session: ClientSession) -> None:
    res = await mcp_client_session.list_resource_templates()
    templates = set(template.name for template in res.resourceTemplates)

    assert "echo_resource" in templates


@pytest.mark.anyio
async def test_list_tools(mcp_client_session: ClientSession) -> None:
    res = await mcp_client_session.list_tools()
    tools = set(tool.name for tool in res.tools)

    assert "echo_tool" in tools


@pytest.mark.anyio
async def test_list_prompts(mcp_client_session: ClientSession) -> None:
    res = await mcp_client_session.list_prompts()
    prompts = set(prompt.name for prompt in res.prompts)

    assert "echo_prompt" in prompts


if __name__ == "__main__":
    server().run()
