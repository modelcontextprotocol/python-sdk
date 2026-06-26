"""End-to-end tests for the Tasks extension (`io.modelcontextprotocol/tasks`, SEP-2133).

Tasks is a reference implementation of the *interceptive* half of the extension API: a
task-augmented `tools/call` runs the tool, records the result under a task id, and stamps that
id into `_meta[RELATED_TASK_META_KEY]`; the `tasks/*` methods then poll status and fetch the
payload. The lifecycle verbs are vendor methods, so they go through the `client.session`
escape hatch (`Client` only exposes spec verbs). A fixed `clock` makes timestamps deterministic.
"""

from typing import Any, cast

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS, CallToolResult, TextContent

from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import RELATED_TASK_META_KEY, Tasks
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio

FIXED_NOW = "2026-01-01T00:00:00Z"


def _server() -> MCPServer:
    mcp = MCPServer("demo", extensions=[Tasks(clock=lambda: FIXED_NOW)])

    @mcp.tool()
    def greet(name: str) -> str:
        return f"hi {name}"

    @mcp.tool()
    def boom() -> str:
        raise ValueError("kaboom")

    return mcp


def _call_tool_request(name: str, arguments: dict[str, Any], task: types.TaskMetadata | None) -> types.ClientRequest:
    request = types.CallToolRequest(params=types.CallToolRequestParams(name=name, arguments=arguments, task=task))
    return cast("types.ClientRequest", request)


async def test_plain_tool_call_carries_no_related_task_meta() -> None:
    """A `tools/call` with no `task` field passes through the interceptor untouched: SDK-defined."""
    async with Client(_server()) as client:
        result = await client.call_tool("greet", {"name": "ada"})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="hi ada")],
            structured_content={"result": "hi ada"},
        )
    )
    assert result.meta is None


async def test_task_augmented_call_runs_tool_and_stamps_task_id() -> None:
    """A task-augmented `tools/call` runs the tool and returns its result with the new task id
    stamped into `_meta[RELATED_TASK_META_KEY]`: SDK-defined."""
    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        result = await client.session.send_request(request, CallToolResult)

    assert result.content == snapshot([TextContent(text="hi ada")])
    assert result.meta == snapshot({RELATED_TASK_META_KEY: {"taskId": "task-1"}})


async def test_tasks_get_reports_completed_status_and_injected_clock() -> None:
    """`tasks/get` returns the task as `completed` with timestamps from the injected clock: SDK-defined."""
    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        get_request = cast(
            "types.ClientRequest", types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=task_id))
        )
        task = await client.session.send_request(get_request, types.GetTaskResult)

    assert task == snapshot(
        types.GetTaskResult(
            task_id="task-1",
            status="completed",
            created_at=FIXED_NOW,
            last_updated_at=FIXED_NOW,
            ttl=60,
        )
    )


async def test_tasks_get_uses_default_clock_when_none_injected() -> None:
    """A `Tasks()` with no injected clock stamps the default `_fixed_clock` epoch timestamp: SDK-defined."""
    mcp = MCPServer("demo", extensions=[Tasks()])

    @mcp.tool()
    def greet(name: str) -> str:
        return f"hi {name}"

    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(mcp) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        get_request = cast(
            "types.ClientRequest", types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=task_id))
        )
        task = await client.session.send_request(get_request, types.GetTaskResult)

    assert task == snapshot(
        types.GetTaskResult(
            task_id="task-1",
            status="completed",
            created_at="1970-01-01T00:00:00Z",
            last_updated_at="1970-01-01T00:00:00Z",
            ttl=60,
        )
    )


async def test_tasks_result_returns_stored_tool_payload() -> None:
    """`tasks/result` returns the tool's stored payload, without the related-task `_meta` stamp: SDK-defined."""
    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        result_request = cast(
            "types.ClientRequest",
            types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(task_id=task_id)),
        )
        payload = await client.session.send_request(result_request, CallToolResult)

    assert payload == snapshot(
        CallToolResult(
            content=[TextContent(text="hi ada")],
            structured_content={"result": "hi ada"},
        )
    )
    assert payload.meta is None


