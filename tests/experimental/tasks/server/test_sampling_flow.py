"""
Integration test for task sampling flow.

This tests the complete sampling flow:
1. Client sends task-augmented tool call
2. Server creates task, returns CreateTaskResult immediately
3. Server handler uses TaskSession.create_message() to request LLM completion
4. Client polls, sees input_required status
5. Client calls tasks/result which delivers the sampling request
6. Client responds with CreateMessageResult
7. Response is routed back to server handler
8. Handler completes task
9. Client receives final result
"""

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.experimental.tasks import (
    InMemoryTaskMessageQueue,
    InMemoryTaskStore,
    TaskResultHandler,
    TaskSession,
    task_execution,
)
from mcp.shared.message import SessionMessage
from mcp.types import (
    TASK_REQUIRED,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    ClientRequest,
    CreateMessageRequest,
    CreateMessageResult,
    CreateTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    SamplingMessage,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
)


@dataclass
class AppContext:
    """Application context with task infrastructure."""

    task_group: TaskGroup
    store: InMemoryTaskStore
    queue: InMemoryTaskMessageQueue
    task_result_handler: TaskResultHandler
    # Events to signal when tasks complete (for testing without sleeps)
    task_done_events: dict[str, Event] = field(default_factory=lambda: {})


@pytest.mark.anyio
async def test_sampling_during_task_with_response_routing() -> None:
    """
    Test the complete sampling flow with response routing.

    This is an end-to-end test that verifies:
    - TaskSession.create_message() enqueues the request
    - TaskResultHandler delivers it via tasks/result
    - Client responds with CreateMessageResult
    - Response is routed back to the waiting resolver
    - Handler continues and completes
    """
    server: Server[AppContext, Any] = Server("test-sampling")  # type: ignore[assignment]
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    task_result_handler = TaskResultHandler(store, queue)

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="ai_assistant_tool",
                description="A tool that uses AI for processing",
                inputSchema={
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                },
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent] | CreateTaskResult:
        ctx = server.request_context
        app = ctx.lifespan_context

        if name == "ai_assistant_tool" and ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.taskId] = done_event

            async def do_ai_work():
                async with task_execution(task.taskId, app.store) as task_ctx:
                    await task_ctx.update_status("Requesting AI assistance...", notify=True)

                    # Create TaskSession for task-aware sampling
                    task_session = TaskSession(
                        session=ctx.session,
                        task_id=task.taskId,
                        store=app.store,
                        queue=app.queue,
                    )

                    question = arguments.get("question", "What is 2+2?")

                    # This enqueues the sampling request
                    # It will block until response is routed back
                    sampling_result = await task_session.create_message(
                        messages=[
                            SamplingMessage(
                                role="user",
                                content=TextContent(type="text", text=question),
                            )
                        ],
                        max_tokens=100,
                        system_prompt="You are a helpful assistant. Answer concisely.",
                    )

                    # Process the AI response
                    ai_response = "Unknown"
                    if isinstance(sampling_result.content, TextContent):
                        ai_response = sampling_result.content.text

                    result_text = f"AI answered: {ai_response}"

                    await task_ctx.complete(
                        CallToolResult(content=[TextContent(type="text", text=result_text)]),
                        notify=True,  # Must notify so TaskResultHandler.handle() wakes up
                    )
                done_event.set()

            app.task_group.start_soon(do_ai_work)
            return CreateTaskResult(task=task)

        return [TextContent(type="text", text="Non-task result")]

    @server.experimental.get_task()
    async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
        app = server.request_context.lifespan_context
        task = await app.store.get_task(request.params.taskId)
        if task is None:
            raise ValueError(f"Task {request.params.taskId} not found")
        return GetTaskResult(
            taskId=task.taskId,
            status=task.status,
            statusMessage=task.statusMessage,
            createdAt=task.createdAt,
            lastUpdatedAt=task.lastUpdatedAt,
            ttl=task.ttl,
            pollInterval=task.pollInterval,
        )

    @server.experimental.get_task_result()
    async def handle_get_task_result(
        request: GetTaskPayloadRequest,
    ) -> GetTaskPayloadResult:
        app = server.request_context.lifespan_context
        # Use the TaskResultHandler to handle the dequeue-send-wait pattern
        return await app.task_result_handler.handle(
            request,
            server.request_context.session,
            server.request_context.request_id,
        )

    # Set up bidirectional streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Track sampling requests received by client
    sampling_requests_received: list[CreateMessageRequest] = []

    async def sampling_callback(
        context: Any,
        params: Any,
    ) -> CreateMessageResult:
        """Client-side sampling callback that responds to sampling requests."""
        sampling_requests_received.append(CreateMessageRequest(params=params))
        # Return a mock AI response
        return CreateMessageResult(
            model="test-model",
            role="assistant",
            content=TextContent(type="text", text="The answer is 4"),
        )

    async def run_server(app_context: AppContext, server_session: ServerSession):
        async for message in server_session.incoming_messages:
            await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            task_result_handler=task_result_handler,
        )

        # Create server session and wire up task result handler
        server_session = ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

        # Wire up the task result handler for response routing
        server_session.add_response_router(task_result_handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                sampling_callback=sampling_callback,
            ) as client_session:
                await client_session.initialize()

                # === Step 1: Send task-augmented tool call ===
                create_result = await client_session.send_request(
                    ClientRequest(
                        CallToolRequest(
                            params=CallToolRequestParams(
                                name="ai_assistant_tool",
                                arguments={"question": "What is 2+2?"},
                                task=TaskMetadata(ttl=60000),
                            ),
                        )
                    ),
                    CreateTaskResult,
                )

                assert isinstance(create_result, CreateTaskResult)
                task_id = create_result.task.taskId

                # === Step 2: Poll until input_required or completed ===
                max_polls = 100
                task_status: GetTaskResult | None = None
                for _ in range(max_polls):
                    task_status = await client_session.send_request(
                        ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))),
                        GetTaskResult,
                    )

                    if task_status.status in ("input_required", "completed", "failed"):
                        break
                    await anyio.sleep(0)  # Yield to allow server to process

                # Task should be in input_required state (waiting for sampling response)
                assert task_status is not None, "Polling loop did not execute"
                assert task_status.status == "input_required", f"Expected input_required, got {task_status.status}"

                # === Step 3: Call tasks/result which will deliver sampling request ===
                # This should:
                # 1. Dequeue the sampling request
                # 2. Send it to us (handled by sampling_callback above)
                # 3. Wait for our response
                # 4. Continue until task completes
                # 5. Return final result
                final_result = await client_session.send_request(
                    ClientRequest(GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task_id))),
                    CallToolResult,
                )

                # === Verify results ===
                # We should have received and responded to a sampling request
                assert len(sampling_requests_received) == 1
                first_message_content = sampling_requests_received[0].params.messages[0].content
                assert isinstance(first_message_content, TextContent)
                assert first_message_content.text == "What is 2+2?"

                # Final result should reflect the AI response
                assert len(final_result.content) == 1
                content = final_result.content[0]
                assert isinstance(content, TextContent)
                assert "AI answered: The answer is 4" in content.text

                # Task should be completed
                final_status = await client_session.send_request(
                    ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))),
                    GetTaskResult,
                )
                assert final_status.status == "completed"

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()
