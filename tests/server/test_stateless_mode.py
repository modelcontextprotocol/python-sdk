"""Tests for stateless HTTP mode limitations.

Stateless HTTP mode does not support server-to-client requests because there
is no persistent connection for bidirectional communication. These tests verify
that appropriate errors are raised when attempting to use unsupported features.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1097
"""

from collections.abc import AsyncGenerator
from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.exceptions import StatelessModeNotSupported
from mcp.shared.message import SessionMessage
from mcp.types import ServerCapabilities


@pytest.fixture
async def stateless_session() -> AsyncGenerator[ServerSession, None]:
    """Create a stateless ServerSession for testing."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    init_options = InitializationOptions(
        server_name="test",
        server_version="0.1.0",
        capabilities=ServerCapabilities(),
    )

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            init_options,
            stateless=True,
        ) as session:
            yield session


@pytest.mark.anyio
async def test_list_roots_fails_in_stateless_mode(stateless_session: ServerSession):
    """Test that list_roots raises StatelessModeNotSupported in stateless mode."""
    with pytest.raises(StatelessModeNotSupported, match="list_roots"):
        await stateless_session.list_roots()


@pytest.mark.anyio
async def test_create_message_fails_in_stateless_mode(stateless_session: ServerSession):
    """Test that create_message raises StatelessModeNotSupported in stateless mode."""
    with pytest.raises(StatelessModeNotSupported, match="sampling"):
        await stateless_session.create_message(
            messages=[
                types.SamplingMessage(
                    role="user",
                    content=types.TextContent(type="text", text="hello"),
                )
            ],
            max_tokens=100,
        )


@pytest.mark.anyio
async def test_elicit_form_fails_in_stateless_mode(stateless_session: ServerSession):
    """Test that elicit_form raises StatelessModeNotSupported in stateless mode."""
    with pytest.raises(StatelessModeNotSupported, match="elicitation"):
        await stateless_session.elicit_form(
            message="Please provide input",
            requestedSchema={"type": "object", "properties": {}},
        )


@pytest.mark.anyio
async def test_elicit_url_fails_in_stateless_mode(stateless_session: ServerSession):
    """Test that elicit_url raises StatelessModeNotSupported in stateless mode."""
    with pytest.raises(StatelessModeNotSupported, match="elicitation"):
        await stateless_session.elicit_url(
            message="Please authenticate",
            url="https://example.com/auth",
            elicitation_id="test-123",
        )


@pytest.mark.anyio
async def test_elicit_deprecated_fails_in_stateless_mode(stateless_session: ServerSession):
    """Test that the deprecated elicit method also fails in stateless mode."""
    with pytest.raises(StatelessModeNotSupported, match="elicitation"):
        await stateless_session.elicit(
            message="Please provide input",
            requestedSchema={"type": "object", "properties": {}},
        )


@pytest.mark.anyio
async def test_stateless_error_message_is_actionable(stateless_session: ServerSession):
    """Test that the error message provides actionable guidance."""
    with pytest.raises(StatelessModeNotSupported) as exc_info:
        await stateless_session.list_roots()

    error_message = str(exc_info.value)
    # Should mention it's stateless mode
    assert "stateless HTTP mode" in error_message
    # Should explain why it doesn't work
    assert "server-to-client requests" in error_message
    # Should tell user how to fix it
    assert "stateless_http=False" in error_message


@pytest.mark.anyio
async def test_exception_has_method_attribute(stateless_session: ServerSession):
    """Test that the exception has a method attribute for programmatic access."""
    with pytest.raises(StatelessModeNotSupported) as exc_info:
        await stateless_session.list_roots()

    assert exc_info.value.method == "list_roots"


@pytest.fixture
async def stateful_session() -> AsyncGenerator[ServerSession, None]:
    """Create a stateful ServerSession for testing."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    init_options = InitializationOptions(
        server_name="test",
        server_version="0.1.0",
        capabilities=ServerCapabilities(),
    )

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            init_options,
            stateless=False,
        ) as session:
            yield session


@pytest.mark.anyio
async def test_stateful_mode_does_not_raise_stateless_error(
    stateful_session: ServerSession, monkeypatch: pytest.MonkeyPatch
):
    """Test that StatelessModeNotSupported is not raised in stateful mode.

    We mock send_request to avoid blocking on I/O while still verifying
    that the stateless check passes.
    """
    send_request_called = False

    async def mock_send_request(*_: Any, **__: Any) -> types.ListRootsResult:
        nonlocal send_request_called
        send_request_called = True
        return types.ListRootsResult(roots=[])

    monkeypatch.setattr(stateful_session, "send_request", mock_send_request)

    # This should NOT raise StatelessModeNotSupported
    result = await stateful_session.list_roots()

    assert send_request_called
    assert isinstance(result, types.ListRootsResult)
