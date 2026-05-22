"""End-to-end tests for which clients can see and control a task.

Every test runs a real server and one or more in-memory client sessions. A
task started with run_task() belongs to the client session that started it:
that session can poll it, list it, and cancel it, while every other session
is told the task does not exist. Tasks whose IDs carry no session marker
(explicitly chosen IDs, or tasks on stateless servers) are usable by any
session that knows the ID, but are never listed.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any

import anyio
import pytest
from anyio.abc import TaskGroup

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.shared.message import SessionMessage
from mcp.types import (
    TASK_REQUIRED,
    CallToolResult,
    CreateTaskResult,
    ListTasksResult,
    TextContent,
    Tool,
    ToolExecution,
)

# The `connect` fixture: each call opens a new client session against the test server.
Connect = Callable[..., Awaitable[ClientSession]]

# Enough tasks that the bundled in-memory store needs more than one page (of 10)
# to list them, so listings that span store pages are exercised.
MORE_TASKS_THAN_ONE_STORE_PAGE = 11


def build_task_server(store: TaskStore | None = None) -> Server:
    """Build a server exposing three task tools.

    - "greet" finishes immediately and returns a greeting.
    - "long_running_job" keeps running until the server shuts down.
    - "nightly_export" is a singleton job: every invocation uses the
      explicitly chosen task ID "the-nightly-export".
    """
    server = Server("task-visibility-test-server")
    server.experimental.enable_tasks(store=store)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=name,
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
            for name in ("greet", "long_running_job", "nightly_export")
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        async def greet(task: ServerTaskContext) -> CallToolResult:
            return CallToolResult(content=[TextContent(type="text", text=f"Hello, {arguments['name']}!")])

        async def long_running_job(task: ServerTaskContext) -> CallToolResult:
            await anyio.sleep_forever()
            raise AssertionError("unreachable")  # pragma: no cover

        async def nightly_export(task: ServerTaskContext) -> CallToolResult:
            return CallToolResult(content=[TextContent(type="text", text="exported")])

        run_task = server.request_context.experimental.run_task
        if name == "nightly_export":
            return await run_task(nightly_export, task_id="the-nightly-export")
        return await run_task(greet if name == "greet" else long_running_job)

    return server


async def open_client(
    server: Server, task_group: TaskGroup, stack: AsyncExitStack, *, stateless: bool = False
) -> ClientSession:
    """Connect a new client session to `server` over in-memory streams."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
            stateless=stateless,
        )

    task_group.start_soon(run_server)
    client = await stack.enter_async_context(ClientSession(server_to_client_receive, client_to_server_send))
    await client.initialize()
    return client


@pytest.fixture
def task_server() -> Server:
    return build_task_server()


@pytest.fixture
async def connect(task_server: Server) -> AsyncIterator[Connect]:
    """A factory that opens a new client session against the test server on each call."""
    async with anyio.create_task_group() as task_group, AsyncExitStack() as stack:

        async def _connect(*, stateless: bool = False) -> ClientSession:
            return await open_client(task_server, task_group, stack, stateless=stateless)

        yield _connect
        task_group.cancel_scope.cancel()


async def start_task(client: ClientSession, tool: str = "long_running_job", **arguments: Any) -> str:
    """Start `tool` as a task and return the new task's ID."""
    result = await client.experimental.call_tool_as_task(tool, arguments)
    return result.task.taskId


async def wait_until_finished(client: ClientSession, task_id: str) -> None:
    """Poll the task until it reaches a terminal status."""
    with anyio.fail_after(5):
        async for _ in client.experimental.poll_task(task_id):
            pass


async def listed_task_ids(client: ClientSession) -> list[str]:
    """Return the IDs of every task the server lists for this client."""
    return [task.taskId for task in (await client.experimental.list_tasks()).tasks]


# --- What the client that started a task can do with it ---


@pytest.mark.anyio
async def test_a_client_can_poll_its_own_task_to_completion_and_read_the_result(connect: Connect) -> None:
    client = await connect()
    task_id = await start_task(client, "greet", name="Ada")
    await wait_until_finished(client, task_id)

    result = await client.experimental.get_task_result(task_id, CallToolResult)

    assert result.content == [TextContent(type="text", text="Hello, Ada!")]


@pytest.mark.anyio
async def test_a_client_sees_its_own_task_when_listing_tasks(connect: Connect) -> None:
    client = await connect()
    task_id = await start_task(client)

    listed = await listed_task_ids(client)

    assert listed == [task_id]


@pytest.mark.anyio
async def test_a_client_can_cancel_its_own_task(connect: Connect) -> None:
    client = await connect()
    task_id = await start_task(client)

    cancelled = await client.experimental.cancel_task(task_id)

    assert cancelled.status == "cancelled"


# --- What a client cannot do with a task started by another client ---


