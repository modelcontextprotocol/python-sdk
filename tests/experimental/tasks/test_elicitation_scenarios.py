"""
Tests for the four elicitation scenarios with tasks.

This tests all combinations of tool call types and elicitation types:
1. Normal tool call + Normal elicitation (session.elicit)
2. Normal tool call + Task-augmented elicitation (session.experimental.elicit_as_task)
3. Task-augmented tool call + Normal elicitation (task.elicit)
4. Task-augmented tool call + Task-augmented elicitation (task.elicit_as_task)

And the same for sampling (create_message).
"""

from typing import Any

import anyio
import pytest
from anyio import Event

from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.context import RequestContext
from mcp.shared.experimental.tasks.helpers import is_terminal
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.message import SessionMessage
from mcp.types import (
    TASK_REQUIRED,
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateTaskResult,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    GetTaskPayloadResult,
    GetTaskResult,
    SamplingMessage,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
)


def create_client_task_handlers(
    client_task_store: InMemoryTaskStore,
    elicit_received: Event,
) -> ExperimentalTaskHandlers:
    """Create task handlers for client to handle task-augmented elicitation from server."""

    elicit_response = ElicitResult(action="accept", content={"confirm": True})
    task_complete_events: dict[str, Event] = {}

    async def handle_augmented_elicitation(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
        task_metadata: TaskMetadata,
    ) -> CreateTaskResult:
        """Handle task-augmented elicitation by creating a client-side task."""
        elicit_received.set()
        task = await client_task_store.create_task(task_metadata)
        task_complete_events[task.taskId] = Event()

        async def complete_task() -> None:
            # Store result before updating status to avoid race condition
            await client_task_store.store_result(task.taskId, elicit_response)
            await client_task_store.update_task(task.taskId, status="completed")
            task_complete_events[task.taskId].set()

        context.session._task_group.start_soon(complete_task)  # pyright: ignore[reportPrivateUsage]
        return CreateTaskResult(task=task)

    async def handle_get_task(
        context: RequestContext[ClientSession, Any],
        params: Any,
    ) -> GetTaskResult:
        """Handle tasks/get from server."""
        task = await client_task_store.get_task(params.taskId)
        assert task is not None, f"Task not found: {params.taskId}"
        return GetTaskResult(
            taskId=task.taskId,
            status=task.status,
            statusMessage=task.statusMessage,
            createdAt=task.createdAt,
            lastUpdatedAt=task.lastUpdatedAt,
            ttl=task.ttl,
            pollInterval=100,
        )

    async def handle_get_task_result(
        context: RequestContext[ClientSession, Any],
        params: Any,
    ) -> GetTaskPayloadResult | ErrorData:
        """Handle tasks/result from server."""
        event = task_complete_events.get(params.taskId)
        assert event is not None, f"No completion event for task: {params.taskId}"
        await event.wait()
        result = await client_task_store.get_result(params.taskId)
        assert result is not None, f"Result not found for task: {params.taskId}"
        return GetTaskPayloadResult.model_validate(result.model_dump(by_alias=True))

    return ExperimentalTaskHandlers(
        augmented_elicitation=handle_augmented_elicitation,
        get_task=handle_get_task,
        get_task_result=handle_get_task_result,
    )


