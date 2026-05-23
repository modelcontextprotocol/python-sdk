"""Form-mode elicitation against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolResult, ElicitRequestFormParams, ElicitResult, TextContent
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
    elicit call raises as an MCPError; the tool reports the code and message it caught.
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
