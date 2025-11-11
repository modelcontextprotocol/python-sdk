"""
ServerSession Module

This module provides the ServerSession class, which manages communication between the
server and client in the MCP (Model Context Protocol) framework. It is most commonly
used in MCP servers to interact with the client.

Common usage pattern:
```
    server = Server(name)

    @server.call_tool()
    async def handle_tool_call(ctx: RequestContext, arguments: dict[str, Any]) -> Any:
        # Check client capabilities before proceeding
        if ctx.session.check_client_capability(
            types.ClientCapabilities(experimental={"advanced_tools": dict()})
        ):
            # Perform advanced tool operations
            result = await perform_advanced_tool_operation(arguments)
        else:
            # Fall back to basic tool operations
            result = await perform_basic_tool_operation(arguments)

        return result

    @server.list_prompts()
    async def handle_list_prompts(ctx: RequestContext) -> list[types.Prompt]:
        # Access session for any necessary checks or operations
        if ctx.session.client_params:
            # Customize prompts based on client initialization parameters
            return generate_custom_prompts(ctx.session.client_params)
        else:
            return default_prompts
```

The ServerSession class is typically used internally by the Server class and should not
be instantiated directly by users of the MCP framework.
"""

from enum import Enum
from typing import Any, TypeVar

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl, BaseModel

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import (
    BaseSession,
    RequestResponder,
)
from mcp.shared.task import TaskStore
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS


class InitializationState(Enum):
    NotInitialized = 1
    Initializing = 2
    Initialized = 3


ServerResultT = TypeVar("ServerResultT", BaseModel, types.ServerResult)
ServerSessionT = TypeVar("ServerSessionT", bound="ServerSession")

ServerRequestResponder = (
    RequestResponder[types.ClientRequest, types.ServerResult] | types.ClientNotification | Exception
)


