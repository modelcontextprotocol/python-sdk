from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from v2_scratch.types import (
    ClientNotificationMethod,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    NotificationParams,
    RequestMethod,
)


class Transport(Protocol):
    async def send(self, message: JSONRPCMessage) -> None: ...
    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse: ...
    def __aiter__(self) -> AsyncIterator[JSONRPCMessage]: ...


@dataclass
class Context:
    transport: Transport

    async def send_notification(self, params: NotificationParams) -> None:
        # Build JSONRPCNotification from params and send
        notification = JSONRPCNotification(
            method=params.method,
            params=params.model_dump(exclude={"method"}),
        )
        await self.transport.send(notification)

    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        return await self.transport.send_request(request)


RequestHandler = Callable[[Context, JSONRPCRequest], Awaitable[JSONRPCResponse]]
NotificationHandler = Callable[[JSONRPCNotification], Awaitable[None]]
GetStreamHandler = Callable[[Context], Awaitable[None]]


class Server:
    def __init__(
        self,
        request_handlers: dict[RequestMethod, RequestHandler] | None = None,
        notification_handlers: dict[ClientNotificationMethod, NotificationHandler] | None = None,
    ):
        # Internal storage uses str keys for lookup with message.method
        self._request_handlers: dict[str, RequestHandler] = cast(
            dict[str, RequestHandler], dict(request_handlers or {})
        )
        self._notification_handlers: dict[str, NotificationHandler] = cast(
            dict[str, NotificationHandler], dict(notification_handlers or {})
        )

    def register_request_handler(self, method: RequestMethod, handler: RequestHandler) -> None:
        self._request_handlers[method] = handler

    def register_notification_handler(
        self, method: ClientNotificationMethod, handler: NotificationHandler
    ) -> None:
        self._notification_handlers[method] = handler

    async def run(self, transport: Transport) -> None:
        async for message in transport:
            if isinstance(message, JSONRPCRequest):
                handler = self._request_handlers.get(message.method)
                if handler:
                    ctx = Context(transport)
                    response = await handler(ctx, message)
                    await transport.send(response)  # Response already complete with id
            elif isinstance(message, JSONRPCNotification):
                handler = self._notification_handlers.get(message.method)
                if handler:
                    await handler(message)


class StreamableHTTPTransport:
    def __init__(self, get_stream_handler: GetStreamHandler):
        self.get_stream_handler = get_stream_handler

    async def handle_get_stream(self, ctx: Context) -> None:
        await self.get_stream_handler(ctx)


