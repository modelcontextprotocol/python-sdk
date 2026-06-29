import anyio
import pytest

from mcp.server.lowlevel.server import Server
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_server_run_exits_cleanly_when_transport_yields_exception_then_closes():
    """Regression test for #1967 / #2064.

    Reproduces stateless streamable HTTP when a POST handler throws: the transport
    yields an Exception into the read stream, then closes it. The message handler
    used to send_log_message through the already-closed write stream, crashing
    server.run() with ClosedResourceError; now the exception is only logged.
    """
    server = Server("test-server")

    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    # Zero-buffer write stream: any send() blocks until the read loop exits and closes
    # the stream, raising ClosedResourceError — reproduces the race without sleeps.
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)

    read_send.send_nowait(RuntimeError("simulated transport error"))
    read_send.close()

    with anyio.fail_after(5):
        await server.run(read_recv, write_send, server.create_initialization_options())

    # EndOfStream on the closed stream proves the server wrote nothing before exiting.
    with pytest.raises(anyio.EndOfStream):
        write_recv.receive_nowait()
    write_recv.close()
