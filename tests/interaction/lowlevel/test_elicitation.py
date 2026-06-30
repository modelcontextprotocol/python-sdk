"""Form- and URL-mode elicitation against the low-level Server, driven through the public Client API.

The final test plays the server's side of the wire by hand to issue an elicitation request with no
mode field, because the typed server API (`elicit_form`/`elicit_url`) always serializes one.
"""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    URL_ELICITATION_REQUIRED,
    CallToolResult,
    ElicitCompleteNotification,
    ElicitCompleteNotificationParams,
    ElicitRequest,
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    ErrorData,
    Implementation,
    InitializeResult,
    InputRequiredResult,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    TextContent,
)
from mcp_types.version import LATEST_MODERN_VERSION

from mcp import MCPError, UrlElicitationRequiredError
from mcp.client import ClientRequestContext, ClientSession
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, mounted_app
from tests.interaction._helpers import IncomingMessage, RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

REQUESTED_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "username": {"type": "string"},
        "newsletter": {"type": "boolean"},
    },
    "required": ["username"],
}


@requirement("elicitation:form:action:accept")
@requirement("elicitation:form:basic")
@requirement("tools:call:elicitation-roundtrip")
async def test_elicit_form_accepted_content_returns_to_handler(connect: Connect) -> None:
    """An accepted form elicitation returns the user's content to the requesting handler.

    The tool reports the action as text and the received content as structured content, proving
    the client's answer made it back into the tool's own result.
    """
    received: list[types.ElicitRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="signup", description="Register the user.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "signup"
        answer = await ctx.session.elicit_form("Choose a username.", REQUESTED_SCHEMA)
        return CallToolResult(content=[TextContent(text=answer.action)], structured_content=answer.content)

    server = Server("registrar", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"username": "ada", "newsletter": True})

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("signup", {})

    assert received == snapshot(
        [
            ElicitRequestFormParams(
                _meta={},
                message="Choose a username.",
                requested_schema={
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "newsletter": {"type": "boolean"},
                    },
                    "required": ["username"],
                },
            )
        ]
    )
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="accept")],
            structured_content={"username": "ada", "newsletter": True},
        )
    )


@requirement("elicitation:form:action:decline")
async def test_elicit_form_decline_returns_no_content(connect: Connect) -> None:
    """A declined form elicitation returns the decline action to the handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="confirm", description="Ask for confirmation.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "confirm"
        answer = await ctx.session.elicit_form("Proceed?", {"type": "object", "properties": {}})
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("confirmer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="decline content=None")]))


@requirement("elicitation:form:action:cancel")
async def test_elicit_form_cancel_returns_no_content(connect: Connect) -> None:
    """A cancelled form elicitation returns the cancel action to the handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="confirm", description="Ask for confirmation.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "confirm"
        answer = await ctx.session.elicit_form("Proceed?", {"type": "object", "properties": {}})
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("confirmer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="cancel")

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:form:not-supported")
@requirement("elicitation:capability:server-respects-mode")
async def test_elicit_form_without_callback_is_error(connect: Connect) -> None:
    """Eliciting from a client that configured no elicitation callback fails with an error.

    The client's default callback answers with an Invalid request error, which the server-side
    elicit call raises as an MCPError; the tool reports the code and message it caught. The spec
    requires -32602 for an undeclared mode (see the divergence note on the requirement). The
    request reaching the client also shows the server does not check the client's declared
    elicitation capability before sending (see the divergence on `server-respects-mode`).
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="ask", description="Ask the user.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        try:
            await ctx.session.elicit_form("Anyone there?", {"type": "object", "properties": {}})
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # elicit_form cannot succeed without a client callback

    server = Server("asker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("ask", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32600: Elicitation not supported")]))


@requirement("elicitation:url:action:accept-no-content")
@requirement("elicitation:url:basic")
async def test_elicit_url_delivers_url_and_returns_accept_without_content(connect: Connect) -> None:
    """A URL elicitation delivers the message, URL, and elicitation id to the client; accepting it
    returns the action with no content.

    Accept means the user agreed to visit the URL, not that the out-of-band interaction finished,
    so there is never form content to return.
    """
    received: list[types.ElicitRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="authorize", description="Link an account.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "authorize"
        answer = await ctx.session.elicit_url(
            "Authorize access to your calendar.", "https://example.com/oauth/authorize", "auth-001"
        )
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("authorizer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept")

    async with connect(server, elicitation_callback=answer_url) as client:
        result = await client.call_tool("authorize", {})

    assert received == snapshot(
        [
            ElicitRequestURLParams(
                _meta={},
                message="Authorize access to your calendar.",
                url="https://example.com/oauth/authorize",
                elicitation_id="auth-001",
            )
        ]
    )
    assert result == snapshot(CallToolResult(content=[TextContent(text="accept content=None")]))


@requirement("elicitation:url:action:decline")
async def test_elicit_url_decline_returns_no_content(connect: Connect) -> None:
    """A declined URL elicitation returns the decline action to the handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="authorize", description="Link an account.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "authorize"
        answer = await ctx.session.elicit_url(
            "Authorize access to your calendar.", "https://example.com/oauth/authorize", "auth-001"
        )
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("authorizer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with connect(server, elicitation_callback=answer_url) as client:
        result = await client.call_tool("authorize", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="decline content=None")]))


