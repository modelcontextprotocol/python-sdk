"""Common test utilities for MCP server tests."""

import contextlib
import gc
import socket
import threading
import time
import warnings
from collections.abc import Generator
from typing import Literal

import uvicorn
from starlette.types import ASGIApp


def wait_for_server(port: int, timeout: float = 20.0) -> None:
    """Wait for server to be ready to accept connections.

    Polls the server port until it accepts connections or timeout is reached.
    This eliminates race conditions without arbitrary sleeps.

    Args:
        port: The port number to check
        timeout: Maximum time to wait in seconds (default 5.0)

    Raises:
        TimeoutError: If server doesn't start within the timeout period
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                # Server is ready
                return
        except (ConnectionRefusedError, OSError):
            # Server not ready yet, retry quickly
            time.sleep(0.01)
    raise TimeoutError(f"Server on port {port} did not start within {timeout} seconds")  # pragma: no cover


@contextlib.contextmanager
def run_server_in_thread(app: ASGIApp, lifespan: Literal["auto", "on", "off"] = "on") -> Generator[str, None, None]:
    """Run a Starlette/ASGI app in a uvicorn server on a background thread.

    Uses `port=0` so the kernel atomically assigns an available port, eliminating
    the TOCTOU port-allocation race that affects subprocess-based fixtures. The
    actual bound port is read back from the server's socket after binding.

    Unlike multiprocessing, this runs in-process so:
    - No port race (port=0 is assigned atomically at bind time)
    - No pickling of app/state (the app runs in the same process)
    - Faster startup (no fork/exec overhead)
    - Works with both asyncio and trio test backends (uvicorn runs its own
      asyncio loop in the thread; uvicorn skips signal handlers automatically
      when not on the main thread)

    Args:
        app: The ASGI application to serve.
        lifespan: uvicorn lifespan mode — "on" to run app lifespan events,
            "off" to skip them (default "on").

    Yields:
        Base URL of the running server (e.g., "http://127.0.0.1:54321").
    """
    config = uvicorn.Config(app=app, host="127.0.0.1", port=0, log_level="error", lifespan=lifespan)
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for uvicorn to bind and start accepting connections
    start_time = time.time()
    while not server.started:
        if time.time() - start_time > 20.0:  # pragma: no cover
            raise TimeoutError("uvicorn server did not start within 20 seconds")
        time.sleep(0.01)

    # Read back the kernel-assigned port from the bound socket
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        # When uvicorn shuts down with in-flight SSE connections, the server
        # cancels request handlers mid-operation. SseServerTransport's internal
        # memory streams may not get their `finally` cleanup run before GC,
        # causing ResourceWarnings. These are artifacts of test abrupt-disconnect
        # patterns (open SSE stream → check status → exit without consuming),
        # not bugs. Force GC here and suppress the warnings so they don't leak
        # into the next test's PytestUnraisableExceptionWarning collector.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
