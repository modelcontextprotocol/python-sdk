"""`docs/advanced/deprecated.md` — the page's behavioural claims, executed against the live SDK.

This chapter has no `docs_src/` example by design: it is the one page allowed to name
the deprecated methods, and a runnable example would teach exactly what the page tells
the reader not to build. So instead of importing an example, each test here runs a
claim the page states in prose — the warning category and text, the warn-*then*-raise
order on a modern connection, the `ping` removal, and both `filterwarnings` recipes —
so the prose cannot drift away from what the SDK does.
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
    """The `!!! warning`: on a modern connection sampling warns AND THEN the send raises.

    The two signals are independent. `@deprecated` fires the moment the method is
    called; only afterwards does the channel refuse the send. A page that says
    "you don't get a warning — you get an error" is wrong, and this is the test
    that would have caught it.
    """
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
    """The page's headline: the deprecation is advisory.

    On a classic-handshake session, the same `ask_model` tool that fails on a modern
    connection runs to completion — sampling round-trips through the client's callback
    and the result comes back. The only difference is the visible warning.
    """

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
    """The opening sentence: every retired method carries an `MCPDeprecationWarning`.

    `ping` is removed from the 2026-07-28 protocol rather than put in a deprecation
    window, but the SDK method is still decorated — its message says *removed* — and
    a modern connection answers the actual request with "Method not found".
    """
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
    """The "Deprecated is advisory" section: the category subclasses `UserWarning`.

    Python's default filter hides `DeprecationWarning` outside `__main__`; deriving
    from `UserWarning` is what makes the warning visible with no `-W` flag.
    """
    assert issubclass(MCPDeprecationWarning, UserWarning)
    assert not issubclass(MCPDeprecationWarning, DeprecationWarning)


@pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")
async def test_error_filter_turns_the_deprecated_call_into_the_documented_tool_error() -> None:
    """The `!!! check`: `"error::mcp.MCPDeprecationWarning"` makes `old_log` fail.

    Under the error filter the warning becomes the raised exception, the tool manager
    wraps it, and the result is exactly the tool error the page quotes.
    """
    async with Client(mcp) as client:
        result = await client.call_tool("old_log", {})
    assert result.is_error
    [content] = result.content
    assert isinstance(content, TextContent)
    assert content.text == (
        "Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577)."
    )


async def test_filterwarnings_ignore_silences_the_whole_category() -> None:
    """The "Silencing the warning" snippet: one `filterwarnings` line quiets the category."""
    async with Client(mcp) as client:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
            result = await client.call_tool("old_log", {})
    assert not result.is_error
    assert not any(issubclass(w.category, MCPDeprecationWarning) for w in caught)