@requirement("elicitation:url:action:cancel")
async def test_elicit_url_cancel_returns_no_content(connect: Connect) -> None:
    """A cancelled URL elicitation returns the cancel action to the handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="authorize", description="Link an account.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "authorize"
        answer = await ctx.session.elicit_url(
            "Authorize access to your calendar.", "https://example.com/oauth/authorize", "auth-001"
        )
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("authorizer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="cancel")

    async with connect(server, elicitation_callback=answer_url) as client:
        result = await client.call_tool("authorize", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:url:complete-notification")
async def test_elicitation_complete_notification_carries_the_elicited_id_back_to_the_client(connect: Connect) -> None:
    """After a URL elicitation finishes, the server announces it with a notification carrying the same id.

    The lifecycle under test: the tool elicits a URL interaction with an elicitationId, the user
    agrees to visit the URL, the out-of-band interaction finishes, and the server emits
    elicitation/complete so the client can correlate the completion with the elicitation it
    accepted earlier. The completion notification carries ``related_request_id`` so over
    streamable HTTP it rides the tool call's own stream and reaches the client before the call
    returns; the same ordering already holds on in-memory and SSE transports.
    """
    elicitation_id = "auth-001"
    elicited_ids: list[str | None] = []
    received: list[IncomingMessage] = []

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="link_account", description="Link an account.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "link_account"
        answer = await ctx.session.elicit_url(
            "Authorize access to your files.", "https://example.com/oauth/authorize", elicitation_id
        )
        assert answer.action == "accept"
        await ctx.session.send_elicit_complete(elicitation_id, related_request_id=ctx.request_id)
        return CallToolResult(content=[TextContent(text="linked")])

    server = Server("authorizer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestURLParams)
        elicited_ids.append(params.elicitation_id)
        return ElicitResult(action="accept")

    async with connect(server, message_handler=collect, elicitation_callback=answer_url) as client:
        await client.call_tool("link_account", {})

    # The completion notification refers to the same elicitation the client accepted.
    assert elicited_ids == [elicitation_id]
    assert received == snapshot(
        [ElicitCompleteNotification(params=ElicitCompleteNotificationParams(elicitation_id="auth-001"))]
    )


@requirement("elicitation:url:required-error")
async def test_url_elicitation_required_error_carries_pending_elicitations(connect: Connect) -> None:
    """A request that cannot proceed until a URL interaction completes is rejected with error -32042.

    This is the non-interactive alternative to elicit_url: instead of asking and waiting, the
    handler rejects the whole request and lists the required URL elicitations in the error data.
    The client is expected to present those URLs, wait for the matching elicitation/complete
    notifications, and retry the original request.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "read_files"
        raise UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    message="Authorization required for your files.",
                    url="https://example.com/oauth/authorize",
                    elicitation_id="auth-001",
                )
            ]
        )

    server = Server("authorizer", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("read_files", {})

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=-32042,
            message="URL elicitation required",
            data={
                "elicitations": [
                    {
                        "mode": "url",
                        "message": "Authorization required for your files.",
                        "url": "https://example.com/oauth/authorize",
                        "elicitationId": "auth-001",
                    }
                ]
            },
        )
    )


