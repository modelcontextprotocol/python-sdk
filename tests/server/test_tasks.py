"""Tests for the SEP-2663 Tasks extension (`io.modelcontextprotocol/tasks`).

These drive `mcp.server.tasks` end-to-end through an in-memory `Client`. `Client`
exposes only spec verbs, so task-augmented calls and the `tasks/*` methods go
through `client.session.send_request`; `CreateTaskResult` and the `tasks/get`
envelope have non-spec shapes, so the raw wire dict is read with a permissive
`dict` result type. Determinism comes from an injected fixed `clock`; task ids
are random `task_<token>` bearer capabilities, so they are captured and reused
for identity rather than snapshotted.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Literal, cast

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    EmptyResult,
    Result,
)
from pydantic import BaseModel, TypeAdapter

from mcp.client import advertise
from mcp.client.client import Client
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import (
    EXTENSION_ID,
    CancelTaskRequestParams,
    CreateTaskResult,
    GetTaskRequestParams,
    InMemoryTaskStore,
    Task,
    TaskRecord,
    Tasks,
    TaskStore,
    UpdateTaskRequestParams,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.tasks import CancelTaskRequest, GetTaskRequest, GetTaskResult, UpdateTaskRequest

pytestmark = pytest.mark.anyio

_RAW: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])

_FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _send_raw(client: Client, request: BaseModel) -> dict[str, object]:
    """Read the raw wire dict for a non-spec `tasks/*` shape (bypasses the typed result model)."""
    result_type = cast("type[Result]", _RAW)
    result = await client.session.send_request(cast("types.ClientRequest", request), result_type)
    return cast("dict[str, object]", result)


class _TasksResultRequest(types.Request[GetTaskRequestParams, Literal["tasks/result"]]):
    method: Literal["tasks/result"] = "tasks/result"
    params: GetTaskRequestParams


class _UpdateTaskWithoutResponsesRequest(types.Request[GetTaskRequestParams, Literal["tasks/update"]]):
    """`tasks/update` carrying only `taskId` -- the wire-required `inputResponses` is absent."""

    method: Literal["tasks/update"] = "tasks/update"
    params: GetTaskRequestParams


def _tasks_server(
    *,
    default_ttl_ms: int | None = None,
    store: TaskStore | None = None,
    extra_extensions: list[Extension] | None = None,
) -> MCPServer:
    """A server exposing `echo` under the Tasks extension with a fixed clock."""
    tasks = Tasks(clock=lambda: _FIXED_NOW, default_ttl_ms=default_ttl_ms, store=store)
    mcp = MCPServer("demo", extensions=[tasks, *(extra_extensions or [])])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    return mcp


def _call_echo() -> types.CallToolRequest:
    return types.CallToolRequest(params=types.CallToolRequestParams(name="echo", arguments={"text": "hi"}))


def _call_echo_with_legacy_task_field() -> types.CallToolRequest:
    """`tools/call` carrying the legacy 2025 `params.task` field (still shipped in `mcp_types`)."""
    return types.CallToolRequest(
        params=types.CallToolRequestParams(name="echo", arguments={"text": "x"}, task=types.TaskMetadata(ttl=60000))
    )


async def _augmented_call(client: Client) -> dict[str, object]:
    return await _send_raw(client, _call_echo())


async def _get_task(client: Client, task_id: str) -> dict[str, object]:
    return await _send_raw(client, GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)))


async def _cancel_task(client: Client, task_id: str) -> dict[str, object]:
    return await _send_raw(client, CancelTaskRequest(params=CancelTaskRequestParams(task_id=task_id)))


async def _update_task(client: Client, task_id: str, responses: dict[str, Any] | None = None) -> dict[str, object]:
    params = UpdateTaskRequestParams(task_id=task_id, input_responses=responses or {})
    return await _send_raw(client, UpdateTaskRequest(params=params))


class _ShortCircuit(Extension):
    """Test double registered INSIDE Tasks: short-circuits `tools/call` with canned outcomes.

    Registered after `Tasks` in `extensions=[...]`, so it runs inside the Tasks
    interceptor and its returns are exactly what `call_next` hands back to it.
    `CALL_THROUGH` falls through to the real tool.
    """

    identifier = "test.example/short-circuit"

    CALL_THROUGH = object()

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes

    async def intercept_tool_call(
        self, params: Any, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        outcome = self._outcomes.pop(0)
        if outcome is self.CALL_THROUGH:
            return await call_next(ctx)
        return cast("HandlerResult", outcome)


class _RecordingStore:
    """`TaskStore` double that records every `put` and serves `get` from an inner store."""

    def __init__(self) -> None:
        self.puts: list[TaskRecord] = []
        self._inner = InMemoryTaskStore(clock=lambda: _FIXED_NOW)

    async def put(self, record: TaskRecord) -> None:
        self.puts.append(record)
        await self._inner.put(record)

    async def get(self, task_id: str) -> TaskRecord | None:
        return await self._inner.get(task_id)


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
    observed as `completed` because the tool runs inline (SEP-2663 allows any seed
    status). `ttlMs` is required-but-nullable, so it is present even when null."""
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
            "ttlMs": None,
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


