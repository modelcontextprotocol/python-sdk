"""Composed multi-feature flows against the low-level Server, driven through the public Client API.

Each test reads as the scenario it proves: the steps run top to bottom in the order a real client
would perform them, composing two or more feature areas (a tool call followed by a resource read;
a chain of elicitations inside one tool call; the full URL-elicitation-required retry loop). The
individual features are pinned by their own tests; these prove they compose.
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
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    EmptyResult,
    ListToolsResult,
    NumberSchema,
    ReadResourceResult,
    ResourceLink,
    StringSchema,
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
    """A tool returns a resource_link; reading that link's URI returns the referenced contents.

    Steps: (1) call the tool, (2) extract the link from its content, (3) read_resource on the
    link's URI, (4) the read result carries the linked contents.
    """

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
    """Sequential form elicitations inside one tool call: each accepted answer feeds the next step.

    Steps: (1) call the tool, (2) the handler issues a step-one form elicitation that the client
    accepts with content, (3) the handler issues a step-two elicitation whose message references
    the step-one answer, (4) the client accepts step two, (5) the tool result summarises both
    answers. The callback is invoked exactly twice with the expected messages and schemas. The
    short-circuit on decline is the application's choice (proven separately by the per-action
    elicitation tests); what this flow pins is that the chain itself works end to end.
    """
    received: list[ElicitRequestFormParams] = []
    answers: list[dict[str, str | int | float | bool | list[str] | None]] = [{"name": "ada"}, {"age": 37}]

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "onboard"
        first = await ctx.session.elicit_form(
            "Step 1: choose a username.", ElicitRequestedSchema(properties={"name": StringSchema(type="string")})
        )
        assert first.action == "accept" and first.content is not None
        second = await ctx.session.elicit_form(
            f"Step 2: confirm age for {first.content['name']}.",
            ElicitRequestedSchema(properties={"age": NumberSchema(type="integer")}),
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
    """The full URL-elicitation-required retry loop: -32042, completion announced, retry succeeds.

    Steps: (1) the first call is rejected with -32042 carrying the required URL elicitation in
    its error data, (2) the client extracts the elicitation id from the error, (3) the server
    announces completion via the elicitation/complete notification (driven via the captured
    session, the same way a real out-of-band callback would reach a held session reference),
    (4) the client observes the matching completion notification and retries, (5) the retry
    succeeds. The handler distinguishes the two calls by a closure flag the test flips between
    them; the test waits on the completion notification with an event so the retry only happens
    after the announcement has arrived.
    """
    elicitation_id = "auth-001"
    authorised: list[bool] = [False]
    captured: list[ServerSession] = []
    completed = anyio.Event()
    notifications: list[ElicitCompleteNotification] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "read_files"
        captured.append(ctx.session)
        if not authorised[0]:
            # The log line gives the message handler a non-completion notification, so the test's
            # filtering branch is exercised in both directions and the wait remains specific.
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
