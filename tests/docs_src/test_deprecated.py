"""`docs/advanced/deprecated.md`: the page's behavioural claims, executed against the live SDK.

The chapter has no `docs_src/` example by design — a runnable one would teach exactly what
the page tells readers not to build — so each test runs a claim the page states in prose,
keeping the prose from drifting away from what the SDK does.
"""

import warnings

import pytest
from mcp_types import CreateMessageRequestParams, CreateMessageResult, SamplingMessage, TextContent

from mcp import Client, MCPDeprecationWarning, MCPError
from mcp.client import ClientRequestContext
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import NoBackChannelError

pytestmark = pytest.mark.anyio

mcp = MCPServer("Deprecated")


@mcp.tool()
async def ask_model(prompt: str, ctx: Context) -> str:
    """A tool still built on server-initiated sampling."""
    result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
        max_tokens=8,
    )
    return str(result.content)


@mcp.tool()
async def old_log(ctx: Context) -> str:
    """A tool still built on protocol logging."""
    await ctx.info("hello")  # pyright: ignore[reportDeprecated]
    return "ok"


async def test_create_message_warns_and_then_raises_on_a_modern_connection() -> None:
    """`@deprecated` warns the moment the method is called; only afterwards does the channel refuse the send."""
    async with Client(mcp) as client:
        with (
            pytest.warns(
                MCPDeprecationWarning,
                match=r"^The sampling capability is deprecated as of 2026-07-28 \(SEP-2577\)\.$",
            ),
            pytest.raises(NoBackChannelError) as exc,
        ):
            await client.call_tool("ask_model", {"prompt": "hi"})
        assert str(exc.value) == (
            "Cannot send 'sampling/createMessage': "
            "this transport context has no back-channel for server-initiated requests."
        )


async def test_a_deprecated_feature_still_works_on_a_legacy_session() -> None:
    """The deprecation is advisory: under mode='legacy' the same tool completes, with only the warning."""

    async def canned_sampling(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="four"),
            model="canned",
            stop_reason="endTurn",
        )

    async with Client(mcp, mode="legacy", sampling_callback=canned_sampling) as client:
        with pytest.warns(MCPDeprecationWarning, match=r"The sampling capability is deprecated"):
            result = await client.call_tool("ask_model", {"prompt": "What is 2 + 2?"})
    assert not result.is_error
    [content] = result.content
    assert isinstance(content, TextContent)
    assert "four" in content.text


async def test_send_ping_still_carries_the_deprecation_warning() -> None:
    """`ping` is removed outright in 2026-07-28 (no deprecation window), yet the method is still decorated."""
    async with Client(mcp) as client:
        with (
            pytest.warns(
                MCPDeprecationWarning,
                match=r"^ping is removed as of 2026-07-28; the method only works under mode='legacy'\.$",
            ),
            pytest.raises(MCPError, match="^Method not found$"),
        ):
            await client.send_ping()  # pyright: ignore[reportDeprecated]


def test_mcp_deprecation_warning_is_a_user_warning() -> None:
    """Deriving from `UserWarning` keeps the warning visible with no `-W` flag;
    Python's default filter hides `DeprecationWarning` outside `__main__`."""
    assert issubclass(MCPDeprecationWarning, UserWarning)
    assert not issubclass(MCPDeprecationWarning, DeprecationWarning)


@pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")
async def test_error_filter_turns_the_deprecated_call_into_the_documented_tool_error() -> None:
    """Under the error filter the warning is raised, wrapped, and surfaces as the tool error the page quotes."""
    async with Client(mcp) as client:
        result = await client.call_tool("old_log", {})
    assert result.is_error
    [content] = result.content
    assert isinstance(content, TextContent)
    assert content.text == (
        "Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577)."
    )


async def test_filterwarnings_ignore_silences_the_whole_category() -> None:
    async with Client(mcp) as client:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
            result = await client.call_tool("old_log", {})
    assert not result.is_error
    assert not any(issubclass(w.category, MCPDeprecationWarning) for w in caught)