@requirement("elicitation:form:schema:primitives")
@requirement("elicitation:form:schema:enum-variants")
async def test_elicit_form_schema_with_every_primitive_and_enum_type_reaches_the_callback_as_sent(
    connect: Connect,
) -> None:
    """A requested schema covering every spec-listed property kind is delivered to the callback unchanged.

    One schema with one property per kind: a formatted string, an integer with bounds, a number,
    a boolean, a plain enum, a oneOf-const titled enum, and a multi-select array-of-enum. The
    callback observing the same schema as the handler sent proves both the primitive coverage and
    the enum-variant coverage in one snapshot.
    """
    schema: ElicitRequestedSchema = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email", "title": "Email", "description": "Contact address."},
            "age": {"type": "integer", "minimum": 0, "maximum": 150},
            "score": {"type": "number"},
            "subscribe": {"type": "boolean", "default": False},
            "tier": {"type": "string", "enum": ["free", "pro", "team"]},
            "region": {
                "type": "string",
                "oneOf": [
                    {"const": "eu", "title": "Europe"},
                    {"const": "na", "title": "North America"},
                ],
            },
            "channels": {"type": "array", "items": {"type": "string", "enum": ["email", "sms", "push"]}},
        },
        "required": ["email"],
    }

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="onboard", description="Onboard the user.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "onboard"
        answer = await ctx.session.elicit_form("Tell us about yourself.", schema)
        return CallToolResult(content=[TextContent(text=answer.action)])

    server = Server("onboarder", on_list_tools=list_tools, on_call_tool=call_tool)

    received: list[types.ElicitRequestParams] = []

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"email": "ada@example.com"})

    async with connect(server, elicitation_callback=answer_form) as client:
        await client.call_tool("onboard", {})

    assert len(received) == 1
    assert isinstance(received[0], ElicitRequestFormParams)
    assert received[0].requested_schema == schema


@requirement("elicitation:form:schema:restricted-subset")
async def test_elicit_form_with_a_nested_schema_is_forwarded_unchanged(connect: Connect) -> None:
    """A requested schema with nested-object and array-of-object properties passes through unchanged.

    The spec restricts form-mode requested schemas to flat objects with primitive-typed properties;
    this test pins that the SDK does not enforce that restriction on either side (see the
    divergence on the requirement). The inbound surface gate is deliberately relaxed here so older
    servers that emit `anyOf` for `Optional` form fields still reach the elicitation callback.
    """
    schema: ElicitRequestedSchema = {
        "type": "object",
        "properties": {
            "address": {
                "type": "object",
                "properties": {"street": {"type": "string"}, "city": {"type": "string"}},
            },
            "contacts": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        },
    }

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="profile", description="Collect a profile.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "profile"
        answer = await ctx.session.elicit_form("Profile details.", schema)
        return CallToolResult(content=[TextContent(text=answer.action)])

    server = Server("profiler", on_list_tools=list_tools, on_call_tool=call_tool)

    received: list[types.ElicitRequestParams] = []

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="decline")

    async with connect(server, elicitation_callback=answer_form) as client:
        await client.call_tool("profile", {})

    assert len(received) == 1
    assert isinstance(received[0], ElicitRequestFormParams)
    assert received[0].requested_schema == schema


