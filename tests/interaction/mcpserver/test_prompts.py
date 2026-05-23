"""Prompt interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import (
    ErrorData,
    GetPromptResult,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:prompts:decorated")
async def test_list_prompts_derives_arguments_from_signature() -> None:
    """A decorated prompt is listed with arguments derived from the function signature.

    Parameters without a default are required; the description comes from the docstring.
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def code_review(code: str, style_guide: str = "pep8") -> str:
        """Review a piece of code."""
        raise NotImplementedError  # registered for listing only; never rendered

    async with Client(mcp) as client:
        result = await client.list_prompts()

    assert result == snapshot(
        ListPromptsResult(
            prompts=[
                Prompt(
                    name="code_review",
                    description="Review a piece of code.",
                    arguments=[
                        PromptArgument(name="code", required=True),
                        PromptArgument(name="style_guide", required=False),
                    ],
                )
            ]
        )
    )


@requirement("mcpserver:prompts:decorated")
async def test_get_prompt_renders_function_return() -> None:
    """The decorated function's string return value is rendered as a single user message."""
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet(name: str) -> str:
        """A personalised greeting."""
        return f"Say hello to {name}."

    async with Client(mcp) as client:
        result = await client.get_prompt("greet", {"name": "Ada"})

    assert result == snapshot(
        GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text="Say hello to Ada."))],
        )
    )


@requirement("mcpserver:prompts:unknown-name")
async def test_get_unknown_prompt_is_error() -> None:
    """Getting a prompt name that was never registered fails with a JSON-RPC error."""
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet(name: str) -> str:
        """A registered prompt; the test requests a different name."""
        raise NotImplementedError

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="Unknown prompt: nope"))
