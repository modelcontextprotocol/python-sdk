"""Common test utilities for MCP server tests."""

import gc
import socket
import threading
import time
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import uvicorn

_SERVER_SHUTDOWN_TIMEOUT_S = 5.0


@contextmanager
def run_uvicorn_in_thread(app: Any, **config_kwargs: Any) -> Generator[str, None, None]:
    """Run a uvicorn server in a background thread on an ephemeral port.

    The socket is bound and put into listening state *before* the thread
    starts, so the port is known immediately with no wait. The kernel's
    listen queue buffers any connections that arrive before uvicorn's event
    loop reaches ``accept()``, so callers can connect as soon as this
    function yields — no polling, no sleeps, no startup race.

    This also avoids the TOCTOU race of the old pick-a-port-then-rebind
    pattern: the socket passed here is the one uvicorn serves on, with no
    gap where another pytest-xdist worker could claim it.

    Args:
        app: ASGI application to serve.
        **config_kwargs: Additional keyword arguments for :class:`uvicorn.Config`
            (e.g. ``log_level``). ``host``/``port`` are ignored since the
            socket is pre-bound.

    Yields:
        The base URL of the running server, e.g. ``http://127.0.0.1:54321``.
    """
    host = "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen()
    port = sock.getsockname()[1]

    config_kwargs.setdefault("log_level", "error")
    # Uvicorn's interface autodetection calls asyncio.iscoroutinefunction,
    # which Python 3.14 deprecates. Under filterwarnings=error this crashes
    # the server thread silently. Starlette is asgi3; skip the autodetect.
    config_kwargs.setdefault("interface", "asgi3")
    server = uvicorn.Server(config=uvicorn.Config(app=app, **config_kwargs))

    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=_SERVER_SHUTDOWN_TIMEOUT_S)
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