@requirement("elicitation:form:response-validation")
async def test_accepted_elicitation_content_that_violates_the_schema_reaches_the_handler_unchanged(
    connect: Connect,
) -> None:
    """Accepted form content that contradicts the requested schema is delivered to the handler unchanged.

    The schema requires a string `name`; the callback answers with a wrong-type value and an extra
    field. Nothing on either side validates the response against the schema (see the divergence on
    the requirement), so the handler observes exactly what the callback sent.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="signup", description="Register the user.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "signup"
        answer = await ctx.session.elicit_form(
            "Choose a name.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        return CallToolResult(content=[TextContent(text=answer.action)], structured_content=answer.content)

    server = Server("registrar", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"name": 42, "extra": "field"})

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("signup", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="accept")], structured_content={"name": 42, "extra": "field"})
    )


@requirement("elicitation:url:complete-unknown-ignored")
async def test_elicitation_complete_for_an_unknown_id_is_received_without_error(connect: Connect) -> None:
    """An elicitation/complete for an id the client never elicited is delivered and does not fail anything.

    No URL elicitation precedes the notification; the client neither tracks elicitation ids nor
    rejects unknown ones, so the call completes normally and the message handler observes the
    notification as-is.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="noop", description="Send a stray complete.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "noop"
        await ctx.session.send_elicit_complete("never-elicited", related_request_id=ctx.request_id)
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("notifier", on_list_tools=list_tools, on_call_tool=call_tool)

    received: list[IncomingMessage] = []

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async with connect(server, message_handler=collect) as client:
        result = await client.call_tool("noop", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")]))
    assert received == snapshot(
        [ElicitCompleteNotification(params=ElicitCompleteNotificationParams(elicitation_id="never-elicited"))]
    )


@requirement("elicitation:form:mode-omitted-default")
async def test_a_mode_less_elicitation_request_is_treated_as_form_mode() -> None:
    """An elicitation/create request with no mode field reaches the client callback as form-mode.

    The typed server API always serializes a mode (`elicit_form` writes 'form', `elicit_url` writes
    'url'), so this test plays the server's side of the wire by hand to send a request body without
    one. Reserve this pattern for behaviour the typed server API cannot produce.
    """
    received: list[types.ElicitRequestParams] = []
    answered = anyio.Event()
    server_received: list[JSONRPCMessage] = []

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={})

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        initialize = await server_read.receive()
        assert isinstance(initialize, SessionMessage)
        request = initialize.message
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "initialize"
        result = InitializeResult(
            protocol_version="2025-11-25",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="legacy", version="0.0.1"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )
        initialized = await server_read.receive()
        assert isinstance(initialized, SessionMessage)
        assert isinstance(initialized.message, JSONRPCNotification)
        assert initialized.message.method == "notifications/initialized"
        # No mode key: a server speaking a pre-mode revision of the spec sends only message + schema.
        await server_write.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="elicitation/create",
                    params={"message": "Legacy ask.", "requestedSchema": {"type": "object", "properties": {}}},
                )
            )
        )
        response = await server_read.receive()
        assert isinstance(response, SessionMessage)
        server_received.append(response.message)
        answered.set()

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as tg,
        ClientSession(client_read, client_write, elicitation_callback=answer_form) as session,
    ):
        tg.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            await session.initialize()
            await answered.wait()

    assert received == snapshot(
        [
            ElicitRequestFormParams(
                _meta=None,
                message="Legacy ask.",
                requested_schema={"type": "object", "properties": {}},
            )
        ]
    )
    assert isinstance(received[0], ElicitRequestFormParams)
    assert received[0].mode == "form"
    assert len(server_received) == 1
    assert isinstance(server_received[0], JSONRPCResponse)
    assert server_received[0].id == 2


