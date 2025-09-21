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

import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool

SERVER_NAME = "test_race_condition_server"


def check_server_logs_for_errors(process: subprocess.Popen[str], test_name: str) -> None:
    """
    Check server logs for ClosedResourceError and other race condition errors.

    Args:
        process: The server process
        test_name: Name of the test for better error messages
    """
    # Get logs from the process
    try:
        stdout, stderr = process.communicate(timeout=10)
        server_logs = stderr + stdout
    except Exception:
        server_logs = ""

    # Check for specific race condition errors
    errors_found: list[str] = []

    if "ClosedResourceError" in server_logs:
        errors_found.append("ClosedResourceError")

    if "Error in message router" in server_logs:
        errors_found.append("Error in message router")

    if "anyio.ClosedResourceError" in server_logs:
        errors_found.append("anyio.ClosedResourceError")

    # Assert no race condition errors occurred
    if errors_found:
        error_msg = f"Test '{test_name}' found race condition errors: {', '.join(errors_found)}\n"
        error_msg += f"Server logs:\n{server_logs}"
        pytest.fail(error_msg)

    # If we get here, no race condition errors were found
    print(f"✓ Test '{test_name}' passed: No race condition errors detected")


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


class RaceConditionTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


def run_server_with_logging(port: int) -> None:
    """Run the StreamableHTTP server with logging to capture race condition errors."""
    app = RaceConditionTestServer()

    # Create session manager
    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=False,
        stateless=True,  # Use stateless mode to trigger the race condition
    )

    # Create the ASGI handler
    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    # Create Starlette app with lifespan
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    routes = [
        Mount("/", app=handle_streamable_http),
    ]

    starlette_app = Starlette(routes=routes, lifespan=lifespan)
    uvicorn.run(starlette_app, host="127.0.0.1", port=port, log_level="debug")


def start_server_process(port: int) -> subprocess.Popen[str]:
    """Start server in a separate process."""
    # Create a temporary script to run the server
    import os
    import tempfile

    script_content = f"""
import sys
sys.path.insert(0, {repr(os.getcwd())})
from tests.issues.test_1363_race_condition_streamable_http import run_server_with_logging
run_server_with_logging({port})
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script_content)
        script_path = f.name

    process = subprocess.Popen([sys.executable, script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Wait for server to be running with connection testing (like other tests)
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        # If server failed to start, terminate the process and raise an error
        process.terminate()
        process.wait()
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    return process


@pytest.mark.anyio
async def test_race_condition_invalid_accept_headers(server_port: int):
    """
    Test the race condition with invalid Accept headers.

    This test reproduces the exact scenario described in issue #1363:
    - Send POST request with incorrect Accept headers (missing either application/json or text/event-stream)
    - Request fails validation early and returns quickly
    - This should trigger the race condition where message_router encounters ClosedResourceError
    """
    process = start_server_process(server_port)

    try:
        # Test with missing text/event-stream in Accept header
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Accept": "application/json",  # Missing text/event-stream
                    "Content-Type": "application/json",
                },
            )
            # Should get 406 Not Acceptable due to missing text/event-stream
            assert response.status_code == 406

        # Test with missing application/json in Accept header
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Accept": "text/event-stream",  # Missing application/json
                    "Content-Type": "application/json",
                },
            )
            # Should get 406 Not Acceptable due to missing application/json
            assert response.status_code == 406

        # Test with completely invalid Accept header
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Accept": "text/plain",  # Invalid Accept header
                    "Content-Type": "application/json",
                },
            )
            # Should get 406 Not Acceptable
            assert response.status_code == 406

    finally:
        process.terminate()
        process.wait()
        # Check server logs for race condition errors
        check_server_logs_for_errors(process, "test_race_condition_invalid_accept_headers")


@pytest.mark.anyio
async def test_race_condition_invalid_content_type(server_port: int):
    """
    Test the race condition with invalid Content-Type headers.

    This test reproduces the race condition scenario with Content-Type validation failure.
    """
    process = start_server_process(server_port)

    try:
        # Test with invalid Content-Type
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "text/plain",  # Invalid Content-Type
                },
            )
            assert response.status_code == 400

    finally:
        process.terminate()
        process.wait()
        # Check server logs for race condition errors
        check_server_logs_for_errors(process, "test_race_condition_invalid_content_type")