async def test_default_clock_stamps_real_utc_wallclock() -> None:
    """SDK-defined: with no `clock` injected, `Tasks` stamps the current UTC time in
    RFC 3339 `Z` form on the wire."""
    mcp = MCPServer("demo", extensions=[Tasks()])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    before = datetime.now(timezone.utc).replace(microsecond=0)
    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
    after = datetime.now(timezone.utc)

    created_at = created["createdAt"]
    assert isinstance(created_at, str)
    assert created_at.endswith("Z")
    stamped = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert before <= stamped <= after
    assert created["lastUpdatedAt"] == created_at


async def test_plain_tools_call_is_untouched_for_non_declaring_client() -> None:
    """SEP-2663: the server never augments a client that did not declare the extension;
    a plain `call_tool` returns the ordinary `CallToolResult` with no task `_meta`."""
    async with Client(_tasks_server()) as client:
        result = await client.call_tool("echo", {"text": "x"})

    assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="x")]))
    assert result.meta is None


async def test_legacy_params_task_field_is_not_the_opt_in_for_a_non_declaring_client() -> None:
    """SEP-2663: servers MUST ignore the legacy `params.task` field (treat it as
    unknown) rather than using it as the opt-in -- a non-declaring client sending it
    still gets a plain `CallToolResult` and no task is recorded."""
    recording = _RecordingStore()
    async with Client(_tasks_server(store=recording)) as client:
        raw = await _send_raw(client, _call_echo_with_legacy_task_field())

    assert "taskId" not in raw
    assert raw["content"] == [{"text": "x", "type": "text"}]
    assert recording.puts == []


