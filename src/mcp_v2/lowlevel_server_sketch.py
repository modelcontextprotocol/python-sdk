from collections.abc import Awaitable, Callable
from typing import cast

from mcp_v2.transport.context import Context
from mcp_v2.transport.transport_interface import Transport
from mcp_v2.types import (
    ClientNotificationMethod,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestMethod,
)

RequestHandler = Callable[[Context, JSONRPCRequest], Awaitable[JSONRPCResponse]]
NotificationHandler = Callable[[JSONRPCNotification], Awaitable[None]]


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

    def register_notification_handler(self, method: ClientNotificationMethod, handler: NotificationHandler) -> None:
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