@requirement("elicitation:mrtr:form:basic")
async def test_embedded_form_elicitation_accepted_content_returns_to_retried_handler(connect: Connect) -> None:
    """An embedded form elicitation reaches the callback as sent and its accepted content reaches the handler.

    Spec-mandated: at 2026-07-28 elicitation/create rides the MRTR flow, not a server-initiated request.
    """
    received: list[types.ElicitRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="signup", description="Register the user.", input_schema={"type": "object"})]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "signup"
        if not params.input_responses:
            return InputRequiredResult(
                input_requests={
                    "signup": ElicitRequest(
                        params=ElicitRequestFormParams(message="Choose a username.", requested_schema=REQUESTED_SCHEMA)
                    )
                }
            )
        answer = params.input_responses["signup"]
        assert isinstance(answer, ElicitResult)
        return CallToolResult(content=[TextContent(text=answer.action)], structured_content=answer.content)

    server = Server("registrar", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"username": "ada", "newsletter": True})

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("signup", {})

    assert received == snapshot(
        [
            ElicitRequestFormParams(
                message="Choose a username.",
                requested_schema={
                    "properties": {"username": {"type": "string"}, "newsletter": {"type": "boolean"}},
                    "required": ["username"],
                    "type": "object",
                },
            )
        ]
    )
    assert result == snapshot(
        CallToolResult(content=[TextContent(text="accept")], structured_content={"username": "ada", "newsletter": True})
    )


@requirement("elicitation:mrtr:form:action:decline")
async def test_embedded_form_elicitation_decline_reaches_retried_handler_with_no_content(connect: Connect) -> None:
    """An embedded form elicitation declined by the callback reaches the retried handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="confirm", description="Ask for confirmation.", input_schema={"type": "object"})]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "confirm"
        if not params.input_responses:
            return InputRequiredResult(
                input_requests={
                    "confirm": ElicitRequest(
                        params=ElicitRequestFormParams(
                            message="Proceed?", requested_schema={"type": "object", "properties": {}}
                        )
                    )
                }
            )
        answer = params.input_responses["confirm"]
        assert isinstance(answer, ElicitResult)
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("confirmer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="decline content=None")]))


@requirement("elicitation:mrtr:form:action:cancel")
async def test_embedded_form_elicitation_cancel_reaches_retried_handler_with_no_content(connect: Connect) -> None:
    """An embedded form elicitation cancelled by the callback reaches the retried handler with no content."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="confirm", description="Ask for confirmation.", input_schema={"type": "object"})]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "confirm"
        if not params.input_responses:
            return InputRequiredResult(
                input_requests={
                    "confirm": ElicitRequest(
                        params=ElicitRequestFormParams(
                            message="Proceed?", requested_schema={"type": "object", "properties": {}}
                        )
                    )
                }
            )
        answer = params.input_responses["confirm"]
        assert isinstance(answer, ElicitResult)
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("confirmer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="cancel")

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:mrtr:form:schema:primitives")
async def test_embedded_form_elicitation_schema_primitives_reach_the_callback_as_sent(connect: Connect) -> None:
    """Primitive requested-schema fields on an embedded form elicitation reach the callback intact.

    Spec-mandated. One representative constraint per type; the exhaustive sweep lives with the 2025 push-path sibling.
    """
    schema: ElicitRequestedSchema = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email", "title": "Email"},
            "age": {"type": "integer", "minimum": 0},
            "score": {"type": "number"},
            "subscribed": {"type": "boolean", "default": False},
        },
        "required": ["email"],
    }
    received: list[types.ElicitRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="profile", description="Collect a profile.", input_schema={"type": "object"})]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "profile"
        if not params.input_responses:
            return InputRequiredResult(
                input_requests={
                    "profile": ElicitRequest(
                        params=ElicitRequestFormParams(message="Complete your profile.", requested_schema=schema)
                    )
                }
            )
        answer = params.input_responses["profile"]
        assert isinstance(answer, ElicitResult)
        return CallToolResult(content=[TextContent(text=answer.action)], structured_content=answer.content)

    server = Server("profiler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(
            action="accept", content={"email": "ada@example.com", "age": 36, "score": 9.5, "subscribed": True}
        )

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("profile", {})

    assert received == snapshot(
        [
            ElicitRequestFormParams(
                message="Complete your profile.",
                requested_schema={
                    "properties": {
                        "email": {"type": "string", "format": "email", "title": "Email"},
                        "age": {"type": "integer", "minimum": 0},
                        "score": {"type": "number"},
                        "subscribed": {"type": "boolean", "default": False},
                    },
                    "required": ["email"],
                    "type": "object",
                },
            )
        ]
    )
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="accept")],
            structured_content={"email": "ada@example.com", "age": 36, "score": 9.5, "subscribed": True},
        )
    )


