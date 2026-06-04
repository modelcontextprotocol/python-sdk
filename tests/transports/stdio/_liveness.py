"""Kernel-synchronized liveness probes for the real-subprocess stdio lifecycle suite.

A spawned (grand)child connects back to a test-owned TCP listener and sends
`b'alive'`. From there the kernel provides every signal a test needs, with no
sleeps or polling anywhere:

1. `accept_alive` blocks until the subprocess connects, proving it is running (and
   that the script lines before the connect have executed).
2. `assert_stream_closed` proves the peer terminated: the kernel closes all of a
   process's file descriptors on exit, surfacing EOF (clean close / FIN) or
   `BrokenResourceError` (abrupt close / RST, typical of SIGKILL and Windows job
   termination).
3. `assert_peer_echoes` proves the peer is *alive*: only a running process can
   answer an echo, so a positive reply cannot race a kill the way a "no FIN yet"
   observation could.

These helpers are extracted from the real-process section of
tests/client/test_stdio.py; the two copies on this branch are deliberate —
consolidating that file onto this module is follow-up work.
"""

import anyio
import anyio.abc
import pytest


def connect_back_script(port: int, *, echo: bool = False) -> str:
    """Return a `python -c` script body that connects to 127.0.0.1:`port` and
    sends `b'alive'`.

    By default the process then blocks forever, serving as a pure liveness beacon
    for kill/termination tests. With `echo=True` it instead echoes every received
    chunk back (the recv parks it just as indefinitely), so a survival test can
    prove the process is still running after the client is gone — see
    `assert_peer_echoes`.
    """
    # Excluded from coverage (lax: exempt from strict-no-cover): echo mode is
    # used only by POSIX-gated tests, and Windows runners enforce 100% per job.
    if echo:  # pragma: lax no cover
        tail = "while True:\n    data = s.recv(65536)\n    if not data:\n        break\n    s.sendall(data)\n"
    else:
        tail = "time.sleep(3600)\n"
    return f"import socket, time\ns = socket.create_connection(('127.0.0.1', {port}))\ns.sendall(b'alive')\n" + tail


async def open_liveness_listener() -> tuple[anyio.abc.SocketListener, int]:
    """Open a TCP listener on localhost and return it along with its port."""
    multi = await anyio.create_tcp_listener(local_host="127.0.0.1")
    sock = multi.listeners[0]
    assert isinstance(sock, anyio.abc.SocketListener)
    addr = sock.extra(anyio.abc.SocketAttribute.local_address)
    # IPv4 local_address is (host: str, port: int)
    assert isinstance(addr, tuple) and len(addr) >= 2 and isinstance(addr[1], int)
    return sock, addr[1]


async def accept_alive(sock: anyio.abc.SocketListener) -> anyio.abc.SocketStream:
    """Accept one connection and assert the peer sent `b'alive'`.

    Blocks deterministically until a subprocess connects (no polling), reading
    until the full 5-byte banner has arrived — TCP may legally split even a tiny
    send. The calling test bounds this with `anyio.fail_after` to catch the case
    where the subprocess chain failed to start.
    """
    stream = await sock.accept()
    msg = b""
    while len(msg) < 5:
        msg += await stream.receive(5 - len(msg))
    assert msg == b"alive", f"expected b'alive', got {msg!r}"
    return stream


async def assert_stream_closed(stream: anyio.abc.SocketStream) -> None:
    """Assert the peer holding the other end of `stream` has terminated."""
    with anyio.fail_after(5.0), pytest.raises((anyio.EndOfStream, anyio.BrokenResourceError)):
        await stream.receive(1)


async def assert_peer_echoes(stream: anyio.abc.SocketStream) -> None:  # pragma: lax no cover
    """Assert the peer holding the other end of `stream` is still running, by
    round-tripping one echo through it (the peer must use `echo=True`).

    A dead process can never answer, so under a regression that kills the peer this
    raises (EOF/reset) or times out via the bound — it cannot pass spuriously; the
    sub-millisecond window between a kill being issued and taking effect is dwarfed
    by the socket round trip that must complete after it.

    Excluded from coverage (lax: exempt from strict-no-cover) like `connect_back_script`'s
    echo mode: only POSIX-gated survival tests call this, and Windows runners enforce
    100% coverage per job.
    """
    with anyio.fail_after(5.0):
        await stream.send(b"ping")
        # Read until the full echo has arrived: TCP may legally split even a tiny send.
        echoed = b""
        while len(echoed) < 4:
            echoed += await stream.receive(4 - len(echoed))
    assert echoed == b"ping", f"expected b'ping', got {echoed!r}"
