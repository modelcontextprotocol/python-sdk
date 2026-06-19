"""Behaviour of the streamable-HTTP client transport under the 2026-07-28 stateless protocol.

A pinned session stamps the ``io.modelcontextprotocol/*`` `_meta` envelope onto every outgoing
request, and the streamable-HTTP transport derives the ``MCP-Protocol-Version`` / ``Mcp-Method`` /
``Mcp-Name`` headers from that body. These tests pin the composition through a real ``httpx``
request against a canned ``httpx.MockTransport`` -- no in-process 2026 server exists yet to record
the headers against. The header-derivation helpers themselves are unit-tested in
``tests/client/test_streamable_http.py``.
"""

import json

import anyio
import httpx
import pytest
from inline_snapshot import snapshot

from mcp.client import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation
from tests.interaction._connect import BASE_URL
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("client-transport:http:body-derived-headers")
@requirement("lifecycle:stateless:request-envelope")
async def test_pinned_session_post_carries_body_derived_headers_on_the_wire() -> None:
    """A pinned ``call_tool`` over streamable HTTP lands as a POST whose headers were derived from its body.

    Spec-mandated for the body-derived headers and the request envelope: this is the wire-seam proof
    that the ``ClientSession`` envelope stamp and the transport's header derivation are actually
    composed -- the streamable-HTTP POST wiring is driven through a real ``httpx`` request. A canned
    ``httpx.MockTransport`` stands in for the (not-yet-existing) 2026 server; the ``isError`` result
    skips the client's implicit ``tools/list`` output-schema fetch so the recorded log is the single
    POST.
    """
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        result = {"content": [{"type": "text", "text": "5"}], "isError": True, "resultType": "complete"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write),
            ClientSession(
                read,
                write,
                client_info=Implementation(name="pin-client", version="1.0.0"),
                protocol_version="2026-07-28",
            ) as session,
        ):
            await session.call_tool("add", {"a": 2, "b": 3})

    assert [r.method for r in recorded] == snapshot(["POST"])
    post = recorded[0]
    assert {k: v for k, v in post.headers.items() if k.startswith("mcp-")} == snapshot(
        {"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": "add"}
    )
    assert json.loads(post.content)["params"]["_meta"] == snapshot(
        {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "pin-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )


@requirement("client-transport:http:stateless-ignores-session-id")
async def test_pinned_session_ignores_returned_session_id_and_never_opens_get_or_delete() -> None:
    """A server-issued ``Mcp-Session-Id`` never reaches a pinned client's wire: only POSTs are sent.

    Spec-mandated for the stateless transport: the session-id capture, the standalone GET listening
    stream, and the DELETE-on-close are all gated on state a pinned session never produces (no
    ``initialize``, no ``notifications/initialized``), so even when the canned server volunteers a
    session id on every response the recorded log stays POST-only and no request echoes the id back.
    The successful ``tools/call`` triggers the client's implicit ``tools/list`` output-schema fetch so
    there is a second POST after the id was offered.
    """
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            result: dict[str, object] = {
                "tools": [{"name": "add", "inputSchema": {"type": "object"}}],
                "resultType": "complete",
                "ttlMs": 0,
                "cacheScope": "public",
            }
        else:
            result = {"content": [{"type": "text", "text": "5"}], "isError": False, "resultType": "complete"}
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, headers={"mcp-session-id": "srv-123"}
        )

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write),
            ClientSession(read, write, protocol_version="2026-07-28") as session,
        ):
            await session.call_tool("add", {"a": 2, "b": 3})

    assert [r.method for r in recorded] == snapshot(["POST", "POST"])
    assert all("mcp-session-id" not in r.headers for r in recorded)
