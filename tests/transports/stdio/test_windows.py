"""Windows-only stdio lifecycle behaviors, against real subprocesses.

Each test pins a contract that exists only on Windows: Job-Object reaping of a
gracefully-exited server's children (the deliberate divergence from the POSIX
policy in test_posix.py), the SelectorEventLoop fallback wrapper, and the CRLF
line endings a native text-mode server emits. Synchronization is kernel-level
only (liveness sockets); see `_liveness`.

Per-test no-cover pragmas (as in tests/issues/test_552_windows_hang.py): bodies run
only on windows-latest CI legs, the per-job 100% gate would count them uncovered on
non-Windows runners, and strict-no-cover is skipped on Windows where they execute.
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
    """A gracefully-exited server's child is killed deterministically when shutdown closes the job handle.

    The server exits cleanly on stdin closure, leaving a child behind; shutdown's
    close of the server's Job Object handle (`close_process_job` +
    `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) kills that child deterministically, not at
    GC time. Documented divergence from POSIX (docs/migration.md; the POSIX twin is
    test_posix.py::test_a_gracefully_exiting_servers_child_survives_the_client_shutdown).

    `terminate_calls == []` is the load-bearing distinction: the child died through
    the graceful path's job-handle close, not the escalation's `TerminateJobObject`;
    the two kills are indistinguishable on the socket.

    Both processes connect back and their stderr is captured via `errlog`, so a
    timeout failure can report which process never showed and the child's fate
    (xdist swallows subprocess stderr on CI).
    """
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # The startup marker (and any child traceback, via stderr=sys.stderr below)
        # lands in errlog, splitting "never started" from "started but never connected".
        child = "import sys\nprint('child-started', file=sys.stderr, flush=True)\n" + connect_back_script(port)
        # The server spawns a child, connects back itself, then exits as soon as
        # its stdin closes: the graceful path, so the escalation never runs.
        # The child inherits Job membership: the SDK assigns the server to the Job
        # synchronously after spawn, long before the cold-starting interpreter can
        # Popen the child (membership is inherited at CreateProcess, never
        # acquired retroactively).
        #
        # The child's stdin must be DEVNULL: CPython startup queries fd 0, and
        # Windows serializes that query behind the server's pending blocking
        # `sys.stdin.read()` on the inherited pipe, so the child would freeze at
        # interpreter startup until the next inbound byte or EOF.
        #
        # After stdin EOF ends the server, it reports the child's `poll()` status:
        # `None` means alive at server exit; an exit/NTSTATUS code names the killer.
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
                # Two interpreter cold starts on a loaded runner; healthy runs
                # take well under a second.
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
                # `stdio_client.__aexit__` has already completed its shielded shutdown,
                # so the stderr read carries the server's final `child-rc` line, not a
                # mid-flight snapshot.
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

            # Context exit closed the job handle: KILL_ON_JOB_CLOSE killed the
            # child and the server exited gracefully, so both sockets close.
            # The `spawned_processes` strong reference is load-bearing: `_process_jobs`
            # is weak-keyed, so without it a GC between context exit and this assert
            # could close the job handle itself and mask a regression in the
            # deterministic close.
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


# Overrides the suite-wide anyio_backend fixture for this test only: a selector
# event loop cannot run asyncio subprocesses, forcing stdio_client onto FallbackProcess.
@pytest.mark.parametrize("anyio_backend", [("asyncio", {"loop_factory": asyncio.SelectorEventLoop})])
async def test_a_selector_event_loop_session_uses_the_fallback_process_and_exits_cleanly(  # pragma: no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Under a `SelectorEventLoop`, `stdio_client` falls back to `FallbackProcess` and still exits cleanly.

    A selector event loop has no asyncio subprocess support, so `stdio_client`
    falls back to the Popen-based `FallbackProcess` wrapper; a well-behaved server
    still completes the full clean lifecycle: spawn, liveness, exit on stdin
    closure, reaped, never escalated against.

    The `isinstance` check is the engagement proof: if a future anyio gains selector
    subprocess support, the spawn would silently return a normal Process. A hang here
    most likely means the known fallback hazard documented in `stdio_client`'s
    shutdown comment (reader thread parked in a synchronous `ReadFile`), which is
    why this test pins only the clean-exit path, never a kill path.
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
    """The client round-trips messages from a text-mode Windows server that frames its output with \\r\\n.

    `TextIOWrapper`'s `newline=None` translates "\\n" to `os.linesep`, so such a
    server emits \\r\\n; the client still parses each line because the reader
    splits on "\\n" only and the JSON parser tolerates the trailing "\\r" as
    whitespace. The SDK's own server writes through such a wrapper, so this
    tolerance is load-bearing for Windows interop.

    tests/issues/test_552_windows_hang.py exercises the same wire form implicitly
    through `initialize()`; this test is the explicit owner of the framing claim.
    """
    # Read one request, answer it via print() (which emits \r\n on Windows), then
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


async def test_a_tool_spawned_python_child_with_default_stdin_completes_promptly() -> None:  # pragma: no cover
    """A tool that runs a Python subprocess without redirecting stdin returns promptly.

    Regression for #671 (SDK-defined isolation behavior): before `stdio_server`
    pointed fd 0 at the null device, such a child inherited the protocol stdin
    pipe and blocked inside interpreter startup behind the transport's pending
    read (CPython gh-78961) until the next inbound message arrived - so these
    calls, with no follow-up traffic, hung until the timeout. Covers both
    reported shapes: output piped with stdin defaulted, and no redirection at
    all (the console subsystem still propagates the standard handles).
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
            # No redirection at all: Windows still hands a console child the
            # parent's standard handles, so pre-isolation this hung too. The
            # child prints nothing, keeping this test pinned on the hang; the
            # noisy-child shape is owned by test_lifecycle.py.
            proc = subprocess.run([sys.executable, "-c", "pass"], timeout=20)
            return str(proc.returncode)

        mcp.run()
        """
    )
    transport = stdio_client(StdioServerParameters(command=sys.executable, args=["-c", server]))

    # Four interpreter cold starts on a loaded runner (the server also imports
    # the SDK); healthy runs take ~3s. A regression hangs forever, so the bound
    # only has to beat "never".
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
