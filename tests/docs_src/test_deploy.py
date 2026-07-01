"""`docs/run/deploy.md`: every claim the page makes, proved against the real SDK."""

import anyio
import httpx
import pytest
from mcp_types import (
    INVALID_PARAMS,
    CallToolResult,
    ElicitResult,
    InputRequiredResult,
    ResourceUpdatedNotification,
    SubscriptionFilter,
    SubscriptionsListenRequest,
    SubscriptionsListenRequestParams,
    SubscriptionsListenResult,
    TextContent,
)

from docs_src.deploy import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client, MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, RequestStateSecurity
from mcp.server.subscriptions import InMemorySubscriptionBus

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

_KEY = "0123456789abcdef0123456789abcdef"  # 32 bytes: the smallest secret the SDK accepts.

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "b", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


# -- the Host allowlist ----------------------------------------------------------------


async def test_the_default_app_rejects_a_real_hostname_before_mcp_runs() -> None:
    """The section's `!!! check`: without `transport_security=`, a deployed hostname gets the page's exact 421."""
    bare = MCPServer("Notes")
    app = bare.streamable_http_app()
    async with bare.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.example.com") as h:
            response = await h.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert (response.status_code, response.text) == (421, "Invalid Host header")


async def test_the_allowlisted_app_serves_its_hostname_and_still_rejects_others() -> None:
    """tutorial001: `allowed_hosts=` opens exactly the hostname you named, and nothing else."""
    transport = httpx.ASGITransport(app=tutorial001.app)
    async with tutorial001.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=transport, base_url="https://mcp.example.com") as http:
            allowed = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.example.com") as http:
            rejected = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert allowed.status_code == 200
    assert allowed.headers["mcp-session-id"]
    assert (rejected.status_code, rejected.text) == (421, "Invalid Host header")


# -- `requestState` across workers -----------------------------------------------------


async def _first_round(client: Client, amount: int) -> str:
    """Round one of `refund`: no answers yet, so the server returns the `InputRequiredResult`."""
    first = await client.session.call_tool("refund", {"amount": amount}, allow_input_required=True)
    assert isinstance(first, InputRequiredResult)
    assert first.request_state is not None
    return first.request_state


async def _retry(client: Client, amount: int, token: str) -> CallToolResult | InputRequiredResult:
    """The retry: same tool, same arguments, the elicited answer, and the echoed token."""
    return await client.session.call_tool(
        "refund",
        {"amount": amount},
        input_responses={"ok": ElicitResult(action="accept", content={"ok": True})},
        request_state=token,
        allow_input_required=True,
    )


def _assert_frozen_rejection(exc: pytest.ExceptionInfo[MCPError]) -> None:
    """The one wire shape every inbound `requestState` verification failure produces."""
    assert exc.value.error.code == INVALID_PARAMS
    assert exc.value.error.message == "Invalid or expired requestState"
    assert exc.value.error.data == {"reason": "invalid_request_state"}


