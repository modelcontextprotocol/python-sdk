"""Cross-platform stdio lifecycle tests using real subprocesses."""

import os
import subprocess
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from textwrap import dedent

import anyio
import anyio.abc
import pytest
from mcp_types import TextContent

from mcp.client import stdio
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.os.win32.utilities import FallbackProcess
from tests.transports.stdio._liveness import (
    accept_alive,
    assert_stream_closed,
    connect_back_script,
    open_liveness_listener,
)


@pytest.mark.anyio
async def test_a_server_that_exits_on_stdin_close_is_reaped_and_never_terminated(
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Closing stdin reaps a well-behaved server without escalation."""
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stdin.read()\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Allow one cold interpreter start on loaded CI.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        await assert_stream_closed(stream)

    assert spawned_processes[0].returncode == 0
    assert terminate_calls == []


@pytest.mark.anyio
async def test_cancelling_the_client_mid_session_terminates_the_whole_server_tree(
    monkeypatch: pytest.MonkeyPatch,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Cancellation terminates a server tree that ignores stdin closure."""
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 0.2)

    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        child = connect_back_script(port)
        parent = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n" + connect_back_script(
            port
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", parent])

        entered = anyio.Event()
        # A child-task scope avoids a CPython 3.11 coverage tracing bug during host self-cancellation.
        cancel_scope = anyio.CancelScope()

        async def run_client_until_cancelled() -> None:
            with cancel_scope:
                async with stdio_client(params):
                    entered.set()
                    await anyio.sleep_forever()

        streams: list[anyio.abc.SocketStream] = []
        # Allow two cold interpreter starts and the shortened escalation wait.
        with anyio.fail_after(10.0):
            async with anyio.create_task_group() as tg:
                tg.start_soon(run_client_until_cancelled)
                await entered.wait()
                for _ in range(2):
                    stream = await accept_alive(sock)
                    stack.push_async_callback(stream.aclose)
                    streams.append(stream)
                cancel_scope.cancel()

        for stream in streams:
            await assert_stream_closed(stream)

    assert terminate_calls == spawned_processes


@pytest.mark.anyio
async def test_a_server_that_exits_mid_session_keeps_its_own_exit_code(
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """A server that dies mid-session retains its exit code without escalation."""
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.exit(7)\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Allow one cold interpreter start on loaded CI.
        with anyio.fail_after(10.0):
            # Coverage mis-traces nested `async with` exit arcs on Python 3.11+.
            async with stdio_client(params):  # pragma: no branch
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                await assert_stream_closed(stream)

    assert spawned_processes[0].returncode == 7
    assert terminate_calls == []


@pytest.mark.anyio
async def test_server_stderr_output_reaches_the_errlog_file(
    tmp_path: Path,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Server stderr reaches the file passed as `errlog`."""
    marker = "stdio-lifecycle stderr marker 4242"

    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stderr.write({marker!r} + '\\n')\n"
            f"sys.stderr.flush()\n"
            f"sys.stdin.read()\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        with (tmp_path / "errlog.txt").open("w+", encoding="utf-8") as errlog:
            # Allow one cold interpreter start on loaded CI.
            with anyio.fail_after(10.0):
                async with stdio_client(params, errlog=errlog):
                    stream = await accept_alive(sock)
                    stack.push_async_callback(stream.aclose)

            errlog.seek(0)
            content = errlog.read()

    assert marker in content
    assert spawned_processes[0].returncode == 0


@pytest.mark.skipif(
    not hasattr(os, "waitid"), reason="needs os.waitid(WNOWAIT); absent on Windows and macOS before 3.13"
)
# lax no cover: Windows runners enforce 100% per job but lack os.waitid and skip this
# test; test_windows.py's SelectorEventLoop lifecycle test exercises the property there.
def test_fallback_process_reports_death_through_returncode_without_a_wait_call() -> None:  # pragma: lax no cover
    """`FallbackProcess.returncode` observes death without calling `wait()`.

    `waitid(WNOWAIT)` avoids priming Popen's cached return code or reaping the child.
    """
    popen = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert popen.stdin is not None and popen.stdout is not None
    try:
        process = FallbackProcess(popen)

        os.waitid(os.P_PID, popen.pid, os.WEXITED | os.WNOWAIT)
        assert process.returncode == 0
    finally:
        popen.stdin.close()
        popen.stdout.close()
        # Reap the child left by `WNOWAIT`.
        popen.wait()


@pytest.mark.anyio
async def test_fallback_process_wait_is_cancellable_while_the_child_lives() -> None:
    """`FallbackProcess.wait()` remains cancellable while the child runs."""
    popen = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert popen.stdin is not None and popen.stdout is not None
    # The watchdog converts a blocked worker thread into a failure.
    watchdog = threading.Timer(8.0, popen.kill)
    watchdog.start()
    try:
        process = FallbackProcess(popen)

        # The short deadline is the cancellability behavior under test.
        with anyio.fail_after(5):
            with anyio.move_on_after(0.1) as scope:
                await process.wait()

        assert scope.cancelled_caught
        assert popen.poll() is None
    finally:
        watchdog.cancel()
        popen.kill()
        popen.wait()
        popen.stdin.close()
        popen.stdout.close()


@pytest.mark.anyio
async def test_a_tool_spawned_childs_stdout_writes_never_reach_the_wire(tmp_path: Path) -> None:
    """A child's inherited stdout reaches server stderr, not the protocol."""
    server = dedent(
        """
        import subprocess, sys
        from mcp.server import MCPServer

        mcp = MCPServer("noisy-spawner")

        @mcp.tool()
        def run_noisy_child() -> str:
            proc = subprocess.run([sys.executable, "-c", "print('this is not json')"], timeout=20)
            return str(proc.returncode)

        mcp.run()
        """
    )

    with (tmp_path / "server-stderr.txt").open("w+", encoding="utf-8") as errlog:
        transport = stdio_client(StdioServerParameters(command=sys.executable, args=["-c", server]), errlog=errlog)
        # Allow three cold interpreter starts.
        with anyio.fail_after(40):
            async with Client(transport) as client:
                result = await client.call_tool("run_noisy_child")
        errlog.seek(0)
        server_stderr = errlog.read()

    content = result.content[0]
    assert isinstance(content, TextContent)
    assert content.text == "0"
    assert "this is not json" in server_stderr
