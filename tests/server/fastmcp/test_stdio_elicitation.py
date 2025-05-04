"""
Test the elicitation feature using stdio transport.
"""

import pytest

from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitResult, TextContent


@pytest.mark.anyio
async def test_stdio_elicitation():
    """Test the elicitation feature using stdio transport."""

    # Create a FastMCP server with a tool that uses elicitation
    mcp = FastMCP(name="StdioElicitationServer")

    @mcp.tool(description="A tool that uses elicitation")
    async def ask_user(prompt: str, ctx: Context) -> str:
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
            },
            "required": ["answer"],
        }

        response = await ctx.elicit(
            message=f"Tool wants to ask: {prompt}",
            requestedSchema=schema,
        )
        return f"User answered: {response['answer']}"

    # Create a custom handler for elicitation requests
    async def elicitation_callback(context, params):
        # Verify the elicitation parameters
        if params.message == "Tool wants to ask: What is your name?":
            return ElicitResult(response={"answer": "Test User"})
        else:
            raise ValueError(f"Unexpected elicitation message: {params.message}")

    # Use memory-based session to test with stdio transport
    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        # First initialize the session
        result = await client_session.initialize()
        assert result.serverInfo.name == "StdioElicitationServer"

        # Call the tool that uses elicitation
        tool_result = await client_session.call_tool(
            "ask_user", {"prompt": "What is your name?"}
        )

        # Verify the result
        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        assert tool_result.content[0].text == "User answered: Test User"
