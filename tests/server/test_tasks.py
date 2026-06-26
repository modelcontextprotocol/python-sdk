"""Tests for the SEP-2663 Tasks extension (`io.modelcontextprotocol/tasks`).

These drive the conformant core in `mcp.server.tasks` end-to-end through an
in-memory `Client`. `Client` exposes only spec verbs, so task-augmented calls and
the `tasks/*` methods go through `client.session.send_request`; `CreateTaskResult`
and `DetailedTask` have non-spec shapes, so the raw wire dict is read with a
permissive `dict` result type. Determinism comes from an injected fixed `clock`;
task ids are random `task_<token>` bearer capabilities, so they are captured and
reused for identity rather than snapshotted.
"""

from typing import Literal, cast

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS, METHOD_NOT_FOUND, Result
from pydantic import BaseModel, TypeAdapter

from mcp.client import advertise
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import (
    EXTENSION_ID,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CancelTaskRequestParams,
    GetTaskRequestParams,
    Tasks,
)
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio

_RAW: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])


async def _send_raw(client: Client, request: BaseModel) -> dict[str, object]:
    """Read the raw wire dict for a non-spec `tasks/*` shape (bypasses the typed result model)."""
    result_type = cast("type[Result]", _RAW)
    result = await client.session.send_request(cast("types.ClientRequest", request), result_type)
    return cast("dict[str, object]", result)


class _GetTaskRequest(types.Request[GetTaskRequestParams, Literal["tasks/get"]]):
    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


class _CancelTaskRequest(types.Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class _TasksResultRequest(types.Request[GetTaskRequestParams, Literal["tasks/result"]]):
    method: Literal["tasks/result"] = "tasks/result"
    params: GetTaskRequestParams


def _tasks_server(*, default_ttl_ms: int | None = None) -> MCPServer:
    """A server exposing `echo` under the Tasks extension with a fixed clock."""
    tasks = Tasks(clock=lambda: "2026-01-01T00:00:00Z", default_ttl_ms=default_ttl_ms)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    return mcp


def _call_echo() -> types.CallToolRequest:
    return types.CallToolRequest(params=types.CallToolRequestParams(name="echo", arguments={"text": "hi"}))


async def _augmented_call(client: Client) -> dict[str, object]:
    return await _send_raw(client, _call_echo())


async def _get_task(client: Client, task_id: str) -> dict[str, object]:
    return await _send_raw(client, _GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)))


async def _cancel_task(client: Client, task_id: str) -> dict[str, object]:
    return await _send_raw(client, _CancelTaskRequest(params=CancelTaskRequestParams(task_id=task_id)))


async def test_tasks_capability_advertised_under_extensions_on_modern_path() -> None:
    """SEP-2663: the Tasks extension rides `server/discover`, so a `mode='auto'` client
    sees `EXTENSION_ID` under `server_capabilities.extensions`."""
    async with Client(_tasks_server(), mode="auto", extensions=[advertise(EXTENSION_ID)]) as client:
        assert client.server_capabilities.extensions == snapshot({"io.modelcontextprotocol/tasks": {}})


async def test_tasks_capability_dropped_on_legacy_handshake() -> None:
    """Pinned gap: the 2025 `ServerCapabilities` wire schema has no `extensions` field,
    so a `mode='legacy'` handshake cannot carry the Tasks capability even though the
    modern `auto` path does."""
    async with Client(_tasks_server(), mode="legacy", extensions=[advertise(EXTENSION_ID)]) as client:
        assert client.server_capabilities.extensions is None


async def test_augmented_tools_call_returns_create_task_result_for_declaring_client() -> None:
    """SEP-2663: the server decides augmentation; a declaring client's `tools/call`
    returns a flat `Result & Task` envelope discriminated by `resultType: "task"`,
    observed as `completed` because the tool runs inline (documented core scope)."""
    captured: list[str] = []
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])

    assert created == snapshot(
        {
            "resultType": "task",
            "taskId": captured[0],
            "status": "completed",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
        }
    )


async def test_create_task_result_carries_ttl_when_configured() -> None:
    """SEP-2663: a server with a default TTL stamps `ttlMs` on the `CreateTaskResult`."""
    captured: list[str] = []
    async with Client(_tasks_server(default_ttl_ms=60000), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])

    assert created == snapshot(
        {
            "resultType": "task",
            "taskId": captured[0],
            "status": "completed",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
            "ttlMs": 60000,
        }
    )


