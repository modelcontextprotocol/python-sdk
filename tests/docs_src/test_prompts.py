"""`docs/servers/prompts.md`: every claim the page makes, proved against the real SDK."""

import traceback

import pytest
from inline_snapshot import snapshot
from mcp_types import PromptArgument, PromptMessage, TextContent

from docs_src.prompts import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError
from tests.docs_src._helpers import strip_server_info

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_function_becomes_the_prompt() -> None:
    """tutorial001: the name, the docstring and the parameters are the whole `prompts/list` entry."""
    async with Client(tutorial001.mcp) as client:
        (prompt,) = (await client.list_prompts()).prompts
        assert prompt.model_dump(mode="json", by_alias=True, exclude_none=True) == snapshot(
            {
                "name": "review_code",
                "description": "Review a piece of code.",
                "arguments": [{"name": "code", "required": True}],
            }
        )


async def test_returned_string_becomes_one_user_message() -> None:
    """tutorial001: a `str` return value is rendered as a single `user` message."""
    async with Client(tutorial001.mcp) as client:
        result = await client.get_prompt("review_code", {"code": "def add(a, b): return a + b"})
        result = strip_server_info(result, tutorial001.mcp)
        assert result.model_dump(mode="json", by_alias=True, exclude_none=True) == snapshot(
            {
                "description": "Review a piece of code.",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Please review this code:\n\ndef add(a, b): return a + b",
                        },
                    }
                ],
                "resultType": "complete",
            }
        )


async def test_missing_required_argument_is_a_protocol_error() -> None:
    """tutorial001: omitting a required argument fails the request itself. There is no error result."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("review_code")
        assert exc_info.value.code == -32603
        assert exc_info.value.message == "Internal server error"
        # The line a traceback prints, exactly as the page quotes it: the code is not in the message.
        assert traceback.format_exception_only(exc_info.value) == snapshot(
            ["mcp.shared.exceptions.MCPError: Internal server error\n"]
        )


async def test_message_list_becomes_a_multi_turn_template() -> None:
    """tutorial002: a list of `UserMessage` / `AssistantMessage` renders in order, roles intact."""
    async with Client(tutorial002.mcp) as client:
        assert [p.name for p in (await client.list_prompts()).prompts] == ["review_code", "debug_error"]
        result = await client.get_prompt("debug_error", {"error": "TypeError: 'int' object is not iterable"})
        assert result.messages == [
            PromptMessage(role="user", content=TextContent(type="text", text="I'm seeing this error:")),
            PromptMessage(
                role="user",
                content=TextContent(type="text", text="TypeError: 'int' object is not iterable"),
            ),
            PromptMessage(
                role="assistant",
                content=TextContent(type="text", text="I'll help debug that. What have you tried so far?"),
            ),
        ]


async def test_title_and_argument_descriptions() -> None:
    """tutorial003: `title=` and `Field(description=...)` land in the `prompts/list` entry."""
    async with Client(tutorial003.mcp) as client:
        (prompt,) = (await client.list_prompts()).prompts
        assert prompt.title == "Code review"
        assert prompt.arguments == [
            PromptArgument(name="code", description="The code to review.", required=True),
            PromptArgument(name="language", description="The language the code is written in.", required=False),
        ]


async def test_default_value_makes_the_argument_optional() -> None:
    """tutorial003: a parameter with a default can be omitted and the default is used in the render."""
    async with Client(tutorial003.mcp) as client:
        result = await client.get_prompt("review_code", {"code": "x = 1"})
        assert result.messages == [
            PromptMessage(
                role="user",
                content=TextContent(type="text", text="Please review this python code:\n\nx = 1"),
            )
        ]
