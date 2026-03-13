"""Common test utilities for MCP server tests."""

import socket
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import uvicorn


def wait_for_server(port: int, timeout: float = 20.0) -> None:
    """Wait for server to be ready to accept connections.

    Polls the server port until it accepts connections or timeout is reached.

    .. deprecated::
        This has a race: the port may be bound by a different server (another
        pytest-xdist worker). Prefer :func:`run_uvicorn_in_thread` which holds
        the port atomically from bind until shutdown.

    Args:
        port: The port number to check
        timeout: Maximum time to wait in seconds

    Raises:
        TimeoutError: If server doesn't start within the timeout period
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.01)
    raise TimeoutError(f"Server on port {port} did not start within {timeout} seconds")  # pragma: no cover


@contextmanager
def run_uvicorn_in_thread(app: Any, **config_kwargs: Any) -> Generator[str, None, None]:
    """Run a uvicorn server in a background thread with an ephemeral port.

    This eliminates the TOCTOU race that occurs when a test picks a free port
    with ``socket.bind((host, 0))``, releases it, then starts a server hoping
    to rebind the same port — between release and rebind, another pytest-xdist
    worker may claim it, causing connection errors or cross-test contamination.

    We bind the listening socket here with ``port=0`` and pass it to uvicorn
    via ``server.run(sockets=[sock])`` — the OS assigns the port atomically at
    bind time and we hold it until shutdown. No polling; the port is known
    before the server thread even starts, and the kernel's listen queue buffers
    any connections that arrive during startup.

    Args:
        app: ASGI application to serve.
        **config_kwargs: Additional keyword arguments for :class:`uvicorn.Config`
            (e.g. ``log_level``, ``limit_concurrency``). ``host`` defaults to
            ``127.0.0.1``.

    Yields:
        The base URL of the running server, e.g. ``http://127.0.0.1:54321``.
    """
    host = config_kwargs.setdefault("host", "127.0.0.1")
    config_kwargs.setdefault("log_level", "error")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen()
    port = sock.getsockname()[1]

    config = uvicorn.Config(app=app, **config_kwargs)
    server = uvicorn.Server(config=config)
    thread = threading.Thread(target=server.run, args=([sock],), daemon=True)
    thread.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        server.force_exit = True
        thread.join(timeout=5)
        sock.close()