def create_sampling_task_handlers(
    client_task_store: InMemoryTaskStore,
    sampling_received: Event,
) -> ExperimentalTaskHandlers:
    """Create task handlers for client to handle task-augmented sampling from server."""

    sampling_response = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="Hello from the model!"),
        model="test-model",
    )
    task_complete_events: dict[str, Event] = {}

    async def handle_augmented_sampling(
        context: RequestContext[ClientSession, Any],
        params: CreateMessageRequestParams,
        task_metadata: TaskMetadata,
    ) -> CreateTaskResult:
        """Handle task-augmented sampling by creating a client-side task."""
        sampling_received.set()
        task = await client_task_store.create_task(task_metadata)
        task_complete_events[task.taskId] = Event()

        async def complete_task() -> None:
            # Store result before updating status to avoid race condition
            await client_task_store.store_result(task.taskId, sampling_response)
            await client_task_store.update_task(task.taskId, status="completed")
            task_complete_events[task.taskId].set()

        context.session._task_group.start_soon(complete_task)  # pyright: ignore[reportPrivateUsage]
        return CreateTaskResult(task=task)

    async def handle_get_task(
        context: RequestContext[ClientSession, Any],
        params: Any,
    ) -> GetTaskResult:
        """Handle tasks/get from server."""
        task = await client_task_store.get_task(params.taskId)
        assert task is not None, f"Task not found: {params.taskId}"
        return GetTaskResult(
            taskId=task.taskId,
            status=task.status,
            statusMessage=task.statusMessage,
            createdAt=task.createdAt,
            lastUpdatedAt=task.lastUpdatedAt,
            ttl=task.ttl,
            pollInterval=100,
        )

    async def handle_get_task_result(
        context: RequestContext[ClientSession, Any],
        params: Any,
    ) -> GetTaskPayloadResult | ErrorData:
        """Handle tasks/result from server."""
        event = task_complete_events.get(params.taskId)
        assert event is not None, f"No completion event for task: {params.taskId}"
        await event.wait()
        result = await client_task_store.get_result(params.taskId)
        assert result is not None, f"Result not found for task: {params.taskId}"
        return GetTaskPayloadResult.model_validate(result.model_dump(by_alias=True))

    return ExperimentalTaskHandlers(
        augmented_sampling=handle_augmented_sampling,
        get_task=handle_get_task,
        get_task_result=handle_get_task_result,
    )


@pytest.mark.anyio
async def test_scenario1_normal_tool_normal_elicitation() -> None:
    """
    Scenario 1: Normal tool call with normal elicitation.

    Server calls session.elicit() directly, client responds immediately.
    """
    server = Server("test-scenario1")
    elicit_received = Event()
    tool_result: list[str] = []

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="confirm_action",
                description="Confirm an action",
                inputSchema={"type": "object"},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        ctx = server.request_context

        # Normal elicitation - expects immediate response
        result = await ctx.session.elicit(
            message="Please confirm the action",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}},
        )

        confirmed = result.content.get("confirm", False) if result.content else False
        tool_result.append("confirmed" if confirmed else "cancelled")
        return CallToolResult(content=[TextContent(type="text", text="confirmed" if confirmed else "cancelled")])

    # Elicitation callback for client
    async def elicitation_callback(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        elicit_received.set()
        return ElicitResult(action="accept", content={"confirm": True})

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            elicitation_callback=elicitation_callback,
        ) as client_session:
            await client_session.initialize()

            # Call tool normally (not as task)
            result = await client_session.call_tool("confirm_action", {})

            # Verify elicitation was received and tool completed
            assert elicit_received.is_set()
            assert len(result.content) > 0
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "confirmed"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert tool_result[0] == "confirmed"


@pytest.mark.anyio
async def test_scenario2_normal_tool_task_augmented_elicitation() -> None:
    """
    Scenario 2: Normal tool call with task-augmented elicitation.

    Server calls session.experimental.elicit_as_task(), client creates a task
    for the elicitation and returns CreateTaskResult. Server polls client.
    """
    server = Server("test-scenario2")
    elicit_received = Event()
    tool_result: list[str] = []

    # Client-side task store for handling task-augmented elicitation
    client_task_store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="confirm_action",
                description="Confirm an action",
                inputSchema={"type": "object"},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        ctx = server.request_context

        # Task-augmented elicitation - server polls client
        result = await ctx.session.experimental.elicit_as_task(
            message="Please confirm the action",
            requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}},
            ttl=60000,
        )

        confirmed = result.content.get("confirm", False) if result.content else False
        tool_result.append("confirmed" if confirmed else "cancelled")
        return CallToolResult(content=[TextContent(type="text", text="confirmed" if confirmed else "cancelled")])

    task_handlers = create_client_task_handlers(client_task_store, elicit_received)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as client_session:
            await client_session.initialize()

            # Call tool normally (not as task)
            result = await client_session.call_tool("confirm_action", {})

            # Verify elicitation was received and tool completed
            assert elicit_received.is_set()
            assert len(result.content) > 0
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "confirmed"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert tool_result[0] == "confirmed"
    client_task_store.cleanup()


