"""
Integration test for task elicitation flow.

This tests the complete elicitation flow:
1. Client sends task-augmented tool call
2. Server creates task, returns CreateTaskResult immediately
3. Server handler uses TaskSession.elicit() to request input
4. Client polls, sees input_required status
5. Client calls tasks/result which delivers the elicitation
6. Client responds to elicitation
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
    CreateTaskResult,
    ElicitRequest,
    ElicitResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
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
async def test_elicitation_during_task_with_response_routing() -> None:
    """
    Test the complete elicitation flow with response routing.

    This is an end-to-end test that verifies:
    - TaskSession.elicit() enqueues the request
    - TaskResultHandler delivers it via tasks/result
    - Client responds
    - Response is routed back to the waiting resolver
    - Handler continues and completes
    """
    server: Server[AppContext, Any] = Server("test-elicitation")  # type: ignore[assignment]
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    task_result_handler = TaskResultHandler(store, queue)

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="interactive_tool",
                description="A tool that asks for user confirmation",
                inputSchema={
                    "type": "object",
                    "properties": {"data": {"type": "string"}},
                },
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent] | CreateTaskResult:
        ctx = server.request_context
        app = ctx.lifespan_context

        if name == "interactive_tool" and ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.taskId] = done_event

            async def do_interactive_work():
                async with task_execution(task.taskId, app.store) as task_ctx:
                    await task_ctx.update_status("Requesting confirmation...", notify=True)

                    # Create TaskSession for task-aware elicitation
                    task_session = TaskSession(
                        session=ctx.session,
                        task_id=task.taskId,
                        store=app.store,
                        queue=app.queue,
                    )

                    # This enqueues the elicitation request
                    # It will block until response is routed back
                    elicit_result = await task_session.elicit(
                        message=f"Confirm processing of: {arguments.get('data', '')}",
                        requestedSchema={
                            "type": "object",
                            "properties": {
                                "confirmed": {"type": "boolean"},
                            },
                            "required": ["confirmed"],
                        },
                    )

                    # Process based on user response
                    if elicit_result.action == "accept" and elicit_result.content:
                        confirmed = elicit_result.content.get("confirmed", False)
                        if confirmed:
                            result_text = f"Confirmed and processed: {arguments.get('data', '')}"
                        else:
                            result_text = "User declined - not processed"
                    else:
                        result_text = "Elicitation cancelled or declined"

                    await task_ctx.complete(
                        CallToolResult(content=[TextContent(type="text", text=result_text)]),
                        notify=True,  # Must notify so TaskResultHandler.handle() wakes up
                    )
                done_event.set()

            app.task_group.start_soon(do_interactive_work)
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
            ttl=task.ttl,
            pollInterval=task.pollInterval,
        )

    @server.experimental.get_task_result()
    async def handle_get_task_result(request: GetTaskPayloadRequest) -> GetTaskPayloadResult:
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

    # Track elicitation requests received by client
    elicitation_received: list[ElicitRequest] = []

    async def elicitation_callback(
        context: Any,
        params: Any,
    ) -> ElicitResult:
        """Client-side elicitation callback that responds to elicitations."""
        elicitation_received.append(ElicitRequest(params=params))
        return ElicitResult(
            action="accept",
            content={"confirmed": True},
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
        server_session.set_task_result_handler(task_result_handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                elicitation_callback=elicitation_callback,
            ) as client_session:
                await client_session.initialize()

                # === Step 1: Send task-augmented tool call ===
                create_result = await client_session.send_request(
                    ClientRequest(
                        CallToolRequest(
                            params=CallToolRequestParams(
                                name="interactive_tool",
                                arguments={"data": "important data"},
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

                # Task should be in input_required state (waiting for elicitation response)
                assert task_status is not None, "Polling loop did not execute"
                assert task_status.status == "input_required", f"Expected input_required, got {task_status.status}"

                # === Step 3: Call tasks/result which will deliver elicitation ===
                # This should:
                # 1. Dequeue the elicitation request
                # 2. Send it to us (handled by elicitation_callback above)
                # 3. Wait for our response
                # 4. Continue until task completes
                # 5. Return final result
                final_result = await client_session.send_request(
                    ClientRequest(GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task_id))),
                    CallToolResult,
                )

                # === Verify results ===
                # We should have received and responded to an elicitation
                assert len(elicitation_received) == 1
                assert "Confirm processing of: important data" in elicitation_received[0].params.message

                # Final result should reflect our confirmation
                assert len(final_result.content) == 1
                content = final_result.content[0]
                assert isinstance(content, TextContent)
                assert "Confirmed and processed: important data" in content.text

                # Task should be completed
                final_status = await client_session.send_request(
                    ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))),
                    GetTaskResult,
                )
                assert final_status.status == "completed"

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()
