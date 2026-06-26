"""Form- and URL-mode elicitation against the low-level Server, driven through the public Client API.

Two tests play the server's side of the wire by hand: one to issue an elicitation request with no
mode field (the typed server API always serializes one), and one to deliver a non-conforming
requested schema (the typed server API can no longer construct one).
"""

from typing import Any

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    BooleanSchema,
    CallToolResult,
    ElicitCompleteNotification,
    ElicitCompleteNotificationParams,
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    ErrorData,
    Implementation,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    StringSchema,
    TextContent,
)
from pydantic import ValidationError

from mcp import MCPError, UrlElicitationRequiredError
from mcp.client import ClientRequestContext, ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

REQUESTED_SCHEMA = ElicitRequestedSchema(
    properties={
        "username": StringSchema(type="string"),
        "newsletter": BooleanSchema(type="boolean"),
    },
    required=["username"],
)


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
        answer = await ctx.session.elicit_form("Proceed?", ElicitRequestedSchema(properties={}))
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
        answer = await ctx.session.elicit_form("Proceed?", ElicitRequestedSchema(properties={}))
        return CallToolResult(content=[TextContent(text=f"{answer.action} content={answer.content}")])

    server = Server("confirmer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="cancel")

    async with connect(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:form:not-supported")
@requirement("elicitation:capability:server-respects-mode")
async def test_elicit_form_without_callback_fails_with_invalid_params(connect: Connect) -> None:
    """Eliciting from a client that configured no elicitation callback fails with `INVALID_PARAMS`.

    Spec-mandated (MUST): an elicitation/create whose mode the client never declared is answered
    with -32602 Invalid params, and a client with no callback declared no elicitation modes at all.
    The request reaching the client at all also shows the server does not check the client's
    declared elicitation capability before sending (see the divergence on `server-respects-mode`).
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="ask", description="Ask the user.", input_schema={"type": "object"})]
        )

    errors: list[ErrorData] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        try:
            await ctx.session.elicit_form("Anyone there?", ElicitRequestedSchema(properties={}))
        except MCPError as exc:
            errors.append(exc.error)
            return CallToolResult(content=[TextContent(text=exc.error.message)])
        raise NotImplementedError  # elicit_form cannot succeed without a client callback

    server = Server("asker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("ask", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="Elicitation not supported")]))
    (error,) = errors
    assert error.code == INVALID_PARAMS


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


@requirement("elicitation:url:decline")
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


@requirement("elicitation:url:cancel")
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

    One schema with one property per kind: a formatted string, a constrained string, an integer with
    bounds, a number, a boolean, a plain enum, a oneOf-const titled enum, and a multi-select
    array-of-enum. The callback observing the exact dict `ElicitRequestedSchema` was built from
    proves the primitive and enum-variant coverage AND that the typed model round-trips losslessly:
    `username` carries `pattern`, a key the spec's prose documents on `StringSchema` but schema.ts
    omits, so it must survive as an extra rather than be silently dropped from the wire.
    """
    wire_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email", "title": "Email", "description": "Contact address."},
            "username": {"type": "string", "minLength": 3, "pattern": "^[A-Za-z]+$"},
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
        answer = await ctx.session.elicit_form(
            "Tell us about yourself.", ElicitRequestedSchema.model_validate(wire_schema)
        )
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
    assert received[0].requested_schema == wire_schema


@requirement("elicitation:form:schema:restricted-subset")
def test_elicit_form_requested_schema_rejects_nested_object_and_array_of_object_properties() -> None:
    """Spec-mandated: form-mode requested schemas are flat objects with primitive-typed properties only.

    `ElicitRequestedSchema` is the only schema type the typed send methods (`ServerSession.elicit_form`,
    `ClientPeer.elicit_form`) accept, so a non-conforming schema is unconstructible on the send side.
    The closure is scoped to property shapes: top-level keys outside schema.ts (`title`, `allOf`,
    `$defs`, ...) still pass, because the top level is deliberately an open bag -- the SDK's own
    schema renderer emits a top-level `title`.
    """
    # No `match=`: pydantic-authored message text, not ours to pin.
    with pytest.raises(ValidationError):
        ElicitRequestedSchema.model_validate(
            {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "object",
                        "properties": {"street": {"type": "string"}, "city": {"type": "string"}},
                    },
                },
            }
        )
    with pytest.raises(ValidationError):
        ElicitRequestedSchema.model_validate(
            {
                "type": "object",
                "properties": {
                    "contacts": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"name": {"type": "string"}}},
                    },
                },
            }
        )


@requirement("elicitation:form:schema:restricted-subset")
async def test_an_inbound_elicitation_with_a_non_conforming_schema_still_reaches_the_callback() -> None:
    """An inbound elicitation whose requested schema is non-conforming reaches the callback unchanged.

    Pins a deliberate, documented divergence: interop beats purity on receive. Older python-sdk
    servers emit `anyOf` for `Optional` form fields, and the inbound surface gate is relaxed for
    `requestedSchema.properties`, so those (and any other non-conforming property) still reach the
    user's elicitation callback. The server's side of the wire is scripted by hand because the typed
    server API can no longer produce a non-conforming schema.
    """
    wire_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "age": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "address": {"type": "object", "properties": {"street": {"type": "string"}}},
        },
    }
    received: list[types.ElicitRequestParams] = []
    answered = anyio.Event()
    server_received: list[JSONRPCMessage] = []

    async def answer_form(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="decline")

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
            server_info=Implementation(name="older-sdk", version="0.0.1"),
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
        await server_write.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="elicitation/create",
                    params={"mode": "form", "message": "Profile details.", "requestedSchema": wire_schema},
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

    assert len(received) == 1
    assert isinstance(received[0], ElicitRequestFormParams)
    assert received[0].requested_schema == wire_schema
    assert len(server_received) == 1
    assert isinstance(server_received[0], JSONRPCResponse)
    assert server_received[0].id == 2


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
            ElicitRequestedSchema(properties={"name": StringSchema(type="string")}, required=["name"]),
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
