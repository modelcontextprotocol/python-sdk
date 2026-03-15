"""Stdio Server Transport Module

This module provides functionality for creating an stdio-based transport layer
that can be used to communicate with an MCP client through standard input/output
streams.

Example:
    ```python
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            # read_stream contains incoming JSONRPCMessages from stdin
            # write_stream allows sending JSONRPCMessages to stdout
            server = await create_my_server()
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    ```
"""

import select
import sys
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import anyio.lowlevel
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.shared.message import SessionMessage

# How often to check for stdin EOF (seconds)
STDIN_EOF_CHECK_INTERVAL = 0.1


def _create_stdin_eof_monitor(
    tg: TaskGroup,
) -> Callable[[], Coroutine[object, object, None]] | None:
    """Create a platform-appropriate stdin EOF monitor.

    Returns an async callable that monitors stdin for EOF and cancels the task
    group when detected, or None if monitoring is not supported on this platform.

    When the parent process dies, stdin reaches EOF. The anyio.wrap_file async
    iterator may not detect this promptly because it runs readline() in a worker
    thread. This monitor polls the underlying file descriptor directly using
    OS-level I/O, and cancels the task group when EOF is detected, ensuring the
    server shuts down cleanly.
    """
    if sys.platform == "win32":
        return None

    if not hasattr(select, "poll"):
        return None  # pragma: no cover

    # The remaining code uses select.poll() which is not available on Windows.
    # Coverage is exercised on non-Windows platforms only.
    try:  # pragma: lax no cover
        fd = sys.stdin.buffer.fileno()
    except Exception:  # pragma: lax no cover
        return None

    async def monitor() -> None:  # pragma: lax no cover
        poll_obj = select.poll()
        poll_obj.register(fd, select.POLLIN | select.POLLHUP)
        try:
            while True:
                await anyio.sleep(STDIN_EOF_CHECK_INTERVAL)
                events = poll_obj.poll(0)
                for _, event_mask in events:
                    if event_mask & (select.POLLHUP | select.POLLERR | select.POLLNVAL):
                        tg.cancel_scope.cancel()
                        return
        finally:
            poll_obj.unregister(fd)

    return monitor  # pragma: lax no cover


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # Purposely not using context managers for these, as we don't want to close
    # standard process handles. Encoding of stdin/stdout as text streams on
    # python is platform-dependent (Windows is particularly problematic), so we
    # re-wrap the underlying binary stream to ensure UTF-8.
    if not stdin:
        stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
    if not stdout:
        stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def stdin_reader():
        try:
            async with read_stream_writer:
                async for line in stdin:
                    try:
                        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                    except Exception as exc:  # pragma: no cover
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def stdout_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    await stdout.write(json + "\n")
                    await stdout.flush()
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)

        eof_monitor = _create_stdin_eof_monitor(tg)
        if eof_monitor is not None:
            tg.start_soon(eof_monitor)  # pragma: lax no cover

        yield read_stream, write_stream
