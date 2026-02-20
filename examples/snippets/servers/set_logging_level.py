import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Logging Level Example")

current_level: types.LoggingLevel = "warning"


@server.set_logging_level()
async def handle_set_level(level: types.LoggingLevel) -> None:
    """Handle client request to change the logging level."""
    global current_level
    current_level = level