@pytest.mark.anyio
async def test_scenario3_task_augmented_tool_normal_elicitation() -> None:
    """
    Scenario 3: Task-augmented tool call with normal elicitation.

    Client calls tool as task. Inside the task, server uses task.elicit()
    which queues the request and delivers via tasks/result.
    """
    server = Server("test-scenario3")
    server.experimental.enable_tasks()

    elicit_received = Event()
    work_completed = Event()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="confirm_action",
                description="Confirm an action",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            # Normal elicitation within task - queued and delivered via tasks/result
            result = await task.elicit(
                message="Please confirm the action",
                requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}},
            )

            confirmed = result.content.get("confirm", False) if result.content else False
            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text="confirmed" if confirmed else "cancelled")])

        return await ctx.experimental.run_task(work)

    # Elicitation callback for client
    async def elicitation_callback(
        context: RequestContext[ClientSession, Any],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        elicit_received.set()
        return ElicitResult(action="accept", content={"confirm": True})

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            elicitation_callback=elicitation_callback,
        ) as client_session:
            await client_session.initialize()

            # Call tool as task
            create_result = await client_session.experimental.call_tool_as_task("confirm_action", {})
            task_id = create_result.task.taskId
            assert create_result.task.status == "working"

            # Poll until input_required, then call tasks/result
            found_input_required = False
            async for status in client_session.experimental.poll_task(task_id):  # pragma: no branch
                if status.status == "input_required":  # pragma: no branch
                    found_input_required = True
                    break
            assert found_input_required, "Expected to see input_required status"

            # This will deliver the elicitation and get the response
            final_result = await client_session.experimental.get_task_result(task_id, CallToolResult)

            # Verify
            assert elicit_received.is_set()
            assert len(final_result.content) > 0
            assert isinstance(final_result.content[0], TextContent)
            assert final_result.content[0].text == "confirmed"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert work_completed.is_set()


@pytest.mark.anyio
async def test_scenario4_task_augmented_tool_task_augmented_elicitation() -> None:
    """
    Scenario 4: Task-augmented tool call with task-augmented elicitation.

    Client calls tool as task. Inside the task, server uses task.elicit_as_task()
    which sends task-augmented elicitation. Client creates its own task for the
    elicitation, and server polls the client.

    This tests the full bidirectional flow where:
    1. Client calls tasks/result on server (for tool task)
    2. Server delivers task-augmented elicitation through that stream
    3. Client creates its own task and returns CreateTaskResult
    4. Server polls the client's task while the client's tasks/result is still open
    5. Server gets the ElicitResult and completes the tool task
    6. Client's tasks/result returns with the CallToolResult
    """
    server = Server("test-scenario4")
    server.experimental.enable_tasks()

    elicit_received = Event()
    work_completed = Event()

    # Client-side task store for handling task-augmented elicitation
    client_task_store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="confirm_action",
                description="Confirm an action",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            # Task-augmented elicitation within task - server polls client
            result = await task.elicit_as_task(
                message="Please confirm the action",
                requestedSchema={"type": "object", "properties": {"confirm": {"type": "boolean"}}},
                ttl=60000,
            )

            confirmed = result.content.get("confirm", False) if result.content else False
            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text="confirmed" if confirmed else "cancelled")])

        return await ctx.experimental.run_task(work)

    task_handlers = create_client_task_handlers(client_task_store, elicit_received)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as client_session:
            await client_session.initialize()

            # Call tool as task
            create_result = await client_session.experimental.call_tool_as_task("confirm_action", {})
            task_id = create_result.task.taskId
            assert create_result.task.status == "working"

            # Poll until input_required or terminal, then call tasks/result
            found_expected_status = False
            async for status in client_session.experimental.poll_task(task_id):  # pragma: no branch
                if status.status == "input_required" or is_terminal(status.status):  # pragma: no branch
                    found_expected_status = True
                    break
            assert found_expected_status, "Expected to see input_required or terminal status"

            # This will deliver the task-augmented elicitation,
            # server will poll client, and eventually return the tool result
            final_result = await client_session.experimental.get_task_result(task_id, CallToolResult)

            # Verify
            assert elicit_received.is_set()
            assert len(final_result.content) > 0
            assert isinstance(final_result.content[0], TextContent)
            assert final_result.content[0].text == "confirmed"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert work_completed.is_set()
    client_task_store.cleanup()


