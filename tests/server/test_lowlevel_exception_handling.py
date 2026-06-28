import anyio
import pytest

from mcp.server.lowlevel.server import Server
from mcp.shared.message import RequestSettled, SessionMessage


@pytest.mark.anyio
async def test_server_run_exits_cleanly_when_transport_yields_exception_then_closes():
    """Regression test for #1967 / #2064.

    Exercises the real Server.run() path with real memory streams, reproducing
    what happens in stateless streamable HTTP when a POST handler throws:

    1. Transport yields an Exception into the read stream
       (streamable_http.py does this in its broad POST-handler except).
    2. Transport closes the read stream (terminate() in stateless mode).
    3. The read loop exits and closes the write stream.

    Before the fix, the message handler tried to send_log_message through the
    closed write stream, raising ClosedResourceError and crashing server.run().
    After the fix (and now in the dispatcher), the exception is only logged
    locally.
    """
    server = Server("test-server")

    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    # Zero-buffer on the write stream forces send() to block until received.
    # With no receiver, a send() sits blocked until the read loop exits its
    # `async with read_stream, write_stream:` block and closes the stream, at
    # which point the blocked send raises ClosedResourceError. This
    # deterministically reproduces the race without sleeps.
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage | RequestSettled](0)

    # What the streamable HTTP transport does: push the exception, then close.
    read_send.send_nowait(RuntimeError("simulated transport error"))
    read_send.close()

    with anyio.fail_after(5):
        # stateless=True so server.run doesn't wait for initialize handshake.
        # Before the fix, this raised ExceptionGroup(ClosedResourceError).
        await server.run(read_recv, write_send, server.create_initialization_options())

    # write_send was closed inside run's `async with`; receive_nowait raises
    # EndOfStream iff the buffer is empty (i.e., server wrote nothing).
    with pytest.raises(anyio.EndOfStream):
        write_recv.receive_nowait()
    write_recv.close()