async def test_a_retry_that_reaches_a_different_worker_is_rejected_by_default() -> None:
    """tutorial002: two default servers hold two `os.urandom(32)` keys, so a cross-instance retry is refused."""
    worker_a = tutorial002.make_server()
    worker_b = tutorial002.make_server()

    with anyio.fail_after(5):
        async with Client(worker_a) as on_a, Client(worker_b) as on_b:
            token = await _first_round(on_a, 120)
            with pytest.raises(MCPError) as exc:
                await _retry(on_b, 120, token)
            # Land back on the worker that minted the token and the identical retry completes.
            second = await _retry(on_a, 120, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert second.content == [TextContent(type="text", text="refunded $120")]


async def test_a_refund_the_human_declined_is_not_issued() -> None:
    """tutorial002/003: the second round reads the answer, so anything but an accepted ok is no refund."""
    server = tutorial002.make_server()
    with anyio.fail_after(5):
        async with Client(server) as client:
            token = await _first_round(client, 120)
            declined = await client.session.call_tool(
                "refund",
                {"amount": 120},
                input_responses={"ok": ElicitResult(action="decline")},
                request_state=token,
                allow_input_required=True,
            )
    assert isinstance(declined, CallToolResult)
    assert declined.content == [TextContent(type="text", text="refund cancelled")]


async def test_a_shared_key_and_name_let_any_worker_finish_a_round_trip() -> None:
    """tutorial003: instances built with the same key and the same name unseal what a sibling minted."""
    worker_a = tutorial003.make_server(_KEY)
    worker_b = tutorial003.make_server(_KEY)

    with anyio.fail_after(5):
        async with Client(worker_a) as on_a, Client(worker_b) as on_b:
            token = await _first_round(on_a, 120)
            second = await _retry(on_b, 120, token)

    assert isinstance(second, CallToolResult)
    assert not second.is_error
    assert second.content == [TextContent(type="text", text="refunded $120")]


async def test_a_shared_key_is_not_enough_without_a_shared_name() -> None:
    """The `!!! warning`: the server name is the default `audience` claim, so keys alone don't cross instances."""

    def named(name: str) -> MCPServer:
        mcp = MCPServer(name, request_state_security=RequestStateSecurity(keys=[_KEY]))

        @mcp.tool()
        async def refund(amount: int, ctx: Context) -> str | InputRequiredResult:
            if ctx.input_responses is None:
                return InputRequiredResult(input_requests={"ok": tutorial002.CONFIRM}, request_state="pending")
            return f"refunded ${amount}"

        return mcp

    with anyio.fail_after(5):
        async with Client(named("billing-1")) as on_one, Client(named("billing-2")) as on_two:
            token = await _first_round(on_one, 120)
            with pytest.raises(MCPError) as exc:
                await _retry(on_two, 120, token)

    _assert_frozen_rejection(exc)


# -- change notifications across replicas ----------------------------------------------


class _Stream:
    """Collects a listen stream's frames and lets the test await arrival counts."""

    def __init__(self) -> None:
        self.received: list[object] = []
        self._arrival = anyio.Event()

    async def handler(self, message: object) -> None:
        self.received.append(message)
        self._arrival.set()
        self._arrival = anyio.Event()

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while len(self.received) < count:
                await self._arrival.wait()


async def test_one_bus_carries_a_publish_on_one_replica_to_a_stream_on_another() -> None:
    """tutorial004: a `subscriptions/listen` stream on replica A hears a publish that happened on replica B."""
    bus = InMemorySubscriptionBus()
    replica_a = tutorial004.make_server(bus)
    replica_b = tutorial004.make_server(bus)
    stream = _Stream()

    with anyio.fail_after(10):
        await _listen_and_edit(replica_a, replica_b, stream)


async def _listen_and_edit(replica_a: MCPServer, replica_b: MCPServer, stream: _Stream) -> None:
    """Open a listen stream on replica A, edit on replica B, and wait for the update to cross the bus."""
    async with (
        Client(replica_a, mode="2026-07-28", message_handler=stream.handler) as on_a,
        Client(replica_b) as on_b,
    ):
        async with anyio.create_task_group() as tg:

            async def listen() -> None:
                await on_a.session.send_request(
                    SubscriptionsListenRequest(
                        params=SubscriptionsListenRequestParams(
                            notifications=SubscriptionFilter(resource_subscriptions=["note://todo"])
                        )
                    ),
                    SubscriptionsListenResult,
                )

            tg.start_soon(listen)
            await stream.wait_for(1)  # the acknowledgment: the stream is live on replica A

            await on_b.call_tool("edit_note", {"name": "todo", "text": "water plants"})
            await stream.wait_for(2)
            updated = stream.received[1]
            assert isinstance(updated, ResourceUpdatedNotification)
            assert updated.params.uri == "note://todo"

            tg.cancel_scope.cancel()