@requirement("elicitation:mrtr:capability:not-declared")
async def test_server_embeds_elicitation_for_a_client_that_declared_no_elicitation_capability(
    connect: Connect,
) -> None:
    """Pins a known gap: the SDK embeds an elicitation for a client that declared no elicitation capability.

    The manual loop (allow_input_required=True) surfaces the server-side embed the auto loop would mask.
    When the embed gate lands: re-pin to the gated behaviour and delete the Divergence.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "ask"
        # In-band precondition: the request envelope declared no elicitation capability.
        assert ctx.session.client_params is not None
        assert ctx.session.client_params.capabilities.elicitation is None
        return InputRequiredResult(
            input_requests={
                "ask": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Anyone there?", requested_schema={"type": "object", "properties": {}}
                    )
                )
            }
        )

    server = Server("asker", on_call_tool=call_tool)

    async with connect(server) as client:
        raw = await client.session.call_tool("ask", {}, allow_input_required=True)

    assert isinstance(raw, InputRequiredResult)
    assert raw == snapshot(
        InputRequiredResult(
            input_requests={
                "ask": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Anyone there?", requested_schema={"properties": {}, "type": "object"}
                    )
                )
            }
        )
    )


@requirement("mrtr:url-elicitation:no-32042-on-2026")
async def test_url_elicitation_rides_mrtr_and_no_32042_error_crosses_the_wire() -> None:
    """At 2026-07-28 URL elicitation rides the MRTR loop and the retired -32042 code crosses no frame.

    Spec-mandated (-32042 is reserved-never-reused). Asserted at the client transport seam over
    streamable HTTP; the exchange is POST-only, so every frame is captured before call_tool returns.
    """
    received: list[types.ElicitRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live handler: the client's output-schema cache refresh calls tools/list after the first tools/call.
        return types.ListToolsResult(
            tools=[types.Tool(name="protected", description="Needs a sign-in.", input_schema={"type": "object"})]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "protected"
        if not params.input_responses:
            return InputRequiredResult(
                input_requests={
                    "link": ElicitRequest(
                        params=ElicitRequestURLParams(message="Sign in to continue.", url="https://example.com/auth")
                    )
                }
            )
        answer = params.input_responses["link"]
        assert isinstance(answer, ElicitResult)
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("guard", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept")

    with anyio.fail_after(5):
        # Combined async-with (recorder bound via :=): a nested async-with mis-traces exit arcs under branch coverage.
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer_url,
            ) as client,
        ):
            result = await client.call_tool("protected", {})

    assert received == snapshot(
        [ElicitRequestURLParams(message="Sign in to continue.", url="https://example.com/auth")]
    )
    assert result == snapshot(CallToolResult(content=[TextContent(text="accept content=None")]))
    # Positive control: the interim input_required leg was captured, so the scan below is not vacuous.
    interim = [
        message.message
        for message in recording.received
        if isinstance(message, SessionMessage)
        and isinstance(message.message, JSONRPCResponse)
        and message.message.result.get("resultType") == "input_required"
    ]
    assert len(interim) == 1
    # Substring scan catches the code inside a result body; test payloads leave no legitimate "32042".
    frames = [
        message.message.model_dump_json(by_alias=True, exclude_none=True)
        for message in [*recording.sent, *recording.received]
        if isinstance(message, SessionMessage)
    ]
    assert all(str(URL_ELICITATION_REQUIRED) not in frame for frame in frames)