async def test_create_task_result_uses_default_clock_when_none_injected() -> None:
    """SDK-defined: with no `clock` injected, `Tasks` falls back to its fixed default clock,
    stamping the SDK's epoch sentinel timestamps on the task."""
    tasks = Tasks()
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    captured: list[str] = []
    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])

    assert created == snapshot(
        {
            "resultType": "task",
            "taskId": captured[0],
            "status": "completed",
            "createdAt": "1970-01-01T00:00:00Z",
            "lastUpdatedAt": "1970-01-01T00:00:00Z",
        }
    )


async def test_plain_tools_call_is_untouched_for_non_declaring_client() -> None:
    """SEP-2663: the server never augments a client that did not declare the extension;
    a plain `call_tool` returns the ordinary `CallToolResult` with no task `_meta`."""
    async with Client(_tasks_server()) as client:
        result = await client.call_tool("echo", {"text": "x"})

    assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="x")]))
    assert result.meta is None


async def test_get_task_inlines_completed_call_tool_result_without_related_task_meta() -> None:
    """SEP-2663: `tasks/get` returns a `DetailedTask` (`resultType: "complete"`); a
    completed task inlines the original `CallToolResult`, which must NOT carry an
    `io.modelcontextprotocol/related-task` `_meta` key."""
    captured: list[str] = []
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])
        detailed = await _get_task(client, created["taskId"])

    assert detailed == snapshot(
        {
            "taskId": captured[0],
            "status": "completed",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
            "resultType": "complete",
            "result": {
                "content": [{"text": "hi", "type": "text"}],
                "isError": False,
                "resultType": "complete",
            },
        }
    )
    inlined = detailed["result"]
    assert isinstance(inlined, dict)
    assert "_meta" not in inlined


async def test_cancel_task_returns_empty_ack_and_marks_task_cancelled() -> None:
    """SEP-2663: `tasks/cancel` is an empty acknowledgement (`resultType: "complete"`),
    and a subsequent `tasks/get` reports the task as `cancelled`."""
    captured: list[str] = []
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])
        ack = await _cancel_task(client, created["taskId"])
        after = await _get_task(client, created["taskId"])

    assert ack == snapshot({"resultType": "complete"})
    assert after == snapshot(
        {
            "taskId": captured[0],
            "status": "cancelled",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
            "resultType": "complete",
        }
    )


async def test_tasks_result_method_is_method_not_found() -> None:
    """SEP-2663 core scope: `tasks/result` is not part of the conformant core, so it is
    rejected with METHOD_NOT_FOUND."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        task_id = created["taskId"]
        assert isinstance(task_id, str)
        with pytest.raises(MCPError) as exc_info:
            await _send_raw(client, _TasksResultRequest(params=GetTaskRequestParams(task_id=task_id)))

    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_tasks_get_from_non_declaring_client_is_missing_required_capability() -> None:
    """SEP-2663: a `tasks/*` call from a client that did not declare the extension is
    rejected with -32003, carrying the required-capabilities data."""
    async with Client(_tasks_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_anything")

    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == snapshot(
        {"requiredCapabilities": {"extensions": {"io.modelcontextprotocol/tasks": {}}}}
    )


async def test_get_unknown_task_id_is_invalid_params() -> None:
    """SEP-2663: a declaring client requesting an unknown `taskId` gets INVALID_PARAMS."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_does_not_exist")

    assert exc_info.value.code == INVALID_PARAMS


async def test_cancel_unknown_task_id_is_invalid_params() -> None:
    """SEP-2663: a declaring client cancelling an unknown `taskId` gets INVALID_PARAMS."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        with pytest.raises(MCPError) as exc_info:
            await _cancel_task(client, "task_does_not_exist")

    assert exc_info.value.code == INVALID_PARAMS


async def test_task_ids_are_prefixed_and_unique_per_creation() -> None:
    """SEP-2663 security: task ids are unguessable bearer capabilities, so each creation
    yields a distinct `task_`-prefixed id."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        first = await _augmented_call(client)
        second = await _augmented_call(client)

    assert isinstance(first["taskId"], str)
    assert isinstance(second["taskId"], str)
    assert first["taskId"].startswith("task_")
    assert second["taskId"].startswith("task_")
    assert first["taskId"] != second["taskId"]


async def test_legacy_connection_is_not_augmented_even_when_client_declares_tasks() -> None:
    """SEP-2663: the extension is modern-only. On a legacy handshake the server cannot
    carry `capabilities.extensions` back, so it must not augment - a `tools/call`
    returns a normal `CallToolResult`, never a `CreateTaskResult`."""
    async with Client(_tasks_server(), mode="legacy", extensions=[advertise(EXTENSION_ID)]) as client:
        result = await client.call_tool("echo", {"text": "hi"})

    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "hi"
    assert result.meta is None
