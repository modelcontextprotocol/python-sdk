from collections.abc import Awaitable, Callable
from typing import Any, Generic, Literal, overload

from typing_extensions import TypeVar

from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    CancelledNotificationParams,
    CompleteRequestParams,
    CompleteResult,
    EmptyResult,
    GetPromptRequestParams,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    ProgressNotificationParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    RequestParams,
    SetLevelRequestParams,
    SubscribeRequestParams,
    TextContent,
    UnsubscribeRequestParams,
)

LifespanResultT = TypeVar("LifespanResultT", default=Any)
RequestT = TypeVar("RequestT", default=Any)

Ctx = RequestContext[ServerSession, LifespanResultT, RequestT]


class RequestHandler(Generic[LifespanResultT, RequestT]):
    @overload
    def __init__(
        self,
        method: Literal["ping"],
        handler: Callable[[Ctx, RequestParams | None], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListPromptsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/get"],
        handler: Callable[[Ctx, GetPromptRequestParams], Awaitable[GetPromptResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListResourcesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/templates/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListResourceTemplatesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/read"],
        handler: Callable[[Ctx, ReadResourceRequestParams], Awaitable[ReadResourceResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/subscribe"],
        handler: Callable[[Ctx, SubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/unsubscribe"],
        handler: Callable[[Ctx, UnsubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["logging/setLevel"],
        handler: Callable[[Ctx, SetLevelRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListToolsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/call"],
        handler: Callable[[Ctx, CallToolRequestParams], Awaitable[CallToolResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["completion/complete"],
        handler: Callable[[Ctx, CompleteRequestParams], Awaitable[CompleteResult]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[Any, Any], Any]) -> None:
        self.method = method
        self.endpoint = handler

    async def handle(self, ctx: Ctx, params: Any) -> Any:
        return await self.endpoint(ctx, params)


class NotificationHandler(Generic[LifespanResultT, RequestT]):
    @overload
    def __init__(
        self,
        method: Literal["notifications/initialized"],
        handler: Callable[[Ctx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/cancelled"],
        handler: Callable[[Ctx, CancelledNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/progress"],
        handler: Callable[[Ctx, ProgressNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/roots/list_changed"],
        handler: Callable[[Ctx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[Any, Any], Any]) -> None:
        self.method = method
        self.endpoint = handler

    async def handle(self, ctx: Ctx, params: Any) -> None:
        await self.endpoint(ctx, params)


class Server(Generic[LifespanResultT, RequestT]):
    def __init__(
        self,
        handlers: list[RequestHandler[LifespanResultT, RequestT] | NotificationHandler[LifespanResultT, RequestT]],
    ) -> None:
        self._request_handlers: dict[str, RequestHandler[LifespanResultT, RequestT]] = {}
        self._notification_handlers: dict[str, NotificationHandler[LifespanResultT, RequestT]] = {}
        for handler in handlers:
            if isinstance(handler, RequestHandler):
                if handler.method in self._request_handlers:
                    raise ValueError(f"Duplicate request handler for '{handler.method}'")
                self._request_handlers[handler.method] = handler
            elif isinstance(handler, NotificationHandler):  # pyright: ignore[reportUnnecessaryIsInstance]
                if handler.method in self._notification_handlers:
                    raise ValueError(f"Duplicate notification handler for '{handler.method}'")
                self._notification_handlers[handler.method] = handler
            else:
                raise TypeError(f"Unknown handler type: {type(handler)}")

    def add_handler(
        self, handler: RequestHandler[LifespanResultT, RequestT] | NotificationHandler[LifespanResultT, RequestT]
    ) -> None:
        if isinstance(handler, RequestHandler):
            self._request_handlers[handler.method] = handler
        elif isinstance(handler, NotificationHandler):  # pyright: ignore[reportUnnecessaryIsInstance]
            self._notification_handlers[handler.method] = handler
        else:
            raise TypeError(f"Unknown handler type: {type(handler)}")


# ===== sample usage below ====


async def call_tool_handler(context: Ctx, params: CallToolRequestParams) -> CallToolResult:
    if params.name == "slow_tool":
        ...
    return CallToolResult(content=[TextContent(type="text", text=f"Called {params.name}")], is_error=False)


async def list_handler(context: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult: ...
async def progress_handler(context: Ctx, params: ProgressNotificationParams) -> None: ...
async def cancelled_handler(context: Ctx, params: CancelledNotificationParams) -> None: ...


app2 = Server(
    handlers=[
        RequestHandler("tools/call", handler=call_tool_handler),
        RequestHandler("tools/list", handler=list_handler),
        NotificationHandler("notifications/progress", handler=progress_handler),
        NotificationHandler("notifications/cancelled", handler=cancelled_handler),
    ],
)