class ServerSession(
    BaseSession[
        types.ServerRequest,
        types.ServerNotification,
        types.ServerResult,
        types.ClientRequest,
        types.ClientNotification,
    ]
):
    _initialized: InitializationState = InitializationState.NotInitialized
    _client_params: types.InitializeRequestParams | None = None

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        init_options: InitializationOptions,
        stateless: bool = False,
        task_store: TaskStore | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(
            read_stream,
            write_stream,
            types.ClientRequest,
            types.ClientNotification,
            task_store=task_store,
            session_id=session_id,
        )
        self._initialization_state = (
            InitializationState.Initialized if stateless else InitializationState.NotInitialized
        )

        self._init_options = init_options
        self._incoming_message_stream_writer, self._incoming_message_stream_reader = anyio.create_memory_object_stream[
            ServerRequestResponder
        ](0)
        self._exit_stack.push_async_callback(lambda: self._incoming_message_stream_reader.aclose())

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        return self._client_params  # pragma: no cover

    def _check_tasks_capability(
        self, required: types.ClientTasksCapability, client: types.ClientTasksCapability
    ) -> bool:
        """Check if client supports required tasks capabilities."""
        if required.requests is None:
            return True
        if client.requests is None:
            return False

        req_cap = required.requests
        client_req_cap = client.requests

        # Check sampling requests
        if req_cap.sampling is not None and (
            client_req_cap.sampling is None
            or (req_cap.sampling.createMessage and not client_req_cap.sampling.createMessage)
        ):
            return False

        # Check elicitation requests
        if req_cap.elicitation is not None and (
            client_req_cap.elicitation is None or (req_cap.elicitation.create and not client_req_cap.elicitation.create)
        ):
            return False

        # Check roots requests
        if req_cap.roots is not None and (
            client_req_cap.roots is None or (req_cap.roots.list and not client_req_cap.roots.list)
        ):
            return False

        # Check tasks operations
        if req_cap.tasks is not None:
            if client_req_cap.tasks is None:
                return False
            tasks_checks = [
                not req_cap.tasks.get or client_req_cap.tasks.get,
                not req_cap.tasks.list or client_req_cap.tasks.list,
                not req_cap.tasks.result or client_req_cap.tasks.result,
                not req_cap.tasks.delete or client_req_cap.tasks.delete,
            ]
            if not all(tasks_checks):
                return False

        return True

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:  # pragma: no cover
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

        if capability.tasks is not None:
            if client_caps.tasks is None:
                return False
            if not self._check_tasks_capability(capability.tasks, client_caps.tasks):
                return False

        return True

    async def _receive_loop(self) -> None:
        async with self._incoming_message_stream_writer:
            await super()._receive_loop()

    async def _received_request(  # noqa: PLR0912
        self, responder: RequestResponder[types.ClientRequest, types.ServerResult]
    ):
        # Handle task creation if task metadata is present
        if responder.request_meta and responder.request_meta.task and self._task_store:
            task_meta = responder.request_meta.task
            # Create the task in the task store
            await self._task_store.create_task(
                task_meta,
                responder.request_id,
                responder.request.root,
                session_id=self._session_id,  # type: ignore[arg-type]
            )
            # Send task created notification with related task metadata
            notification_params = types.TaskCreatedNotificationParams(
                _meta=types.NotificationParams.Meta(
                    **{types.RELATED_TASK_META_KEY: types.RelatedTaskMetadata(taskId=task_meta.taskId)}
                )
            )
            await self.send_notification(
                types.ServerNotification(
                    types.TaskCreatedNotification(method="notifications/tasks/created", params=notification_params)
                ),
                related_request_id=responder.request_id,
            )

        match responder.request.root:
            case types.InitializeRequest(params=params):
                requested_version = params.protocolVersion
                self._initialization_state = InitializationState.Initializing
                self._client_params = params
                with responder:
                    await responder.respond(
                        types.ServerResult(
                            types.InitializeResult(
                                protocolVersion=requested_version
                                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                                else types.LATEST_PROTOCOL_VERSION,
                                capabilities=self._init_options.capabilities,
                                serverInfo=types.Implementation(
                                    name=self._init_options.server_name,
                                    version=self._init_options.server_version,
                                    websiteUrl=self._init_options.website_url,
                                    icons=self._init_options.icons,
                                ),
                                instructions=self._init_options.instructions,
                            )
                        )
                    )
                self._initialization_state = InitializationState.Initialized
            case types.PingRequest():
                # Ping requests are allowed at any time
                pass
            case types.GetTaskRequest(params=params):
                # Check if client has announced tasks capability
                if self._client_params is None or self._client_params.capabilities.tasks is None:
                    with responder:
                        await responder.respond(
                            types.ErrorData(
                                code=types.INVALID_REQUEST,
                                message="Client has not announced tasks capability",
                            )
                        )
                # Handle get task requests if task store is available
                elif self._task_store:
                    task = await self._task_store.get_task(params.taskId, session_id=self._session_id)
                    if task is None:
                        with responder:
                            await responder.respond(
                                types.ErrorData(
                                    code=types.INVALID_PARAMS, message="Failed to retrieve task: Task not found"
                                )
                            )
                    else:
                        with responder:
                            result = types.GetTaskResult(
                                taskId=task.taskId,
                                status=task.status,
                                keepAlive=task.keepAlive,
                                pollInterval=task.pollInterval,
                                error=task.error,
                                _meta={types.RELATED_TASK_META_KEY: {"taskId": params.taskId}},
                            )
                            await responder.respond(types.ServerResult(result))
                else:
                    with responder:
                        await responder.respond(
                            types.ErrorData(code=types.INVALID_REQUEST, message="Task store not configured")
                        )
            case types.GetTaskPayloadRequest(params=params):
                # Check if client has announced tasks capability
                if self._client_params is None or self._client_params.capabilities.tasks is None:
                    with responder:
                        await responder.respond(
                            types.ErrorData(
                                code=types.INVALID_REQUEST,
                                message="Client has not announced tasks capability",
                            )
                        )
                # Handle get task result requests if task store is available
                elif self._task_store:
                    task = await self._task_store.get_task(params.taskId, session_id=self._session_id)
                    if task is None:
                        with responder:
                            await responder.respond(
                                types.ErrorData(
                                    code=types.INVALID_PARAMS, message="Failed to retrieve task: Task not found"
                                )
                            )
                    elif task.status != "completed":
                        with responder:
                            await responder.respond(
                                types.ErrorData(
                                    code=types.INVALID_PARAMS,
                                    message=f"Cannot retrieve result: Task status is '{task.status}', not 'completed'",
                                )
                            )
                    else:
                        result = await self._task_store.get_task_result(params.taskId, session_id=self._session_id)
                        # Add related-task metadata
                        result_dict = result.model_dump(by_alias=True, mode="json", exclude_none=True)
                        if "_meta" not in result_dict:
                            result_dict["_meta"] = {}
                        result_dict["_meta"][types.RELATED_TASK_META_KEY] = {"taskId": params.taskId}
                        with responder:
                            await responder.respond(types.ServerResult.model_validate(result_dict))
                else:
                    with responder:
                        await responder.respond(
                            types.ErrorData(code=types.INVALID_REQUEST, message="Task store not configured")
                        )
            case types.ListTasksRequest(params=params):
                # Check if client has announced tasks capability
                if self._client_params is None or self._client_params.capabilities.tasks is None:
                    with responder:
                        await responder.respond(
                            types.ErrorData(
                                code=types.INVALID_REQUEST,
                                message="Client has not announced tasks capability",
                            )
                        )
                # Handle list tasks requests if task store is available
                elif self._task_store:
                    try:
                        result = await self._task_store.list_tasks(
                            params.cursor if params else None, session_id=self._session_id
                        )
                        with responder:
                            await responder.respond(
                                types.ServerResult(
                                    types.ListTasksResult(
                                        tasks=result["tasks"],  # type: ignore[arg-type]
                                        nextCursor=result.get("nextCursor"),  # type: ignore[arg-type]
                                        _meta={},
                                    )
                                )
                            )
                    except Exception as e:
                        with responder:
                            await responder.respond(
                                types.ErrorData(code=types.INVALID_PARAMS, message=f"Failed to list tasks: {e}")
                            )
                else:
                    with responder:
                        await responder.respond(
                            types.ErrorData(code=types.INVALID_REQUEST, message="Task store not configured")
                        )
            case types.DeleteTaskRequest(params=params):
                # Check if client has announced tasks capability
                if self._client_params is None or self._client_params.capabilities.tasks is None:
                    with responder:
                        await responder.respond(
                            types.ErrorData(
                                code=types.INVALID_REQUEST,
                                message="Client has not announced tasks capability",
                            )
                        )
                # Handle delete task requests if task store is available
                elif self._task_store:
                    try:
                        await self._task_store.delete_task(params.taskId, session_id=self._session_id)
                        with responder:
                            await responder.respond(types.ServerResult(types.EmptyResult(_meta={})))
                    except Exception as e:
                        with responder:
                            await responder.respond(
                                types.ErrorData(code=types.INVALID_PARAMS, message=f"Failed to delete task: {e}")
                            )
                else:
                    with responder:
                        await responder.respond(
                            types.ErrorData(code=types.INVALID_REQUEST, message="Task store not configured")
                        )
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError("Received request before initialization was complete")

    async def _received_notification(self, notification: types.ClientNotification) -> None:
        # Need this to avoid ASYNC910
        await anyio.lowlevel.checkpoint()
        match notification.root:
            case types.InitializedNotification():
                self._initialization_state = InitializationState.Initialized
            case _:
                if self._initialization_state != InitializationState.Initialized:  # pragma: no cover
                    raise RuntimeError("Received notification before initialization was complete")

    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification."""
        await self.send_notification(
            types.ServerNotification(
                types.LoggingMessageNotification(
                    params=types.LoggingMessageNotificationParams(
                        level=level,
                        data=data,
                        logger=logger,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_updated(self, uri: AnyUrl) -> None:  # pragma: no cover
        """Send a resource updated notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ResourceUpdatedNotification(
                    params=types.ResourceUpdatedNotificationParams(uri=uri),
                )
            )
        )

    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult:
        """Send a sampling/create_message request."""
        return await self.send_request(
            request=types.ServerRequest(
                types.CreateMessageRequest(
                    params=types.CreateMessageRequestParams(
                        messages=messages,
                        systemPrompt=system_prompt,
                        includeContext=include_context,
                        temperature=temperature,
                        maxTokens=max_tokens,
                        stopSequences=stop_sequences,
                        metadata=metadata,
                        modelPreferences=model_preferences,
                    ),
                )
            ),
            result_type=types.CreateMessageResult,
            metadata=ServerMessageMetadata(
                related_request_id=related_request_id,
            ),
        )

    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        return await self.send_request(
            types.ServerRequest(types.ListRootsRequest()),
            types.ListRootsResult,
        )

    async def elicit(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send an elicitation/create request.

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure

        Returns:
            The client's response
        """
        return await self.send_request(
            types.ServerRequest(
                types.ElicitRequest(
                    params=types.ElicitRequestParams(
                        message=message,
                        requestedSchema=requestedSchema,
                    ),
                )
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def send_ping(self) -> types.EmptyResult:  # pragma: no cover
        """Send a ping request."""
        return await self.send_request(
            types.ServerRequest(types.PingRequest()),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ProgressNotification(
                    params=types.ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                        message=message,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_list_changed(self) -> None:  # pragma: no cover
        """Send a resource list changed notification."""
        await self.send_notification(types.ServerNotification(types.ResourceListChangedNotification()))

    async def send_tool_list_changed(self) -> None:  # pragma: no cover
        """Send a tool list changed notification."""
        await self.send_notification(types.ServerNotification(types.ToolListChangedNotification()))

    async def send_prompt_list_changed(self) -> None:  # pragma: no cover
        """Send a prompt list changed notification."""
        await self.send_notification(types.ServerNotification(types.PromptListChangedNotification()))

    async def get_task(self, task_id: str) -> types.GetTaskResult:
        """Get the current status of a task."""
        return await self.send_request(
            types.ServerRequest(types.GetTaskRequest(method="tasks/get", params=types.GetTaskParams(taskId=task_id))),
            types.GetTaskResult,
        )

    async def get_task_result(self, task_id: str, result_type: type[ServerResultT]) -> ServerResultT:
        """Retrieve the result of a completed task."""
        return await self.send_request(
            types.ServerRequest(
                types.GetTaskPayloadRequest(method="tasks/result", params=types.GetTaskPayloadParams(taskId=task_id))
            ),
            result_type,
        )

    async def list_tasks(self, cursor: str | None = None) -> types.ListTasksResult:
        """List tasks, optionally starting from a pagination cursor."""
        return await self.send_request(
            types.ServerRequest(
                types.ListTasksRequest(
                    method="tasks/list", params=types.PaginatedRequestParams(cursor=cursor) if cursor else None
                )
            ),
            types.ListTasksResult,
        )

    async def delete_task(self, task_id: str) -> types.EmptyResult:
        """Delete a specific task."""
        return await self.send_request(
            types.ServerRequest(
                types.DeleteTaskRequest(method="tasks/delete", params=types.DeleteTaskParams(taskId=task_id))
            ),
            types.EmptyResult,
        )

    async def _handle_incoming(self, req: ServerRequestResponder) -> None:
        await self._incoming_message_stream_writer.send(req)

    @property
    def incoming_messages(
        self,
    ) -> MemoryObjectReceiveStream[ServerRequestResponder]:
        return self._incoming_message_stream_reader
