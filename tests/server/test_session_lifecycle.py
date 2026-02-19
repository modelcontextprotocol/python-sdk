"""Tests for session lifecycle state machine (Issue #1691)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.models import InitializationOptions
from mcp.server.session import _VALID_TRANSITIONS, InitializationState, ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    InitializedNotification,
    ServerCapabilities,
)

pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_INIT_OPTIONS = InitializationOptions(
    server_name="test",
    server_version="0.1.0",
    capabilities=ServerCapabilities(),
)


@asynccontextmanager
async def _session_context(
    *,
    stateless: bool = False,
) -> AsyncGenerator[ServerSession]:
    """Create a ServerSession with bidirectional memory streams.

    All stream endpoints — both the external four and the two internal ones
    created by ``ServerSession.__init__`` — are properly closed when the
    context exits.
    """
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    session = ServerSession(
        client_to_server_receive,
        server_to_client_send,
        _DEFAULT_INIT_OPTIONS,
        stateless=stateless,
    )
    async with server_to_client_send, server_to_client_receive, client_to_server_send, client_to_server_receive:
        try:
            yield session
        finally:
            # ServerSession.__init__ creates an internal stream pair
            # (_incoming_message_stream_writer / _incoming_message_stream_reader)
            # that is normally cleaned up by __aexit__ / _receive_loop. For
            # tests that don't enter the session as a context manager we must
            # close them explicitly to avoid ResourceWarning.
            await session._incoming_message_stream_writer.aclose()
            await session._incoming_message_stream_reader.aclose()


# ---------------------------------------------------------------------------
# InitializationState enum tests
# ---------------------------------------------------------------------------


class TestInitializationStateEnum:
    """Verify the expanded InitializationState enum values."""

    def test_all_states_present(self) -> None:
        expected = {"NotInitialized", "Initializing", "Initialized", "Stateless", "Closing", "Closed"}
        actual = {s.name for s in InitializationState}
        assert actual == expected

    def test_values_are_distinct(self) -> None:
        values = [s.value for s in InitializationState]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# Transition table tests
# ---------------------------------------------------------------------------


class TestValidTransitions:
    """Verify the _VALID_TRANSITIONS table is complete and correct."""

    def test_all_states_have_entry(self) -> None:
        for state in InitializationState:
            assert state in _VALID_TRANSITIONS, f"Missing entry for {state.name}"

    def test_closed_is_terminal(self) -> None:
        assert _VALID_TRANSITIONS[InitializationState.Closed] == set()


# ---------------------------------------------------------------------------
# _transition_state tests
# ---------------------------------------------------------------------------


class TestTransitionState:
    """Unit tests for ServerSession._transition_state."""

    async def test_valid_stateful_lifecycle(self) -> None:
        """NotInitialized -> Initializing -> Initialized -> Closing -> Closed."""
        async with _session_context() as session:
            assert session.initialization_state == InitializationState.NotInitialized

            session._transition_state(InitializationState.Initializing)
            assert session.initialization_state == InitializationState.Initializing

            session._transition_state(InitializationState.Initialized)
            assert session.initialization_state == InitializationState.Initialized

            session._transition_state(InitializationState.Closing)
            assert session.initialization_state == InitializationState.Closing

            session._transition_state(InitializationState.Closed)
            assert session.initialization_state == InitializationState.Closed

    async def test_valid_stateless_lifecycle(self) -> None:
        """Stateless -> Closing -> Closed."""
        async with _session_context(stateless=True) as session:
            assert session.initialization_state == InitializationState.Stateless

            session._transition_state(InitializationState.Closing)
            assert session.initialization_state == InitializationState.Closing

            session._transition_state(InitializationState.Closed)
            assert session.initialization_state == InitializationState.Closed

    async def test_invalid_transition_raises(self) -> None:
        """Attempting an invalid transition raises RuntimeError."""
        async with _session_context() as session:
            with pytest.raises(RuntimeError, match="Invalid session state transition"):
                session._transition_state(InitializationState.Closed)

    async def test_closed_to_anything_raises(self) -> None:
        """Closed is terminal — no transitions allowed."""
        async with _session_context() as session:
            session._transition_state(InitializationState.Closing)
            session._transition_state(InitializationState.Closed)

            for state in InitializationState:
                with pytest.raises(RuntimeError, match="Invalid session state transition"):
                    session._transition_state(state)


# ---------------------------------------------------------------------------
# is_initialized property tests
# ---------------------------------------------------------------------------


class TestIsInitialized:
    """Tests for the is_initialized property."""

    @pytest.mark.parametrize(
        ("stateless", "expected_state"),
        [
            (False, InitializationState.NotInitialized),
            (True, InitializationState.Stateless),
        ],
    )
    async def test_initial_state(self, stateless: bool, expected_state: InitializationState) -> None:
        async with _session_context(stateless=stateless) as session:
            assert session.initialization_state == expected_state

    async def test_not_initialized_returns_false(self) -> None:
        async with _session_context() as session:
            assert not session.is_initialized

    async def test_initializing_returns_false(self) -> None:
        async with _session_context() as session:
            session._transition_state(InitializationState.Initializing)
            assert not session.is_initialized

    async def test_initialized_returns_true(self) -> None:
        async with _session_context() as session:
            session._transition_state(InitializationState.Initializing)
            session._transition_state(InitializationState.Initialized)
            assert session.is_initialized

    async def test_stateless_returns_true(self) -> None:
        async with _session_context(stateless=True) as session:
            assert session.is_initialized


# ---------------------------------------------------------------------------
# __aexit__ lifecycle tests
# ---------------------------------------------------------------------------


class TestSessionExit:
    """Test that __aexit__ transitions to Closing -> Closed."""

    async def test_aexit_transitions_to_closed(self) -> None:
        """Normal exit transitions through Closing -> Closed."""
        async with _session_context() as session:
            async with session:
                assert session.initialization_state == InitializationState.NotInitialized

            assert session.initialization_state == InitializationState.Closed

    async def test_aexit_from_initialized(self) -> None:
        """Session transitions to Closed even when initialized."""
        async with _session_context() as session:
            async with session:
                session._transition_state(InitializationState.Initializing)
                session._transition_state(InitializationState.Initialized)
                assert session.is_initialized

            assert session.initialization_state == InitializationState.Closed

    async def test_aexit_stateless_transitions_to_closed(self) -> None:
        """Stateless sessions also transition to Closed on exit."""
        async with _session_context(stateless=True) as session:
            async with session:
                assert session.initialization_state == InitializationState.Stateless

            assert session.initialization_state == InitializationState.Closed


# ---------------------------------------------------------------------------
# Integration: full handshake lifecycle
# ---------------------------------------------------------------------------


class TestFullHandshakeLifecycle:
    """Integration test: client/server handshake uses state transitions correctly."""

    async def test_stateful_handshake(self) -> None:
        """Stateful handshake transitions NotInitialized -> Initializing -> Initialized."""
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage | Exception](
            1
        )
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](
            1
        )

        received_initialized = False

        async def run_server() -> None:
            nonlocal received_initialized
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                _DEFAULT_INIT_OPTIONS,
            ) as server_session:
                async for message in server_session.incoming_messages:  # pragma: no branch
                    if isinstance(message, Exception):  # pragma: no cover
                        raise message
                    if isinstance(message, InitializedNotification):  # pragma: no branch
                        assert server_session.is_initialized
                        assert server_session.initialization_state == InitializationState.Initialized
                        received_initialized = True
                        return

        async def message_handler(  # pragma: no cover
            message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        try:
            async with (
                server_to_client_receive,
                client_to_server_send,
                ClientSession(
                    server_to_client_receive,
                    client_to_server_send,
                    message_handler=message_handler,
                ) as client_session,
                anyio.create_task_group() as tg,
            ):
                tg.start_soon(run_server)
                await client_session.initialize()
        except anyio.ClosedResourceError:  # pragma: no cover
            pass

        assert received_initialized
