"""Tests for StreamableHTTP server DNS rebinding protection."""

import gc
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sse_starlette.sse import AppStatus
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from tests.interaction.transports import StreamingASGITransport

SERVER_NAME = "test_streamable_http_security_server"

# The in-process app is mounted at this origin purely so URLs are well-formed and the default
# Host header is a localhost form; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

# v1's streamable-HTTP server transport leaks a handful of anyio memory streams on teardown when
# run in process; the old subprocess harness never observed them. The interaction suite registers
# the same two scoped filters globally from tests/interaction/conftest.py (see the comment there),
# but they only take effect when that package's conftest is loaded; these markers keep the tests
# that complete the initialize handshake passing in isolated runs. The filters are scoped to
# anyio's MemoryObject*Stream leak signature so an unrelated leak still fails the suite.
pytestmark = [
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:ResourceWarning"),
]


@pytest.fixture(autouse=True)
def _collect_leaked_streams() -> Iterator[None]:
    """Garbage-collect each test's leaked memory streams inside its own teardown.

    The filterwarnings marks above only apply while a test in this file is the
    active warning context. The leaked streams sit in reference cycles, so without
    a forced collection their deallocator warnings fire wherever the garbage
    collector happens to run next: during an unrelated test (failing it, since the
    global ``filterwarnings = ["error"]`` has no ignore there) or at pytest's
    session-unconfigure unraisable sweep (exit code 1 after all tests passed when
    running without xdist, e.g. ``-n 0`` for ``--pdb`` debugging).
    """
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _reset_sse_starlette_exit_event() -> Iterator[None]:
    """Reset sse-starlette's module-global exit Event around each test.

    sse-starlette <3.0 (allowed by this branch's dependency floor; CI's lowest-direct leg
    installs it) stores an `anyio.Event` on the `AppStatus` class the first time an
    `EventSourceResponse` runs; that Event is bound to the test's event loop and breaks every
    subsequent in-process SSE response. sse-starlette 3.x switched to a ContextVar and has no
    such attribute. Resetting on both sides of the test keeps this module immune to a stale
    Event left behind by an earlier test on the same worker as well as cleaning up after its
    own. This mirrors the autouse fixtures in tests/shared/test_sse.py and
    tests/interaction/conftest.py.
    """
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        # setattr keeps pyright happy: the locked sse-starlette 3.x has no such attribute.
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover
    yield
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover


@asynccontextmanager
async def streamable_http_security_client(
    security_settings: TransportSecuritySettings | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx client served in process by a StreamableHTTP app with the given settings."""
    session_manager = StreamableHTTPSessionManager(app=Server(SERVER_NAME), security_settings=security_settings)
    app = Starlette(routes=[Mount("/", app=session_manager.handle_request)])

    async with session_manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as client:
            yield client


def _base_headers() -> dict[str, str]:
    """Headers every well-formed request carries, so each test varies only the header under test."""
    return {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _initialize_body() -> dict[str, object]:
    """A minimal initialize POST body; these tests assert header validation, not the handshake."""
    return {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}}


@pytest.mark.anyio
async def test_streamable_http_security_default_settings() -> None:
    """With default security settings, a request with localhost headers is served."""
    async with streamable_http_security_client() as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers())
        assert response.status_code == 200
        assert "mcp-session-id" in response.headers


@pytest.mark.anyio
async def test_streamable_http_security_invalid_host_header() -> None:
    """A Host header outside allowed_hosts is rejected with 421."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True)

    async with streamable_http_security_client(security_settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "evil.com"})
        assert response.status_code == 421
        assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_origin_header() -> None:
    """An Origin header outside allowed_origins is rejected with 403."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"])

    async with streamable_http_security_client(security_settings) as client:
        response = await client.post(
            "/", json=_initialize_body(), headers=_base_headers() | {"Origin": "http://evil.com"}
        )
        assert response.status_code == 403
        assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_content_type() -> None:
    """A POST whose Content-Type is not application/json (or is missing) is rejected with 400."""
    async with streamable_http_security_client() as client:
        response = await client.post("/", headers=_base_headers() | {"Content-Type": "text/plain"}, content="test")
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"

        response = await client.post("/", headers={"Accept": "application/json, text/event-stream"}, content="test")
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_streamable_http_security_disabled() -> None:
    """With protection explicitly disabled, a disallowed Host is still served."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    async with streamable_http_security_client(settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "evil.com"})
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_custom_allowed_hosts() -> None:
    """A custom entry in allowed_hosts is served."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )

    async with streamable_http_security_client(settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "custom.host"})
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_get_request() -> None:
    """GET requests pass the same Host validation before any session handling."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1"])

    async with streamable_http_security_client(security_settings) as client:
        response = await client.get("/", headers={"Accept": "text/event-stream", "Host": "evil.com"})
        assert response.status_code == 421
        assert response.text == "Invalid Host header"

        response = await client.get("/", headers={"Accept": "text/event-stream", "Host": "127.0.0.1"})
        # An allowed host passes security and fails on session validation instead.
        assert response.status_code == 400
        body = response.json()
        assert "Missing session ID" in body["error"]["message"]
