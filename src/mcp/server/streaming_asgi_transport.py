"""
A modified version of httpx.ASGITransport that supports streaming responses.

This transport runs the ASGI app as a separate anyio task, allowing it to
handle streaming responses like SSE where the app doesn't terminate until
the connection is closed.

This is only intended for writing tests for the SSE transport.
"""

import typing
from typing import Any, cast

import anyio
import anyio.abc
import anyio.streams.memory
from httpx._models import Request, Response
from httpx._transports.base import AsyncBaseTransport
from httpx._types import AsyncByteStream
from starlette.types import ASGIApp, Receive, Scope, Send


class StreamingASGITransport(AsyncBaseTransport):
    """
    A custom AsyncTransport that handles sending requests directly to an ASGI app
    and supports streaming responses like SSE.

    Unlike the standard ASGITransport, this transport runs the ASGI app in a
    separate anyio task, allowing it to handle responses from apps that don't
    terminate immediately (like SSE endpoints).

    Arguments:

    * `app` - The ASGI application.
    * `raise_app_exceptions` - Boolean indicating if exceptions in the application
       should be raised. Default to `True`. Can be set to `False` for use cases
       such as testing the content of a client 500 response.
    * `root_path` - The root path on which the ASGI application should be mounted.
    * `client` - A two-tuple indicating the client IP and port of incoming requests.
    * `response_timeout` - Timeout in seconds to wait for the initial response.
       Default is 10 seconds.

    TODO: https://github.com/encode/httpx/pull/3059 is adding something similar to
    upstream httpx. When that merges, we should delete this & switch back to the
    upstream implementation.
    """

    def __init__(
        self,
        app: ASGIApp,
        task_group: anyio.abc.TaskGroup,
        raise_app_exceptions: bool = True,
        root_path: str = "",
        client: tuple[str, int] = ("127.0.0.1", 123),
    ) -> None:
        self.app = app
        self.raise_app_exceptions = raise_app_exceptions
        self.root_path = root_path
        self.client = client
        self.task_group = task_group

    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)

        # ASGI scope.
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for (k, v) in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": self.client,
            "root_path": self.root_path,
        }

        # Request body
        request_body_chunks = request.stream.__aiter__()
        request_complete = False

        # Response state
        status_code = 499
        response_headers = None
        response_started = False
        response_complete = anyio.Event()
        initial_response_ready = anyio.Event()

        # Synchronization for streaming response
        asgi_send_channel, asgi_receive_channel = anyio.create_memory_object_stream[
            dict[str, Any]
        ](100)
        content_send_channel, content_receive_channel = (
            anyio.create_memory_object_stream[bytes](100)
        )

        # ASGI callables.
        async def receive() -> dict[str, Any]:
            nonlocal request_complete

            if request_complete:
                await response_complete.wait()
                return {"type": "http.disconnect"}

            try:
                body = await request_body_chunks.__anext__()
            except StopAsyncIteration:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.request", "body": body, "more_body": True}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code, response_headers, response_started

            await asgi_send_channel.send(message)

        # Start the ASGI application in a separate task
        async def run_app() -> None:
            try:
                # Cast the receive and send functions to the ASGI types
                await self.app(
                    cast(Scope, scope), cast(Receive, receive), cast(Send, send)
                )
            except Exception:
                if self.raise_app_exceptions:
                    raise

                if not response_started:
                    await asgi_send_channel.send(
                        {"type": "http.response.start", "status": 500, "headers": []}
                    )

                await asgi_send_channel.send(
                    {"type": "http.response.body", "body": b"", "more_body": False}
                )
            finally:
                await asgi_send_channel.aclose()

        # Process messages from the ASGI app
        async def process_messages() -> None:
            nonlocal status_code, response_headers, response_started

            try:
                async with asgi_receive_channel:
                    async for message in asgi_receive_channel:
                        if message["type"] == "http.response.start":
                            assert not response_started
                            status_code = message["status"]
                            response_headers = message.get("headers", [])
                            response_started = True

                            # As soon as we have headers, we can return a response
                            initial_response_ready.set()

                        elif message["type"] == "http.response.body":
                            body = message.get("body", b"")
                            more_body = message.get("more_body", False)

                            if body and request.method != "HEAD":
                                await content_send_channel.send(body)

                            if not more_body:
                                response_complete.set()
                                await content_send_channel.aclose()
                                break
            finally:
                # Ensure events are set even if there's an error
                initial_response_ready.set()
                response_complete.set()
                await content_send_channel.aclose()

        # Create tasks for running the app and processing messages
        self.task_group.start_soon(run_app)
        self.task_group.start_soon(process_messages)

        # Wait for the initial response or timeout
        await initial_response_ready.wait()

        # Create a streaming response
        return Response(
            status_code,
            headers=response_headers,
            stream=StreamingASGIResponseStream(content_receive_channel),
        )


class StreamingASGIResponseStream(AsyncByteStream):
    """
    A modified ASGIResponseStream that supports streaming responses.

    This class extends the standard ASGIResponseStream to handle cases where
    the response body continues to be generated after the initial response
    is returned.
    """

    def __init__(
        self,
        receive_channel: anyio.streams.memory.MemoryObjectReceiveStream[bytes],
    ) -> None:
        self.receive_channel = receive_channel

    async def __aiter__(self) -> typing.AsyncIterator[bytes]:
        try:
            async for chunk in self.receive_channel:
                yield chunk
        finally:
            await self.receive_channel.aclose()
