"""Common test utilities for MCP server tests."""

import os
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


def parse_worker_index(worker_id: str) -> int:
    """Parse worker index from pytest-xdist worker ID.

    Extracts the numeric worker index from worker_id strings. Handles standard
    formats ('master', 'gwN') with fallback for unexpected formats.

    Args:
        worker_id: pytest-xdist worker ID string (e.g., 'master', 'gw0', 'gw1')

    Returns:
        Worker index: 0 for 'master', N for 'gwN', hash-based fallback otherwise

    Examples:
        >>> parse_worker_index('master')
        0
        >>> parse_worker_index('gw0')
        0
        >>> parse_worker_index('gw5')
        5
        >>> parse_worker_index('unexpected_format')  # Returns consistent hash-based value
        42  # (example - actual value depends on hash)
    """
    if worker_id == "master":
        return 0

    try:
        # Try to extract number from 'gwN' format
        return int(worker_id.replace("gw", ""))
    except (ValueError, AttributeError):
        # Fallback: if parsing fails, use hash of worker_id to avoid collisions
        # Modulo 100 to keep worker indices reasonable
        return abs(hash(worker_id)) % 100


def calculate_port_range(
    worker_index: int, worker_count: int, base_port: int = 40000, total_ports: int = 20000
) -> tuple[int, int]:
    """Calculate non-overlapping port range for a worker.

    Divides the total port range equally among workers, ensuring each worker
    gets an exclusive range. Guarantees minimum of 100 ports per worker.

    Args:
        worker_index: Zero-based worker index
        worker_count: Total number of workers in the test session
        base_port: Starting port of the total range (default: 40000)
        total_ports: Total number of ports available (default: 20000)

    Returns:
        Tuple of (start_port, end_port) where end_port is exclusive

    Examples:
        >>> calculate_port_range(0, 4)  # 4 workers, first worker
        (40000, 45000)
        >>> calculate_port_range(1, 4)  # 4 workers, second worker
        (45000, 50000)
        >>> calculate_port_range(0, 1)  # Single worker gets all ports
        (40000, 60000)
    """
    # Calculate ports per worker (minimum 100 ports per worker)
    ports_per_worker = max(100, total_ports // worker_count)

    # Calculate this worker's port range
    worker_base_port = base_port + (worker_index * ports_per_worker)
    worker_max_port = min(worker_base_port + ports_per_worker, base_port + total_ports)

    return worker_base_port, worker_max_port


def get_worker_specific_port(worker_id: str) -> int:
    """Get a free port specific to this pytest-xdist worker.

    Allocates non-overlapping port ranges to each worker to prevent port conflicts
    when running tests in parallel. This eliminates race conditions where multiple
    workers try to bind to the same port.

    Args:
        worker_id: pytest-xdist worker ID string (e.g., 'master', 'gw0', 'gw1')

    Returns:
        An available port in this worker's range

    Raises:
        RuntimeError: If no available ports found in the worker's range
    """
    # Parse worker index from worker_id
    worker_index = parse_worker_index(worker_id)

    # Get total number of workers from environment variable
    worker_count = 1
    worker_count_str = os.environ.get("PYTEST_XDIST_WORKER_COUNT")
    if worker_count_str:
        try:
            worker_count = int(worker_count_str)
        except ValueError:
            # Fallback to single worker if parsing fails
            worker_count = 1

    # Calculate this worker's port range
    worker_base_port, worker_max_port = calculate_port_range(worker_index, worker_count)

    # Try to find an available port in this worker's range
    for port in range(worker_base_port, worker_max_port):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
                # Port is available, return it immediately
                return port
        except OSError:
            # Port in use, try next one
            continue

    raise RuntimeError(f"No available ports in range {worker_base_port}-{worker_max_port - 1} for worker {worker_id}")
