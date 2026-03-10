"""Common test utilities for MCP server tests."""

import socket
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import uvicorn

# How long to wait for the uvicorn server thread to reach `started`.
# Generous to absorb CI scheduling delays — actual startup is typically <100ms.
_SERVER_START_TIMEOUT_S = 20.0
_SERVER_SHUTDOWN_TIMEOUT_S = 5.0


@contextmanager
def run_uvicorn_in_thread(app: Any, **config_kwargs: Any) -> Generator[str, None, None]:
    """Run a uvicorn server in a background thread with an ephemeral port.

    This eliminates the TOCTOU race that occurs when a test picks a free port
    with ``socket.bind((host, 0))``, releases it, then starts a server hoping
    to rebind the same port — between release and rebind, another pytest-xdist
    worker may claim it, causing connection errors or cross-test contamination.

    With ``port=0``, the OS atomically assigns a free port at bind time; the
    server holds it from that moment until shutdown. We read the actual port
    back from uvicorn's bound socket after startup completes.

    Args:
        app: ASGI application to serve.
        **config_kwargs: Additional keyword arguments for :class:`uvicorn.Config`
            (e.g. ``log_level``, ``limit_concurrency``). ``host`` defaults to
            ``127.0.0.1`` and ``port`` is forced to 0.

    Yields:
        The base URL of the running server, e.g. ``http://127.0.0.1:54321``.

    Raises:
        TimeoutError: If the server does not start within 20 seconds.
        RuntimeError: If the server thread dies during startup.
    """
    config_kwargs.setdefault("host", "127.0.0.1")
    config_kwargs.setdefault("log_level", "error")
    config = uvicorn.Config(app=app, port=0, **config_kwargs)
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # uvicorn sets `server.started = True` at the end of `Server.startup()`,
    # after sockets are bound and the lifespan startup phase has completed.
    start = time.monotonic()
    while not server.started:
        if time.monotonic() - start > _SERVER_START_TIMEOUT_S:  # pragma: no cover
            raise TimeoutError(f"uvicorn server failed to start within {_SERVER_START_TIMEOUT_S}s")
        if not thread.is_alive():  # pragma: no cover
            raise RuntimeError("uvicorn server thread exited during startup")
        time.sleep(0.001)

    # server.servers[0] is the asyncio.Server; its bound socket has the real port
    port = server.servers[0].sockets[0].getsockname()[1]
    host = config.host

    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=_SERVER_SHUTDOWN_TIMEOUT_S)


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
