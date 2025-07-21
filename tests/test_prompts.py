
import pytest
from mcp.server.fastmcp import FastMCP

@pytest.mark.asyncio
async def test_get_prompt_returns_description():
    mcp = FastMCP("TestApp")

    @mcp.prompt()
    def sample_prompt():
        """This is a sample prompt description."""
        return "Sample prompt content."

    prompt_info = await mcp.get_prompt("sample_prompt")
    assert prompt_info["description"] == "This is a sample prompt description."
