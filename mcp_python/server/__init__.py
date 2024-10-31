import contextvars
import logging
import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl

from mcp_python.server import types
from mcp_python.server.session import ServerSession
from mcp_python.server.stdio import stdio_server as stdio_server
from mcp_python.shared.context import RequestContext
from mcp_python.shared.session import RequestResponder
from mcp_python.types import (
    METHOD_NOT_FOUND,
    CallToolRequest,
    ClientNotification,
    ClientRequest,
    CompleteRequest,
    ErrorData,
    JSONRPCMessage,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsRequest,
    ListToolsResult,
    LoggingLevel,
    ProgressNotification,
    Prompt,
    PromptReference,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceReference,
    ServerCapabilities,
    ServerResult,
    SetLevelRequest,
    SubscribeRequest,
    Tool,
    UnsubscribeRequest,
)

logger = logging.getLogger(__name__)

request_ctx: contextvars.ContextVar[RequestContext] = contextvars.ContextVar(
    "request_ctx"
)


class Server:
    def __init__(self, name: str):
        self.name = name
        self.request_handlers: dict[type, Callable[..., Awaitable[ServerResult]]] = {}
        self.notification_handlers: dict[type, Callable[..., Awaitable[None]]] = {}
        logger.info(f"Initializing server '{name}'")

    def create_initialization_options(self) -> types.InitializationOptions:
        """Create initialization options from this server instance."""

        def pkg_version(package: str) -> str:
            try:
                from importlib.metadata import version

                v = version(package)
                if v is not None:
                    return v
            except Exception:
                pass

            return "unknown"

        return types.InitializationOptions(
            server_name=self.name,
            server_version=pkg_version("mcp_python"),
            capabilities=self.get_capabilities(),
        )

    def get_capabilities(self) -> ServerCapabilities:
        """Convert existing handlers to a ServerCapabilities object."""

        def get_capability(req_type: type) -> dict[str, Any] | None:
            return {} if req_type in self.request_handlers else None

        return ServerCapabilities(
            prompts=get_capability(ListPromptsRequest),
            resources=get_capability(ListResourcesRequest),
            tools=get_capability(ListToolsRequest),
            logging=get_capability(SetLevelRequest),
        )

    @property
    def request_context(self) -> RequestContext:
        """If called outside of a request context, this will raise a LookupError."""
        return request_ctx.get()

    def list_prompts(self):
        def decorator(func: Callable[[], Awaitable[list[Prompt]]]):
            logger.debug("Registering handler for PromptListRequest")

            async def handler(_: Any):
                prompts = await func()
                return ServerResult(ListPromptsResult(prompts=prompts))

            self.request_handlers[ListPromptsRequest] = handler
            return func

        return decorator

    def get_prompt(self):
        from mcp_python.types import (
            GetPromptRequest,
            GetPromptResult,
            ImageContent,
            SamplingMessage,
            TextContent,
        )
        from mcp_python.types import (
            Role as Role,
        )

        def decorator(
            func: Callable[
                [str, dict[str, str] | None], Awaitable[types.PromptResponse]
            ],
        ):
            logger.debug("Registering handler for GetPromptRequest")

            async def handler(req: GetPromptRequest):
                prompt_get = await func(req.params.name, req.params.arguments)
                messages: list[SamplingMessage] = []
                for message in prompt_get.messages:
                    match message.content:
                        case str() as text_content:
                            content = TextContent(type="text", text=text_content)
                        case types.ImageContent() as img_content:
                            content = ImageContent(
                                type="image",
                                data=img_content.data,
                                mimeType=img_content.mime_type,
                            )
                        case _:
                            raise ValueError(
                                f"Unexpected content type: {type(message.content)}"
                            )

                    sampling_message = SamplingMessage(
                        role=message.role, content=content
                    )
                    messages.append(sampling_message)

                return ServerResult(
                    GetPromptResult(description=prompt_get.desc, messages=messages)
                )

            self.request_handlers[GetPromptRequest] = handler
            return func

        return decorator

    def list_resources(self):
        def decorator(func: Callable[[], Awaitable[list[Resource]]]):
            logger.debug("Registering handler for ListResourcesRequest")

            async def handler(_: Any):
                resources = await func()
                return ServerResult(
                    ListResourcesResult(resources=resources)
                )

            self.request_handlers[ListResourcesRequest] = handler
            return func

        return decorator

    def read_resource(self):
        from mcp_python.types import (
            BlobResourceContents,
            TextResourceContents,
        )

        def decorator(func: Callable[[AnyUrl], Awaitable[str | bytes]]):
            logger.debug("Registering handler for ReadResourceRequest")

            async def handler(req: ReadResourceRequest):
                result = await func(req.params.uri)
                match result:
                    case str(s):
                        content = TextResourceContents(
                            uri=req.params.uri,
                            text=s,
                            mimeType="text/plain",
                        )
                    case bytes(b):
                        import base64

                        content = BlobResourceContents(
                            uri=req.params.uri,
                            blob=base64.urlsafe_b64encode(b).decode(),
                            mimeType="application/octet-stream",
                        )

                return ServerResult(
                    ReadResourceResult(
                        contents=[content],
                    )
                )

            self.request_handlers[ReadResourceRequest] = handler
            return func

        return decorator


    def set_logging_level(self):
        from mcp_python.types import EmptyResult

        def decorator(func: Callable[[LoggingLevel], Awaitable[None]]):
            logger.debug("Registering handler for SetLevelRequest")

            async def handler(req: SetLevelRequest):
                await func(req.params.level)
                return ServerResult(EmptyResult())

            self.request_handlers[SetLevelRequest] = handler
            return func

        return decorator

    def subscribe_resource(self):
        from mcp_python.types import EmptyResult

        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for SubscribeRequest")

            async def handler(req: SubscribeRequest):
                await func(req.params.uri)
                return ServerResult(EmptyResult())

            self.request_handlers[SubscribeRequest] = handler
            return func

        return decorator

    def unsubscribe_resource(self):
        from mcp_python.types import EmptyResult

        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for UnsubscribeRequest")

            async def handler(req: UnsubscribeRequest):
                await func(req.params.uri)
                return ServerResult(EmptyResult())

            self.request_handlers[UnsubscribeRequest] = handler
            return func

        return decorator

    def list_tools(self):
        def decorator(func: Callable[[], Awaitable[list[Tool]]]):
            logger.debug("Registering handler for ListToolsRequest")

            async def handler(_: Any):
                tools = await func()
                return ServerResult(ListToolsResult(tools=tools))

            self.request_handlers[ListToolsRequest] = handler
            return func

        return decorator

    def call_tool(self):
        from mcp_python.types import CallToolResult

        def decorator(func: Callable[..., Awaitable[Any]]):
            logger.debug("Registering handler for CallToolRequest")

            async def handler(req: CallToolRequest):
                result = await func(req.params.name, (req.params.arguments or {}))
                return ServerResult(CallToolResult(toolResult=result))

            self.request_handlers[CallToolRequest] = handler
            return func

        return decorator

    def progress_notification(self):
        def decorator(
            func: Callable[[str | int, float, float | None], Awaitable[None]],
        ):
            logger.debug("Registering handler for ProgressNotification")

            async def handler(req: ProgressNotification):
                await func(
                    req.params.progressToken, req.params.progress, req.params.total
                )

            self.notification_handlers[ProgressNotification] = handler
            return func

        return decorator

    def completion(self):
        """Provides completions for prompts and resource templates"""
        from mcp_python.types import CompleteResult, Completion, CompletionArgument

        def decorator(
            func: Callable[
                [PromptReference | ResourceReference, CompletionArgument],
                Awaitable[Completion | None],
            ],
        ):
            logger.debug("Registering handler for CompleteRequest")

            async def handler(req: CompleteRequest):
                completion = await func(req.params.ref, req.params.argument)
                return ServerResult(
                    CompleteResult(
                        completion=completion
                        if completion is not None
                        else Completion(values=[], total=None, hasMore=None),
                    )
                )

            self.request_handlers[CompleteRequest] = handler
            return func

        return decorator

    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        write_stream: MemoryObjectSendStream[JSONRPCMessage],
        initialization_options: types.InitializationOptions,
        # When True, exceptions are returned as messages to the client.
        # When False, exceptions are raised, which will cause the server to shut down
        # but also make tracing exceptions much easier during testing and when using
        # in-process servers.
        raise_exceptions: bool = False,
    ):
        with warnings.catch_warnings(record=True) as w:
            async with ServerSession(
                read_stream, write_stream, initialization_options
            ) as session:
                async for message in session.incoming_messages:
                    logger.debug(f"Received message: {message}")

                    match message:
                        case RequestResponder(request=ClientRequest(root=req)):
                            logger.info(
                                f"Processing request of type {type(req).__name__}"
                            )
                            if type(req) in self.request_handlers:
                                handler = self.request_handlers[type(req)]
                                logger.debug(
                                    f"Dispatching request of type {type(req).__name__}"
                                )

                                token = None
                                try:
                                    # Set our global state that can be retrieved via
                                    # app.get_request_context()
                                    token = request_ctx.set(
                                        RequestContext(
                                            message.request_id,
                                            message.request_meta,
                                            session,
                                        )
                                    )
                                    response = await handler(req)
                                except Exception as err:
                                    if raise_exceptions:
                                        raise err
                                    response = ErrorData(
                                        code=0, message=str(err), data=None
                                    )
                                finally:
                                    # Reset the global state after we are done
                                    if token is not None:
                                        request_ctx.reset(token)

                                await message.respond(response)
                            else:
                                await message.respond(
                                    ErrorData(
                                        code=METHOD_NOT_FOUND,
                                        message="Method not found",
                                    ),
                                )

                            logger.debug("Response sent")
                        case ClientNotification(root=notify):
                            if type(notify) in self.notification_handlers:
                                assert type(notify) in self.notification_handlers

                                handler = self.notification_handlers[type(notify)]
                                logger.debug(
                                    f"Dispatching notification of type "
                                    f"{type(notify).__name__}"
                                )

                                try:
                                    await handler(notify)
                                except Exception as err:
                                    logger.error(
                                        f"Uncaught exception in notification handler: "
                                        f"{err}"
                                    )

                    for warning in w:
                        logger.info(
                            f"Warning: {warning.category.__name__}: {warning.message}"
                        )
