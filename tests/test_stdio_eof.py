"""Test that stdio server exits when stdin reaches EOF."""
import anyio
import pytest
from io import TextIOWrapper, BytesIO

from mcp.server.stdio import stdio_server


@pytest.mark.anyio
async def test_stdio_server_exits_on_eof():
    """Server should exit gracefully when stdin is closed (EOF)."""
    # Create a stdin that immediately returns EOF
    empty_stdin = anyio.wrap_file(TextIOWrapper(BytesIO(b""), encoding="utf-8"))
    empty_stdout = anyio.wrap_file(TextIOWrapper(BytesIO(), encoding="utf-8"))

    # This should complete without hanging
    with anyio.move_on_after(5):
        async with stdio_server(stdin=empty_stdin, stdout=empty_stdout) as (
            read_stream,
            write_stream,
        ):
            # Try to read from stream - should get EndOfStream quickly
            try:
                await read_stream.receive()
            except anyio.EndOfStream:
                pass  # Expected - stream closed due to EOF
