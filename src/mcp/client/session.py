from datetime import timedelta
from typing import Any, Generic, Protocol, TypeVar, get_args

import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl, BaseModel, TypeAdapter

import mcp.types as types
from mcp.shared.context import RequestContext
from mcp.shared.session import BaseSession, RequestResponder
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

DEFAULT_CLIENT_INFO = types.Implementation(name="mcp", version="0.1.0")
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)
CustomRequestMethodT = TypeVar("CustomRequestMethodT", bound=str)


class SamplingFnT(Protocol):
    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData: ...


class ListRootsFnT(Protocol):
    async def __call__(
        self, context: RequestContext["ClientSession", Any]
    ) -> types.ListRootsResult | types.ErrorData: ...


class LoggingFnT(Protocol):
    async def __call__(
        self,
        params: types.LoggingMessageNotificationParams,
    ) -> None: ...


class MessageHandlerFnT(Protocol):
    async def __call__(
        self,
        message: RequestResponder[types.ServerRequest, types.ClientResult]
        | types.ServerNotification
        | Exception,
    ) -> None: ...


class CustomRequestHandlerFnT(Protocol, Generic[types.CustomRequestT]):
    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        message: types.CustomRequestT,
    ) -> types.ClientResult | types.ErrorData: ...


async def _default_custom_request_handler(
    context: RequestContext["ClientSession", Any],
    message: types.CustomRequest[dict[str, Any] | None, str],
) -> types.ClientResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message=f"Custom request method {message.method} not supported",
    )


async def _default_message_handler(
    message: (
        RequestResponder[types.ServerRequest, types.ClientResult]
        | types.ServerNotification
        | Exception
    ),
) -> None:
    await anyio.lowlevel.checkpoint()


async def _default_sampling_callback(
    context: RequestContext["ClientSession", Any],
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Sampling not supported",
    )


async def _default_list_roots_callback(
    context: RequestContext["ClientSession", Any],
) -> types.ListRootsResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="List roots not supported",
    )


async def _default_logging_callback(
    params: types.LoggingMessageNotificationParams,
) -> None:
    pass


ClientResponse: TypeAdapter[types.ClientResult | types.ErrorData] = TypeAdapter(
    types.ClientResult | types.ErrorData
)


