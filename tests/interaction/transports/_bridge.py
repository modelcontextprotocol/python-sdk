"""An in-process, full-duplex HTTP transport for driving ASGI applications from httpx.

`httpx.ASGITransport` buffers the whole response before handing it to the caller, so a server that
streams — the streamable HTTP transport's SSE responses — deadlocks on any server-initiated
exchange nested inside a still-open call. This transport runs the application as a background task
and forwards each `http.response.body` chunk the moment it is sent, all on one event loop.

The contract, pinned by `test_bridge.py`: the request body is buffered before the application is
invoked; the response streams chunk by chunk; closing the response or the client delivers
`http.disconnect`; an exception before `http.response.start` fails the originating request, while
a later failure is visible only through the response itself — the same signal a real socket gives.

The application task group is opened and closed by `httpx.AsyncClient`'s own context manager.
"""

import math
from collections.abc import AsyncIterator
from types import TracebackType

import anyio
import anyio.abc
import httpx
from anyio.streams.memory import MemoryObjectReceiveStream
from starlette.types import ASGIApp, Message, Scope

from mcp.shared._compat import resync_tracer


class _StreamingResponseBody(httpx.AsyncByteStream):
    """Streams response chunks as produced; closing it delivers `http.disconnect` to the application."""

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
    """Drive an ASGI application in-process, streaming each response as it is produced.

    Closing cancels running application tasks so teardown can never hang; `cancel_on_close=False`
    instead waits for the application's own disconnect handling (the legacy SSE server transport
    relies on this for resource cleanup).
    """

    _task_group: anyio.abc.TaskGroup

    def __init__(self, app: ASGIApp, *, cancel_on_close: bool = True) -> None:
        self._app = app
        self._cancel_on_close = cancel_on_close

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
        # By now httpx has closed every streamed response, delivering `http.disconnect` to each application task.
        if self._cancel_on_close:
            self._task_group.cancel_scope.cancel()
        await self._task_group.__aexit__(exc_type, exc_value, traceback)
        await resync_tracer()

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
            except Exception as exc:  # Outermost boundary: a crash fails this request, never the shared task group.
                application_error = exc
            finally:
                response_started.set()
                await chunk_writer.aclose()

        self._task_group.start_soon(run_application)
        try:
            await response_started.wait()
            if application_error is not None:
                raise application_error
        except BaseException:
            # No response will be built: close the reader the body would have owned and signal disconnect.
            client_disconnected.set()
            await chunk_reader.aclose()
            raise
        return httpx.Response(
            status_code=response_status,
            headers=response_headers,
            stream=_StreamingResponseBody(chunk_reader, client_disconnected),
            request=request,
        )
