"""Kernel-synchronized liveness probes for the real-subprocess stdio lifecycle suite.

A spawned (grand)child connects back to a test-owned TCP listener and sends
`b'alive'`; the kernel then provides every signal a test needs, with no sleeps or
polling. The kernel closes all of a process's file descriptors on exit, so EOF
(clean close / FIN) or `BrokenResourceError` (abrupt close / RST, typical of
SIGKILL and Windows job termination) proves death; only a running process can
answer an echo, so a reply proves liveness without racing a kill.

Extracted from the real-process section of tests/client/test_stdio.py; the two
copies on this branch are deliberate -- consolidating them is follow-up work.
"""

import anyio
import anyio.abc
import pytest


def connect_back_script(port: int, *, echo: bool = False) -> str:
    """Return a `python -c` script body that connects to 127.0.0.1:`port` and
    sends `b'alive'`, then blocks forever -- or, with `echo=True`, echoes every
    received chunk back so `assert_peer_echoes` can prove the process still runs.
    """
    # lax no cover: echo mode is used only by POSIX-gated tests; Windows runners enforce 100% per job.
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
    """Accept one connection and assert the peer sent `b'alive'`, reading until the
    full 5-byte banner arrives (TCP may legally split even a tiny send). Callers
    bound this with `anyio.fail_after` to catch a subprocess that never started.
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
    round-tripping one echo through it (the peer must use `echo=True`). A dead
    process can never answer, so this cannot pass spuriously.

    lax no cover: only POSIX-gated survival tests call this; Windows runners
    enforce 100% coverage per job.
    """
    with anyio.fail_after(5.0):
        await stream.send(b"ping")
        # Read until the full echo has arrived: TCP may legally split even a tiny send.
        echoed = b""
        while len(echoed) < 4:
            echoed += await stream.receive(4 - len(echoed))
    assert echoed == b"ping", f"expected b'ping', got {echoed!r}"