async def test_tasks_list_returns_created_task() -> None:
    """`tasks/list` returns the tasks recorded by task-augmented calls: SDK-defined."""
    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        await client.session.send_request(request, CallToolResult)

        list_request = cast("types.ClientRequest", types.ListTasksRequest(params=types.PaginatedRequestParams()))
        listing = await client.session.send_request(list_request, types.ListTasksResult)

    assert listing == snapshot(
        types.ListTasksResult(
            tasks=[
                types.Task(
                    task_id="task-1",
                    status="completed",
                    created_at=FIXED_NOW,
                    last_updated_at=FIXED_NOW,
                    ttl=60,
                )
            ]
        )
    )


async def test_tasks_cancel_sets_cancelled_status() -> None:
    """`tasks/cancel` transitions the task to `cancelled`: SDK-defined."""
    request = _call_tool_request("greet", {"name": "ada"}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        cancel_request = cast(
            "types.ClientRequest", types.CancelTaskRequest(params=types.CancelTaskRequestParams(task_id=task_id))
        )
        cancelled = await client.session.send_request(cancel_request, types.CancelTaskResult)

    assert cancelled == snapshot(
        types.CancelTaskResult(
            task_id="task-1",
            status="cancelled",
            created_at=FIXED_NOW,
            last_updated_at=FIXED_NOW,
            ttl=60,
        )
    )


async def test_failing_task_augmented_call_marks_task_failed() -> None:
    """A task-augmented call to a tool that raises returns `is_error` and records the task as `failed`,
    so a later `tasks/get` reports `failed`: SDK-defined."""
    request = _call_tool_request("boom", {}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        get_request = cast(
            "types.ClientRequest", types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=task_id))
        )
        task = await client.session.send_request(get_request, types.GetTaskResult)

    assert created.is_error is True
    assert created.meta == snapshot({RELATED_TASK_META_KEY: {"taskId": "task-1"}})
    assert task == snapshot(
        types.GetTaskResult(
            task_id="task-1",
            status="failed",
            created_at=FIXED_NOW,
            last_updated_at=FIXED_NOW,
            ttl=60,
        )
    )


async def test_tasks_result_on_failed_task_raises_invalid_params() -> None:
    """`tasks/result` for a task that exists but stored no payload (a failed task) raises INVALID_PARAMS.

    SDK-defined.
    """
    request = _call_tool_request("boom", {}, types.TaskMetadata(ttl=60))

    async with Client(_server()) as client:
        created = await client.session.send_request(request, CallToolResult)
        assert created.meta is not None
        task_id = created.meta[RELATED_TASK_META_KEY]["taskId"]

        result_request = cast(
            "types.ClientRequest",
            types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(task_id=task_id)),
        )
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(result_request, CallToolResult)

    assert exc_info.value.code == INVALID_PARAMS


_UNKNOWN_TASK_ID = "does-not-exist"

_UNKNOWN_ID_CASES: list[tuple[types.ClientRequest, type[types.Result]]] = [
    (
        cast("types.ClientRequest", types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=_UNKNOWN_TASK_ID))),
        types.GetTaskResult,
    ),
    (
        cast(
            "types.ClientRequest",
            types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(task_id=_UNKNOWN_TASK_ID)),
        ),
        CallToolResult,
    ),
    (
        cast(
            "types.ClientRequest",
            types.CancelTaskRequest(params=types.CancelTaskRequestParams(task_id=_UNKNOWN_TASK_ID)),
        ),
        types.CancelTaskResult,
    ),
]


@pytest.mark.parametrize(
    ("request_", "result_type"), _UNKNOWN_ID_CASES, ids=["tasks/get", "tasks/result", "tasks/cancel"]
)
async def test_unknown_task_id_raises_invalid_params(
    request_: types.ClientRequest, result_type: type[types.Result]
) -> None:
    """`tasks/get`, `tasks/result`, and `tasks/cancel` reject an unknown task id with INVALID_PARAMS: SDK-defined."""
    async with Client(_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request_, result_type)

    assert exc_info.value.code == INVALID_PARAMS
