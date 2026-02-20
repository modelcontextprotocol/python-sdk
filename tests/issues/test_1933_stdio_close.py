"""Test for issue #1933: stdio_server closes real process stdio handles."""

import gc
import io
import os
import sys

import pytest

from mcp.server.stdio import stdio_server


@pytest.mark.anyio
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_stdio_server_preserves_process_handles():
    """After stdio_server() exits, the underlying stdin/stdout fds should still be open.

    Before the fix, TextIOWrapper took ownership of sys.stdin.buffer and
    sys.stdout.buffer. When the wrapper was garbage-collected, it closed the
    underlying buffer, permanently killing process stdio.
    """
    # Create real pipes to stand in for process stdin/stdout.
    # Real fds are required because the bug involves TextIOWrapper closing
    # the underlying fd — StringIO doesn't have file descriptors.
    stdin_r_fd, stdin_w_fd = os.pipe()
    stdout_r_fd, stdout_w_fd = os.pipe()

    fake_stdin = io.TextIOWrapper(io.BufferedReader(io.FileIO(stdin_r_fd, "rb")))
    fake_stdout = io.TextIOWrapper(io.BufferedWriter(io.FileIO(stdout_w_fd, "wb")))

    saved_stdin, saved_stdout = sys.stdin, sys.stdout
    sys.stdin = fake_stdin
    sys.stdout = fake_stdout

    # Close write end so stdin_reader gets EOF immediately
    os.close(stdin_w_fd)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()

        await read_stream.aclose()
        gc.collect()

        # os.fstat raises OSError if the fd was closed
        os.fstat(stdin_r_fd)
        os.fstat(stdout_w_fd)
    finally:
        sys.stdin = saved_stdin
        sys.stdout = saved_stdout
        for fd in [stdin_r_fd, stdout_r_fd, stdout_w_fd]:
            try:
                os.close(fd)
            except OSError:  # pragma: no cover
                pass
