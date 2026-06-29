"""Windows-only stdio lifecycle behaviors, against real subprocesses.

Synchronization is kernel-level only (liveness sockets); see `_liveness`.

Per-test no-cover pragmas (as in tests/issues/test_552_windows_hang.py): bodies run
only on windows-latest CI legs, the per-job 100% gate would count them uncovered on
non-Windows runners, and strict-no-cover is skipped on Windows where they execute.
"""

import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import anyio
import anyio.abc
import pytest
from mcp_types import JSONRPCRequest, JSONRPCResponse

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


async def test_a_gracefully_exited_servers_child_is_reaped_when_the_job_handle_closes(  # pragma: no cover
    tmp_path: Path,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """A gracefully-exited server's child is killed deterministically when shutdown closes the job handle.

    Shutdown's close of the server's Job Object handle (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)
    kills the leftover child at context exit, not at GC time -- the documented POSIX divergence
    (docs/migration.md; twin: test_posix.py::test_a_gracefully_exiting_servers_child_survives_the_client_shutdown).
    `terminate_calls == []` is load-bearing: a job-handle-close kill and the escalation's
    `TerminateJobObject` are indistinguishable on the socket. Both stderr streams land in
    `errlog` so a timeout failure can name the missing process (xdist swallows subprocess stderr on CI).
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # The 'child-started' marker in errlog splits "never started" from "started but never connected".
        child = "import sys\nprint('child-started', file=sys.stderr, flush=True)\n" + connect_back_script(port)
        # Job membership is inherited at CreateProcess: the SDK assigns the server to the Job
        # synchronously after spawn, before the cold-starting interpreter can Popen the child.
        # The child's stdin must be DEVNULL: CPython startup queries fd 0, and Windows serializes
        # that behind the server's blocking `sys.stdin.read()`, freezing the child at startup.
        # On stdin EOF the server prints the child's `poll()`: `None` = alive; an exit/NTSTATUS code names the killer.
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
                # Two interpreter cold starts on a loaded runner; healthy runs take well under a second.
                with anyio.fail_after(15.0):
                    async with stdio_client(server_params, errlog=errlog):
                        entered_at = anyio.current_time()
                        # The server and child race to connect; accept both, order-agnostic.
                        for _ in range(2):
                            stream = await accept_alive(sock)
                            stack.push_async_callback(stream.aclose)
                            streams.append(stream)
            except TimeoutError:
                # `__aexit__` already ran its shielded shutdown, so stderr carries the final `child-rc` line.
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

            # KILL_ON_JOB_CLOSE killed the child at context exit, so both sockets close. The
            # `spawned_processes` strong reference is load-bearing: `_process_jobs` is weak-keyed,
            # so a GC here could otherwise close the job handle itself and mask a regression.
            try:
                for stream in streams:
                    await assert_stream_closed(stream)
            except TimeoutError:
                pytest.fail(f"a socket stayed open after shutdown; server stderr: {server_stderr()!r}")

            leader = spawned_processes[0]
            assert leader.returncode == 0, server_stderr()
            assert terminate_calls == [], server_stderr()


# Overrides the suite-wide anyio_backend fixture for this test only: a selector
# event loop cannot run asyncio subprocesses, forcing stdio_client onto FallbackProcess.
@pytest.mark.parametrize("anyio_backend", [("asyncio", {"loop_factory": asyncio.SelectorEventLoop})])
async def test_a_selector_event_loop_session_uses_the_fallback_process_and_exits_cleanly(  # pragma: no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Under a `SelectorEventLoop`, `stdio_client` falls back to `FallbackProcess` and still exits cleanly.

    The `isinstance` check is the engagement proof: if a future anyio gains selector subprocess
    support, the spawn would silently return a normal Process. A hang here most likely means the
    fallback hazard documented in `stdio_client`'s shutdown comment (reader thread parked in a
    synchronous `ReadFile`), which is why this test pins only the clean-exit path, never a kill path.
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

        # One interpreter cold start on a loaded runner; healthy runs take ~0.3s.
        with anyio.fail_after(10.0):
            async with stdio_client(server_params):
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                # The engagement proof, asserted while the session is live.
                assert isinstance(spawned_processes[0], FallbackProcess)

        await assert_stream_closed(stream)
        assert spawned_processes[0].returncode == 0
        assert terminate_calls == []


async def test_a_native_server_emitting_crlf_line_endings_round_trips_messages() -> None:  # pragma: no cover
    """The client round-trips messages from a text-mode Windows server that frames its output with \\r\\n.

    `TextIOWrapper`'s `newline=None` makes `print()` emit \\r\\n on Windows (the SDK's own server
    writes through such a wrapper); the client copes because the reader splits on "\\n" only and
    the JSON parser tolerates the trailing "\\r" as whitespace.
    tests/issues/test_552_windows_hang.py hits the same wire form implicitly via `initialize()`;
    this test is the explicit owner of the framing claim.
    """
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

    # One interpreter cold start on a loaded runner; healthy runs take ~0.3s.
    with anyio.fail_after(10.0):
        async with stdio_client(server_params) as (read_stream, write_stream):
            await write_stream.send(SessionMessage(ping))
            received = await read_stream.receive()
            # A reader that choked on the trailing \r would deliver a ValueError instead of a parsed message.
            assert isinstance(received, SessionMessage)
            assert received.message == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
