from collections.abc import Callable

import httpx2
import pytest

from mcp.server.mcpserver.resources import HttpResource

pytestmark = pytest.mark.anyio


def mock_client_factory(handler: Callable[[httpx2.Request], httpx2.Response]) -> Callable[[], httpx2.AsyncClient]:
    """An `httpx2.AsyncClient` stand-in whose requests are answered by `handler`."""
    real_client = httpx2.AsyncClient

    def factory() -> httpx2.AsyncClient:
        return real_client(transport=httpx2.MockTransport(handler))

    return factory


async def test_http_resource_reads_the_response_body_as_text(monkeypatch: pytest.MonkeyPatch):
    """`HttpResource.read()` fetches its URL and returns the response text."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=f"body of {request.url}")

    monkeypatch.setattr(httpx2, "AsyncClient", mock_client_factory(handler))
    resource = HttpResource(uri="resource://remote", url="http://example.test/data")
    assert await resource.read() == "body of http://example.test/data"


async def test_http_resource_read_raises_for_error_status(monkeypatch: pytest.MonkeyPatch):
    """A non-2xx response surfaces as `httpx2.HTTPStatusError` rather than being read as content."""
    monkeypatch.setattr(httpx2, "AsyncClient", mock_client_factory(lambda request: httpx2.Response(404)))
    resource = HttpResource(uri="resource://remote", url="http://example.test/missing")
    with pytest.raises(httpx2.HTTPStatusError):
        await resource.read()
