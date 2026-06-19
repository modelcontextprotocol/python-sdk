"""Tests for BearerAuth — the minimal two-method bearer-token provider."""

from __future__ import annotations

import json

import httpx
import pytest

from mcp.client.auth import BearerAuth, UnauthorizedContext, UnauthorizedError
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

pytestmark = pytest.mark.anyio


def make_request(url: str = "https://api.example.com/mcp") -> httpx.Request:
    return httpx.Request("POST", url)


def make_response(status: int, *, request: httpx.Request, www_auth: str | None = None) -> httpx.Response:
    headers = {"WWW-Authenticate": www_auth} if www_auth else {}
    return httpx.Response(status, headers=headers, request=request)


# --- token() resolution ------------------------------------------------------


async def test_static_string_token_sets_authorization_header():
    auth = BearerAuth("my-api-key")
    request = make_request()

    flow = auth.async_auth_flow(request)
    sent = await flow.__anext__()

    assert sent.headers["Authorization"] == "Bearer my-api-key"

    with pytest.raises(StopAsyncIteration):
        await flow.asend(make_response(200, request=request))


async def test_sync_callable_token_resolved_per_request():
    calls = 0

    def get_token() -> str:
        nonlocal calls
        calls += 1
        return f"token-{calls}"

    auth = BearerAuth(get_token)

    for expected in ("token-1", "token-2"):
        request = make_request()
        flow = auth.async_auth_flow(request)
        sent = await flow.__anext__()
        assert sent.headers["Authorization"] == f"Bearer {expected}"
        with pytest.raises(StopAsyncIteration):
            await flow.asend(make_response(200, request=request))

    assert calls == 2


async def test_async_callable_token_awaited():
    async def get_token() -> str:
        return "async-token"

    auth = BearerAuth(get_token)
    request = make_request()

    flow = auth.async_auth_flow(request)
    sent = await flow.__anext__()

    assert sent.headers["Authorization"] == "Bearer async-token"


async def test_none_token_omits_authorization_header():
    auth = BearerAuth(lambda: None)
    request = make_request()

    flow = auth.async_auth_flow(request)
    sent = await flow.__anext__()

    assert "Authorization" not in sent.headers


async def test_no_token_source_omits_authorization_header():
    auth = BearerAuth()
    request = make_request()

    flow = auth.async_auth_flow(request)
    sent = await flow.__anext__()

    assert "Authorization" not in sent.headers


# --- 401 handling: no on_unauthorized handler --------------------------------


async def test_401_without_handler_raises_unauthorized_error():
    auth = BearerAuth("rejected-token")
    request = make_request()

    flow = auth.async_auth_flow(request)
    await flow.__anext__()

    with pytest.raises(UnauthorizedError, match="401 Unauthorized"):
        await flow.asend(make_response(401, request=request))


async def test_401_without_handler_includes_www_authenticate_in_error():
    auth = BearerAuth("rejected-token")
    request = make_request()

    flow = auth.async_auth_flow(request)
    await flow.__anext__()

    www_auth = 'Bearer resource_metadata="https://example.com/.well-known/oauth-protected-resource"'
    with pytest.raises(UnauthorizedError, match="WWW-Authenticate"):
        await flow.asend(make_response(401, request=request, www_auth=www_auth))


# --- 401 handling: with on_unauthorized handler ------------------------------


async def test_401_with_handler_retries_once_with_fresh_token():
    current = "old-token"
    token_calls = 0
    handler_calls = 0

    def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return current

    async def refresh(ctx: UnauthorizedContext) -> None:
        nonlocal current, handler_calls
        handler_calls += 1
        assert ctx.response.status_code == 401
        assert ctx.request.url == "https://api.example.com/mcp"
        current = "new-token"

    auth = BearerAuth(get_token, on_unauthorized=refresh)
    request = make_request()

    flow = auth.async_auth_flow(request)

    first = await flow.__anext__()
    assert first.headers["Authorization"] == "Bearer old-token"

    retry = await flow.asend(make_response(401, request=request))
    assert retry.headers["Authorization"] == "Bearer new-token"

    with pytest.raises(StopAsyncIteration):
        await flow.asend(make_response(200, request=request))

    assert token_calls == 2
    assert handler_calls == 1


async def test_401_on_retry_raises_unauthorized_error():
    async def noop(ctx: UnauthorizedContext) -> None:
        pass

    auth = BearerAuth("still-bad", on_unauthorized=noop)
    request = make_request()

    flow = auth.async_auth_flow(request)
    await flow.__anext__()
    await flow.asend(make_response(401, request=request))

    with pytest.raises(UnauthorizedError, match="after re-authentication"):
        await flow.asend(make_response(401, request=request))


async def test_handler_exception_propagates_without_retry():
    token_calls = 0

    def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return "token"

    async def signal_and_abort(ctx: UnauthorizedContext) -> None:
        raise RuntimeError("user action required")

    auth = BearerAuth(get_token, on_unauthorized=signal_and_abort)
    request = make_request()

    flow = auth.async_auth_flow(request)
    await flow.__anext__()

    with pytest.raises(RuntimeError, match="user action required"):
        await flow.asend(make_response(401, request=request))

    assert token_calls == 1  # no retry attempted