async def test_legacy_params_task_field_changes_nothing_for_a_declaring_client() -> None:
    """SEP-2663: augmentation is the server's decision either way -- a declaring client
    sending the legacy `params.task` field gets the same `CreateTaskResult` envelope
    as one that omits it."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        raw = await _send_raw(client, _call_echo_with_legacy_task_field())

    assert raw["resultType"] == "task"


async def test_client_declaring_only_another_extension_is_not_augmented() -> None:
    """SEP-2663: declaring some other extension is not declaring Tasks -- the
    `tools/call` stays a plain `CallToolResult` and `tasks/*` is still rejected with
    the missing-capability error."""
    async with Client(_tasks_server(), extensions=[advertise("com.example/other")]) as client:
        result = await client.call_tool("echo", {"text": "x"})
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_anything")

    assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="x")]))
    assert result.meta is None
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY


async def test_request_without_client_info_is_never_augmented() -> None:
    """SDK-defined: a modern request with no client info (`session.client_params` is
    None, e.g. an envelope-less stateless request) passes through un-augmented."""
    ctx = ServerRequestContext(
        session=cast("Any", SimpleNamespace(client_params=None)),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
        params={"name": "echo", "arguments": {"text": "x"}},
    )
    sentinel = {"resultType": "complete", "content": [{"text": "x", "type": "text"}], "isError": False}

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return sentinel

    params = types.CallToolRequestParams(name="echo", arguments={"text": "x"})
    result = await Tasks(clock=lambda: _FIXED_NOW).intercept_tool_call(params, ctx, call_next)

    assert result is sentinel


async def test_augment_predicate_scopes_augmentation_per_request() -> None:
    """SEP-2663: `Tasks(augment=...)` is the server deciding "at its own discretion and
    on a per-request basis" -- the declaring client's excluded call returns a plain
    `CallToolResult` (no task recorded), while its included call still returns a task."""
    recording = _RecordingStore()
    tasks = Tasks(augment=lambda p: p.name in {"slow"}, clock=lambda: _FIXED_NOW, store=recording)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def fast(text: str) -> str:
        return text

    @mcp.tool(structured_output=False)
    def slow(text: str) -> str:
        return text

    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        plain = await client.call_tool("fast", {"text": "x"})
        assert recording.puts == []
        augmented = await _send_raw(
            client, types.CallToolRequest(params=types.CallToolRequestParams(name="slow", arguments={"text": "x"}))
        )

    assert plain == snapshot(types.CallToolResult(content=[types.TextContent(text="x")]))
    assert plain.meta is None
    assert augmented["resultType"] == "task"
    assert len(recording.puts) == 1


async def test_augment_predicate_false_lets_errors_propagate() -> None:
    """SDK-defined: an `augment`-excluded call behaves exactly as for a non-declaring
    client, errors included -- the JSON-RPC error propagates and no task is recorded."""
    recording = _RecordingStore()
    tasks = Tasks(augment=lambda p: False, clock=lambda: _FIXED_NOW, store=recording)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def rejecting() -> str:
        raise MCPError(code=INVALID_PARAMS, message="bad input")

    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("rejecting", {})

    assert exc_info.value.code == INVALID_PARAMS
    assert recording.puts == []


async def test_get_task_inlines_completed_call_tool_result_without_related_task_meta() -> None:
    """SEP-2663: `tasks/get` returns the task (`resultType: "complete"`) inlining the
    original `CallToolResult`, which must NOT carry an
    `io.modelcontextprotocol/related-task` `_meta` key (that is the 2025 design)."""
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
            "ttlMs": None,
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


async def test_tool_error_result_is_a_completed_task_with_is_error_inlined() -> None:
    """SEP-2663: a tool result with `isError: true` is a `completed` task, not `failed`
    (`failed` is reserved for JSON-RPC errors)."""
    tasks = Tasks(clock=lambda: _FIXED_NOW)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def boom() -> str:
        raise ValueError("nope")

    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _send_raw(
            client, types.CallToolRequest(params=types.CallToolRequestParams(name="boom", arguments={}))
        )
        assert created["status"] == "completed"
        assert isinstance(created["taskId"], str)
        detailed = await _get_task(client, created["taskId"])

    inlined = detailed["result"]
    assert isinstance(inlined, dict)
    assert inlined["isError"] is True


async def test_mcp_error_from_tool_records_failed_task_for_declaring_client() -> None:
    """SEP-2663: a JSON-RPC error during an augmented call is a `failed` task -- the
    declaring client gets a failed `CreateTaskResult` instead of the error, and
    `tasks/get` inlines the JSON-RPC error (code/message/data) with NO `result` key.
    Cancelling the failed task is still the empty-ack no-op (terminal is absorbing)."""
    recording = _RecordingStore()
    tasks = Tasks(clock=lambda: _FIXED_NOW, store=recording)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def rejecting() -> str:
        raise MCPError(code=INVALID_PARAMS, message="bad input", data={"field": "text"})

    captured: list[str] = []
    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _send_raw(
            client, types.CallToolRequest(params=types.CallToolRequestParams(name="rejecting", arguments={}))
        )
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])
        detailed = await _get_task(client, created["taskId"])
        ack = await _cancel_task(client, created["taskId"])
        after = await _get_task(client, created["taskId"])

    assert created == snapshot(
        {
            "resultType": "task",
            "taskId": captured[0],
            "status": "failed",
            "statusMessage": "bad input",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
            "ttlMs": None,
        }
    )
    assert detailed == snapshot(
        {
            "taskId": captured[0],
            "status": "failed",
            "statusMessage": "bad input",
            "createdAt": "2026-01-01T00:00:00Z",
            "lastUpdatedAt": "2026-01-01T00:00:00Z",
            "ttlMs": None,
            "resultType": "complete",
            "error": {"code": -32602, "message": "bad input", "data": {"field": "text"}},
        }
    )
    assert "result" not in detailed
    assert len(recording.puts) == 1
    assert ack == snapshot({"resultType": "complete"})
    assert after["status"] == "failed"


async def test_error_data_from_nested_extension_records_failed_task() -> None:
    """SDK-defined: an extension nested inside Tasks may return `ErrorData` instead of
    raising (the runner's middleware error channel); under augmentation it is folded
    into the same arm as a raise -- a `failed` task, not a JSON-RPC error response."""
    recording = _RecordingStore()
    short_circuit = _ShortCircuit([types.ErrorData(code=INTERNAL_ERROR, message="boom")])
    server = _tasks_server(store=recording, extra_extensions=[short_circuit])

    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        detailed = await _get_task(client, created["taskId"])

    assert created["status"] == "failed"
    assert detailed["error"] == snapshot({"code": -32603, "message": "boom"})
    assert "result" not in detailed
    assert len(recording.puts) == 1


async def test_mcp_error_still_propagates_for_non_declaring_client() -> None:
    """SEP-2663: failed-task recording is an augmentation behaviour -- the same tool's
    JSON-RPC error reaches a non-declaring client untouched, and no task is recorded."""
    recording = _RecordingStore()
    tasks = Tasks(clock=lambda: _FIXED_NOW, store=recording)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def rejecting() -> str:
        raise MCPError(code=INVALID_PARAMS, message="bad input")

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("rejecting", {})

    assert exc_info.value.code == INVALID_PARAMS
    assert recording.puts == []


async def test_get_task_result_parses_completed_and_failed_wire_shapes() -> None:
    """SDK-defined: `GetTaskResult` is the lenient client-side parse model for
    `tasks/get` -- it parses the real wire dict of both terminal shapes, carrying
    `result` for `completed` and `error` for `failed`, never both."""
    tasks = Tasks(clock=lambda: _FIXED_NOW)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    @mcp.tool(structured_output=False)
    def rejecting() -> str:
        raise MCPError(code=INVALID_PARAMS, message="bad input")

    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        ok = await _augmented_call(client)
        bad = await _send_raw(
            client, types.CallToolRequest(params=types.CallToolRequestParams(name="rejecting", arguments={}))
        )
        assert isinstance(ok["taskId"], str)
        assert isinstance(bad["taskId"], str)
        completed = GetTaskResult.model_validate(await _get_task(client, ok["taskId"]))
        failed = GetTaskResult.model_validate(await _get_task(client, bad["taskId"]))

    assert completed.status == "completed"
    assert completed.result_type == "complete"
    assert completed.result is not None
    assert completed.result["content"] == [{"text": "hi", "type": "text"}]
    assert completed.error is None
    assert failed.status == "failed"
    assert failed.status_message == "bad input"
    assert failed.error == {"code": INVALID_PARAMS, "message": "bad input"}
    assert failed.result is None
    assert failed.ttl_ms is None


async def test_input_required_interim_passes_through_and_only_the_completing_leg_mints_a_task() -> None:
    """SEP-2663: MRTR exchanges resolve on the original `tools/call` before task
    creation, so an `input_required` interim is passed through un-augmented and only
    the leg that produces the final result becomes a task -- one task per logical call."""
    interim: dict[str, Any] = {
        "resultType": "input_required",
        "inputRequests": {
            "demo:confirm": {
                "method": "elicitation/create",
                "params": {"message": "Proceed?", "requestedSchema": {"type": "object", "properties": {}}},
            }
        },
        "requestState": "s1",
    }
    recording = _RecordingStore()
    short_circuit = _ShortCircuit([interim, _ShortCircuit.CALL_THROUGH])
    server = _tasks_server(store=recording, extra_extensions=[short_circuit])

    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as client:
        first = await _augmented_call(client)
        second = await _augmented_call(client)

    # The RequestStateBoundary (#3032) seals the interim's requestState on the way
    # out; everything else passes through byte-identical.
    sealed_state = first.pop("requestState")
    assert isinstance(sealed_state, str) and sealed_state != "s1"
    assert first == {k: v for k, v in interim.items() if k != "requestState"}
    assert second["resultType"] == "task"
    assert len(recording.puts) == 1


async def test_interceptor_normalizes_model_and_none_outcomes_from_nested_extensions() -> None:
    """SDK-defined: an extension nested inside Tasks may short-circuit with a model or
    `None`; the stored result is the wire dict the chain would have emitted ({} for
    `None`)."""
    store = InMemoryTaskStore(clock=lambda: _FIXED_NOW)
    short_circuit = _ShortCircuit([EmptyResult(result_type="complete"), None])
    server = _tasks_server(store=store, extra_extensions=[short_circuit])

    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as client:
        from_model = await _augmented_call(client)
        from_none = await _augmented_call(client)
        assert isinstance(from_model["taskId"], str)
        assert isinstance(from_none["taskId"], str)
        model_detailed = await _get_task(client, from_model["taskId"])
        none_detailed = await _get_task(client, from_none["taskId"])

    assert model_detailed["result"] == {"resultType": "complete"}
    assert none_detailed["result"] == {}


async def test_cancel_acks_empty_and_completed_task_keeps_its_status_and_result() -> None:
    """SEP-2663: `tasks/cancel` is an empty acknowledgement (`resultType: "complete"`),
    and cancellation may never take effect -- a task that already completed keeps its
    terminal status and its result stays retrievable."""
    captured: list[str] = []
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        captured.append(created["taskId"])
        ack = await _cancel_task(client, created["taskId"])
        after = await _get_task(client, created["taskId"])

    assert ack == snapshot({"resultType": "complete"})
    assert after["status"] == "completed"
    inlined = after["result"]
    assert isinstance(inlined, dict)
    assert inlined["content"] == [{"text": "hi", "type": "text"}]


async def test_update_acks_empty_and_ignores_input_responses_for_unissued_keys() -> None:
    """SEP-2663: `tasks/update` acknowledges with an empty result; `inputResponses`
    mapped to keys that were never issued are ignored rather than rejected."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        ack = await _update_task(client, created["taskId"], {"never-issued": {"value": 1}})
        after = await _get_task(client, created["taskId"])

    assert ack == snapshot({"resultType": "complete"})
    assert after["status"] == "completed"


async def test_update_without_input_responses_is_invalid_params() -> None:
    """SEP-2663: `UpdateTaskRequest.inputResponses` is required on the wire, so a
    `tasks/update` whose params carry only `taskId` is rejected with INVALID_PARAMS."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        task_id = created["taskId"]
        assert isinstance(task_id, str)
        with pytest.raises(MCPError) as exc_info:
            await _send_raw(client, _UpdateTaskWithoutResponsesRequest(params=GetTaskRequestParams(task_id=task_id)))

    assert exc_info.value.code == INVALID_PARAMS


async def test_tasks_result_method_is_method_not_found() -> None:
    """SEP-2663 removed `tasks/result`; it is not bound, so it is rejected with
    METHOD_NOT_FOUND."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        task_id = created["taskId"]
        assert isinstance(task_id, str)
        with pytest.raises(MCPError) as exc_info:
            await _send_raw(client, _TasksResultRequest(params=GetTaskRequestParams(task_id=task_id)))

    assert exc_info.value.code == METHOD_NOT_FOUND


@pytest.mark.parametrize("method", ["get", "update", "cancel"])
async def test_tasks_methods_from_non_declaring_client_are_missing_required_capability(method: str) -> None:
    """SEP-2663: every `tasks/*` call from a modern client that did not declare the
    extension is rejected with `-32021`, carrying the required-capabilities data."""
    senders = {"get": _get_task, "cancel": _cancel_task, "update": _update_task}
    async with Client(_tasks_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await senders[method](client, "task_anything")

    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == snapshot(
        {"requiredCapabilities": {"extensions": {"io.modelcontextprotocol/tasks": {}}}}
    )


@pytest.mark.parametrize("method", ["get", "update", "cancel"])
async def test_tasks_methods_on_legacy_connection_are_method_not_found(method: str) -> None:
    """SEP-2663 is not defined under 2025-11-25, so the bindings are version-scoped:
    a legacy client gets METHOD_NOT_FOUND, never a capability error it could not
    satisfy on that wire."""
    senders = {"get": _get_task, "cancel": _cancel_task, "update": _update_task}
    async with Client(_tasks_server(), mode="legacy", extensions=[advertise(EXTENSION_ID)]) as client:
        with pytest.raises(MCPError) as exc_info:
            await senders[method](client, "task_anything")

    assert exc_info.value.code == METHOD_NOT_FOUND


@pytest.mark.parametrize("sender", [_get_task, _cancel_task, _update_task])
async def test_unknown_task_id_is_invalid_params(sender: Callable[[Client, str], Awaitable[dict[str, object]]]) -> None:
    """SEP-2663: a declaring client naming an unknown `taskId` gets INVALID_PARAMS."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        with pytest.raises(MCPError) as exc_info:
            await sender(client, "task_does_not_exist")

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


async def test_task_id_is_a_bearer_capability_across_connections() -> None:
    """SDK-defined: task ids are bearer capabilities -- a new declaring connection
    presenting a captured id can fetch a completed task it did not create (the modern
    wire has no sessions, so a reconnecting client must be able to poll)."""
    server = _tasks_server()
    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as creator:
        created = await _augmented_call(creator)
        task_id = created["taskId"]
        assert isinstance(task_id, str)

    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as reconnected:
        detailed = await _get_task(reconnected, task_id)

    assert detailed["status"] == "completed"
    inlined = detailed["result"]
    assert isinstance(inlined, dict)
    assert inlined["content"] == [{"text": "hi", "type": "text"}]


async def test_legacy_connection_is_not_augmented_even_when_client_declares_tasks() -> None:
    """SEP-2663: the extension is modern-only. On a legacy handshake the server cannot
    carry `capabilities.extensions` back, so it must not augment - a `tools/call`
    returns a normal `CallToolResult`, never a `CreateTaskResult`."""
    async with Client(_tasks_server(), mode="legacy", extensions=[advertise(EXTENSION_ID)]) as client:
        result = await client.call_tool("echo", {"text": "hi"})

    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "hi"
    assert result.meta is None


def _ticking_server(current: dict[str, datetime], *, store: InMemoryTaskStore) -> MCPServer:
    """A tasks server whose extension and store share one settable clock."""
    tasks = Tasks(clock=lambda: current["now"], default_ttl_ms=60_000, store=store)
    mcp = MCPServer("demo", extensions=[tasks])

    @mcp.tool(structured_output=False)
    def echo(text: str) -> str:
        return text

    return mcp


async def test_expired_task_is_unknown_on_get() -> None:
    """SEP-2663: `ttlMs` is enforced -- once the TTL elapses the task is unknown
    (INVALID_PARAMS), dropped by the store on access."""
    current = {"now": _FIXED_NOW}
    store = InMemoryTaskStore(clock=lambda: current["now"])

    async with Client(_ticking_server(current, store=store), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        before = await _get_task(client, created["taskId"])
        assert before["status"] == "completed"
        current["now"] = _FIXED_NOW + timedelta(milliseconds=60_000)
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, created["taskId"])

    assert exc_info.value.code == INVALID_PARAMS
    assert store._records == {}  # pyright: ignore[reportPrivateUsage]


async def test_put_sweeps_expired_records_so_the_store_stays_bounded() -> None:
    """SDK-defined: inserting a new task drops records whose TTL has elapsed, while a
    TTL-less record survives both the sweep and drop-on-access -- the in-memory store
    retains exactly the live tasks."""
    current = {"now": _FIXED_NOW}
    store = InMemoryTaskStore(clock=lambda: current["now"])
    stamp = "2026-01-01T00:00:00Z"
    no_ttl = Task(task_id="task_no_ttl", status="completed", created_at=stamp, last_updated_at=stamp)
    await store.put(TaskRecord(task=no_ttl, result={}, error=None, expires_at=None))

    async with Client(_ticking_server(current, store=store), extensions=[advertise(EXTENSION_ID)]) as client:
        first = await _augmented_call(client)
        assert isinstance(first["taskId"], str)
        current["now"] = _FIXED_NOW + timedelta(milliseconds=60_000)
        second = await _augmented_call(client)
        assert isinstance(second["taskId"], str)

    assert set(store._records) == {second["taskId"], "task_no_ttl"}  # pyright: ignore[reportPrivateUsage]
    assert await store.get("task_no_ttl") is not None


async def test_get_responses_do_not_alias_the_stored_record() -> None:
    """SDK-defined: mutating a served `tasks/get` response must not corrupt the stored
    result."""
    async with Client(_tasks_server(), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        first = await _get_task(client, created["taskId"])
        inlined = first["result"]
        assert isinstance(inlined, dict)
        inlined["content"] = [{"text": "TAMPERED", "type": "text"}]
        inlined["injected"] = True
        second = await _get_task(client, created["taskId"])

    fresh = second["result"]
    assert isinstance(fresh, dict)
    assert fresh["content"] == [{"text": "hi", "type": "text"}]
    assert "injected" not in fresh


async def test_stored_records_do_not_alias_the_chain_result_dict() -> None:
    """SDK-defined: results are deep-copied at the put boundary too -- a nested
    extension mutating the dict it short-circuited with must not corrupt the stored
    result served by `tasks/get`."""
    retained: dict[str, Any] = {"resultType": "complete", "content": [{"text": "hi", "type": "text"}]}
    server = _tasks_server(extra_extensions=[_ShortCircuit([retained])])

    async with Client(server, extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        retained["content"] = [{"text": "TAMPERED", "type": "text"}]
        retained["injected"] = True
        detailed = await _get_task(client, created["taskId"])

    served = detailed["result"]
    assert isinstance(served, dict)
    assert served["content"] == [{"text": "hi", "type": "text"}]
    assert "injected" not in served


async def test_custom_store_receives_puts_and_serves_gets() -> None:
    """SDK-defined: `Tasks(store=...)` is the persistence seam: the extension writes
    and reads through whatever store the operator supplies."""
    recording = _RecordingStore()
    async with Client(_tasks_server(store=recording), extensions=[advertise(EXTENSION_ID)]) as client:
        created = await _augmented_call(client)
        assert isinstance(created["taskId"], str)
        detailed = await _get_task(client, created["taskId"])

    assert len(recording.puts) == 1
    assert recording.puts[0].task.task_id == created["taskId"]
    assert detailed["status"] == "completed"


def test_ttl_ms_survives_exclude_none_in_both_alias_and_snake_dumps() -> None:
    """SDK-defined: the `ttlMs` wrap serializer reinstates a null TTL under
    `exclude_none` in both spellings -- `ttlMs` for wire dumps, `ttl_ms` for plain
    `model_dump()` on the public models."""
    result = CreateTaskResult(task_id="t", status="completed", created_at="x", last_updated_at="x")

    assert result.model_dump(exclude_none=True) == snapshot(
        {
            "result_type": "task",
            "task_id": "t",
            "status": "completed",
            "created_at": "x",
            "last_updated_at": "x",
            "ttl_ms": None,
        }
    )
    assert result.model_dump(by_alias=True, exclude_none=True)["ttlMs"] is None


@pytest.mark.parametrize("bad_ttl", [0, -5])
def test_non_positive_default_ttl_is_rejected_at_construction(bad_ttl: int) -> None:
    """SDK-defined: a zero or negative TTL would advertise a nonsensical `ttlMs` on the
    wire, so construction rejects it."""
    with pytest.raises(ValueError):
        Tasks(default_ttl_ms=bad_ttl)
