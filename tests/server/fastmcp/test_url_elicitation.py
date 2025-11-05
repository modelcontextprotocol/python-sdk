"""Test URL mode elicitation feature (SEP 1036)."""

import pytest

from mcp.client.session import ClientSession
from mcp.server.elicitation import AcceptedUrlElicitation, CancelledElicitation, DeclinedElicitation
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitRequestParams, ElicitResult, TextContent


@pytest.mark.anyio
async def test_url_elicitation_accept():
    """Test URL mode elicitation with user acceptance."""
    mcp = FastMCP(name="URLElicitationServer")

    @mcp.tool(description="A tool that uses URL elicitation")
    async def request_api_key(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.session.elicit_url(
            message="Please provide your API key to continue.",
            url="https://example.com/api_key_setup",
            elicitation_id="test-elicitation-001",
        )

        if result.action == "accept":
            return "User consented to navigate to URL"
        elif result.action == "decline":
            return "User declined"
        else:
            return "User cancelled"

    # Create elicitation callback that accepts URL mode
    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        assert params.mode == "url"
        assert params.url == "https://example.com/api_key_setup"
        assert params.elicitationId == "test-elicitation-001"
        assert params.message == "Please provide your API key to continue."
        return ElicitResult(action="accept")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("request_api_key", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "User consented to navigate to URL"


@pytest.mark.anyio
async def test_url_elicitation_decline():
    """Test URL mode elicitation with user declining."""
    mcp = FastMCP(name="URLElicitationDeclineServer")

    @mcp.tool(description="A tool that uses URL elicitation")
    async def oauth_flow(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.session.elicit_url(
            message="Authorize access to your files.",
            url="https://example.com/oauth/authorize",
            elicitation_id="oauth-001",
        )

        if result.action == "accept":
            return "User consented"
        elif result.action == "decline":
            return "User declined authorization"
        else:
            return "User cancelled"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        assert params.mode == "url"
        return ElicitResult(action="decline")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("oauth_flow", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "User declined authorization"


@pytest.mark.anyio
async def test_url_elicitation_cancel():
    """Test URL mode elicitation with user cancelling."""
    mcp = FastMCP(name="URLElicitationCancelServer")

    @mcp.tool(description="A tool that uses URL elicitation")
    async def payment_flow(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.session.elicit_url(
            message="Complete payment to proceed.",
            url="https://example.com/payment",
            elicitation_id="payment-001",
        )

        if result.action == "accept":
            return "User consented"
        elif result.action == "decline":
            return "User declined"
        else:
            return "User cancelled payment"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        assert params.mode == "url"
        return ElicitResult(action="cancel")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("payment_flow", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "User cancelled payment"


@pytest.mark.anyio
async def test_url_elicitation_helper_function():
    """Test the elicit_url helper function."""
    from mcp.server.elicitation import elicit_url

    mcp = FastMCP(name="URLElicitationHelperServer")

    @mcp.tool(description="Tool using elicit_url helper")
    async def setup_credentials(ctx: Context[ServerSession, None]) -> str:
        result = await elicit_url(
            session=ctx.session,
            message="Set up your credentials",
            url="https://example.com/setup",
            elicitation_id="setup-001",
        )

        if isinstance(result, AcceptedUrlElicitation):
            return "Accepted"
        elif isinstance(result, DeclinedElicitation):
            return "Declined"
        elif isinstance(result, CancelledElicitation):
            return "Cancelled"
        else:
            return "Unknown"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="accept")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("setup_credentials", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Accepted"


@pytest.mark.anyio
async def test_url_no_content_in_response():
    """Test that URL mode elicitation responses don't include content field."""
    mcp = FastMCP(name="URLContentCheckServer")

    @mcp.tool(description="Check URL response format")
    async def check_url_response(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.session.elicit_url(
            message="Test message",
            url="https://example.com/test",
            elicitation_id="test-001",
        )

        # URL mode responses should not have content
        assert result.content is None
        return f"Action: {result.action}, Content: {result.content}"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        # Verify that no content field is expected for URL mode
        assert params.mode == "url"
        assert params.requestedSchema is None
        # Return without content - this is correct for URL mode
        return ElicitResult(action="accept")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("check_url_response", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert "Content: None" in result.content[0].text


@pytest.mark.anyio
async def test_form_mode_still_works():
    """Ensure form mode elicitation still works after SEP 1036."""
    from pydantic import BaseModel, Field

    mcp = FastMCP(name="FormModeBackwardCompatServer")

    class NameSchema(BaseModel):
        name: str = Field(description="Your name")

    @mcp.tool(description="Test form mode")
    async def ask_name(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="What is your name?", schema=NameSchema)

        if result.action == "accept" and result.data:
            return f"Hello, {result.data.name}!"
        else:
            return "No name provided"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        # Verify form mode parameters
        assert params.mode == "form"
        assert params.requestedSchema is not None
        assert params.url is None
        assert params.elicitationId is None
        return ElicitResult(action="accept", content={"name": "Alice"})

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("ask_name", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, Alice!"
