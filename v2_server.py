from asyncio import Queue

from v2_scratch.lowlevel_server_sketch import Server
from v2_scratch.transport.context import Context
from v2_scratch.types import (
    CallToolResult,
    InitializeResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    NotificationParams,
    ProgressNotificationParams,
    ResourceUpdatedNotificationParams,
)

notification_queue: Queue[NotificationParams] = Queue()


"""

client -> server - tool call

server -> client SSE stream

SSE: server -> client JSONRPCRequest

client -> server JSONRPCResponse via HTTP post request
"""


async def tool_call_handler(ctx: Context, request: JSONRPCRequest) -> JSONRPCResponse:
    tool_name = request.params["name"] if request.params else None

    if tool_name == "get_weather":
        # send_notification -> per-request stream
        await ctx.send_notification(ProgressNotificationParams(progressToken="weather-fetch", progress=0.5))

        # send_request -> bidirectional (e.g., sampling)
        # _ = await ctx.send_request(...)

        # queue -> GET stream (user manages this)
        await notification_queue.put(ResourceUpdatedNotificationParams(uri="file:///weather.txt"))

        return CallToolResult(
            id=request.id,  # ID from request!
            content=[{"type": "text", "text": "it's hot"}],
        )
    else:
        return CallToolResult(
            id=request.id,
            content=[{"type": "text", "text": "unknown tool"}],
            isError=True,
        )


async def tool_list_handler(ctx: Context, request: JSONRPCRequest) -> JSONRPCResponse: ...


async def initialize_handler(ctx: Context, request: JSONRPCRequest) -> JSONRPCResponse:
    return InitializeResult(
        id=request.id,
        protocolVersion="2025-11-25",
        capabilities={},
        serverInfo={"name": "my-server", "version": "1.0.0"},
    )


async def initialized_handler(notification: JSONRPCNotification) -> None:
    # Client has completed initialization
    ...


async def cancelled_handler(notification: JSONRPCNotification) -> None: ...


async def get_stream_handler(ctx: Context) -> None:
    while True:
        params = await notification_queue.get()
        await ctx.send_notification(params)


# todo:
#  - replace with flatenned args instead of dict, to comapre against this one
#  - evaluate cuteness between these two methods, and just having a single jsonrequest handler function
app = Server(
    request_handlers={
        "initialize": initialize_handler,
        "tools/call": tool_call_handler,
        "tools/list": tool_list_handler,
    },
    notification_handlers={
        "notifications/initialized": initialized_handler,
        "notifications/cancelled": cancelled_handler,
    },
)

# transport = StreamableHTTPTransport(get_stream_handler=get_stream_handler)
#
#
# app.run(transport)


"""

Session????

Server
Request ID resolving???
Transport
"""
