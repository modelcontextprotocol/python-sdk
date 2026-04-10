"""Test that respond() is a no-op when a concurrent cancellation already completed the request.

When a CancelledNotification arrives after the handler has returned its result but before
respond() is called, cancel() sets _completed = True and sends an error response. The
subsequent respond() call must return silently rather than crashing with AssertionError.
"""

import anyio
import pytest

from mcp import types
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import ServerCapabilities


@pytest.mark.anyio
async def test_respond_after_cancellation_is_silent() -> None:
    """respond() must return silently when _completed is True.

    This guards the race window in _handle_request where a CancelledNotification
    arrives after the handler returns but before respond() is called:
    1. cancel() sets _completed = True and sends an error response
    2. respond() is called — must return silently, not crash with AssertionError
    """
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)

    respond_raised = False
    respond_called = False

    async def run_server() -> None:
        nonlocal respond_raised, respond_called

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(tools=types.ToolsCapability(list_changed=False)),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:  # pragma: no branch
                if isinstance(message, Exception):  # pragma: no cover
                    raise message

                if isinstance(message, RequestResponder):
                    if isinstance(message.request, types.ListToolsRequest):  # pragma: no branch
                        with message:
                            # Simulate: concurrent cancellation set _completed = True
                            # (as if cancel() already ran and sent the error response)
                            message._completed = True  # type: ignore[reportPrivateUsage]
                            respond_called = True
                            try:
                                await message.respond(types.ListToolsResult(tools=[]))
                            except Exception:  # pragma: no cover
                                respond_raised = True
                        return

                if isinstance(message, types.ClientNotification):  # pragma: no cover
                    if isinstance(message, types.InitializedNotification):
                        return

    async def mock_client() -> None:
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="initialize",
                    params=types.InitializeRequestParams(
                        protocol_version=types.LATEST_PROTOCOL_VERSION,
                        capabilities=types.ClientCapabilities(),
                        client_info=types.Implementation(name="test-client", version="1.0.0"),
                    ).model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

        await server_to_client_receive.receive()  # InitializeResult

        await client_to_server_send.send(
            SessionMessage(types.JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list"))
        )

        # Drain any pending messages (server may have sent nothing for the silenced respond)
        with anyio.fail_after(3):
            try:
                while True:
                    await server_to_client_receive.receive()
            except anyio.EndOfStream:
                pass

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)
        tg.start_soon(mock_client)

    assert respond_called, "respond() was never invoked"
    assert not respond_raised, "respond() raised an exception after concurrent cancellation"
