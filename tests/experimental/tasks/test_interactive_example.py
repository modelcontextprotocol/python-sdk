"""
Unit test that demonstrates the correct interactive task pattern.

This test serves as the reference implementation for the simple-task-interactive
examples. It demonstrates:

1. A server with two tools:
   - confirm_delete: Uses elicitation to ask for user confirmation
   - write_haiku: Uses sampling to request LLM completion

2. A client that:
   - Calls tools as tasks using session.experimental.call_tool_as_task()
   - Handles elicitation via callback
   - Handles sampling via callback
   - Retrieves results via session.experimental.get_task_result()

Key insight: The client must call get_task_result() to receive elicitation/sampling
requests. The server delivers these requests via the tasks/result response stream.
Simply polling get_task() will not trigger the callbacks.
"""

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from anyio.abc import TaskGroup

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.experimental.tasks import (
    InMemoryTaskMessageQueue,
    InMemoryTaskStore,
    TaskResultHandler,
    TaskSession,
    task_execution,
)
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    SamplingMessage,
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
    handler: TaskResultHandler
    configured_sessions: dict[int, bool] = field(default_factory=lambda: {})


def create_server() -> Server[AppContext, Any]:
    """Create the server with confirm_delete and write_haiku tools."""
    server: Server[AppContext, Any] = Server("simple-task-interactive")  # type: ignore[assignment]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="confirm_delete",
                description="Asks for confirmation before deleting (demonstrates elicitation)",
                inputSchema={"type": "object", "properties": {"filename": {"type": "string"}}},
                execution=ToolExecution(task="always"),
            ),
            Tool(
                name="write_haiku",
                description="Asks LLM to write a haiku (demonstrates sampling)",
                inputSchema={"type": "object", "properties": {"topic": {"type": "string"}}},
                execution=ToolExecution(task="always"),
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent] | Any:
        ctx = server.request_context
        app = ctx.lifespan_context

        # Validate task mode
        ctx.experimental.validate_task_mode("always")

        # Ensure handler is configured for response routing
        session_id = id(ctx.session)
        if session_id not in app.configured_sessions:
            ctx.session.set_task_result_handler(app.handler)
            app.configured_sessions[session_id] = True

        # Create task
        metadata = ctx.experimental.task_metadata
        assert metadata is not None
        task = await app.store.create_task(metadata)

        if name == "confirm_delete":
            filename = arguments.get("filename", "unknown.txt")

            async def do_confirm() -> None:
                async with task_execution(task.taskId, app.store) as task_ctx:
                    task_session = TaskSession(
                        session=ctx.session,
                        task_id=task.taskId,
                        store=app.store,
                        queue=app.queue,
                    )

                    result = await task_session.elicit(
                        message=f"Are you sure you want to delete '{filename}'?",
                        requestedSchema={
                            "type": "object",
                            "properties": {"confirm": {"type": "boolean"}},
                            "required": ["confirm"],
                        },
                    )

                    if result.action == "accept" and result.content:
                        confirmed = result.content.get("confirm", False)
                        text = f"Deleted '{filename}'" if confirmed else "Deletion cancelled"
                    else:
                        text = "Deletion cancelled"

                    await task_ctx.complete(
                        CallToolResult(content=[TextContent(type="text", text=text)]),
                        notify=True,
                    )

            app.task_group.start_soon(do_confirm)

        elif name == "write_haiku":
            topic = arguments.get("topic", "nature")

            async def do_haiku() -> None:
                async with task_execution(task.taskId, app.store) as task_ctx:
                    task_session = TaskSession(
                        session=ctx.session,
                        task_id=task.taskId,
                        store=app.store,
                        queue=app.queue,
                    )

                    result = await task_session.create_message(
                        messages=[
                            SamplingMessage(
                                role="user",
                                content=TextContent(type="text", text=f"Write a haiku about {topic}"),
                            )
                        ],
                        max_tokens=50,
                    )

                    haiku = "No response"
                    if isinstance(result.content, TextContent):
                        haiku = result.content.text

                    await task_ctx.complete(
                        CallToolResult(content=[TextContent(type="text", text=f"Haiku:\n{haiku}")]),
                        notify=True,
                    )

            app.task_group.start_soon(do_haiku)

        # Import here to avoid circular imports at module level
        from mcp.types import CreateTaskResult

        return CreateTaskResult(task=task)

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
        ctx = server.request_context
        app = ctx.lifespan_context

        # Ensure handler is configured for this session
        session_id = id(ctx.session)
        if session_id not in app.configured_sessions:
            ctx.session.set_task_result_handler(app.handler)
            app.configured_sessions[session_id] = True

        return await app.handler.handle(request, ctx.session, ctx.request_id)

    return server


@pytest.mark.anyio
async def test_confirm_delete_with_elicitation() -> None:
    """
    Test the confirm_delete tool which uses elicitation.

    This demonstrates:
    1. Client calls tool as task
    2. Server asks for confirmation via elicitation
    3. Client receives elicitation via get_task_result() and responds
    4. Server completes task based on response
    """
    server = create_server()
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)

    # Track elicitation requests
    elicitation_messages: list[str] = []

    async def elicitation_callback(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        """Handle elicitation - simulates user confirming deletion."""
        elicitation_messages.append(params.message)
        # User confirms
        return ElicitResult(action="accept", content={"confirm": True})

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server(app_context: AppContext, server_session: ServerSession) -> None:
        async for message in server_session.incoming_messages:
            await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            handler=handler,
        )

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
        server_session.set_task_result_handler(handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                elicitation_callback=elicitation_callback,
            ) as client:
                await client.initialize()

                # List tools
                tools = await client.list_tools()
                tool_names = [t.name for t in tools.tools]
                assert "confirm_delete" in tool_names
                assert "write_haiku" in tool_names

                # Call tool as task
                result = await client.experimental.call_tool_as_task(
                    "confirm_delete",
                    {"filename": "important.txt"},
                )
                task_id = result.task.taskId

                # KEY PATTERN: Call get_task_result() to receive elicitation and get final result
                # This is the critical difference from the broken example which only polled get_task()
                final = await client.experimental.get_task_result(task_id, CallToolResult)

                # Verify elicitation was received
                assert len(elicitation_messages) == 1
                assert "important.txt" in elicitation_messages[0]

                # Verify result
                assert len(final.content) == 1
                assert isinstance(final.content[0], TextContent)
                assert final.content[0].text == "Deleted 'important.txt'"

                # Verify task is completed
                status = await client.experimental.get_task(task_id)
                assert status.status == "completed"

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()


