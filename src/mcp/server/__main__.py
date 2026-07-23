import logging
import sys
import warnings

import anyio

from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

if not sys.warnoptions:
    warnings.simplefilter("ignore")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")


async def main() -> None:
    server: Server[dict[str, object]] = Server("mcp")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    anyio.run(main, backend="trio")
