"""Common test utilities for MCP server tests."""

import socket
import time


def wait_for_server(port: int, timeout: float = 5.0) -> None:
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
    raise TimeoutError(f"Server on port {port} did not start within {timeout} seconds")
