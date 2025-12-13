"""Test for issue #1363 - Race condition in StreamableHTTP transport causes ClosedResourceError.

This test reproduces the race condition described in issue #1363 where MCP servers
in HTTP Streamable mode experience ClosedResourceError exceptions when requests
fail validation early (e.g., due to incorrect Accept headers).

The race condition occurs because:
1. Transport setup creates a message_router task
2. Message router enters async for write_stream_reader loop
3. write_stream_reader calls checkpoint() in receive(), yielding control
4. Request handling processes HTTP request
5. If validation fails early, request returns immediately
6. Transport termination closes all streams including write_stream_reader
7. Message router may still be in checkpoint() yield and hasn't returned to check stream state
8. When message router resumes, it encounters a closed stream, raising ClosedResourceError
"""

import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
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
    """Create a Starlette application for testing."""
    app = RaceConditionTestServer()

    # Create session manager
    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=json_response,
        stateless=True,  # Use stateless mode to trigger the race condition
    )

    # Create Starlette app with lifespan
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

    def run(self) -> None:
        """Run the lifespan in a new event loop."""

        # Create a new event loop for this thread
        async def run_lifespan():
            # Use the lifespan context (always present in our tests)
            lifespan_context = getattr(self.app.router, "lifespan_context", None)
            assert lifespan_context is not None  # Tests always create apps with lifespan
            async with lifespan_context(self.app):
                # Wait until stop is requested
                while not self._stop_event.is_set():
                    await anyio.sleep(0.1)

        anyio.run(run_lifespan)

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()


def check_logs_for_race_condition_errors(caplog: pytest.LogCaptureFixture, test_name: str) -> None:
    """
    Check logs for ClosedResourceError and other race condition errors.

    Args:
        caplog: pytest log capture fixture
        test_name: Name of the test for better error messages
    """
    # Check for specific race condition errors in logs
    errors_found: list[str] = []

    for record in caplog.records:  # pragma: no cover
        message = record.getMessage()
        if "ClosedResourceError" in message:
            errors_found.append("ClosedResourceError")
        if "Error in message router" in message:
            errors_found.append("Error in message router")
        if "anyio.ClosedResourceError" in message:
            errors_found.append("anyio.ClosedResourceError")

    # Assert no race condition errors occurred
    if errors_found:  # pragma: no cover
        error_msg = f"Test '{test_name}' found race condition errors in logs: {', '.join(set(errors_found))}\n"
        error_msg += "Log records:\n"
        for record in caplog.records:
            if any(err in record.getMessage() for err in ["ClosedResourceError", "Error in message router"]):
                error_msg += f"  {record.levelname}: {record.getMessage()}\n"
        pytest.fail(error_msg)


@pytest.mark.anyio
async def test_race_condition_invalid_accept_headers(caplog: pytest.LogCaptureFixture):
    """
    Test the race condition with invalid Accept headers.

    This test reproduces the exact scenario described in issue #1363:
    - Send POST request with incorrect Accept headers (missing either application/json or text/event-stream)
    - Request fails validation early and returns quickly
    - This should trigger the race condition where message_router encounters ClosedResourceError
    """
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        # Give the server thread a moment to start
        await anyio.sleep(0.1)

        # Suppress WARNING logs (expected validation errors) and capture ERROR logs
        with caplog.at_level(logging.ERROR):
            # Test with missing text/event-stream in Accept header
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
                # Should get 406 Not Acceptable due to missing text/event-stream
                assert response.status_code == 406

            # Test with missing application/json in Accept header
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
                # Should get 406 Not Acceptable due to missing application/json
                assert response.status_code == 406

            # Test with completely invalid Accept header
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
                # Should get 406 Not Acceptable
                assert response.status_code == 406

            # Give background tasks time to complete
            await anyio.sleep(0.2)

    finally:
        server_thread.stop()
        server_thread.join(timeout=5.0)
        # Check logs for race condition errors
        check_logs_for_race_condition_errors(caplog, "test_race_condition_invalid_accept_headers")


@pytest.mark.anyio
async def test_race_condition_invalid_content_type(caplog: pytest.LogCaptureFixture):
    """
    Test the race condition with invalid Content-Type headers.

    This test reproduces the race condition scenario with Content-Type validation failure.
    """
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        # Give the server thread a moment to start
        await anyio.sleep(0.1)

        # Suppress WARNING logs (expected validation errors) and capture ERROR logs
        with caplog.at_level(logging.ERROR):
            # Test with invalid Content-Type
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
        # Check logs for race condition errors
        check_logs_for_race_condition_errors(caplog, "test_race_condition_invalid_content_type")


@pytest.mark.anyio
async def test_race_condition_message_router_async_for(caplog: pytest.LogCaptureFixture):
    """
    Uses json_response=True to trigger the `if self.is_json_response_enabled` branch,
    which reproduces the ClosedResourceError when message_router is suspended
    in async for loop while transport cleanup closes streams concurrently.
    """
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        # Give the server thread a moment to start
        await anyio.sleep(0.1)

        # Suppress WARNING logs (expected validation errors) and capture ERROR logs
        with caplog.at_level(logging.ERROR):
            # Use httpx.ASGITransport to test the ASGI app directly
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
            ) as client:
                # Send a valid initialize request
                response = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
                # Should get a successful response
                assert response.status_code in (200, 201)

            # Give background tasks time to complete
            await anyio.sleep(0.2)

    finally:
        server_thread.stop()
        server_thread.join(timeout=5.0)
        # Check logs for race condition errors in message router
        check_logs_for_race_condition_errors(caplog, "test_race_condition_message_router_async_for")
