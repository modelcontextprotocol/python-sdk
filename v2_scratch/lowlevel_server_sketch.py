from asyncio import Queue
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Protocol, TypeAlias

from mcp import CallToolRequest, InitializeRequest, JSONRPCRequest
from mcp.types import (
    CallToolResult,
    Implementation,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCResponse,
    Notification,
    ResourceUpdatedNotification,
    Result,
    ServerCapabilities,
    TextContent,
)

JSONRPCMessageType: TypeAlias = JSONRPCMessage | Notification
JSONRPCResponseType: TypeAlias = JSONRPCResponse | Result

Emitter = Callable[[JSONRPCMessageType], Coroutine[None, None, None]]
RequestHandler = Callable[[JSONRPCRequest, Emitter], Coroutine[None, None, JSONRPCResponseType]]
NotificationHandler = Callable[[JSONRPCNotification], Coroutine[None, None, None]]
GetStreamHandler = Callable[[Emitter], Coroutine[None, None, None]]


class Transport(Protocol):
    async def send(self, message: JSONRPCMessage) -> None: ...
    def __aiter__(self) -> AsyncIterator[JSONRPCMessage]: ...


class StreamableHTTPTransport:
    def __init__(self, get_stream_handler: GetStreamHandler):
        self.get_stream_handler = get_stream_handler

    async def handle_get_stream(self, emit: Emitter) -> None:
        await self.get_stream_handler(emit)


class Server:
    def __init__(
        self,
        request_handlers: dict[str, RequestHandler] | None = None,
        notification_handlers: dict[str, NotificationHandler] | None = None,
    ):
        self._request_handlers: dict[str, RequestHandler] = request_handlers or {}
        self._notification_handlers: dict[str, NotificationHandler] = notification_handlers or {}

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        self._request_handlers[method] = handler

    def register_notification_handler(self, method: str, handler: NotificationHandler) -> None:
        self._notification_handlers[method] = handler

    # async def _emit(self, message: JSONRPCMessageType) -> None:
    #     if self._transport:
    #         await self._transport.send(message)

    # async def handle_message(self, message):
    #     if isinstance(message, JSONRPCRequest):
    #         handler = self._request_handlers.get(message.method)
    #         if handler:
    #             response = await handler(message, self._emit)
    #             await transport.send(response)
    #     elif isinstance(message, JSONRPCNotification):
    #         handler = self._notification_handlers.get(message.method)
    #         if handler:
    #             await handler(message)

    async def run(self, transport: Transport) -> None:
        async for message in transport:
            if isinstance(message, JSONRPCRequest):
                handler = self._request_handlers.get(message.method)
                if handler:
                    ctx = Context(transport.send_request)
                    response = await handler(ctx, message)
                    await transport.send(response)
            elif isinstance(message, JSONRPCNotification):
                handler = self._notification_handlers.get(message.method)
                if handler:
                    await handler(message)


notification_queue: Queue[JSONRPCMessageType] = Queue()


class Context:
    async def send_notification(self, message: JSONRPCNotification) -> None:
        pass

    async def send_request(self, JSONRPCMessage: JSONRPCMessageType) -> JSONRPCResponse:
        pass


"""

client -> server - tool call

server -> client SSE stream

SSE: server -> client JSONRPCREquest

client -> server JSONRPCResponse via HTTP post request
"""


async def tool_call_handler(ctx: Context, request: JSONRPCRequest) -> JSONRPCResponseType:
    assert isinstance(request, CallToolRequest)
    if request.params.name == "get_weather":
        # emit() -> per-request stream
        await ctx.send_notification(
            params={"type": "progress_notification", "progressToken": "connecting to api", "progress": 0.1}
        )

        response = await ctx.send_request(params={})

        # queue -> GET stream (user manages this)
        await notification_queue.put(ResourceUpdatedNotification(...))
        return CallToolResult(content=[TextContent(type="text", text="it's hot")])
    else:
        return CallToolResult(content=[TextContent(type="text", text="shit's fucked")], isError=True)


async def tool_list_handler(request: JSONRPCRequest, emit: Emitter) -> JSONRPCResponseType: ...


async def initialize_handler(request: JSONRPCRequest, emit: Emitter) -> JSONRPCResponseType:
    assert isinstance(request, InitializeRequest)
    return InitializeResult(
        protocolVersion="2025-11-25",
        capabilities=ServerCapabilities(tools={}),
        serverInfo=Implementation(name="my-server", version="1.0.0"),
    )


async def initialized_handler(notification: JSONRPCNotification) -> None:
    # Client has completed initialization
    ...


async def cancelled_handler(notification: JSONRPCNotification) -> None: ...


async def get_stream_handler(emit: Emitter) -> None:
    while True:
        notification = await notification_queue.get()
        await emit(notification)


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

transport = StreamableHTTPTransport(get_stream_handler=get_stream_handler)


app.run(transport)


"""

Session????

Server
Request ID resolving???
Transport

"""
