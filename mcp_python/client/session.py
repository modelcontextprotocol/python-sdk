from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl

from mcp_python.shared.session import BaseSession
from mcp_python.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp_python.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    ClientCapabilities,
    ClientNotification,
    ClientRequest,
    ClientResult,
    EmptyResult,
    Implementation,
    InitializedNotification,
    InitializeResult,
    JSONRPCMessage,
    ListResourcesResult,
    LoggingLevel,
    ReadResourceResult,
    ServerNotification,
    ServerRequest,
)


class ClientSession(
    BaseSession[
        ClientRequest,
        ClientNotification,
        ClientResult,
        ServerRequest,
        ServerNotification,
    ]
):
    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        write_stream: MemoryObjectSendStream[JSONRPCMessage],
        read_timeout_seconds: int | float | None = None,
    ) -> None:
        super().__init__(read_stream, write_stream, ServerRequest, ServerNotification, read_timeout_seconds=read_timeout_seconds)

    async def initialize(self) -> InitializeResult:
        from mcp_python.types import (
            InitializeRequest,
            InitializeRequestParams,
        )

        result = await self.send_request(
            ClientRequest(
                InitializeRequest(
                    method="initialize",
                    params=InitializeRequestParams(
                        protocolVersion=LATEST_PROTOCOL_VERSION,
                        capabilities=ClientCapabilities(
                            sampling=None, experimental=None
                        ),
                        clientInfo=Implementation(name="mcp_python", version="0.1.0"),
                    ),
                )
            ),
            InitializeResult,
        )

        if result.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(
                "Unsupported protocol version from the server: "
                f"{result.protocolVersion}"
            )

        await self.send_notification(
            ClientNotification(
                InitializedNotification(method="notifications/initialized")
            )
        )

        return result

    async def send_ping(self) -> EmptyResult:
        """Send a ping request."""
        from mcp_python.types import PingRequest

        return await self.send_request(
            ClientRequest(
                PingRequest(
                    method="ping",
                )
            ),
            EmptyResult,
        )

    async def send_progress_notification(
        self, progress_token: str | int, progress: float, total: float | None = None
    ) -> None:
        """Send a progress notification."""
        from mcp_python.types import (
            ProgressNotification,
            ProgressNotificationParams,
        )

        await self.send_notification(
            ClientNotification(
                ProgressNotification(
                    method="notifications/progress",
                    params=ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                    ),
                ),
            )
        )

    async def set_logging_level(self, level: LoggingLevel) -> EmptyResult:
        """Send a logging/setLevel request."""
        from mcp_python.types import (
            SetLevelRequest,
            SetLevelRequestParams,
        )

        return await self.send_request(
            ClientRequest(
                SetLevelRequest(
                    method="logging/setLevel",
                    params=SetLevelRequestParams(level=level),
                )
            ),
            EmptyResult,
        )

    async def list_resources(self) -> ListResourcesResult:
        """Send a resources/list request."""
        from mcp_python.types import (
            ListResourcesRequest,
        )

        return await self.send_request(
            ClientRequest(
                ListResourcesRequest(
                    method="resources/list",
                )
            ),
            ListResourcesResult,
        )

    async def read_resource(self, uri: AnyUrl) -> ReadResourceResult:
        """Send a resources/read request."""
        from mcp_python.types import (
            ReadResourceRequest,
            ReadResourceRequestParams,
        )

        return await self.send_request(
            ClientRequest(
                ReadResourceRequest(
                    method="resources/read",
                    params=ReadResourceRequestParams(uri=uri),
                )
            ),
            ReadResourceResult,
        )

    async def subscribe_resource(self, uri: AnyUrl) -> EmptyResult:
        """Send a resources/subscribe request."""
        from mcp_python.types import (
            SubscribeRequest,
            SubscribeRequestParams,
        )

        return await self.send_request(
            ClientRequest(
                SubscribeRequest(
                    method="resources/subscribe",
                    params=SubscribeRequestParams(uri=uri),
                )
            ),
            EmptyResult,
        )

    async def unsubscribe_resource(self, uri: AnyUrl) -> EmptyResult:
        """Send a resources/unsubscribe request."""
        from mcp_python.types import (
            UnsubscribeRequest,
            UnsubscribeRequestParams,
        )

        return await self.send_request(
            ClientRequest(
                UnsubscribeRequest(
                    method="resources/unsubscribe",
                    params=UnsubscribeRequestParams(uri=uri),
                )
            ),
            EmptyResult,
        )

    async def call_tool(
        self, name: str, arguments: dict | None = None
    ) -> CallToolResult:
        """Send a tools/call request."""
        from mcp_python.types import (
            CallToolRequest,
            CallToolRequestParams,
        )

        return await self.send_request(
            ClientRequest(
                CallToolRequest(
                    method="tools/call",
                    params=CallToolRequestParams(name=name, arguments=arguments),
                )
            ),
            CallToolResult,
        )
