"""Composed multi-feature flows against the low-level Server, driven through the public Client API.

The individual features are pinned by their own tests; these flows prove they compose.
"""

from collections.abc import Awaitable, Callable

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    URL_ELICITATION_REQUIRED,
    CallToolResult,
    ElicitCompleteNotification,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    EmptyResult,
    ListToolsResult,
    ReadResourceResult,
    ResourceLink,
    TextContent,
    TextResourceContents,
    Tool,
)

from mcp import MCPError, UrlElicitationRequiredError
from mcp.client import ClientRequestContext
from mcp.server import Server, ServerRequestContext
from mcp.server.session import ServerSession
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

ListToolsHandler = Callable[
    [ServerRequestContext, types.PaginatedRequestParams | None], Awaitable[types.ListToolsResult]
]


def _list_tools(*names: str) -> ListToolsHandler:
    """A list_tools handler advertising the named tools, so call_tool's implicit list succeeds."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name=name, input_schema={"type": "object"}) for name in names])

    return list_tools


@requirement("flow:tool-result:resource-link-follow")
async def test_a_resource_link_returned_by_a_tool_can_be_followed_with_read(connect: Connect) -> None:
    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "generate"
        return CallToolResult(content=[ResourceLink(uri="file:///report.txt", name="report")])

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        assert str(params.uri) == "file:///report.txt"
        return ReadResourceResult(contents=[TextResourceContents(uri="file:///report.txt", text="generated")])

    server = Server(
        "linker", on_list_tools=_list_tools("generate"), on_call_tool=call_tool, on_read_resource=read_resource
    )

    async with connect(server) as client:
        called = await client.call_tool("generate", {})
        link = called.content[0]
        assert isinstance(link, ResourceLink)
        read = await client.read_resource(link.uri)

    assert called == snapshot(CallToolResult(content=[ResourceLink(name="report", uri="file:///report.txt")]))
    assert read == snapshot(
        ReadResourceResult(contents=[TextResourceContents(uri="file:///report.txt", text="generated")])
    )


@requirement("flow:elicitation:multi-step-form")
async def test_a_tool_handler_chains_form_elicitations_feeding_each_answer_forward(connect: Connect) -> None:
    """Decline short-circuiting is the application's choice, pinned by the per-action elicitation tests."""
    received: list[ElicitRequestFormParams] = []
    answers: list[dict[str, str | int | float | bool | list[str] | None]] = [{"name": "ada"}, {"age": 37}]

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "onboard"
        first = await ctx.session.elicit_form(
            "Step 1: choose a username.", {"type": "object", "properties": {"name": {"type": "string"}}}
        )
        assert first.action == "accept" and first.content is not None
        second = await ctx.session.elicit_form(
            f"Step 2: confirm age for {first.content['name']}.",
            {"type": "object", "properties": {"age": {"type": "integer"}}},
        )
        assert second.action == "accept" and second.content is not None
        return CallToolResult(content=[TextContent(text=f"{first.content['name']} is {second.content['age']}")])

    server = Server("onboarder", on_list_tools=_list_tools("onboard"), on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        received.append(params)
        return ElicitResult(action="accept", content=answers[len(received) - 1])

    async with connect(server, elicitation_callback=answer) as client:
        result = await client.call_tool("onboard", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ada is 37")]))
    assert [(p.message, p.requested_schema) for p in received] == snapshot(
        [
            ("Step 1: choose a username.", {"type": "object", "properties": {"name": {"type": "string"}}}),
            ("Step 2: confirm age for ada.", {"type": "object", "properties": {"age": {"type": "integer"}}}),
        ]
    )


@requirement("flow:elicitation:url-required-then-retry")
async def test_a_tool_rejected_with_url_elicitation_required_succeeds_on_retry_after_completion(
    connect: Connect,
) -> None:
    elicitation_id = "auth-001"
    authorised: list[bool] = [False]
    captured: list[ServerSession] = []
    completed = anyio.Event()
    notifications: list[ElicitCompleteNotification] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "read_files"
        captured.append(ctx.session)
        if not authorised[0]:
            # A non-completion notification, so collect's filtering branch is exercised in both directions.
            await ctx.session.send_log_message(level="warning", data="authorisation required", logger="gate")  # pyright: ignore[reportDeprecated]
            raise UrlElicitationRequiredError(
                [
                    ElicitRequestURLParams(
                        message="Authorize file access.",
                        url="https://example.com/oauth/authorize",
                        elicitation_id=elicitation_id,
                    )
                ]
            )
        return CallToolResult(content=[TextContent(text="contents")])

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        """Registered so the logging capability is advertised; the client never sets a level."""
        raise NotImplementedError

    server = Server(  # pyright: ignore[reportDeprecated]
        "gatekeeper",
        on_list_tools=_list_tools("read_files"),
        on_call_tool=call_tool,
        on_set_logging_level=set_logging_level,
    )

    async def collect(message: IncomingMessage) -> None:
        if isinstance(message, ElicitCompleteNotification):
            notifications.append(message)
            completed.set()

    async with connect(server, message_handler=collect) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("read_files", {})
        assert exc_info.value.error.code == URL_ELICITATION_REQUIRED
        required = UrlElicitationRequiredError.from_error(exc_info.value.error)
        assert [e.elicitation_id for e in required.elicitations] == [elicitation_id]

        # The out-of-band interaction completes; the server announces it on the same session.
        await captured[0].send_elicit_complete(elicitation_id)
        with anyio.fail_after(5):
            await completed.wait()
        assert notifications[0].params.elicitation_id == elicitation_id

        authorised[0] = True
        result = await client.call_tool("read_files", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="contents")]))