@pytest.mark.anyio
async def test_scenario2_sampling_normal_tool_task_augmented_sampling() -> None:
    """
    Scenario 2 for sampling: Normal tool call with task-augmented sampling.

    Server calls session.experimental.create_message_as_task(), client creates
    a task for the sampling and returns CreateTaskResult. Server polls client.
    """
    server = Server("test-scenario2-sampling")
    sampling_received = Event()
    tool_result: list[str] = []

    # Client-side task store for handling task-augmented sampling
    client_task_store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="generate_text",
                description="Generate text using sampling",
                inputSchema={"type": "object"},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        ctx = server.request_context

        # Task-augmented sampling - server polls client
        result = await ctx.session.experimental.create_message_as_task(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
            max_tokens=100,
            ttl=60000,
        )

        assert isinstance(result.content, TextContent), "Expected TextContent response"
        response_text = result.content.text

        tool_result.append(response_text)
        return CallToolResult(content=[TextContent(type="text", text=response_text)])

    task_handlers = create_sampling_task_handlers(client_task_store, sampling_received)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as client_session:
            await client_session.initialize()

            # Call tool normally (not as task)
            result = await client_session.call_tool("generate_text", {})

            # Verify sampling was received and tool completed
            assert sampling_received.is_set()
            assert len(result.content) > 0
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Hello from the model!"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert tool_result[0] == "Hello from the model!"
    client_task_store.cleanup()


@pytest.mark.anyio
async def test_scenario4_sampling_task_augmented_tool_task_augmented_sampling() -> None:
    """
    Scenario 4 for sampling: Task-augmented tool call with task-augmented sampling.

    Client calls tool as task. Inside the task, server uses task.create_message_as_task()
    which sends task-augmented sampling. Client creates its own task for the sampling,
    and server polls the client.
    """
    server = Server("test-scenario4-sampling")
    server.experimental.enable_tasks()

    sampling_received = Event()
    work_completed = Event()

    # Client-side task store for handling task-augmented sampling
    client_task_store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="generate_text",
                description="Generate text using sampling",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            # Task-augmented sampling within task - server polls client
            result = await task.create_message_as_task(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
                max_tokens=100,
                ttl=60000,
            )

            assert isinstance(result.content, TextContent), "Expected TextContent response"
            response_text = result.content.text

            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text=response_text)])

        return await ctx.experimental.run_task(work)

    task_handlers = create_sampling_task_handlers(client_task_store, sampling_received)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as client_session:
            await client_session.initialize()

            # Call tool as task
            create_result = await client_session.experimental.call_tool_as_task("generate_text", {})
            task_id = create_result.task.taskId
            assert create_result.task.status == "working"

            # Poll until input_required or terminal
            found_expected_status = False
            async for status in client_session.experimental.poll_task(task_id):  # pragma: no branch
                if status.status == "input_required" or is_terminal(status.status):  # pragma: no branch
                    found_expected_status = True
                    break
            assert found_expected_status, "Expected to see input_required or terminal status"

            final_result = await client_session.experimental.get_task_result(task_id, CallToolResult)

            # Verify
            assert sampling_received.is_set()
            assert len(final_result.content) > 0
            assert isinstance(final_result.content[0], TextContent)
            assert final_result.content[0].text == "Hello from the model!"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    assert work_completed.is_set()
    client_task_store.cleanup()
