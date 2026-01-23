"""
gRPC transport implementation for MCP client.

This implements ClientTransportSession using gRPC, providing:
- Binary protobuf encoding (more efficient than JSON)
- HTTP/2 multiplexing
- Native streaming for progress updates and resource watching
- Built-in flow control and backpressure
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import grpc
from google.protobuf import struct_pb2
from pydantic import AnyUrl

import mcp.types as types
from mcp.client.transport_session import ClientTransportSession
from mcp.shared.session import ProgressFnT

# Generated from proto/mcp/v1/mcp.proto
# Generate with: python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src proto/mcp/v1/mcp.proto
try:
    from mcp.v1.mcp_pb2 import (
        CallToolRequest,
        CallToolWithProgressRequest,
        CompleteRequest,
        GetPromptRequest,
        InitializeRequest,
        ListPromptsRequest,
        ListResourcesRequest,
        ListResourceTemplatesRequest,
        ListToolsRequest,
        PingRequest,
        PromptRef,
        ReadResourceChunkedRequest,
        ResourceTemplateRef,
        SessionRequest,
        SessionResponse,
        WatchResourcesRequest,
    )
    from mcp.v1.mcp_pb2_grpc import McpServiceStub

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

logger = logging.getLogger(__name__)


class GrpcClientTransport(ClientTransportSession):
    """
    gRPC-based MCP client transport.

    This transport implements the ClientTransportSession interface using gRPC,
    providing efficient binary communication with native streaming support.

    Example:
        async with GrpcClientTransport("localhost:50051") as transport:
            result = await transport.initialize()
            tools = await transport.list_tools()
    """

    def __init__(
        self,
        target: str,
        *,
        credentials: grpc.ChannelCredentials | None = None,
        options: list[tuple[str, Any]] | None = None,
        client_info: types.Implementation | None = None,
    ) -> None:
        """
        Initialize gRPC transport.

        Args:
            target: gRPC server address (e.g., "localhost:50051")
            credentials: Optional TLS credentials for secure channels
            options: Optional gRPC channel options
            client_info: Client implementation info for initialization
        """
        if not GRPC_AVAILABLE:
            raise ImportError(
                "gRPC dependencies not installed. "
                "Install with: uv add grpcio grpcio-tools"
            )

        self._target = target
        self._credentials = credentials
        self._options = options or []
        self._client_info = client_info or types.Implementation(
            name="mcp-python-grpc", version="0.1.0"
        )

        self._channel: grpc.aio.Channel | None = None
        self._stub: McpServiceStub | None = None
        self._server_info: types.Implementation | None = None
        self._server_capabilities: types.ServerCapabilities | None = None

        # Bidirectional session state
        self._session_task: asyncio.Task[None] | None = None
        self._session_requests: asyncio.Queue[SessionRequest] | None = None
        self._session_responses: dict[str, asyncio.Future[SessionResponse]] = {}
        self._session_notifications: asyncio.Queue[SessionResponse] | None = None

    async def __aenter__(self) -> GrpcClientTransport:
        """Open the gRPC channel and start the session stream if supported."""
        if self._credentials:
            self._channel = grpc.aio.secure_channel(
                self._target, self._credentials, options=self._options
            )
        else:
            self._channel = grpc.aio.insecure_channel(
                self._target, options=self._options
            )
        self._stub = McpServiceStub(self._channel)

        # Initialize session stream
        self._session_requests = asyncio.Queue()
        self._session_notifications = asyncio.Queue()
        self._session_task = asyncio.create_task(self._run_session_stream())

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Close the gRPC channel and stop the session stream."""
        if self._session_task:
            self._session_task.cancel()
            try:
                await self._session_task
            except asyncio.CancelledError:
                pass
            self._session_task = None

        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    async def _run_session_stream(self) -> None:
        """Maintain the bidirectional session stream."""
        stub = self._ensure_connected()

        async def request_generator() -> AsyncIterator[SessionRequest]:
            while True:
                req = await self._session_requests.get()  # type: ignore
                yield req

        try:
            async for response in stub.Session(request_generator()):
                if response.in_reply_to:
                    future = self._session_responses.pop(response.in_reply_to, None)
                    if future:
                        future.set_result(response)
                else:
                    # It's a notification/server-initiated message
                    await self._session_notifications.put(response)  # type: ignore
        except Exception as e:
            if not isinstance(e, asyncio.CancelledError):
                logger.exception("gRPC session stream error")
            # Fail all pending requests
            for future in self._session_responses.values():
                if not future.done():
                    future.set_exception(e)
            self._session_responses.clear()

    async def _call_session(self, request: SessionRequest) -> SessionResponse:
        """Call an RPC via the bidirectional session stream."""
        if not request.message_id:
            import uuid

            request.message_id = str(uuid.uuid4())

        future: asyncio.Future[SessionResponse] = asyncio.get_running_loop().create_future()
        self._session_responses[request.message_id] = future
        await self._session_requests.put(request)  # type: ignore

        try:
            return await future
        except Exception:
            self._session_responses.pop(request.message_id, None)
            raise

    def _ensure_connected(self) -> McpServiceStub:
        """Ensure we have an active stub."""
        if self._stub is None:
            raise RuntimeError(
                "Transport not connected. Use 'async with' or call __aenter__"
            )
        return self._stub

    def _map_error(self, e: grpc.RpcError) -> Exception:
        """Map gRPC errors to MCP errors or standard Python exceptions."""
        code = e.code()
        if code == grpc.StatusCode.NOT_FOUND:
            return ValueError(f"Not found: {e.details()}")
        elif code == grpc.StatusCode.INVALID_ARGUMENT:
            return ValueError(f"Invalid argument: {e.details()}")
        elif code == grpc.StatusCode.UNIMPLEMENTED:
            return NotImplementedError(f"Not implemented: {e.details()}")
        elif code == grpc.StatusCode.PERMISSION_DENIED:
            return PermissionError(f"Permission denied: {e.details()}")
        return e

    # -------------------------------------------------------------------------
    # Type Conversion Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _dict_to_struct(d: dict[str, Any] | None) -> struct_pb2.Struct:
        """Convert a Python dict to protobuf Struct."""
        struct = struct_pb2.Struct()
        if d:
            struct.update(d)
        return struct

    @staticmethod
    def _struct_to_dict(struct: struct_pb2.Struct) -> dict[str, Any]:
        """Convert protobuf Struct to Python dict."""
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(struct)

    def _convert_tool(self, proto_tool: Any) -> types.Tool:
        """Convert proto Tool to MCP Tool."""
        return types.Tool(
            name=proto_tool.name,
            description=proto_tool.description or None,
            inputSchema=self._struct_to_dict(proto_tool.input_schema),
        )

    def _convert_resource(self, proto_resource: Any) -> types.Resource:
        """Convert proto Resource to MCP Resource."""
        return types.Resource(
            uri=AnyUrl(proto_resource.uri),
            name=proto_resource.name,
            description=proto_resource.description or None,
            mimeType=proto_resource.mime_type or None,
        )

    def _convert_prompt(self, proto_prompt: Any) -> types.Prompt:
        """Convert proto Prompt to MCP Prompt."""
        return types.Prompt(
            name=proto_prompt.name,
            description=proto_prompt.description or None,
            arguments=[
                types.PromptArgument(
                    name=arg.name,
                    description=arg.description or None,
                    required=arg.required,
                )
                for arg in proto_prompt.arguments
            ]
            if proto_prompt.arguments
            else None,
        )

    def _convert_content(self, proto_content: Any) -> types.TextContent | types.ImageContent:
        """Convert proto Content to MCP Content."""
        content_type = proto_content.WhichOneof("content")
        if content_type == "text":
            return types.TextContent(type="text", text=proto_content.text.text)
        elif content_type == "image":
            return types.ImageContent(
                type="image",
                data=proto_content.image.data,
                mimeType=proto_content.image.mime_type,
            )
        else:
            raise ValueError(f"Unknown content type: {content_type}")

    # -------------------------------------------------------------------------
    # ClientTransportSession Implementation
    # -------------------------------------------------------------------------

    async def initialize(self) -> types.InitializeResult:
        """Initialize the MCP session."""
        stub = self._ensure_connected()

        request = InitializeRequest(
            protocol_version=types.LATEST_PROTOCOL_VERSION,
        )
        request.client_info.name = self._client_info.name
        request.client_info.version = self._client_info.version

        try:
            response = await stub.Initialize(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        self._server_info = types.Implementation(
            name=response.server_info.name,
            version=response.server_info.version,
        )

        # Convert capabilities
        self._server_capabilities = types.ServerCapabilities(
            prompts=types.PromptsCapability(
                listChanged=response.capabilities.prompts.list_changed
            )
            if response.capabilities.HasField("prompts")
            else None,
            resources=types.ResourcesCapability(
                subscribe=response.capabilities.resources.subscribe,
                listChanged=response.capabilities.resources.list_changed,
            )
            if response.capabilities.HasField("resources")
            else None,
            tools=types.ToolsCapability(
                listChanged=response.capabilities.tools.list_changed
            )
            if response.capabilities.HasField("tools")
            else None,
        )

        return types.InitializeResult(
            protocolVersion=response.protocol_version,
            capabilities=self._server_capabilities,
            serverInfo=self._server_info,
            instructions=response.instructions or None,
        )

    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        stub = self._ensure_connected()
        try:
            await stub.Ping(PingRequest())
        except grpc.RpcError as e:
            raise self._map_error(e) from e
        return types.EmptyResult()

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Send a progress notification.

        Note: In gRPC, progress is typically sent via streaming responses
        rather than separate notifications. This method is provided for
        compatibility but may use the bidirectional Session stream.
        """
        # In gRPC transport, progress is handled via streaming RPCs
        # This could use the Session bidirectional stream for notifications
        logger.debug(
            "Progress notification: token=%s, progress=%s, total=%s, message=%s",
            progress_token,
            progress,
            total,
            message,
        )

    async def set_logging_level(
        self,
        level: types.LoggingLevel,
    ) -> types.EmptyResult:
        """Set logging level.

        Note: This may need a custom RPC added to the proto.
        """
        # TODO: Add SetLoggingLevel RPC to proto
        logger.info("Setting logging level to %s (not yet implemented in gRPC)", level)
        return types.EmptyResult()

    async def list_resources(
        self,
        cursor: str | None = None,
    ) -> types.ListResourcesResult:
        """List available resources."""
        stub = self._ensure_connected()

        request = ListResourcesRequest()
        if cursor:
            request.cursor.value = cursor

        try:
            response = await stub.ListResources(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.ListResourcesResult(
            resources=[self._convert_resource(r) for r in response.resources],
            nextCursor=response.next_cursor.value if response.HasField("next_cursor") else None,
        )

    async def list_resource_templates(
        self,
        cursor: str | None = None,
    ) -> types.ListResourceTemplatesResult:
        """List resource templates."""
        stub = self._ensure_connected()

        request = ListResourceTemplatesRequest()
        if cursor:
            request.cursor.value = cursor

        try:
            response = await stub.ListResourceTemplates(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.ListResourceTemplatesResult(
            resourceTemplates=[
                types.ResourceTemplate(
                    uriTemplate=t.uri_template,
                    name=t.name,
                    description=t.description or None,
                    mimeType=t.mime_type or None,
                )
                for t in response.resource_templates
            ],
            nextCursor=response.next_cursor.value if response.HasField("next_cursor") else None,
        )

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        """Read a resource. Uses ReadResourceChunked for large resources."""
        stub = self._ensure_connected()

        # We'll use ReadResourceChunked by default to handle any size
        request = ReadResourceChunkedRequest(uri=str(uri))
        
        contents_map: dict[str, Any] = {} # uri -> {mime_type, text_chunks, blob_chunks}
        
        async for chunk in stub.ReadResourceChunked(request):
            if chunk.uri not in contents_map:
                contents_map[chunk.uri] = {
                    "mime_type": chunk.mime_type,
                    "text_chunks": [],
                    "blob_chunks": []
                }
            
            chunk_type = chunk.WhichOneof("content")
            if chunk_type == "text_chunk":
                contents_map[chunk.uri]["text_chunks"].append(chunk.text_chunk)
            elif chunk_type == "blob_chunk":
                contents_map[chunk.uri]["blob_chunks"].append(chunk.blob_chunk)

        result_contents: list[types.TextResourceContents | types.BlobResourceContents] = []
        for res_uri, data in contents_map.items():
            if data["text_chunks"]:
                result_contents.append(
                    types.TextResourceContents(
                        uri=AnyUrl(res_uri),
                        mimeType=data["mime_type"] or None,
                        text="".join(data["text_chunks"]),
                    )
                )
            elif data["blob_chunks"]:
                import base64
                full_blob = b"".join(data["blob_chunks"])
                result_contents.append(
                    types.BlobResourceContents(
                        uri=AnyUrl(res_uri),
                        mimeType=data["mime_type"] or None,
                        blob=base64.b64encode(full_blob).decode("ascii"),
                    )
                )

        return types.ReadResourceResult(contents=result_contents)

    async def subscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Subscribe to resource changes."""
        stub = self._ensure_connected()
        request = WatchResourcesRequest(uri_patterns=[str(uri)])
        
        # Start the watch stream in the background if not already running
        # For now, we'll just call the unary-like stream start
        # In a full implementation, we'd manage these streams and route notifications
        stream = stub.WatchResources(request)
        
        async def _watch():
            async for notification in stream:
                # Handle notification (e.g., put into a queue or trigger callback)
                logger.debug("Resource change: %s", notification.uri)

        asyncio.create_task(_watch())
        return types.EmptyResult()

    async def unsubscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Unsubscribe from resource changes."""
        # In this simplified implementation, we don't track the tasks to cancel them
        logger.info("Resource unsubscription requested for %s", uri)
        return types.EmptyResult()

    async def call_tool(
        self,
        name: str,
        arguments: Any | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> types.CallToolResult:
        """Call a tool."""
        stub = self._ensure_connected()

        request = CallToolRequest(
            name=name,
            arguments=self._dict_to_struct(arguments) if arguments else None,
        )

        timeout = read_timeout_seconds.total_seconds() if read_timeout_seconds else None

        if progress_callback:
            # Use streaming RPC for progress support
            progress_request = CallToolWithProgressRequest(
                name=name,
                arguments=self._dict_to_struct(arguments) if arguments else None,
            )
            contents: list[types.TextContent | types.ImageContent] = []
            is_error = False

            async for response in stub.CallToolWithProgress(progress_request, timeout=timeout):
                update_type = response.WhichOneof("update")
                if update_type == "progress":
                    await progress_callback(
                        response.progress.progress,
                        response.progress.total or None,
                        response.progress.message or None,
                    )
                elif update_type == "result":
                    contents = [self._convert_content(c) for c in response.result.content]
                    is_error = response.result.is_error

            return types.CallToolResult(content=contents, isError=is_error)
        else:
            # Use simple unary RPC
            response = await stub.CallTool(request, timeout=timeout)
            return types.CallToolResult(
                content=[self._convert_content(c) for c in response.content],
                isError=response.is_error,
            )

    async def list_prompts(
        self,
        cursor: str | None = None,
    ) -> types.ListPromptsResult:
        """List available prompts."""
        stub = self._ensure_connected()

        request = ListPromptsRequest()
        if cursor:
            request.cursor.value = cursor

        try:
            response = await stub.ListPrompts(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.ListPromptsResult(
            prompts=[self._convert_prompt(p) for p in response.prompts],
            nextCursor=response.next_cursor.value if response.HasField("next_cursor") else None,
        )

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> types.GetPromptResult:
        """Get a prompt."""
        stub = self._ensure_connected()

        request = GetPromptRequest(name=name)
        if arguments:
            request.arguments.update(arguments)

        try:
            response = await stub.GetPrompt(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.GetPromptResult(
            description=response.description or None,
            messages=[
                types.PromptMessage(
                    role="user" if m.role == 1 else "assistant",
                    content=self._convert_content(m.content),
                )
                for m in response.messages
            ],
        )

    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult:
        """Complete a resource template or prompt argument."""
        stub = self._ensure_connected()

        request = CompleteRequest()

        if isinstance(ref, types.PromptReference):
            request.prompt_ref.CopyFrom(
                PromptRef(type="ref/prompt", name=ref.name)
            )
        else:
            request.resource_template_ref.CopyFrom(
                ResourceTemplateRef(type="ref/resource", uri=str(ref.uri))
            )

        # Get first argument name and value
        if argument:
            arg_name, arg_value = next(iter(argument.items()))
            request.argument_name = arg_name
            request.argument_value = arg_value

        try:
            response = await stub.Complete(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.CompleteResult(
            completion=types.Completion(
                values=list(response.completion.values),
                total=response.completion.total or None,
                hasMore=response.completion.has_more,
            )
        )

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        """List available tools."""
        stub = self._ensure_connected()

        request = ListToolsRequest()
        effective_cursor = params.cursor if params else cursor
        if effective_cursor:
            request.cursor.value = effective_cursor

        try:
            response = await stub.ListTools(request)
        except grpc.RpcError as e:
            raise self._map_error(e) from e

        return types.ListToolsResult(
            tools=[self._convert_tool(t) for t in response.tools],
            nextCursor=response.next_cursor.value if response.HasField("next_cursor") else None,
        )

    async def send_roots_list_changed(self) -> None:
        """Send roots/list_changed notification.

        Note: In gRPC, this would use the bidirectional Session stream.
        """
        # TODO: Send via Session bidirectional stream
        logger.debug("Roots list changed notification (not yet implemented in gRPC)")
