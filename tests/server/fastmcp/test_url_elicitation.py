"""Test URL mode elicitation feature (SEP 1036)."""

import anyio
import pytest

from mcp import types
from mcp.client.session import ClientSession
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
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
        # Test only checks accept path
        return f"User {result.action}"

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
        assert result.content[0].text == "User accept"


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
        # Test only checks decline path
        return f"User {result.action} authorization"

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
        assert result.content[0].text == "User decline authorization"


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
        # Test only checks cancel path
        return f"User {result.action} payment"

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
        assert result.content[0].text == "User cancel payment"


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
        # Test only checks accept path - return the type name
        return type(result).__name__

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="accept")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("setup_credentials", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "AcceptedUrlElicitation"


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
        # Verify that this is URL mode
        assert params.mode == "url"
        assert isinstance(params, types.ElicitRequestURLParams)
        # URL params have url and elicitationId, not requestedSchema
        assert params.url == "https://example.com/test"
        assert params.elicitationId == "test-001"
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
        # Test only checks accept path with data
        assert result.action == "accept"
        assert result.data is not None
        return f"Hello, {result.data.name}!"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        # Verify form mode parameters
        assert params.mode == "form"
        assert isinstance(params, types.ElicitRequestFormParams)
        # Form params have requestedSchema, not url/elicitationId
        assert params.requestedSchema is not None
        return ElicitResult(action="accept", content={"name": "Alice"})

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("ask_name", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, Alice!"


@pytest.mark.anyio
async def test_elicit_complete_notification():
    """Test that elicitation completion notifications can be sent and received."""
    mcp = FastMCP(name="ElicitCompleteServer")

    # Track if the notification was sent
    notification_sent = False

    @mcp.tool(description="Tool that sends completion notification")
    async def trigger_elicitation(ctx: Context[ServerSession, None]) -> str:
        nonlocal notification_sent

        # Simulate an async operation (e.g., user completing auth in browser)
        elicitation_id = "complete-test-001"

        # Send completion notification
        await ctx.session.send_elicit_complete(elicitation_id)
        notification_sent = True

        return "Elicitation completed"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="accept")  # pragma: no cover

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("trigger_elicitation", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Elicitation completed"

        # Give time for notification to be processed
        await anyio.sleep(0.1)

        # Verify the notification was sent
        assert notification_sent


@pytest.mark.anyio
async def test_url_elicitation_required_error_code():
    """Test that the URL_ELICITATION_REQUIRED error code is correct."""
    # Verify the error code matches the specification (SEP 1036)
    assert types.URL_ELICITATION_REQUIRED == -32042, (
        "URL_ELICITATION_REQUIRED error code must be -32042 per SEP 1036 specification"
    )


@pytest.mark.anyio
async def test_elicit_url_typed_results():
    """Test that elicit_url returns properly typed result objects."""
    from mcp.server.elicitation import elicit_url

    mcp = FastMCP(name="TypedResultsServer")

    @mcp.tool(description="Test declined result")
    async def test_decline(ctx: Context[ServerSession, None]) -> str:
        result = await elicit_url(
            session=ctx.session,
            message="Test decline",
            url="https://example.com/decline",
            elicitation_id="decline-001",
        )

        if isinstance(result, DeclinedElicitation):
            return "Declined"
        return "Not declined"  # pragma: no cover

    @mcp.tool(description="Test cancelled result")
    async def test_cancel(ctx: Context[ServerSession, None]) -> str:
        result = await elicit_url(
            session=ctx.session,
            message="Test cancel",
            url="https://example.com/cancel",
            elicitation_id="cancel-001",
        )

        if isinstance(result, CancelledElicitation):
            return "Cancelled"
        return "Not cancelled"  # pragma: no cover

    # Test declined result
    async def decline_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="decline")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=decline_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("test_decline", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Declined"

    # Test cancelled result
    async def cancel_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="cancel")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=cancel_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("test_cancel", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Cancelled"


@pytest.mark.anyio
async def test_deprecated_elicit_method():
    """Test the deprecated elicit() method for backward compatibility."""
    from pydantic import BaseModel, Field

    mcp = FastMCP(name="DeprecatedElicitServer")

    class EmailSchema(BaseModel):
        email: str = Field(description="Email address")

    @mcp.tool(description="Test deprecated elicit method")
    async def use_deprecated_elicit(ctx: Context[ServerSession, None]) -> str:
        # Use the deprecated elicit() method which should call elicit_form()
        result = await ctx.session.elicit(
            message="Enter your email",
            requestedSchema=EmailSchema.model_json_schema(),
        )

        if result.action == "accept" and result.content:
            return f"Email: {result.content.get('email', 'none')}"
        return "No email provided"  # pragma: no cover

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        # Verify this is form mode
        assert params.mode == "form"
        assert params.requestedSchema is not None
        return ElicitResult(action="accept", content={"email": "test@example.com"})

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("use_deprecated_elicit", {})
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Email: test@example.com"


@pytest.mark.anyio
async def test_ctx_elicit_url_convenience_method():
    """Test the ctx.elicit_url() convenience method (vs ctx.session.elicit_url())."""
    mcp = FastMCP(name="CtxElicitUrlServer")

    @mcp.tool(description="A tool that uses ctx.elicit_url() directly")
    async def direct_elicit_url(ctx: Context[ServerSession, None]) -> str:
        # Use ctx.elicit_url() directly instead of ctx.session.elicit_url()
        result = await ctx.elicit_url(
            message="Test the convenience method",
            url="https://example.com/test",
            elicitation_id="ctx-test-001",
        )
        return f"Result: {result.action}"

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        assert params.mode == "url"
        assert params.elicitationId == "ctx-test-001"
        return ElicitResult(action="accept")

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()
        result = await client_session.call_tool("direct_elicit_url", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Result: accept"
