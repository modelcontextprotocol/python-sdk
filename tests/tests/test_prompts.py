def test_get_prompt_returns_description():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("TestApp")

    @mcp.prompt()
    def sample_prompt():
        """This is a sample prompt description."""
        return "Sample prompt content."

    prompt_info = mcp.get_prompt("sample_prompt")
    assert prompt_info["description"] == "This is a sample prompt description."
    assert callable(prompt_info["function"])
