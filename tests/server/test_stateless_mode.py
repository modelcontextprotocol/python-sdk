"""Tests for stateless HTTP mode limitations.

Stateless HTTP mode does not support server-to-client requests because there
is no persistent connection for bidirectional communication. These tests verify
that appropriate errors are raised when attempting to use unsupported features.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1097
"""

import anyio
import pytest

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.types import ServerCapabilities


def create_test_streams():
    """Create memory streams for testing."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    return (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    )


def create_init_options():
    """Create default initialization options for testing."""
    return InitializationOptions(
        server_name="test",
        server_version="0.1.0",
        capabilities=ServerCapabilities(),
    )


@pytest.mark.anyio
async def test_list_roots_fails_in_stateless_mode():
    """Test that list_roots raises RuntimeError in stateless mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.list_roots()

            assert "stateless HTTP mode" in str(exc_info.value)
            assert "list_roots" in str(exc_info.value)


@pytest.mark.anyio
async def test_create_message_fails_in_stateless_mode():
    """Test that create_message raises RuntimeError in stateless mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.create_message(
                    messages=[
                        types.SamplingMessage(
                            role="user",
                            content=types.TextContent(type="text", text="hello"),
                        )
                    ],
                    max_tokens=100,
                )

            assert "stateless HTTP mode" in str(exc_info.value)
            assert "sampling" in str(exc_info.value)


@pytest.mark.anyio
async def test_elicit_form_fails_in_stateless_mode():
    """Test that elicit_form raises RuntimeError in stateless mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.elicit_form(
                    message="Please provide input",
                    requestedSchema={"type": "object", "properties": {}},
                )

            assert "stateless HTTP mode" in str(exc_info.value)
            assert "elicitation" in str(exc_info.value)


@pytest.mark.anyio
async def test_elicit_url_fails_in_stateless_mode():
    """Test that elicit_url raises RuntimeError in stateless mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.elicit_url(
                    message="Please authenticate",
                    url="https://example.com/auth",
                    elicitation_id="test-123",
                )

            assert "stateless HTTP mode" in str(exc_info.value)
            assert "elicitation" in str(exc_info.value)


@pytest.mark.anyio
async def test_elicit_deprecated_fails_in_stateless_mode():
    """Test that the deprecated elicit method also fails in stateless mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.elicit(
                    message="Please provide input",
                    requestedSchema={"type": "object", "properties": {}},
                )

            assert "stateless HTTP mode" in str(exc_info.value)
            assert "elicitation" in str(exc_info.value)


@pytest.mark.anyio
async def test_require_stateful_mode_does_not_raise_in_stateful_mode():
    """Test that _require_stateful_mode does not raise in stateful mode."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=False,  # Stateful mode
        ) as session:
            # These should not raise - the check passes in stateful mode
            session._require_stateful_mode("list_roots")
            session._require_stateful_mode("sampling")
            session._require_stateful_mode("elicitation")


@pytest.mark.anyio
async def test_stateless_error_message_is_actionable():
    """Test that the error message provides actionable guidance."""
    (
        server_to_client_send,
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
    ) = create_test_streams()

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            create_init_options(),
            stateless=True,
        ) as session:
            with pytest.raises(RuntimeError) as exc_info:
                await session.list_roots()

            error_message = str(exc_info.value)
            # Should mention it's stateless mode
            assert "stateless HTTP mode" in error_message
            # Should explain why it doesn't work
            assert "server-to-client requests" in error_message
            # Should tell user how to fix it
            assert "stateless_http=False" in error_message
