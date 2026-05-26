"""An in-process, full-duplex HTTP transport for driving ASGI applications from httpx.

`httpx.ASGITransport` runs the application to completion and only then hands the buffered
response to the caller, so a server that streams its response — the streamable HTTP transport's
SSE responses — can never converse with the client mid-request: a server-initiated request
nested inside a still-open call deadlocks. `StreamingASGITransport` removes that limitation by
running the application as a background task and forwarding every `http.response.body` chunk to
the client the moment it is sent. Everything happens on the one event loop: no sockets, no
threads, no sleeps, no extra dependencies.

The behavioural contract, pinned by `test_bridge.py`:

- The request body is buffered before the application is invoked (MCP requests are small JSON
  documents); the response streams chunk by chunk.
- Closing the response — or the whole client — delivers `http.disconnect` to the application,
  exactly as a real server sees when its peer goes away.
- An exception the application raises before sending `http.response.start` fails the originating
  request with that same exception. After the response has started, a failure is visible to the
  client only through the response itself (status code, truncated body) — the same signal a real
  server over a real socket would give.

The transport owns an anyio task group for the application tasks; it is opened and closed by
`httpx.AsyncClient`'s own context manager, so use the client as a context manager (the suite
always does).
"""

import math
from collections.abc import AsyncIterator
from types import TracebackType

import anyio
import anyio.abc
import httpx
from anyio.streams.memory import MemoryObjectReceiveStream
from starlette.types import ASGIApp, Message, Scope


class _StreamingResponseBody(httpx.AsyncByteStream):
    """A response body that yields chunks as the application produces them.

    Closing it tells the application the client has gone away (`http.disconnect`), mirroring a
    peer that drops the connection mid-response.
    """

    def __init__(self, chunks: MemoryObjectReceiveStream[bytes], client_disconnected: anyio.Event) -> None:
        self._chunks = chunks
        self._client_disconnected = client_disconnected

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self._client_disconnected.set()
        await self._chunks.aclose()


class StreamingASGITransport(httpx.AsyncBaseTransport):
    """Drive an ASGI application in-process, streaming each response as it is produced."""

    _task_group: anyio.abc.TaskGroup

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __aenter__(self) -> "StreamingASGITransport":
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        # Any application task still running at this point is serving a client that no longer
        # exists; cancel rather than wait so harness teardown can never hang.
        self._task_group.cancel_scope.cancel()
        await self._task_group.__aexit__(exc_type, exc_value, traceback)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        request_body = b"".join([chunk async for chunk in request.stream])

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?", maxsplit=1)[0],
            "query_string": request.url.query,
            "root_path": "",
            "headers": [(name.lower(), value) for name, value in request.headers.raw],
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 1234),
        }

        request_delivered = False
        client_disconnected = anyio.Event()
        response_started = anyio.Event()
        response_status = 0
        response_headers: list[tuple[bytes, bytes]] = []
        application_error: Exception | None = None
        chunk_writer, chunk_reader = anyio.create_memory_object_stream[bytes](math.inf)

        async def receive_request() -> Message:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": request_body, "more_body": False}
            await client_disconnected.wait()
            return {"type": "http.disconnect"}

        async def send_response(message: Message) -> None:
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
                response_started.set()
                return
            assert message["type"] == "http.response.body"
            body: bytes = message.get("body", b"")
            if body:
                await chunk_writer.send(body)
            if not message.get("more_body", False):
                await chunk_writer.aclose()

        async def run_application() -> None:
            nonlocal application_error
            try:
                await self._app(scope, receive_request, send_response)
            except Exception as exc:  # The bridge is the application's outermost boundary: a crash
                # must fail the originating request (or show up in the already-started response),
                # never tear down the task group shared with every other in-flight request.
                application_error = exc
            finally:
                response_started.set()
                await chunk_writer.aclose()

        self._task_group.start_soon(run_application)
        await response_started.wait()
        if application_error is not None:
            # No response will be built, so close the reader the response body would have owned.
            await chunk_reader.aclose()
            raise application_error
        return httpx.Response(
            status_code=response_status,
            headers=response_headers,
            stream=_StreamingResponseBody(chunk_reader, client_disconnected),
            request=request,
        )