async def test_retry_state_is_per_operation_not_shared():
    """Each request gets a fresh generator, so a failed retry on one request
    doesn't prevent retry on the next. This is the httpx.Auth generator pattern's
    natural per-operation isolation — no instance state to reset or leak."""
    attempts: list[str] = []

    async def track(ctx: UnauthorizedContext) -> None:
        attempts.append("refresh")

    auth = BearerAuth("token", on_unauthorized=track)

    # First request: 401 → retry → 401 → UnauthorizedError
    request1 = make_request()
    flow1 = auth.async_auth_flow(request1)
    await flow1.__anext__()
    await flow1.asend(make_response(401, request=request1))
    with pytest.raises(UnauthorizedError):
        await flow1.asend(make_response(401, request=request1))

    # Second request: fresh generator, retry allowed again
    request2 = make_request()
    flow2 = auth.async_auth_flow(request2)
    await flow2.__anext__()
    retry = await flow2.asend(make_response(401, request=request2))
    assert retry.headers["Authorization"] == "Bearer token"
    with pytest.raises(StopAsyncIteration):
        await flow2.asend(make_response(200, request=request2))

    assert attempts == ["refresh", "refresh"]


async def test_retry_clears_stale_header_when_token_becomes_none():
    """If token() returns None on retry, the stale Authorization header from the
    first attempt must be cleared — not silently re-sent."""
    tokens = iter(["first", None])

    async def refresh(ctx: UnauthorizedContext) -> None:
        pass

    auth = BearerAuth(lambda: next(tokens), on_unauthorized=refresh)
    request = make_request()

    flow = auth.async_auth_flow(request)
    first = await flow.__anext__()
    assert first.headers["Authorization"] == "Bearer first"

    retry = await flow.asend(make_response(401, request=request))
    assert "Authorization" not in retry.headers


async def test_handler_can_read_response_body():
    """Response body is read before on_unauthorized, so handlers can inspect it
    even when the transport uses streaming (httpx stream() mode)."""
    captured: list[str] = []

    async def inspect_body(ctx: UnauthorizedContext) -> None:
        captured.append(ctx.response.text)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    auth = BearerAuth("bad", on_unauthorized=inspect_body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=auth) as client:
        with pytest.raises(UnauthorizedError):
            async with client.stream("POST", "https://api.example.com/mcp"):
                pass  # pragma: no cover — auth flow raises before stream body opens

    assert [json.loads(body) for body in captured] == [{"error": "invalid_token"}]


async def test_handler_receives_www_authenticate_header():
    captured: list[str] = []

    async def inspect(ctx: UnauthorizedContext) -> None:
        captured.append(ctx.response.headers.get("WWW-Authenticate", ""))

    auth = BearerAuth("token", on_unauthorized=inspect)
    request = make_request()

    flow = auth.async_auth_flow(request)
    await flow.__anext__()

    www_auth = 'Bearer scope="read write", resource_metadata="https://example.com/prm"'
    await flow.asend(make_response(401, request=request, www_auth=www_auth))

    assert captured == [www_auth]


# --- subclassing -------------------------------------------------------------


async def test_subclass_override_token_and_on_unauthorized():
    class RefreshingAuth(BearerAuth):
        def __init__(self) -> None:
            super().__init__()
            self.current = "initial"
            self.refreshed = False

        async def token(self) -> str | None:
            return self.current

        async def on_unauthorized(self, context: UnauthorizedContext) -> None:
            self.current = "refreshed"
            self.refreshed = True

    auth = RefreshingAuth()
    request = make_request()

    flow = auth.async_auth_flow(request)
    first = await flow.__anext__()
    assert first.headers["Authorization"] == "Bearer initial"

    retry = await flow.asend(make_response(401, request=request))
    assert retry.headers["Authorization"] == "Bearer refreshed"
    assert auth.refreshed is True


# --- httpx integration (wire-level) ------------------------------------------


async def test_e2e_with_mock_transport_sets_header():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    auth = BearerAuth("wire-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=auth) as client:
        response = await client.post("https://api.example.com/mcp", json={})

    assert response.status_code == 200
    assert captured[0].headers["Authorization"] == "Bearer wire-token"


async def test_e2e_with_mock_transport_retries_on_401():
    seen_tokens: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization")
        seen_tokens.append(token)
        if token == "Bearer old":
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})
        return httpx.Response(200, json={"ok": True})

    current = "old"

    async def refresh(ctx: UnauthorizedContext) -> None:
        nonlocal current
        current = "new"

    auth = BearerAuth(lambda: current, on_unauthorized=refresh)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=auth) as client:
        response = await client.post("https://api.example.com/mcp", json={})

    assert response.status_code == 200
    assert seen_tokens == ["Bearer old", "Bearer new"]


async def test_e2e_unauthorized_error_propagates():
    def always_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    auth = BearerAuth("rejected")
    async with httpx.AsyncClient(transport=httpx.MockTransport(always_401), auth=auth) as client:
        with pytest.raises(UnauthorizedError):
            await client.post("https://api.example.com/mcp", json={})


# --- sync client guard -------------------------------------------------------


def test_sync_client_raises_clear_error():
    auth = BearerAuth("token")
    with pytest.raises(RuntimeError, match="async-only"):
        with httpx.Client(auth=auth) as client:
            client.get("https://api.example.com/mcp")


# --- streamable_http_client integration --------------------------------------


async def test_streamable_http_client_rejects_both_auth_and_http_client():
    auth = BearerAuth("token")
    http_client = httpx.AsyncClient()

    with pytest.raises(ValueError, match="either `http_client` or `auth`"):
        async with streamable_http_client("https://example.com/mcp", auth=auth, http_client=http_client):
            pass  # pragma: no cover

    await http_client.aclose()


async def test_create_mcp_http_client_passes_auth():
    auth = BearerAuth("factory-token")
    async with create_mcp_http_client(auth=auth) as client:
        assert client.auth is auth
