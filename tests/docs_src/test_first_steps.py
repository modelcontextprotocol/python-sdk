"""`docs/tutorial/first-steps.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    PromptArgument,
    PromptMessage,
    TextContent,
    TextResourceContents,
)

from docs_src.first_steps import tutorial001
from mcp import Client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_each_decorator_registers_one_primitive() -> None:
    """tutorial001: name, description and schema all come from the decorated function."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.name == "add"
        assert tool.description == "Add two numbers."
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {
                    "a": {"title": "A", "type": "integer"},
                    "b": {"title": "B", "type": "integer"},
                },
                "required": ["a", "b"],
                "title": "addArguments",
            }
        )

        (template,) = (await client.list_resource_templates()).resource_templates
        assert template.name == "greeting"
        assert template.uri_template == "greeting://{name}"
        assert template.description == "Greet someone by name."

        (prompt,) = (await client.list_prompts()).prompts
        assert prompt.name == "summarize"
        assert prompt.description == "Summarize a piece of text in one sentence."
        assert prompt.arguments == [PromptArgument(name="text", required=True)]


async def test_call_the_tool() -> None:
    """tutorial001: the Inspector walkthrough. `add` with 1 and 2 answers 3."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="3")]
        assert result.structured_content == {"result": 3}


async def test_templated_resource_is_a_template_not_a_resource() -> None:
    """tutorial001: a `{param}` in the URI means the concrete-resource list stays empty."""
    async with Client(tutorial001.mcp) as client:
        assert (await client.list_resources()).resources == []


async def test_read_the_resource_template() -> None:
    """tutorial001: supplying a `name` reads the template as a concrete resource."""
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource("greeting://World")
        assert result.contents == [
            TextResourceContents(uri="greeting://World", mime_type="text/plain", text="Hello, World!")
        ]


async def test_get_the_prompt() -> None:
    """tutorial001: the returned string becomes a single user message."""
    async with Client(tutorial001.mcp) as client:
        result = await client.get_prompt("summarize", {"text": "MCP is a protocol."})
        rendered = "Summarize the following text in one sentence:\n\nMCP is a protocol."
        assert result.messages == [PromptMessage(role="user", content=TextContent(type="text", text=rendered))]


async def test_the_three_primitive_capabilities_are_always_declared() -> None:
    """tutorial001: `MCPServer` always declares tools/resources/prompts; only `completions` follows your code.

    An `MCPServer` with nothing registered declares the same three, which is why the
    page ties registration to the *optional* capabilities only.
    """
    async with Client(tutorial001.mcp) as client:
        declared = client.server_capabilities
        # The exact dictionary the page prints from `model_dump(exclude_none=True)`.
        assert declared.model_dump(exclude_none=True) == snapshot(
            {
                "prompts": {"list_changed": False},
                "resources": {"subscribe": False, "list_changed": False},
                "tools": {"list_changed": False},
            }
        )
    async with Client(MCPServer("Empty")) as client:
        assert client.server_capabilities == declared