class ClientSession(
    BaseSession[
        types.ClientRequest,
        types.ClientNotification,
        types.ClientResult,
        types.ServerRequest,
        types.ServerNotification,
    ]
):
    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception],
        write_stream: MemoryObjectSendStream[types.JSONRPCMessage],
        read_timeout_seconds: timedelta | None = None,
        sampling_callback: SamplingFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: types.Implementation | None = None,
        custom_request_handlers: (
            dict[
                str,
                CustomRequestHandlerFnT[
                    types.CustomRequest[dict[str, Any] | None, str]
                ],
            ]
            | None
        ) = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            read_stream,
            write_stream,
            types.ServerRequest,
            types.ServerNotification,
            read_timeout_seconds=read_timeout_seconds,
        )
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._sampling_callback = sampling_callback or _default_sampling_callback
        self._list_roots_callback = list_roots_callback or _default_list_roots_callback
        self._logging_callback = logging_callback or _default_logging_callback
        self._message_handler = message_handler or _default_message_handler
        self._custom_request_handlers: dict[
            str,
            CustomRequestHandlerFnT[types.CustomRequest[dict[str, Any] | None, str]],
        ] = custom_request_handlers or {}
        self._experimental_capabilities = experimental_capabilities or {}

    async def initialize(self) -> types.InitializeResult:
        sampling = types.SamplingCapability()
        roots = types.RootsCapability(
            # TODO: Should this be based on whether we
            # _will_ send notifications, or only whether
            # they're supported?
            listChanged=True,
        )

        result = await self.send_request(
            types.ClientRequest(
                types.InitializeRequest(
                    method="initialize",
                    params=types.InitializeRequestParams(
                        protocolVersion=types.LATEST_PROTOCOL_VERSION,
                        capabilities=types.ClientCapabilities(
                            sampling=sampling,
                            experimental=self._experimental_capabilities,
                            roots=roots,
                        ),
                        clientInfo=self._client_info,
                    ),
                )
            ),
            types.InitializeResult,
        )

        if result.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(
                "Unsupported protocol version from the server: "
                f"{result.protocolVersion}"
            )

        await self.send_notification(
            types.ClientNotification(
                types.InitializedNotification(method="notifications/initialized")
            )
        )

        return result

    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(
            types.ClientRequest(
                types.PingRequest(
                    method="ping",
                )
            ),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self, progress_token: str | int, progress: float, total: float | None = None
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ClientNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                    ),
                ),
            )
        )

    async def send_custom_request(
        self,
        request: types.CustomRequest[types.RequestParamsT, types.MethodT],
        response_type: type[ReceiveResultT],
    ) -> ReceiveResultT:
        """Send a custom request."""
        if self._experimental_capabilities.get("custom_requests", None) is None:
            raise RuntimeError(
                "experimental capability 'custom_requests' must be set in the"
                " client capabilities to send custom requests."
            )
        request_params = (
            request.params.model_dump(by_alias=True, mode="json", exclude_none=True)
            if isinstance(request.params, types.BaseModel)
            else request.params
        )
        inner_request = types.CustomRequest[dict[str, Any] | None, str](
            method=request.method,
            params=request_params,
        )
        return await self.send_request(
            types.ClientRequest(
                types.CustomRequestWrapper(
                    method="custom/request",
                    params=types.CustomRequestWrapperParams(
                        inner=inner_request,
                    ),
                )
            ),
            response_type,
        )

    async def set_logging_level(self, level: types.LoggingLevel) -> types.EmptyResult:
        """Send a logging/setLevel request."""
        return await self.send_request(
            types.ClientRequest(
                types.SetLevelRequest(
                    method="logging/setLevel",
                    params=types.SetLevelRequestParams(level=level),
                )
            ),
            types.EmptyResult,
        )

    async def list_resources(self) -> types.ListResourcesResult:
        """Send a resources/list request."""
        return await self.send_request(
            types.ClientRequest(
                types.ListResourcesRequest(
                    method="resources/list",
                )
            ),
            types.ListResourcesResult,
        )

    async def list_resource_templates(self) -> types.ListResourceTemplatesResult:
        """Send a resources/templates/list request."""
        return await self.send_request(
            types.ClientRequest(
                types.ListResourceTemplatesRequest(
                    method="resources/templates/list",
                )
            ),
            types.ListResourceTemplatesResult,
        )

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        """Send a resources/read request."""
        return await self.send_request(
            types.ClientRequest(
                types.ReadResourceRequest(
                    method="resources/read",
                    params=types.ReadResourceRequestParams(uri=uri),
                )
            ),
            types.ReadResourceResult,
        )

    async def subscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Send a resources/subscribe request."""
        return await self.send_request(
            types.ClientRequest(
                types.SubscribeRequest(
                    method="resources/subscribe",
                    params=types.SubscribeRequestParams(uri=uri),
                )
            ),
            types.EmptyResult,
        )

    async def unsubscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Send a resources/unsubscribe request."""
        return await self.send_request(
            types.ClientRequest(
                types.UnsubscribeRequest(
                    method="resources/unsubscribe",
                    params=types.UnsubscribeRequestParams(uri=uri),
                )
            ),
            types.EmptyResult,
        )

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> types.CallToolResult:
        """Send a tools/call request."""
        return await self.send_request(
            types.ClientRequest(
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(name=name, arguments=arguments),
                )
            ),
            types.CallToolResult,
        )

    async def list_prompts(self) -> types.ListPromptsResult:
        """Send a prompts/list request."""
        return await self.send_request(
            types.ClientRequest(
                types.ListPromptsRequest(
                    method="prompts/list",
                )
            ),
            types.ListPromptsResult,
        )

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> types.GetPromptResult:
        """Send a prompts/get request."""
        return await self.send_request(
            types.ClientRequest(
                types.GetPromptRequest(
                    method="prompts/get",
                    params=types.GetPromptRequestParams(name=name, arguments=arguments),
                )
            ),
            types.GetPromptResult,
        )

    async def complete(
        self,
        ref: types.ResourceReference | types.PromptReference,
        argument: dict[str, str],
    ) -> types.CompleteResult:
        """Send a completion/complete request."""
        return await self.send_request(
            types.ClientRequest(
                types.CompleteRequest(
                    method="completion/complete",
                    params=types.CompleteRequestParams(
                        ref=ref,
                        argument=types.CompletionArgument(**argument),
                    ),
                )
            ),
            types.CompleteResult,
        )

    async def list_tools(self) -> types.ListToolsResult:
        """Send a tools/list request."""
        return await self.send_request(
            types.ClientRequest(
                types.ListToolsRequest(
                    method="tools/list",
                )
            ),
            types.ListToolsResult,
        )

    async def send_roots_list_changed(self) -> None:
        """Send a roots/list_changed notification."""
        await self.send_notification(
            types.ClientNotification(
                types.RootsListChangedNotification(
                    method="notifications/roots/list_changed",
                )
            )
        )

    async def _received_request(
        self, responder: RequestResponder[types.ServerRequest, types.ClientResult]
    ) -> None:
        ctx = RequestContext[ClientSession, Any](
            request_id=responder.request_id,
            meta=responder.request_meta,
            session=self,
            lifespan_context=None,
        )

        match responder.request.root:
            case types.CreateMessageRequest(params=params):
                with responder:
                    response = await self._sampling_callback(ctx, params)
                    client_response = ClientResponse.validate_python(response)
                    await responder.respond(client_response)

            case types.ListRootsRequest():
                with responder:
                    response = await self._list_roots_callback(ctx)
                    client_response = ClientResponse.validate_python(response)
                    await responder.respond(client_response)

            case types.PingRequest():
                with responder:
                    return await responder.respond(
                        types.ClientResult(root=types.EmptyResult())
                    )

            case types.CustomRequestWrapper(
                params=types.CustomRequestWrapperParams(inner=custom_request)
            ):
                with responder:
                    custom_request_handler = (
                        self._custom_request_handlers.get(
                            custom_request.method,
                            _default_custom_request_handler,
                        )
                        if self._experimental_capabilities.get("custom_requests", None)
                        is not None
                        else _default_custom_request_handler
                    )

                    ## TODO: This is a hack to get the type of the custom request
                    ##       from the custom request handler.
                    orig_base = custom_request_handler.__orig_bases__[0]  # type: ignore
                    (type_arg,) = get_args(orig_base)
                    CustomRequestType = type_arg
                    parsed_custom_request = CustomRequestType.model_validate(
                        custom_request.model_dump(
                            by_alias=True,
                            exclude_none=True,
                            mode="json",
                        )
                    )

                    custom_request_response = await custom_request_handler(
                        ctx,
                        parsed_custom_request,
                    )
                    client_response = ClientResponse.validate_python(
                        custom_request_response
                    )
                    await responder.respond(client_response)

    async def _handle_incoming(
        self,
        req: (
            RequestResponder[types.ServerRequest, types.ClientResult]
            | types.ServerNotification
            | Exception
        ),
    ) -> None:
        """Handle incoming messages by forwarding to the message handler."""
        await self._message_handler(req)

    async def _received_notification(
        self, notification: types.ServerNotification
    ) -> None:
        """Handle notifications from the server."""
        # Process specific notification types
        match notification.root:
            case types.LoggingMessageNotification(params=params):
                await self._logging_callback(params)
            case _:
                pass
