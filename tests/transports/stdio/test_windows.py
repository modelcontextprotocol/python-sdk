"""Windows-only stdio lifecycle behaviors, against real subprocesses.

Each test pins a contract that exists only on Windows: Job-Object reaping of a
gracefully-exited server's children (the deliberate divergence from the POSIX
policy in test_posix.py), the SelectorEventLoop fallback wrapper, and the CRLF
line endings a native text-mode server emits. Synchronization is kernel-level
only (liveness sockets); see `_liveness`.

These bodies run solely on windows-latest CI legs, so each test function carries
the same no-cover exclusion as tests/issues/test_552_windows_hang.py: the per-job
100% coverage gate on non-Windows runners would otherwise count them as uncovered,
and strict-no-cover (which would object to an executed excluded line) is skipped
on the Windows runners where they do execute.
"""

import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import anyio
import anyio.abc
import pytest

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCRequest, JSONRPCResponse
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
    """A server that exits cleanly on stdin closure leaves a child behind; on Windows
    that child is killed when shutdown closes the server's Job Object handle
    (`close_process_job` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) — deterministically,
    not whenever the handle happens to be garbage-collected. This is the documented
    divergence from POSIX, where the identical scenario leaves the child alive
    (docs/migration.md, "stdio_client no longer kills children of a gracefully-exited
    server on POSIX"; the POSIX twin is
    test_posix.py::test_a_gracefully_exiting_servers_child_survives_the_client_shutdown).

    `terminate_calls == []` is the load-bearing distinction: it proves the child died
    through the graceful path's job-handle close and not through the escalation's
    `TerminateJobObject` — the two kills are indistinguishable on the socket.

    The server connects back too (not just the child), the child's stderr is routed
    into the server's, and both are captured through `errlog`; the child prints a
    startup marker there, and the server reports the child's `poll()` status after
    stdin EOF ends it. A timeout failure then reports how many connections arrived
    (so which process never showed), how long the spawn took, and the captured
    stderr verbatim — including the child's fate — since xdist swallows subprocess
    stderr on CI, and without the capture a broken spawn chain is undiagnosable
    there.
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # The startup marker (and any child traceback, via the Popen's
        # stderr=sys.stderr below) lands in errlog, splitting "child never
        # spawned/started" from "child started but could not connect".
        child = "import sys\nprint('child-started', file=sys.stderr, flush=True)\n" + connect_back_script(port)
        # The server spawns a child (its Popen failure, if any, is surfaced on
        # stderr), connects back itself, then exits as soon as its stdin closes —
        # the well-behaved graceful path, so the escalation never runs. The child
        # inherits Job membership because the SDK assigns the server to the Job
        # synchronously after the spawn returns, while the server's interpreter is
        # still cold-starting — long before it can Popen the child (job membership
        # is inherited at CreateProcess, never acquired retroactively).
        #
        # The child is spawned through the base interpreter, not `sys.executable`:
        # in launcher-wrapped venvs (uv's `python.exe` is a trampoline that runs
        # the real interpreter inside its own Job machinery) the extra launcher
        # layer proved fatal to grandchildren on CI runners — they booted and then
        # died tracelessly inside the launcher's private job. The contract under
        # test is unchanged: the child still inherits the SDK's Job at
        # CreateProcess. After stdin EOF ends the server, it reports the child's
        # `poll()` status — `None` means the child was alive when the server
        # exited; an exit or NTSTATUS code names whatever killed it.
        server = (
            f"import socket, subprocess, sys\n"
            f"exe = getattr(sys, '_base_executable', None) or sys.executable\n"
            f"try:\n"
            f"    p = subprocess.Popen([exe, '-c', {child!r}], stderr=sys.stderr)\n"
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
                # The bound covers two Python interpreter cold starts on a loaded
                # runner; a healthy run takes well under a second.
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
                # By the time this clause runs, `stdio_client.__aexit__` has already
                # completed its shielded shutdown on the way out of the `async
                # with`: stdin closed, the server printed its `child-rc` line and
                # exited. The stderr read below therefore carries the child's fate,
                # not a mid-flight snapshot.
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

            # Both peers connected and the context has fully exited, closing the
            # job handle. KILL_ON_JOB_CLOSE must have killed the child, and the
            # server died with its graceful exit: both sockets close. The
            # `spawned_processes` recording is load-bearing here beyond
            # observability: `_process_jobs` is weak-keyed, and the recorded strong
            # reference pins the process object (and with it the job-handle entry)
            # across this assertion window — without it, a GC between context exit
            # and this assert could close the handle itself and mask a regression
            # in the deterministic close.
            try:
                for stream in streams:
                    await assert_stream_closed(stream)
            except TimeoutError:
                pytest.fail(f"a socket stayed open after shutdown; server stderr: {server_stderr()!r}")

            leader = spawned_processes[0]
            # The graceful path: the server exited on stdin closure with code 0,
            # and the tree-termination escalation was never invoked.
            assert leader.returncode == 0, server_stderr()
            assert terminate_calls == [], server_stderr()


# Overrides the suite-wide plain-"asyncio" anyio_backend fixture for this test only:
# a selector event loop cannot run asyncio subprocesses, which is exactly the
# environment that forces stdio_client onto the FallbackProcess path.
@pytest.mark.parametrize("anyio_backend", [("asyncio", {"loop_factory": asyncio.SelectorEventLoop})])
async def test_a_selector_event_loop_session_uses_the_fallback_process_and_exits_cleanly(  # pragma: no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Under a `SelectorEventLoop` (no asyncio subprocess support), `stdio_client`
    falls back to the Popen-based `FallbackProcess` wrapper and a well-behaved
    server still completes the full clean lifecycle: spawn, liveness, exit on stdin
    closure, reaped, never escalated against.

    The `isinstance` check is the engagement proof: if a future anyio gains selector
    subprocess support, the spawn silently returns a normal Process and this test
    would otherwise stop testing the fallback stack without failing. A hang here
    (a `fail_after` TimeoutError — or, if the reader thread is truly parked in a
    synchronous `ReadFile`, a hard hang that `fail_after` cannot interrupt) most
    likely means that known fallback hazard, documented in `stdio_client`'s
    shutdown comment — which is why this test pins only the clean-exit path, never
    a kill path.
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # Connect back for liveness, then exit as soon as stdin closes: the
        # well-behaved server, so shutdown's first step suffices.
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

        # The server exited on stdin closure: socket closed, exit code 0, and the
        # escalation never fired.
        await assert_stream_closed(stream)
        assert spawned_processes[0].returncode == 0
        assert terminate_calls == []


async def test_a_native_server_emitting_crlf_line_endings_round_trips_messages() -> None:  # pragma: no cover
    """A text-mode Windows server frames its output with \\r\\n (`TextIOWrapper`'s
    `newline=None` translates "\\n" to `os.linesep`), and the client still parses
    each line: the reader splits on "\\n" only, so the trailing "\\r" reaches the
    JSON parser and is tolerated as whitespace. The SDK's own server writes through
    exactly such a wrapper, so this tolerance is load-bearing for Windows interop.

    tests/issues/test_552_windows_hang.py exercises the same wire form implicitly
    through `initialize()`; this test is the explicit owner of the framing claim,
    driving `stdio_client`'s public streams with no session on top.
    """
    # Read one request, answer it via print() — which emits \r\n on Windows — then
    # exit when stdin closes. json.loads/dumps keep the script free of SDK imports.
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
            # A reader that choked on the trailing \r would deliver a ValueError
            # here instead of a parsed message.
            assert isinstance(received, SessionMessage)
            assert received.message == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
