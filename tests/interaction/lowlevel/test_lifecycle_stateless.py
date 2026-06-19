"""Stateless lifecycle at protocol version 2026-07-28, driven through a bare ClientSession.

Under the 2026-07-28 lifecycle the initialize handshake is replaced by a per-request envelope:
every request carries the protocol version, client info, and client capabilities under
``params._meta`` and the server never sees an ``initialize`` frame. These tests pin the session
to that version and observe the outgoing JSON-RPC frame directly, so they drop below the
``connect`` fixture to a bare ClientSession over in-process memory streams. No 2026-aware Server
exists yet, so the receiving side is a scripted peer that hand-builds the wire response — reserve
this pattern for behaviour no real server can be made to produce.
"""

from contextlib import nullcontext

import anyio
import pytest
from inline_snapshot import snapshot

from mcp.client import ClientSession
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolResult,
    Implementation,
    InitializeResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    ServerCapabilities,
)
from tests.interaction._helpers import RecordingTransport
from tests.interaction._modern_vocab import MODERN_BODY_TOKENS
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:stateless:request-envelope")
async def test_pinned_session_stamps_the_envelope_meta_on_every_request_and_never_initializes() -> None:
    """A pinned session's first request is the feature request itself, carrying the three-key envelope.

    The scripted peer asserts the only frame on the wire is ``tools/list`` (no ``initialize``, no
    ``notifications/initialized``) and answers with a hand-built 2026-07-28 result; the test then
    snapshots the captured ``params._meta``.
    """
    received: list[JSONRPCRequest] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        message = await server_read.receive()
        assert isinstance(message, SessionMessage)
        request = message.message
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "tools/list"
        received.append(request)
        result = ListToolsResult(tools=[], cache_scope="public", ttl_ms=0)
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as tg,
        ClientSession(
            client_read,
            client_write,
            client_info=Implementation(name="pin-client", version="1.0.0"),
            protocol_version="2026-07-28",
        ) as session,
    ):
        tg.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            result = await session.list_tools()
        assert isinstance(result, ListToolsResult)

    assert len(received) == 1
    only = received[0]
    assert only.params is not None
    assert only.params["_meta"] == snapshot(
        {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "pin-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )


@requirement("lifecycle:stateless:no-initialize")
async def test_initialize_on_a_pinned_session_is_rejected_before_any_frame_is_sent() -> None:
    """``initialize()`` on a pinned session raises immediately, never reaching the wire.

    After the rejection the client's send stream is closed and the server-side read drains to
    EndOfStream with no buffered frame, proving the guard fired before any write.
    """
    async with create_client_server_memory_streams() as ((client_read, client_write), (server_read, _server_write)):
        async with ClientSession(client_read, client_write, protocol_version="2026-07-28") as session:
            with anyio.fail_after(5):
                with pytest.raises(RuntimeError) as exc_info:  # pragma: no branch
                    await session.initialize()
        assert str(exc_info.value) == snapshot(
            "initialize() must not be called on a session pinned to a stateless protocol version"
        )
        # Nothing left the client: closing the sender turns an empty buffer into EndOfStream.
        await client_write.aclose()
        with anyio.fail_after(5):
            with pytest.raises(anyio.EndOfStream):  # pragma: no branch
                await server_read.receive()


@requirement("lifecycle:stateless:caller-meta-preserved")
async def test_caller_supplied_meta_is_preserved_under_the_envelope_merge() -> None:
    """A caller's ``meta=`` keys survive the pinned session's envelope stamp on the same ``_meta`` object.

    The envelope merge is additive, so a caller-supplied key sits alongside the three
    ``io.modelcontextprotocol/*`` keys rather than being overwritten. The scripted peer captures the
    single ``tools/call`` frame and answers with an ``is_error`` result so the client skips its
    implicit output-schema fetch; the test then snapshots the captured ``params._meta``.
    """
    received: list[JSONRPCRequest] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        message = await server_read.receive()
        assert isinstance(message, SessionMessage)
        request = message.message
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "tools/call"
        received.append(request)
        result = CallToolResult(content=[], is_error=True)
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as tg,
        ClientSession(
            client_read,
            client_write,
            client_info=Implementation(name="pin-client", version="1.0.0"),
            protocol_version="2026-07-28",
        ) as session,
    ):
        tg.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            result = await session.call_tool("add", {"a": 2, "b": 3}, meta={"custom-key": "x"})
        assert isinstance(result, CallToolResult)

    assert len(received) == 1
    only = received[0]
    assert only.params is not None
    assert only.params["_meta"] == snapshot(
        {
            "custom-key": "x",
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "pin-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )


@requirement("lifecycle:stateless:unpinned-legacy-wire")
async def test_unpinned_session_round_trip_carries_no_modern_protocol_vocabulary() -> None:
    """An unpinned session's handshake-plus-request emits no 2026-07-28 vocabulary on any frame.

    The JSON-RPC-seam complement to ``test_legacy_wire.py`` (which records the HTTP seam): a
    ``RecordingTransport`` wrapped around the client side of the in-process memory streams captures
    every frame in either direction, the scripted peer answers ``initialize`` at ``2025-11-25`` then
    ``tools/list``, and every captured frame body is scanned for :data:`MODERN_BODY_TOKENS` so any
    leak of the envelope keys, the result-envelope fields, or the version literal onto the legacy
    session path fails here.
    """

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        init = await server_read.receive()
        assert isinstance(init, SessionMessage)
        assert isinstance(init.message, JSONRPCRequest)
        assert init.message.method == "initialize"
        result = InitializeResult(
            protocol_version="2025-11-25",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="legacy-server", version="0.0.0"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=init.message.id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )
        initialized = await server_read.receive()
        assert isinstance(initialized, SessionMessage)
        assert isinstance(initialized.message, JSONRPCNotification)
        listing = await server_read.receive()
        assert isinstance(listing, SessionMessage)
        assert isinstance(listing.message, JSONRPCRequest)
        assert listing.message.method == "tools/list"
        await server_write.send(
            SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=listing.message.id, result={"tools": []}))
        )

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        recording = RecordingTransport(nullcontext(client_streams))
        async with (
            anyio.create_task_group() as tg,
            recording as (client_read, client_write),
            ClientSession(client_read, client_write) as session,
        ):
            tg.start_soon(scripted_server, server_streams)
            with anyio.fail_after(5):
                await session.initialize()
                result = await session.list_tools()
            assert isinstance(result, ListToolsResult)

    frames = list(recording.sent) + [m for m in recording.received if isinstance(m, SessionMessage)]
    methods = [m.message.method for m in recording.sent if isinstance(m.message, JSONRPCRequest | JSONRPCNotification)]
    assert methods == snapshot(["initialize", "notifications/initialized", "tools/list"])
    bodies = [m.message.model_dump_json(by_alias=True, exclude_none=True) for m in frames]
    leaked = sorted({token for token in MODERN_BODY_TOKENS for body in bodies if token in body})
    assert leaked == []
