"""Regression test for issue #1363: StreamableHTTP race causing ClosedResourceError.

When a request fails validation early (e.g. bad Accept header), transport termination
closes all streams while the message_router task may still be suspended at a checkpoint
inside its `async for` over write_stream_reader; on resume it hit the closed stream and
raised ClosedResourceError.
"""

import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import anyio.to_thread
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

SERVER_NAME = "test_race_condition_server"


class RaceConditionTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)


def create_app(json_response: bool = False) -> Starlette:
    app = RaceConditionTestServer()

    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=json_response,
        stateless=True,  # stateless mode triggers the race
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    routes = [
        Mount("/", app=session_manager.handle_request),
    ]

    return Starlette(routes=routes, lifespan=lifespan)


class ServerThread(threading.Thread):
    """Thread that runs the ASGI application lifespan in a separate event loop."""

    def __init__(self, app: Starlette):
        super().__init__(daemon=True)
        self.app = app
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()

    def run(self) -> None:
        async def run_lifespan():
            lifespan_context = getattr(self.app.router, "lifespan_context", None)
            assert lifespan_context is not None  # Tests always create apps with lifespan
            async with lifespan_context(self.app):
                # Signal readiness only after lifespan startup, when the session manager can handle requests
                self._ready_event.set()
                while not self._stop_event.is_set():
                    await anyio.sleep(0.1)

        anyio.run(run_lifespan)

    def wait_ready(self, timeout: float = 5.0) -> None:
        """Block until the lifespan has started; call from a worker thread, not the event loop."""
        assert self._ready_event.wait(timeout), "server thread did not start its lifespan in time"

    def stop(self) -> None:
        self._stop_event.set()


def check_logs_for_race_condition_errors(caplog: pytest.LogCaptureFixture, test_name: str) -> None:
    """Fail the test if race condition errors (ClosedResourceError) appear in captured logs."""
    errors_found: list[str] = []

    for record in caplog.records:  # pragma: lax no cover
        message = record.getMessage()
        if "ClosedResourceError" in message:
            errors_found.append("ClosedResourceError")
        if "Error in message router" in message:
            errors_found.append("Error in message router")
        if "anyio.ClosedResourceError" in message:
            errors_found.append("anyio.ClosedResourceError")

    if errors_found:  # pragma: no cover
        error_msg = f"Test '{test_name}' found race condition errors in logs: {', '.join(set(errors_found))}\n"
        error_msg += "Log records:\n"
        for record in caplog.records:
            if any(err in record.getMessage() for err in ["ClosedResourceError", "Error in message router"]):
                error_msg += f"  {record.levelname}: {record.getMessage()}\n"
        pytest.fail(error_msg)


@pytest.mark.anyio
async def test_race_condition_invalid_accept_headers(caplog: pytest.LogCaptureFixture):
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.to_thread.run_sync(server_thread.wait_ready)

        # ERROR level suppresses the expected validation WARNINGs
        with caplog.at_level(logging.ERROR):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "application/json",  # Missing text/event-stream
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 406

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "text/event-stream",  # Missing application/json
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 406

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "text/plain",  # Invalid Accept header
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 406

            # Give background tasks time to complete
            await anyio.sleep(0.2)

    finally:
        server_thread.stop()
        server_thread.join(timeout=5.0)
        check_logs_for_race_condition_errors(caplog, "test_race_condition_invalid_accept_headers")


@pytest.mark.anyio
async def test_race_condition_invalid_content_type(caplog: pytest.LogCaptureFixture):
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.to_thread.run_sync(server_thread.wait_ready)

        # ERROR level suppresses the expected validation WARNINGs
        with caplog.at_level(logging.ERROR):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "text/plain",  # Invalid Content-Type
                    },
                )
                assert response.status_code == 400

            # Give background tasks time to complete
            await anyio.sleep(0.2)

    finally:
        server_thread.stop()
        server_thread.join(timeout=5.0)
        check_logs_for_race_condition_errors(caplog, "test_race_condition_invalid_content_type")


@pytest.mark.anyio
async def test_race_condition_message_router_async_for(caplog: pytest.LogCaptureFixture):
    """Reproduce the race on the `is_json_response_enabled` branch via json_response=True.

    ClosedResourceError appeared when message_router was suspended in its async-for
    while transport cleanup closed streams concurrently.
    """
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.to_thread.run_sync(server_thread.wait_ready)

        # ERROR level suppresses the expected validation WARNINGs
        with caplog.at_level(logging.ERROR):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code in (200, 201)

            # Give background tasks time to complete
            await anyio.sleep(0.2)

    finally:
        server_thread.stop()
        server_thread.join(timeout=5.0)
        check_logs_for_race_condition_errors(caplog, "test_race_condition_message_router_async_for")
