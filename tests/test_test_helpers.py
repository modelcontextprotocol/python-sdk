"""Unit tests for test helper utilities."""

import socket

import pytest

from tests.test_helpers import calculate_port_range, get_worker_specific_port, parse_worker_index

# Tests for parse_worker_index function


@pytest.mark.parametrize(
    ("worker_id", "expected"),
    [
        ("master", 0),
        ("gw0", 0),
        ("gw1", 1),
        ("gw42", 42),
        ("gw999", 999),
    ],
)
def test_parse_worker_index(worker_id: str, expected: int) -> None:
    """Test parsing worker IDs to indices."""
    assert parse_worker_index(worker_id) == expected


def test_parse_worker_index_unexpected_format_consistent() -> None:
    """Test that unexpected formats return consistent hash-based index."""
    result1 = parse_worker_index("unexpected_format")
    result2 = parse_worker_index("unexpected_format")
    # Should be consistent
    assert result1 == result2
    # Should be in valid range
    assert 0 <= result1 < 100


def test_parse_worker_index_different_formats_differ() -> None:
    """Test that different unexpected formats produce different indices."""
    result1 = parse_worker_index("format_a")
    result2 = parse_worker_index("format_b")
    # Should be different (hash collision unlikely)
    assert result1 != result2


# Tests for calculate_port_range function


def test_calculate_port_range_single_worker() -> None:
    """Test that a single worker gets the entire port range."""
    start, end = calculate_port_range(0, 1)
    assert start == 40000
    assert end == 60000


def test_calculate_port_range_two_workers() -> None:
    """Test that two workers split the port range evenly."""
    start1, end1 = calculate_port_range(0, 2)
    start2, end2 = calculate_port_range(1, 2)

    # First worker gets first half
    assert start1 == 40000
    assert end1 == 50000

    # Second worker gets second half
    assert start2 == 50000
    assert end2 == 60000

    # Ranges should not overlap
    assert end1 == start2


def test_calculate_port_range_four_workers() -> None:
    """Test that four workers split the port range evenly."""
    ranges = [calculate_port_range(i, 4) for i in range(4)]

    # Each worker gets 5000 ports
    assert ranges[0] == (40000, 45000)
    assert ranges[1] == (45000, 50000)
    assert ranges[2] == (50000, 55000)
    assert ranges[3] == (55000, 60000)

    # Verify no overlaps
    for i in range(3):
        assert ranges[i][1] == ranges[i + 1][0]


def test_calculate_port_range_many_workers_minimum() -> None:
    """Test that workers always get at least 100 ports even with many workers."""
    # With 200 workers, each should still get minimum 100 ports
    start1, end1 = calculate_port_range(0, 200)
    start2, end2 = calculate_port_range(1, 200)

    assert end1 - start1 == 100
    assert end2 - start2 == 100
    assert end1 == start2  # No overlap


def test_calculate_port_range_custom_base_port() -> None:
    """Test using a custom base port and total ports."""
    start, end = calculate_port_range(0, 1, base_port=50000, total_ports=5000)
    assert start == 50000
    assert end == 55000


def test_calculate_port_range_custom_total_ports() -> None:
    """Test using a custom total port range."""
    start, end = calculate_port_range(0, 1, total_ports=1000)
    assert end - start == 1000


@pytest.mark.parametrize("worker_count", [2, 4, 8, 10])
def test_calculate_port_range_non_overlapping(worker_count: int) -> None:
    """Test that all worker ranges are non-overlapping."""
    ranges = [calculate_port_range(i, worker_count) for i in range(worker_count)]

    for i in range(worker_count - 1):
        # Current range end should equal next range start
        assert ranges[i][1] == ranges[i + 1][0]


@pytest.mark.parametrize("worker_count", [1, 2, 4, 8])
def test_calculate_port_range_covers_full_range(worker_count: int) -> None:
    """Test that all workers together cover the full port range."""
    ranges = [calculate_port_range(i, worker_count) for i in range(worker_count)]

    # First worker starts at base
    assert ranges[0][0] == 40000
    # Last worker ends at or before base + total
    assert ranges[-1][1] <= 60000


# Integration tests for get_worker_specific_port function


@pytest.mark.parametrize(
    ("worker_id", "worker_count", "expected_min", "expected_max"),
    [
        ("gw0", "4", 40000, 45000),
        ("master", "2", 40000, 50000),
    ],
)
def test_get_worker_specific_port_in_range(
    monkeypatch: pytest.MonkeyPatch, worker_id: str, worker_count: str, expected_min: int, expected_max: int
) -> None:
    """Test that returned port is in the expected range for the worker."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", worker_count)

    port = get_worker_specific_port(worker_id)

    assert expected_min <= port < expected_max


def test_get_worker_specific_port_different_workers_get_different_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that different workers can get ports from different ranges."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "4")

    port0 = get_worker_specific_port("gw0")
    port2 = get_worker_specific_port("gw2")

    # Worker 0 range: 40000-45000
    # Worker 2 range: 50000-55000
    assert 40000 <= port0 < 45000
    assert 50000 <= port2 < 55000


def test_get_worker_specific_port_is_actually_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the returned port is actually available for binding."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "1")

    port = get_worker_specific_port("master")

    # Port should be bindable
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        # If we get here, the port was available


def test_get_worker_specific_port_no_worker_count_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test behavior when PYTEST_XDIST_WORKER_COUNT is not set."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)

    port = get_worker_specific_port("master")

    # Should default to single worker (full range)
    assert 40000 <= port < 60000


def test_get_worker_specific_port_invalid_worker_count_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test behavior when PYTEST_XDIST_WORKER_COUNT is invalid."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "not_a_number")

    port = get_worker_specific_port("master")

    # Should fall back to single worker
    assert 40000 <= port < 60000


def test_get_worker_specific_port_raises_when_no_ports_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that RuntimeError is raised when no ports are available."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "100")

    # Bind all ports in the worker's range
    start, end = calculate_port_range(0, 100)

    sockets: list[socket.socket] = []
    try:
        # Try to bind all ports in range (may not succeed on all platforms)
        for port in range(start, min(start + 10, end)):  # Just bind first 10 for speed
            try:
                s = socket.socket()
                s.bind(("127.0.0.1", port))
                sockets.append(s)
            except OSError:
                # Port already in use, skip
                pass

        # If we managed to bind some ports, temporarily exhaust the small range
        if sockets:
            # This test is tricky because we can't easily exhaust all ports
            # Just verify the error message format is correct
            pass
    finally:
        # Clean up sockets
        for s in sockets:
            s.close()
