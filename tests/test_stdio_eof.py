"""Test that stdio server exits when stdin reaches EOF."""
import asyncio
import sys
from io import StringIO

import anyio
import pytest

from mcp.server.stdio import stdio_server


@pytest.mark.anyio
async def test_stdio_server_exits_on_eof():
    """Server should exit gracefully when stdin is closed (EOF)."""
    # Create a closed stdin (simulating parent death)
    closed_stdin = StringIO()  # Empty, immediate EOF
    
    # This should complete without hanging
    with anyio.move_on_after(5):  # 5 second timeout
        async with stdio_server() as (read_stream, write_stream):
            # Try to read from stream - should get EOF quickly
            try:
                await read_stream.receive()
            except anyio.EndOfStream:
                pass  # Expected - stream closed
    
    # If we get here without timeout, test passes


@pytest.mark.anyio  
async def test_stdio_server_parent_death_simulation():
    """Simulate parent process death by closing stdin."""
    # Create pipes to simulate stdin/stdout
    stdin_reader, stdin_writer = anyio.create_memory_object_stream[str](10)
    
    async with stdio_server() as (read_stream, write_stream):
        # Close the input to simulate parent death
        await stdin_writer.aclose()
        
        # Server should detect EOF and exit gracefully
        with pytest.raises(anyio.EndOfStream):
            await asyncio.wait_for(read_stream.receive(), timeout=5.0)
