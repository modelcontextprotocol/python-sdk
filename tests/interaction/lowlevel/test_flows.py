"""Composed multi-feature flows against the low-level Server, driven through the public Client API.

Each test reads as the scenario it proves: the steps run top to bottom in the order a real client
would perform them, composing two or more feature areas (a tool call followed by a resource read;
a chain of elicitations inside one tool call; the full URL-elicitation-required retry loop). The
individual features are pinned by their own tests; these prove they compose.
"""

from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import AnyUrl

from mcp import McpError, UrlElicitationRequiredError, types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import (
    URL_ELICITATION_REQUIRED,
    CallToolResult,
    ElicitCompleteNotification,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    ErrorData,
    LoggingLevel,
    ReadResourceResult,
    ResourceLink,
    ServerNotification,
    TextContent,
    TextResourceContents,
    Tool,
)
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _register_list_tools(server: Server, *names: str) -> None:
    """Register a list_tools handler advertising the named tools, so call_tool's cache lookup succeeds."""

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name=name, inputSchema={"type": "object"}) for name in names]


@requirement("flow:tool-result:resource-link-follow")
async def test_a_resource_link_returned_by_a_tool_can_be_followed_with_read(connect: Connect) -> None:
    """A tool returns a resource_link; reading that link's URI returns the referenced contents.

    Steps: (1) call the tool, (2) extract the link from its content, (3) read_resource on the
    link's URI, (4) the read result carries the linked contents.
    """
    server = Server("linker")
    _register_list_tools(server, "generate")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "generate"
        return CallToolResult(content=[ResourceLink(type="resource_link", uri="file:///report.txt", name="report")])

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        assert str(uri) == "file:///report.txt"
        return [ReadResourceContents(content="generated", mime_type="text/plain")]

    async with connect(server) as client:
        called = await client.call_tool("generate", {})
        link = called.content[0]
        assert isinstance(link, ResourceLink)
        read = await client.read_resource(link.uri)

    assert called == snapshot(
        CallToolResult(content=[ResourceLink(type="resource_link", name="report", uri="file:///report.txt")])
    )
    assert read == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="file:///report.txt", mimeType="text/plain", text="generated")]
        )
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

    server = Server("onboarder")
    _register_list_tools(server, "onboard")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "onboard"
        session = server.request_context.session
        first = await session.elicit_form(
            "Step 1: choose a username.", {"type": "object", "properties": {"name": {"type": "string"}}}
        )
        assert first.action == "accept" and first.content is not None
        second = await session.elicit_form(
            f"Step 2: confirm age for {first.content['name']}.",
            {"type": "object", "properties": {"age": {"type": "integer"}}},
        )
        assert second.action == "accept" and second.content is not None
        return CallToolResult(
            content=[TextContent(type="text", text=f"{first.content['name']} is {second.content['age']}")]
        )

    async def answer(
        context: RequestContext[ClientSession, Any], params: types.ElicitRequestParams
    ) -> ElicitResult | ErrorData:
        assert isinstance(params, ElicitRequestFormParams)
        received.append(params)
        return ElicitResult(action="accept", content=answers[len(received) - 1])

    async with connect(server, elicitation_callback=answer) as client:
        result = await client.call_tool("onboard", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="ada is 37")]))
    assert [(p.message, p.requestedSchema) for p in received] == snapshot(
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

    The handler reaches its session via ``server.request_context.session`` and stores it for
    out-of-band use — a v1-public pattern for callbacks that fire after the request returns.
    """
    elicitation_id = "auth-001"
    authorised: list[bool] = [False]
    captured: list[ServerSession] = []
    completed = anyio.Event()
    notifications: list[ElicitCompleteNotification] = []

    server = Server("gatekeeper")
    _register_list_tools(server, "read_files")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "read_files"
        session = server.request_context.session
        captured.append(session)
        if not authorised[0]:
            # The log line gives the message handler a non-completion notification, so the test's
            # filtering branch is exercised in both directions and the wait remains specific.
            await session.send_log_message(level="warning", data="authorisation required", logger="gate")
            raise UrlElicitationRequiredError(
                [
                    ElicitRequestURLParams(
                        message="Authorize file access.",
                        url="https://example.com/oauth/authorize",
                        elicitationId=elicitation_id,
                    )
                ]
            )
        return CallToolResult(content=[TextContent(type="text", text="contents")])

    @server.set_logging_level()
    async def set_logging_level(level: LoggingLevel) -> None:
        """Registered so the logging capability is advertised; the client never sets a level."""
        raise NotImplementedError

    async def collect(message: IncomingMessage) -> None:
        if isinstance(message, ServerNotification) and isinstance(message.root, ElicitCompleteNotification):
            notifications.append(message.root)
            completed.set()

    async with connect(server, message_handler=collect) as client:
        with pytest.raises(McpError) as exc_info:
            await client.call_tool("read_files", {})
        assert exc_info.value.error.code == URL_ELICITATION_REQUIRED
        required = UrlElicitationRequiredError.from_error(exc_info.value.error)
        assert [e.elicitationId for e in required.elicitations] == [elicitation_id]

        # The out-of-band interaction completes; the server announces it on the same session.
        await captured[0].send_elicit_complete(elicitation_id)
        with anyio.fail_after(5):
            await completed.wait()
        assert notifications[0].params.elicitationId == elicitation_id

        authorised[0] = True
        result = await client.call_tool("read_files", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="contents")]))