@pytest.mark.anyio
async def test_a_client_cannot_get_the_status_of_another_clients_task(connect: Connect) -> None:
    creator = await connect()
    other_client = await connect()
    task_id = await start_task(creator)

    with pytest.raises(McpError, match="Task not found"):
        await other_client.experimental.get_task(task_id)


@pytest.mark.anyio
async def test_a_client_cannot_get_the_result_of_another_clients_task(connect: Connect) -> None:
    creator = await connect()
    other_client = await connect()
    task_id = await start_task(creator, "greet", name="Ada")
    await wait_until_finished(creator, task_id)

    with pytest.raises(McpError, match="Task not found"):
        await other_client.experimental.get_task_result(task_id, CallToolResult)


@pytest.mark.anyio
async def test_a_client_cannot_cancel_another_clients_task(connect: Connect) -> None:
    creator = await connect()
    other_client = await connect()
    task_id = await start_task(creator)

    with pytest.raises(McpError, match="Task not found"):
        await other_client.experimental.cancel_task(task_id)

    # The task is unaffected.
    assert (await creator.experimental.get_task(task_id)).status == "working"


@pytest.mark.anyio
async def test_a_client_does_not_see_another_clients_task_when_listing_tasks(connect: Connect) -> None:
    creator = await connect()
    other_client = await connect()
    await start_task(creator)

    listed = await listed_task_ids(other_client)

    assert listed == []


@pytest.mark.anyio
async def test_each_client_lists_only_its_own_tasks(connect: Connect) -> None:
    first_client = await connect()
    second_client = await connect()
    first_task = await start_task(first_client)
    second_task = await start_task(second_client)

    assert await listed_task_ids(first_client) == [first_task]
    assert await listed_task_ids(second_client) == [second_task]


@pytest.mark.anyio
async def test_listing_tasks_reveals_nothing_about_other_clients_tasks_however_many_there_are(
    connect: Connect,
) -> None:
    """The listing must not identify other clients' tasks through any field, including the pagination cursor."""
    creator = await connect()
    other_client = await connect()
    for _ in range(MORE_TASKS_THAN_ONE_STORE_PAGE):
        await start_task(creator)

    listing = await other_client.experimental.list_tasks()

    assert listing == ListTasksResult(tasks=[], nextCursor=None)


@pytest.mark.anyio
async def test_a_client_with_more_than_one_store_page_of_tasks_lists_all_of_them(connect: Connect) -> None:
    client = await connect()
    started = {await start_task(client) for _ in range(MORE_TASKS_THAN_ONE_STORE_PAGE)}

    listing = await client.experimental.list_tasks()

    assert {task.taskId for task in listing.tasks} == started
    assert listing.nextCursor is None


# --- Tasks that do not belong to any client session ---


@pytest.mark.anyio
# Choosing the task ID instead of letting the SDK generate one is deprecated for
# exactly the behaviour this test demonstrates: the task is not tied to the
# session that created it.
@pytest.mark.filterwarnings("ignore:Passing an explicit task_id")
async def test_a_task_whose_id_was_chosen_by_the_server_is_accessible_to_every_client(connect: Connect) -> None:
    creator = await connect()
    other_client = await connect()
    await wait_until_finished(creator, await start_task(creator, "nightly_export"))

    status = await other_client.experimental.get_task("the-nightly-export")

    assert status.status == "completed"


@pytest.mark.anyio
async def test_a_stateless_server_serves_a_task_to_any_session_that_knows_its_id(connect: Connect) -> None:
    first_session = await connect(stateless=True)
    second_session = await connect(stateless=True)
    task_id = await start_task(first_session, "greet", name="Ada")
    await wait_until_finished(second_session, task_id)

    result = await second_session.experimental.get_task_result(task_id, CallToolResult)

    assert result.content == [TextContent(type="text", text="Hello, Ada!")]


@pytest.mark.anyio
async def test_a_stateless_server_lists_no_tasks(connect: Connect) -> None:
    session = await connect(stateless=True)
    await start_task(session)

    listed = await listed_task_ids(session)

    assert listed == []


# --- The behaviour does not depend on the bundled in-memory store ---


@pytest.mark.anyio
async def test_clients_are_isolated_when_the_server_uses_a_custom_task_store() -> None:
    class CustomTaskStore(InMemoryTaskStore):
        """A stand-in for a user-provided TaskStore implementation."""

    server = build_task_server(store=CustomTaskStore())

    async with anyio.create_task_group() as task_group, AsyncExitStack() as stack:
        creator = await open_client(server, task_group, stack)
        other_client = await open_client(server, task_group, stack)
        task_id = await start_task(creator)

        with pytest.raises(McpError, match="Task not found"):
            await other_client.experimental.get_task(task_id)

        assert (await creator.experimental.get_task(task_id)).status == "working"
        task_group.cancel_scope.cancel()
