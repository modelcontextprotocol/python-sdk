import sys
from contextlib import asynccontextmanager
from typing import TextIO

# Import from the new files
from .parameters import StdioServerParameters
from .transport import StdioClientTransport


@asynccontextmanager
async def stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """
    Client transport for stdio: connects to a server by spawning a process
    and communicating with it over stdin/stdout, managed by StdioClientTransport.
    """
    transport = StdioClientTransport(server_params=server, errlog=errlog)
    async with transport as streams:
        yield streams


# Ensure __all__ or exports are updated if this was a public API change, though
# stdio_client itself remains the primary public entry point from this file.