@pytest.mark.anyio
async def test_confirm_delete_user_declines() -> None:
    """Test confirm_delete when user declines."""
    server = create_server()
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)

    async def elicitation_callback(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        # User declines
        return ElicitResult(action="accept", content={"confirm": False})

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server(app_context: AppContext, server_session: ServerSession) -> None:
        async for message in server_session.incoming_messages:
            await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            handler=handler,
        )

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
        server_session.set_task_result_handler(handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                elicitation_callback=elicitation_callback,
            ) as client:
                await client.initialize()

                result = await client.experimental.call_tool_as_task(
                    "confirm_delete",
                    {"filename": "important.txt"},
                )
                task_id = result.task.taskId

                final = await client.experimental.get_task_result(task_id, CallToolResult)

                assert isinstance(final.content[0], TextContent)
                assert final.content[0].text == "Deletion cancelled"

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()


@pytest.mark.anyio
async def test_write_haiku_with_sampling() -> None:
    """
    Test the write_haiku tool which uses sampling.

    This demonstrates:
    1. Client calls tool as task
    2. Server requests LLM completion via sampling
    3. Client receives sampling request via get_task_result() and responds
    4. Server completes task with the haiku
    """
    server = create_server()
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)

    # Track sampling requests
    sampling_prompts: list[str] = []
    test_haiku = """Autumn leaves falling
Softly on the quiet stream
Nature whispers peace"""

    async def sampling_callback(
        context: RequestContext[ClientSession, Any],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        """Handle sampling - returns a test haiku."""
        if params.messages:
            content = params.messages[0].content
            if isinstance(content, TextContent):
                sampling_prompts.append(content.text)

        return CreateMessageResult(
            model="test-model",
            role="assistant",
            content=TextContent(type="text", text=test_haiku),
        )

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server(app_context: AppContext, server_session: ServerSession) -> None:
        async for message in server_session.incoming_messages:
            await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            handler=handler,
        )

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
        server_session.set_task_result_handler(handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                sampling_callback=sampling_callback,
            ) as client:
                await client.initialize()

                # Call tool as task
                result = await client.experimental.call_tool_as_task(
                    "write_haiku",
                    {"topic": "autumn leaves"},
                )
                task_id = result.task.taskId

                # Get result (this delivers the sampling request)
                final = await client.experimental.get_task_result(task_id, CallToolResult)

                # Verify sampling was requested
                assert len(sampling_prompts) == 1
                assert "autumn leaves" in sampling_prompts[0]

                # Verify result contains the haiku
                assert len(final.content) == 1
                assert isinstance(final.content[0], TextContent)
                assert "Haiku:" in final.content[0].text
                assert "Autumn leaves falling" in final.content[0].text

                # Verify task is completed
                status = await client.experimental.get_task(task_id)
                assert status.status == "completed"

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()


@pytest.mark.anyio
async def test_both_tools_sequentially() -> None:
    """
    Test calling both tools sequentially, similar to how the example works.

    This is the closest match to what the example client does.
    """
    server = create_server()
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)

    elicitation_count = 0
    sampling_count = 0

    async def elicitation_callback(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        nonlocal elicitation_count
        elicitation_count += 1
        return ElicitResult(action="accept", content={"confirm": True})

    async def sampling_callback(
        context: RequestContext[ClientSession, Any],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        nonlocal sampling_count
        sampling_count += 1
        return CreateMessageResult(
            model="test-model",
            role="assistant",
            content=TextContent(type="text", text="Cherry blossoms fall"),
        )

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server(app_context: AppContext, server_session: ServerSession) -> None:
        async for message in server_session.incoming_messages:
            await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            handler=handler,
        )

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
        server_session.set_task_result_handler(handler)

        async with server_session:
            tg.start_soon(run_server, app_context, server_session)

            async with ClientSession(
                server_to_client_receive,
                client_to_server_send,
                elicitation_callback=elicitation_callback,
                sampling_callback=sampling_callback,
            ) as client:
                await client.initialize()

                # === Demo 1: Elicitation (confirm_delete) ===
                result1 = await client.experimental.call_tool_as_task(
                    "confirm_delete",
                    {"filename": "important.txt"},
                )
                task_id1 = result1.task.taskId

                final1 = await client.experimental.get_task_result(task_id1, CallToolResult)
                assert isinstance(final1.content[0], TextContent)
                assert "Deleted" in final1.content[0].text

                # === Demo 2: Sampling (write_haiku) ===
                result2 = await client.experimental.call_tool_as_task(
                    "write_haiku",
                    {"topic": "autumn leaves"},
                )
                task_id2 = result2.task.taskId

                final2 = await client.experimental.get_task_result(task_id2, CallToolResult)
                assert isinstance(final2.content[0], TextContent)
                assert "Haiku:" in final2.content[0].text

                # Verify both callbacks were triggered
                assert elicitation_count == 1
                assert sampling_count == 1

                tg.cancel_scope.cancel()

    store.cleanup()
    queue.cleanup()
