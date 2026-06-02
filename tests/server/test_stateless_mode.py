"""Tests for stateless HTTP mode limitations.

Stateless HTTP mode does not support server-to-client requests because there
is no persistent connection for bidirectional communication. These tests verify
that appropriate errors are raised when attempting to use unsupported features.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1097
"""

from typing import Any
from unittest.mock import Mock

import pytest

from mcp import types
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.exceptions import StatelessModeNotSupported
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher


def _make_session(*, stateless: bool) -> ServerSession:
    """A `ServerSession` with a mock dispatcher; the stateless guard fires before any send."""
    return ServerSession(
        Mock(spec=JSONRPCDispatcher),
        Connection(Mock(), has_standalone_channel=False),
        stateless=stateless,
    )


@pytest.fixture
def stateless_session() -> ServerSession:
    return _make_session(stateless=True)


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
            requested_schema={"type": "object", "properties": {}},
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
            requested_schema={"type": "object", "properties": {}},
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
def stateful_session() -> ServerSession:
    return _make_session(stateless=False)


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
