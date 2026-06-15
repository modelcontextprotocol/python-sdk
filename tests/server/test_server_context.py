"""Tests for the server-side `Context`.

`Context` extends `BaseContext` (forwarding to a `DispatchContext`) with
`lifespan`, `connection`, and request-scoped `log`. End-to-end tested over
`DirectDispatcher`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import anyio
import pytest

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.connection import Connection
from mcp.server.context import Context, ServerRequestContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.transport_context import TransportContext

from ..shared.conftest import direct_pair
from ..shared.test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


@dataclass
class _Lifespan:
    name: str


@dataclass
class _RequestWithHeaders:
    headers: Mapping[str, str]


@dataclass
class _RequestWithUser:
    scope: Mapping[str, Any]


def test_server_request_context_reads_headers_from_request_object():
    ctx = ServerRequestContext(
        session=cast(Any, object()),
        lifespan_context={},
        request=_RequestWithHeaders({"x-test": "present"}),
        transport=TransportContext(kind="jsonrpc", can_send_request=True),
    )

    assert ctx.headers == {"x-test": "present"}
    assert ctx.session_id is None


def test_server_request_context_reads_access_token_from_request_user():
    access_token = AccessToken(token="secret", client_id="client-1", scopes=["tools"])
    ctx = ServerRequestContext(
        session=cast(Any, object()),
        lifespan_context={},
        request=_RequestWithUser({"user": AuthenticatedUser(access_token)}),
        transport=TransportContext(kind="streamable-http", can_send_request=True),
    )

    assert ctx.access_token == access_token


@pytest.mark.anyio
async def test_context_exposes_lifespan_and_connection_and_forwards_base_context():
    captured: list[Context[_Lifespan]] = []
    conn = Connection.__new__(Connection)  # placeholder until running_pair gives us the dispatcher

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan] = Context(dctx, lifespan=_Lifespan("app"), connection=conn)
        captured.append(ctx)
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, server, *_):
        # Now we have the server dispatcher; build the real Connection bound to it.
        conn.__init__(server, has_standalone_channel=True, session_id="sess-1")
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
        ctx = captured[0]
        assert ctx.lifespan.name == "app"
        assert ctx.connection is conn
        assert ctx.transport.kind == "direct"
        assert ctx.can_send_request is True
        assert ctx.session_id == "sess-1"
        assert ctx.headers is None


@pytest.mark.anyio
async def test_context_log_sends_request_scoped_message_notification():
    crec = Recorder()
    _, c_notify = echo_handlers(crec)

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        await ctx.log("debug", "hello")
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request, client_on_notify=c_notify) as (
        client,
        *_,
    ):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
            await crec.notified.wait()
        method, params = crec.notifications[0]
        assert method == "notifications/message"
        assert params is not None and params["level"] == "debug" and params["data"] == "hello"


@pytest.mark.anyio
async def test_context_log_includes_logger_and_meta_when_supplied():
    crec = Recorder()
    _, c_notify = echo_handlers(crec)

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        await ctx.log("info", "x", logger="my.log", meta={"traceId": "t"})
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request, client_on_notify=c_notify) as (
        client,
        *_,
    ):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
            await crec.notified.wait()
        _, params = crec.notifications[0]
        assert params is not None
        assert params["logger"] == "my.log"
        assert params["_meta"] == {"traceId": "t"}
