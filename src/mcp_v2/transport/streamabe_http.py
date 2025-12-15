from collections.abc import Awaitable, Callable

from mcp_v2.transport.context import Context

GetStreamHandler = Callable[[Context], Awaitable[None]]


class StreamableHTTPTransport:
    def __init__(self, get_stream_handler: GetStreamHandler):
        self.get_stream_handler = get_stream_handler

    async def handle_get_stream(self, ctx: Context) -> None:
        await self.get_stream_handler(ctx)
