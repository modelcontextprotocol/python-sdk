"""
gRPC server transport for MCP.

This module implements the server-side gRPC transport for MCP, allowing
an MCP server to be exposed over gRPC with support for native streaming
and bidirectional communication.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import grpc
from google.protobuf import struct_pb2
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.lowlevel.server import Server, request_ctx
from mcp.server.transport_session import ServerTransportSession
from mcp.shared.context import RequestContext
from mcp.v1.mcp_pb2 import (
    CallToolResponse,
    CallToolWithProgressResponse,
    CompleteResponse,
    CompletionResult,
    GetPromptResponse,
    InitializeResponse,
    ListPromptsResponse,
    ListResourcesResponse,
    ListResourceTemplatesResponse,
    ListToolsResponse,
    PingResponse,
    PromptMessage,
    ReadResourceChunkedResponse,
    ReadResourceResponse,
    ResourceChangeType,
    ResourceContents,
    ServerCapabilities,
    ServerInfo,
    SessionResponse,
    WatchResourcesResponse,
)
from mcp.v1.mcp_pb2_grpc import McpServiceServicer, add_McpServiceServicer_to_server

logger = logging.getLogger(__name__)

LifespanResultT = TypeVar("LifespanResultT")
RequestT = TypeVar("RequestT")


class GrpcServerSession(ServerTransportSession):
    """
    gRPC implementation of ServerTransportSession.
    
    This session implementation handles the context for gRPC requests,
    bridging the gap between the abstract ServerSession interface and
    gRPC's execution model.
    """
    
    def __init__(self) -> None:
        # In gRPC, we don't manage the stream lifecycle the same way as 
        # the persistent connection in stdio/SSE, as many RPCs are unary.
        # This session object acts primarily as a handle for capabilities.
        self._client_params: types.InitializeRequestParams | None = None

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        return self._client_params

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        """Check if the client supports a specific capability."""
        if self._client_params is None:
            return False

        # Get client capabilities from initialization params
        client_caps = self._client_params.capabilities

        # Check each specified capability in the passed in capability object
        if capability.roots is not None:
            if client_caps.roots is None:
                return False
            if capability.roots.listChanged and not client_caps.roots.listChanged:
                return False

        if capability.sampling is not None:
            if client_caps.sampling is None:
                return False

        if capability.elicitation is not None:
            if client_caps.elicitation is None:
                return False

        if capability.experimental is not None:
            if client_caps.experimental is None:
                return False
            # Check each experimental capability
            for exp_key, exp_value in capability.experimental.items():
                if exp_key not in client_caps.experimental or client_caps.experimental[exp_key] != exp_value:
                    return False

        return True

    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger_name: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        # For unary RPCs, we can't push log messages back easily unless
        # we are in the Session bidirectional stream.
        # TODO: Implement side-channel logging for Session stream
        logger.warning(
            "Log message dropped (not implemented for unary gRPC): %s: %s", 
            level, data
        )

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        # This is handled by specific streaming RPCs (CallToolWithProgress)
        # or the Session stream. If called from a unary context, we log warning.
        logger.warning(
            "Progress notification dropped (not implemented for unary gRPC): %s", 
            progress
        )
        
    async def send_resource_updated(self, uri: AnyUrl) -> None:
        logger.warning("Resource updated notification dropped (not implemented for unary gRPC)")

    async def send_resource_list_changed(self) -> None:
        logger.warning("Resource list changed notification dropped (not implemented for unary gRPC)")

    async def send_tool_list_changed(self) -> None:
        logger.warning("Tool list changed notification dropped (not implemented for unary gRPC)")

    async def send_prompt_list_changed(self) -> None:
        logger.warning("Prompt list changed notification dropped (not implemented for unary gRPC)")

    async def list_roots(self) -> types.ListRootsResult:
        logger.warning("List roots request dropped (not implemented for unary gRPC)")
        return types.ListRootsResult(roots=[])

    async def elicit(
        self,
        message: str,
        requested_schema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        raise NotImplementedError("Elicitation not implemented for unary gRPC")

    async def send_ping(self) -> types.EmptyResult:
        logger.warning("Ping request dropped (not implemented for unary gRPC)")
        return types.EmptyResult()


class McpGrpcServicer(McpServiceServicer):
    """
    Implements the McpService gRPC definition by delegating to an MCP Server instance.
    """

    def __init__(self, server: Server[Any, Any]):
        self._server = server
        self._session = GrpcServerSession()

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

    def _convert_content_to_proto(self, content: types.TextContent | types.ImageContent | types.EmbeddedResource) -> Any:
        """Convert MCP Content to proto Content."""
        from mcp.v1.mcp_pb2 import Content, ImageContent, TextContent
        
        if isinstance(content, types.TextContent):
            return Content(text=TextContent(text=content.text))
        elif isinstance(content, types.ImageContent):
            return Content(image=ImageContent(data=content.data, mime_type=content.mimeType))
        # TODO: Handle EmbeddedResource
        return Content()

    def _convert_tool_to_proto(self, tool: types.Tool) -> Any:
        """Convert MCP Tool to proto Tool."""
        from mcp.v1.mcp_pb2 import Tool
        return Tool(
            name=tool.name,
            description=tool.description or "",
            input_schema=self._dict_to_struct(tool.inputSchema)
        )

    def _convert_resource_to_proto(self, resource: types.Resource) -> Any:
        """Convert MCP Resource to proto Resource."""
        from mcp.v1.mcp_pb2 import Resource
        return Resource(
            uri=str(resource.uri),
            name=resource.name,
            description=resource.description or "",
            mime_type=resource.mimeType or "",
        )
        
    def _convert_prompt_to_proto(self, prompt: types.Prompt) -> Any:
        """Convert MCP Prompt to proto Prompt."""
        from mcp.v1.mcp_pb2 import Prompt, PromptArgument
        return Prompt(
            name=prompt.name,
            description=prompt.description or "",
            arguments=[
                PromptArgument(
                    name=arg.name,
                    description=arg.description or "",
                    required=arg.required or False
                ) for arg in (prompt.arguments or [])
            ]
        )

    async def _execute_handler(self, request_type: type, request_obj: Any, context: grpc.ServicerContext) -> Any:
        """
        Execute a registered handler for the given request type.
        Sets up the request context needed by the handler.
        """
        handler = self._server.request_handlers.get(request_type)
        if not handler:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, f"Method {request_type.__name__} not implemented")
        else:
            # Set up request context
            # We use a unique ID for each request
            import uuid
            token = request_ctx.set(
                RequestContext(
                    request_id=str(uuid.uuid4()),
                    meta=None,
                    session=self._session,
                    lifespan_context={},
                )
            )
            
            try:
                result = await handler(request_obj)
                return result
            except Exception as e:
                logger.exception("Error handling gRPC request")
                await context.abort(grpc.StatusCode.INTERNAL, str(e))
            finally:
                request_ctx.reset(token)

    # -------------------------------------------------------------------------
    # RPC Implementations
    # -------------------------------------------------------------------------

    async def Initialize(self, request, context):
        """Initialize the session."""
        
        # Populate session with client params
        self._session._client_params = types.InitializeRequestParams(
            protocolVersion=request.protocol_version,
            capabilities=types.ClientCapabilities(
                roots=types.RootsCapability(listChanged=request.capabilities.roots.list_changed) if request.capabilities.HasField("roots") else None,
                sampling=types.SamplingCapability() if request.capabilities.HasField("sampling") else None,
                experimental={k: v for k, v in request.capabilities.experimental.capabilities.items()} if request.capabilities.HasField("experimental") else None
            ),
            clientInfo=types.Implementation(
                name=request.client_info.name,
                version=request.client_info.version
            )
        )

        # Convert proto to internal options
        # We manually construct what the server expects for initialization
        # The Server.create_initialization_options normally takes internal types
        # Here we are just bridging the handshake
        
        init_opts = self._server.create_initialization_options()
        
        # Convert internal ServerCapabilities to proto ServerCapabilities
        caps = ServerCapabilities()
        if init_opts.capabilities.prompts:
            caps.prompts.list_changed = init_opts.capabilities.prompts.listChanged or False
        if init_opts.capabilities.resources:
            caps.resources.subscribe = init_opts.capabilities.resources.subscribe or False
            caps.resources.list_changed = init_opts.capabilities.resources.listChanged or False
        if init_opts.capabilities.tools:
            caps.tools.list_changed = init_opts.capabilities.tools.listChanged or False
            
        return InitializeResponse(
            protocol_version=types.LATEST_PROTOCOL_VERSION,
            server_info=ServerInfo(
                name=init_opts.server_name,
                version=init_opts.server_version
            ),
            capabilities=caps,
            instructions=init_opts.instructions or ""
        )

    async def Ping(self, request, context):
        """Ping."""
        await self._execute_handler(types.PingRequest, types.PingRequest(), context)
        return PingResponse()

    async def ListTools(self, request, context):
        """
        List available tools.
        
        Note: The underlying Server implementation currently collects all tools
        into a list before returning. While we stream the response to the client,
        true end-to-end streaming requires updates to mcp.server.lowlevel.server
        to support async generators.
        """
        req = types.ListToolsRequest(
            params=types.PaginatedRequestParams(cursor=None)
        )
        result = await self._execute_handler(types.ListToolsRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            # result.root is ListToolsResult
            tools_result = result.root
            for tool in tools_result.tools:
                yield ListToolsResponse(tool=self._convert_tool_to_proto(tool))

    async def CallTool(self, request, context):
        """Call a tool (unary)."""
        req = types.CallToolRequest(
            params=types.CallToolRequestParams(
                name=request.name,
                arguments=self._struct_to_dict(request.arguments)
            )
        )
        
        result = await self._execute_handler(types.CallToolRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            call_result = result.root
            return CallToolResponse(
                content=[self._convert_content_to_proto(c) for c in call_result.content],
                is_error=call_result.isError
            )
        return CallToolResponse(is_error=True)

    async def CallToolWithProgress(self, request, context):
        """Call a tool with streaming progress updates."""
        # This requires a special handler execution that captures progress notifications
        # and streams them back.
        
        # We need a custom session that intercepts progress
        progress_queue = asyncio.Queue()
        
        class StreamingSession(GrpcServerSession):
            async def send_progress_notification(self, progress_token, progress, total=None, message=None, related_request_id=None):
                from mcp.v1.mcp_pb2 import ProgressNotification, ProgressToken
                token_msg = ProgressToken()
                if isinstance(progress_token, int):
                    token_msg.int_token = progress_token
                else:
                    token_msg.string_token = str(progress_token)
                    
                await progress_queue.put(
                    CallToolWithProgressResponse(
                        progress=ProgressNotification(
                            progress_token=token_msg,
                            progress=progress,
                            total=total or 0.0,
                            message=message or ""
                        )
                    )
                )

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(
                name=request.name,
                arguments=self._struct_to_dict(request.arguments)
            )
        )
        
        handler = self._server.request_handlers.get(types.CallToolRequest)
        if not handler:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, "Tool execution not implemented")
        else:
            async def run_handler():
                streaming_session = StreamingSession()
                # Inherit client params/capabilities from the main session
                streaming_session._client_params = self._session._client_params
                
                import uuid
                token = request_ctx.set(
                    RequestContext(
                        request_id=str(uuid.uuid4()),
                        meta=None,
                        session=streaming_session,
                        lifespan_context={},
                    )
                )
                try:
                    result = await handler(req)
                    return result
                finally:
                    request_ctx.reset(token)

            # Run handler in background task while we stream queue
            task = asyncio.create_task(run_handler())
            
            while not task.done():
                # Wait for either a progress update or task completion
                done, pending = await asyncio.wait(
                    [task, asyncio.create_task(progress_queue.get())],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for f in done:
                    if f is task:
                        # Task finished
                        try:
                            result = f.result()
                            if isinstance(result, types.ServerResult):
                                call_result = result.root
                                from mcp.v1.mcp_pb2 import ToolResult
                                yield CallToolWithProgressResponse(
                                    result=ToolResult(
                                        content=[self._convert_content_to_proto(c) for c in call_result.content],
                                        is_error=call_result.isError
                                    )
                                )
                        except Exception as e:
                            logger.exception("Error in streaming tool call")
                            # gRPC stream error
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))
                    else:
                        # Progress update
                        update = f.result()
                        yield update
                        
            # Drain any remaining progress
            while not progress_queue.empty():
                yield progress_queue.get_nowait()

    async def ListResources(self, request, context):
        """
        List resources.
        
        Note: Currently buffers all resources from the Server handler.
        Future optimization: Support async iterators in Server handlers.
        """
        req = types.ListResourcesRequest(
            params=types.PaginatedRequestParams(cursor=None)
        )
        result = await self._execute_handler(types.ListResourcesRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            res_result = result.root
            for r in res_result.resources:
                yield ListResourcesResponse(resource=self._convert_resource_to_proto(r))

    async def ListResourceTemplates(self, request, context):
        """
        List resource templates.
        
        Note: Currently buffers results from the Server handler.
        """
        req = types.ListResourceTemplatesRequest(
            params=types.PaginatedRequestParams(cursor=None)
        )
        result = await self._execute_handler(types.ListResourceTemplatesRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            res_result = result.root
            from mcp.v1.mcp_pb2 import ResourceTemplate
            for t in res_result.resourceTemplates:
                yield ListResourceTemplatesResponse(
                    resource_template=ResourceTemplate(
                        uri_template=t.uriTemplate,
                        name=t.name,
                        description=t.description or "",
                        mime_type=t.mimeType or ""
                    )
                )

    async def ReadResource(self, request, context):
        """Read a resource."""
        req = types.ReadResourceRequest(
            params=types.ReadResourceRequestParams(uri=AnyUrl(request.uri))
        )
        result = await self._execute_handler(types.ReadResourceRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            read_result = result.root
            contents = []
            for c in read_result.contents:
                msg = ResourceContents(
                    uri=str(c.uri),
                    mime_type=c.mimeType or ""
                )
                if isinstance(c, types.TextResourceContents):
                    msg.text = c.text
                elif isinstance(c, types.BlobResourceContents):
                    import base64
                    msg.blob = base64.b64decode(c.blob)
                contents.append(msg)
                
            return ReadResourceResponse(contents=contents)
        return ReadResourceResponse()

    async def ReadResourceChunked(self, request, context):
        """
        Read a resource in chunks.
        
        Note: The underlying read_resource handler currently returns the full content
        (or a full list of contents), which we then chunk. True streaming from the
        source is not yet supported by the Server class.
        """
        req = types.ReadResourceRequest(
            params=types.ReadResourceRequestParams(uri=AnyUrl(request.uri))
        )
        
        # We reuse the standard ReadResource handler
        # Note: Ideally the handler would support yielding chunks, but for now
        # we get the full result and stream it back.
        result = await self._execute_handler(types.ReadResourceRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            read_result = result.root
            for c in read_result.contents:
                uri = str(c.uri)
                mime_type = c.mimeType or ""
                
                if isinstance(c, types.TextResourceContents):
                    text = c.text
                    # Chunk text to ensure messages stay within reasonable limits
                    # 8192 chars * 4 bytes/char (max utf8) = ~32KB, well within default 4MB limit
                    chunk_size = 8192
                    if not text:
                        yield ReadResourceChunkedResponse(
                            uri=uri,
                            mime_type=mime_type,
                            text_chunk="",
                            is_final=True
                        )
                    else:
                        for i in range(0, len(text), chunk_size):
                            chunk = text[i : i + chunk_size]
                            is_last = (i + chunk_size) >= len(text)
                            yield ReadResourceChunkedResponse(
                                uri=uri,
                                mime_type=mime_type,
                                text_chunk=chunk,
                                is_final=is_last
                            )

                elif isinstance(c, types.BlobResourceContents):
                    import base64
                    # Blob is base64 encoded in the Pydantic model
                    # But gRPC expects raw bytes in blob_chunk
                    blob_data = base64.b64decode(c.blob)
                    
                    # 64KB chunk size for binary data
                    chunk_size = 64 * 1024
                    if not blob_data:
                        yield ReadResourceChunkedResponse(
                            uri=uri,
                            mime_type=mime_type,
                            blob_chunk=b"",
                            is_final=True
                        )
                    else:
                        for i in range(0, len(blob_data), chunk_size):
                            chunk = blob_data[i : i + chunk_size]
                            is_last = (i + chunk_size) >= len(blob_data)
                            yield ReadResourceChunkedResponse(
                                uri=uri,
                                mime_type=mime_type,
                                blob_chunk=chunk,
                                is_final=is_last
                            )

    async def ListPrompts(self, request, context):
        """
        List prompts.
        
        Note: Currently buffers results from the Server handler.
        """
        req = types.ListPromptsRequest(
            params=types.PaginatedRequestParams(cursor=None)
        )
        result = await self._execute_handler(types.ListPromptsRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            prompts_result = result.root
            for p in prompts_result.prompts:
                yield ListPromptsResponse(prompt=self._convert_prompt_to_proto(p))

    async def GetPrompt(self, request, context):
        """Get a prompt."""
        req = types.GetPromptRequest(
            params=types.GetPromptRequestParams(
                name=request.name,
                arguments=dict(request.arguments)
            )
        )
        result = await self._execute_handler(types.GetPromptRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            prompt_result = result.root
            messages = []
            for m in prompt_result.messages:
                # Convert Role enum
                from mcp.v1.mcp_pb2 import Role
                role = Role.ROLE_USER if m.role == "user" else Role.ROLE_ASSISTANT
                
                messages.append(PromptMessage(
                    role=role,
                    content=self._convert_content_to_proto(m.content)
                ))
                
            return GetPromptResponse(
                description=prompt_result.description or "",
                messages=messages
            )
        return GetPromptResponse()

    async def Complete(self, request, context):
        """Autocomplete."""
        # Map proto reference to internal reference
        ref: types.PromptReference | types.ResourceTemplateReference
        if request.HasField("prompt_ref"):
            ref = types.PromptReference(name=request.prompt_ref.name)
        else:
            ref = types.ResourceTemplateReference(uri=request.resource_template_ref.uri)
            
        req = types.CompleteRequest(
            params=types.CompleteRequestParams(
                ref=ref,
                argument=types.CompletionArgument(
                    name=request.argument_name,
                    value=request.argument_value
                )
            )
        )
        
        result = await self._execute_handler(types.CompleteRequest, req, context)
        
        if isinstance(result, types.ServerResult):
            comp_result = result.root.completion
            return CompleteResponse(
                completion=CompletionResult(
                    values=comp_result.values,
                    total=comp_result.total or 0,
                    has_more=comp_result.hasMore or False
                )
            )
        return CompleteResponse()


async def start_grpc_server(
    server: Server,
    address: str = "[::]:50051",
    ssl_key_chain: tuple[bytes, bytes] | None = None
) -> grpc.aio.Server:
    """
    Start a gRPC server serving the given MCP server instance.
    
    Args:
        server: The MCP server instance (from mcp.server.lowlevel.server)
        address: The address to bind to (default: "[::]:50051")
        ssl_key_chain: Optional (private_key, certificate_chain) for SSL/TLS
        
    Returns:
        The started grpc.aio.Server instance.
    """
    grpc_server = grpc.aio.server()
    servicer = McpGrpcServicer(server)
    add_McpServiceServicer_to_server(servicer, grpc_server)
    
    if ssl_key_chain:
        server_credentials = grpc.ssl_server_credentials([ssl_key_chain])
        grpc_server.add_secure_port(address, server_credentials)
    else:
        grpc_server.add_insecure_port(address)
        
    logger.info("Starting MCP gRPC server on %s", address)
    await grpc_server.start()
    return grpc_server
