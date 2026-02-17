"""Common test utilities for MCP server tests."""

import socket
import time
import urllib.error
import urllib.request


def wait_for_server(port: int, timeout: float = 20.0) -> None:
    """Wait for server to be ready to accept connections.

    First polls until the TCP port accepts connections, then verifies the
    HTTP server is actually ready to handle requests. This two-stage check
    prevents race conditions where the port is open but the ASGI app hasn't
    finished initializing.

    Args:
        port: The port number to check
        timeout: Maximum time to wait in seconds (default 20.0)

    Raises:
        TimeoutError: If server doesn't start within the timeout period
    """
    start_time = time.time()

    # Stage 1: Wait for TCP port to accept connections
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                break  # Port is open, move to stage 2
        except (ConnectionRefusedError, OSError):
            time.sleep(0.01)
    else:
        raise TimeoutError(f"Server on port {port} did not start within {timeout} seconds")  # pragma: no cover

    # Stage 2: Verify HTTP server is ready by making a request.
    # A non-existent path returns 404/405 if the app is ready, or
    # raises an error if the ASGI app hasn't finished initializing.
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/healthz",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=1):
                return  # Any successful response means server is ready
        except urllib.error.HTTPError:
            # 404/405/etc means the server IS handling requests
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            # Server not ready for HTTP yet
            time.sleep(0.05)
    raise TimeoutError(f"Server on port {port} did not become HTTP-ready within {timeout} seconds")  # pragma: no cover
