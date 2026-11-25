"""Windows stdio tests for Job Object cleanup, selector fallback, and CRLF framing.

The test bodies are excluded because non-Windows CI also enforces coverage.
"""

import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from textwrap import dedent

import anyio
import anyio.abc
import pytest
from mcp_types import JSONRPCRequest, JSONRPCResponse, TextContent

from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.message import SessionMessage
from tests.transports.stdio._liveness import (
    accept_alive,
    assert_stream_closed,
    connect_back_script,
    open_liveness_listener,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object / event-loop semantics"),
]


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


async def test_a_gracefully_exited_servers_child_is_reaped_when_the_job_handle_closes(  # pragma: no cover
    tmp_path: Path,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Closing a gracefully exited server's Job Object reaps its child.

    This differs from POSIX. Empty `terminate_calls` distinguishes cleanup from escalation.
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # Capture startup failures that xdist would otherwise hide.
        child = "import sys\nprint('child-started', file=sys.stderr, flush=True)\n" + connect_back_script(port)
        # Job membership is inherited; DEVNULL avoids a Windows CPython startup deadlock.
        server = (
            f"import socket, subprocess, sys\n"
            f"try:\n"
            f"    p = subprocess.Popen([sys.executable, '-c', {child!r}], "
            f"stdin=subprocess.DEVNULL, stderr=sys.stderr)\n"
            f"except BaseException as exc:\n"
            f"    print(exc, file=sys.stderr, flush=True)\n"
            f"    raise\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stdin.read()\n"
            f"print('child-rc:%s' % p.poll(), file=sys.stderr, flush=True)\n"
        )
        server_params = StdioServerParameters(command=sys.executable, args=["-c", server])

        with (tmp_path / "errlog.txt").open("w+", encoding="utf-8") as errlog:

            def server_stderr() -> str:
                errlog.seek(0)
                return errlog.read()

            streams: list[anyio.abc.SocketStream] = []
            spawn_started = anyio.current_time()
            entered_at: float | None = None
            try:
                # Allow two cold interpreter starts on loaded CI.
                with anyio.fail_after(15.0):
                    async with stdio_client(server_params, errlog=errlog):
                        entered_at = anyio.current_time()
                        # The server and child race to connect; accept both,
                        # order-agnostic (accept_alive verifies each banner).
                        for _ in range(2):
                            stream = await accept_alive(sock)
                            stack.push_async_callback(stream.aclose)
                            streams.append(stream)
            except TimeoutError:
                missing_leg = "the server never ran its connect line" if not streams else "the child never connected"
                spawn_split = (
                    "the context never entered"
                    if entered_at is None
                    else f"the context entered {entered_at - spawn_started:.1f}s after spawn began"
                )
                pytest.fail(
                    f"{len(streams)}/2 liveness connections arrived ({missing_leg}); "
                    f"{spawn_split}; server stderr: {server_stderr()!r}"
                )

            # Keep references alive so GC cannot close the weak-keyed Job Object early.
            try:
                for stream in streams:
                    await assert_stream_closed(stream)
            except TimeoutError:
                pytest.fail(f"a socket stayed open after shutdown; server stderr: {server_stderr()!r}")

            leader = spawned_processes[0]
            assert leader.returncode == 0, server_stderr()
            assert terminate_calls == [], server_stderr()


# A selector loop forces `stdio_client` to use `FallbackProcess`.
@pytest.mark.parametrize("anyio_backend", [("asyncio", {"loop_factory": asyncio.SelectorEventLoop})])
async def test_a_selector_event_loop_session_uses_the_fallback_process_and_exits_cleanly(  # pragma: no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """`stdio_client` uses `FallbackProcess` under `SelectorEventLoop`.

    This covers clean exit because forced shutdown can strand the fallback reader thread.
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stdin.read()\n"
        )
        server_params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Allow one cold interpreter start on loaded CI.
        with anyio.fail_after(10.0):
            async with stdio_client(server_params):
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                assert isinstance(spawned_processes[0], FallbackProcess)

        await assert_stream_closed(stream)
        assert spawned_processes[0].returncode == 0
        assert terminate_calls == []


async def test_a_native_server_emitting_crlf_line_endings_round_trips_messages() -> None:  # pragma: no cover
    """The client accepts CRLF-framed messages from a native Windows server.

    Text-mode Windows servers write `\\r\\n`, while the client splits on `\\n`.
    """
    # `print()` emits CRLF on Windows.
    server = (
        "import json, sys\n"
        "line = sys.stdin.readline()\n"
        "request = json.loads(line)\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': {}}))\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read()\n"
    )
    server_params = StdioServerParameters(command=sys.executable, args=["-c", server])

    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")

    # Allow one cold interpreter start on loaded CI.
    with anyio.fail_after(10.0):
        async with stdio_client(server_params) as (read_stream, write_stream):
            await write_stream.send(SessionMessage(ping))
            received = await read_stream.receive()
            assert isinstance(received, SessionMessage)
            assert received.message == JSONRPCResponse(jsonrpc="2.0", id=1, result={})


async def test_a_tool_spawned_python_child_with_default_stdin_completes_promptly() -> None:  # pragma: no cover
    """A tool that runs a Python subprocess without redirecting stdin returns promptly.

    Regression for #671: pre-isolation the child inherited the protocol stdin pipe
    and hung in interpreter startup (CPython gh-78961) until the next inbound message.
    """
    server = dedent(
        """
        import subprocess, sys
        from mcp.server import MCPServer

        mcp = MCPServer("spawner")

        @mcp.tool()
        def run_child() -> str:
            proc = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, timeout=20)
            return proc.stdout.decode().strip()

        @mcp.tool()
        def run_child_bare() -> str:
            proc = subprocess.run([sys.executable, "-c", "pass"], timeout=20)
            return str(proc.returncode)

        mcp.run()
        """
    )
    transport = stdio_client(StdioServerParameters(command=sys.executable, args=["-c", server]))

    # Guard against the original deadlock.
    with anyio.fail_after(40.0):
        async with Client(transport) as client:
            result = await client.call_tool("run_child")
            bare = await client.call_tool("run_child_bare")

    content = result.content[0]
    assert isinstance(content, TextContent)
    assert content.text == "ok"
    bare_content = bare.content[0]
    assert isinstance(bare_content, TextContent)
    assert bare_content.text == "0"
