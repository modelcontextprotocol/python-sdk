"""Prove the two error channels: is_error results return; MCPError raises."""

from mcp_types import INVALID_PARAMS, TextContent

from mcp import MCPError
from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        # Success: is_error defaults to False.
        ok = await client.call_tool("divide", {"a": 6, "b": 2})
        assert ok.is_error is False, ok
        assert isinstance(ok.content[0], TextContent)
        assert ok.content[0].text == "3.0"

        # Execution error: arrives as a *result* — await returns, no exception.
        failed = await client.call_tool("divide", {"a": 1, "b": 0})
        assert failed.is_error is True, "execution errors ride CallToolResult, not an exception"
        assert isinstance(failed.content[0], TextContent)
        # MCPServer prefixes "Error executing tool divide: ..."; lowlevel returns
        # the message verbatim. Assert the substring both produce.
        assert "cannot divide by zero" in failed.content[0].text

        # Protocol error: arrives as a raised MCPError.
        try:
            await client.call_tool("restricted", {})
        except MCPError as e:
            assert e.code == INVALID_PARAMS
            assert e.message == "this tool is gated"
            assert e.data == {"reason": "demo"}
        else:
            raise AssertionError("expected MCPError for a protocol-level rejection")


if __name__ == "__main__":
    run_client(main)
