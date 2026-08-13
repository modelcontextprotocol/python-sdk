"""Tests for context parameter discovery and injection."""

from mcp_types import TextContent, TextResourceContents

from mcp.client.client import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter


def test_context_parameter_is_found_by_its_annotation() -> None:
    """SDK-defined: a parameter annotated with `Context` is the one context is injected into."""

    def fn(value: int, ctx: Context) -> str:
        raise NotImplementedError

    assert find_context_parameter(fn) == "ctx"


def test_context_return_annotation_is_not_reported_as_a_parameter() -> None:
    """SDK-defined: a `Context` return annotation is not a parameter, so nothing is injected."""

    def fn(value: int) -> Context:
        raise NotImplementedError

    assert find_context_parameter(fn) is None


def test_context_in_a_union_return_annotation_is_not_reported_as_a_parameter() -> None:
    """SDK-defined: a union return annotation mentioning `Context` is still not a parameter."""

    def fn(value: int) -> Context | None:
        raise NotImplementedError

    assert find_context_parameter(fn) is None


def test_context_parameter_wins_over_a_context_return_annotation() -> None:
    """SDK-defined: the real parameter is found even when the return annotation is also `Context`."""

    def fn(ctx: Context) -> Context:
        raise NotImplementedError

    assert find_context_parameter(fn) == "ctx"


async def test_tool_returning_context_is_called_with_only_its_own_arguments() -> None:
    """A tool whose return annotation mentions `Context` runs without a spurious `return` argument."""
    server = MCPServer("test")

    @server.tool()
    def maybe_context(value: int) -> Context | str:
        return f"got {value}"

    async with Client(server) as client:
        result = await client.call_tool("maybe_context", {"value": 7})

    assert result.is_error is False
    assert result.structured_content == {"result": "got 7"}


async def test_prompt_returning_context_is_called_with_only_its_own_arguments() -> None:
    """A prompt whose return annotation mentions `Context` runs without a spurious `return` argument."""
    server = MCPServer("test")

    @server.prompt()
    def maybe_context(value: str) -> Context | str:
        return f"got {value}"

    async with Client(server) as client:
        result = await client.get_prompt("maybe_context", {"value": "seven"})

    content = result.messages[0].content
    assert isinstance(content, TextContent)
    assert content.text == "got seven"


async def test_resource_template_returning_context_is_called_with_only_its_own_arguments() -> None:
    """A resource template whose return annotation mentions `Context` runs without a spurious `return`."""
    server = MCPServer("test")

    @server.resource("res://{value}")
    def maybe_context(value: str) -> Context | str:
        return f"got {value}"

    async with Client(server) as client:
        result = await client.read_resource("res://seven")

    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.text == "got seven"
