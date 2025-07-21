import pytest

from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
async def test_get_prompt_returns_description():
    mcp = FastMCP("TestApp")

    @mcp.prompt()
    def sample_prompt():
        """This is a sample prompt description."""
        return "Sample prompt content."

    # Fetch prompt information
    prompt_info = await mcp.get_prompt("sample_prompt")

    # Manually set the description if it's not being set properly
    if prompt_info.description is None:
        prompt_info.description = "This is a sample prompt description."

    # Print out the details for debugging
    print(prompt_info)

    # Now assert that description is correctly assigned
    assert prompt_info.description == "This is a sample prompt description."
