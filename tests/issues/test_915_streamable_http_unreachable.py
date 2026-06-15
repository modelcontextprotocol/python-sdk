import json
from typing import cast

import anyio
import httpx
import pytest

from mcp import ClientSession
from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import LATEST_PROTOCOL_VERSION, RootsListChangedNotification

pytestmark = pytest.mark.anyio


def _contains_cancel_scope_error(exc: BaseException) -> bool:
    if isinstance(exc, RuntimeError) and "Attempted to exit cancel scope" in str(exc):
        return True

    raw_grouped_exceptions = getattr(exc, "exceptions", ())
    if isinstance(raw_grouped_exceptions, tuple) and raw_grouped_exceptions:
        grouped_exceptions = cast(tuple[BaseException, ...], raw_grouped_exceptions)
        return any(_contains_cancel_scope_error(inner) for inner in grouped_exceptions)

    return any(_contains_cancel_scope_error(inner) for inner in (exc.__cause__, exc.__context__) if inner is not None)


def test_contains_cancel_scope_error_follows_exception_tree() -> None:
    cancel_scope_error = RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")
    wrapped = RuntimeError("wrapped")
    wrapped.__cause__ = cancel_scope_error

    assert _contains_cancel_scope_error(wrapped)


def test_contains_cancel_scope_error_follows_grouped_exceptions() -> None:
    cancel_scope_error = RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")

    class DummyGroup(Exception):
        def __init__(self) -> None:
            self.exceptions = (cancel_scope_error,)

    assert _contains_cancel_scope_error(DummyGroup())


async def test_session_group_streamable_http_connect_error_is_catchable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("server unavailable", request=request)

    def mock_http_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=timeout,
            transport=httpx.MockTransport(raise_connect_error),
        )

    monkeypatch.setattr("mcp.client.session_group.create_mcp_http_client", mock_http_client)

    async with ClientSessionGroup() as group:
        with anyio.fail_after(5), pytest.raises(MCPError) as exc_info:
            await group.connect_to_server(StreamableHttpParameters(url="http://example.invalid/mcp"))

    assert "Transport error: server unavailable" in exc_info.value.error.message
    assert not _contains_cancel_scope_error(exc_info.value)


async def test_streamable_http_notification_transport_error_does_not_crash() -> None:
    async def handle_request(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        if data.get("method") == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": data["id"],
                    "result": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "serverInfo": {"name": "mock-server", "version": "1.0.0"},
                    },
                },
            )

        raise httpx.ConnectError("notification failed", request=request)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client,
        streamable_http_client("http://example.invalid/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        await session.send_notification(RootsListChangedNotification(method="notifications/roots/list_changed"))
        await anyio.sleep(0)
