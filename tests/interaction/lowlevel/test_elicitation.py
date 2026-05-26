"""Form- and URL-mode elicitation against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, UrlElicitationRequiredError, types
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolResult,
    ElicitCompleteNotification,
    ElicitCompleteNotificationParams,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    ErrorData,
    TextContent,
)
from tests.interaction._helpers import IncomingMessage
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


@requirement("elicitation:form:accept")
async def test_elicit_form_accepted_content_returns_to_handler() -> None:
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

    async with Client(server, elicitation_callback=answer_form) as client:
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


@requirement("elicitation:form:decline")
async def test_elicit_form_decline_returns_no_content() -> None:
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

    async with Client(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="decline content=None")]))


@requirement("elicitation:form:cancel")
async def test_elicit_form_cancel_returns_no_content() -> None:
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

    async with Client(server, elicitation_callback=answer_form) as client:
        result = await client.call_tool("confirm", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:form:not-supported")
async def test_elicit_form_without_callback_is_error() -> None:
    """Eliciting from a client that configured no elicitation callback fails with an error.

    The client's default callback answers with an Invalid request error, which the server-side
    elicit call raises as an MCPError; the tool reports the code and message it caught. The spec
    requires -32602 for an undeclared mode (see the divergence note on the requirement).
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

    async with Client(server) as client:
        result = await client.call_tool("ask", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32600: Elicitation not supported")]))


@requirement("elicitation:url:accept")
async def test_elicit_url_delivers_url_and_returns_accept_without_content() -> None:
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

    async with Client(server, elicitation_callback=answer_url) as client:
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
async def test_elicit_url_decline_returns_no_content() -> None:
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

    async with Client(server, elicitation_callback=answer_url) as client:
        result = await client.call_tool("authorize", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="decline content=None")]))


@requirement("elicitation:url:cancel")
async def test_elicit_url_cancel_returns_no_content() -> None:
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

    async with Client(server, elicitation_callback=answer_url) as client:
        result = await client.call_tool("authorize", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="cancel content=None")]))


@requirement("elicitation:complete-notification")
async def test_elicitation_complete_notification_carries_the_elicited_id_back_to_the_client() -> None:
    """After a URL elicitation finishes, the server announces it with a notification carrying the same id.

    The lifecycle under test: the tool elicits a URL interaction with an elicitationId, the user
    agrees to visit the URL, the out-of-band interaction finishes, and the server emits
    elicitation/complete so the client can correlate the completion with the elicitation it
    accepted earlier. Both messages arrive before the tool call returns, so a plain collected
    list needs no synchronisation.
    """
    elicitation_id = "auth-001"
    elicited_ids: list[str] = []
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
        await ctx.session.send_elicit_complete(elicitation_id)
        return CallToolResult(content=[TextContent(text="linked")])

    server = Server("authorizer", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_url(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestURLParams)
        elicited_ids.append(params.elicitation_id)
        return ElicitResult(action="accept")

    async with Client(server, message_handler=collect, elicitation_callback=answer_url) as client:
        await client.call_tool("link_account", {})

    # The completion notification refers to the same elicitation the client accepted.
    assert elicited_ids == [elicitation_id]
    assert received == snapshot(
        [ElicitCompleteNotification(params=ElicitCompleteNotificationParams(elicitation_id="auth-001"))]
    )


@requirement("elicitation:url:required-error")
async def test_url_elicitation_required_error_carries_pending_elicitations() -> None:
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

    async with Client(server) as client:
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
