"""`ClientSession` result claims: construction validation, activation at modern
adopts only, claimed-result routing, the version-aware capability ad, and the
`allow_claimed` escape hatch."""

from collections.abc import Mapping
from typing import Any, Literal

import anyio
import anyio.abc
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CallToolResult,
    Implementation,
    InputRequiredResult,
    ListToolsResult,
    Result,
    ServerCapabilities,
    TextContent,
    Tool,
)
from mcp_types.methods import validate_server_result
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from pydantic import ValidationError
from typing_extensions import assert_type

from mcp.client.extension import ClaimContext, ResultClaim, UnexpectedClaimedResult
from mcp.client.session import ClientSession, _CallToolResultAdapter
from mcp.shared.dispatcher import CallOptions, OnNotify, OnNotifyIntercept, OnRequest

_TASKS_EXT = "com.example/tasks"
_AD_ONLY_EXT = "com.example/flags"


class _TaskResult(Result):
    """A claimed result shape, tagged `task`."""

    result_type: Literal["task"] = "task"
    task_id: str


async def _resolve_task(result: _TaskResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError  # session-tier tests never drive a resolver; that is the Client's job


def _task_claim(**kwargs: Any) -> ResultClaim[_TaskResult]:
    return ResultClaim(result_type="task", model=_TaskResult, resolve=_resolve_task, **kwargs)


_COMPLETE_TOOL_RESULT = CallToolResult(content=[TextContent(type="text", text="ok")]).model_dump(
    by_alias=True, mode="json", exclude_none=True
)
_CLAIMED_TASK_RESULT = {"resultType": "task", "taskId": "t-1"}
_TOOL_LISTING = ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})]).model_dump(
    by_alias=True, mode="json", exclude_none=True
)
_INITIALIZE_RESULT = types.InitializeResult(
    protocol_version=LATEST_HANDSHAKE_VERSION,
    capabilities=ServerCapabilities(),
    server_info=Implementation(name="stub", version="0"),
).model_dump(by_alias=True, mode="json", exclude_none=True)


class _RecordingDispatcher:
    """Records every send and answers each method with a canned result."""

    def __init__(self, tool_result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, CallOptions]] = []
        self.notifications: list[str] = []
        self._tool_result = tool_result if tool_result is not None else _COMPLETE_TOOL_RESULT

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        task_status.started()
        await anyio.sleep_forever()

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, opts or {}))
        if method == "tools/call":
            return self._tool_result
        if method == "tools/list":
            return _TOOL_LISTING
        if method == "initialize":
            return _INITIALIZE_RESULT
        return {}

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        self.notifications.append(method)


def _claims_session(dispatcher: _RecordingDispatcher, *claims: ResultClaim[Any]) -> ClientSession:
    return ClientSession(dispatcher=dispatcher, extensions={_TASKS_EXT: {}}, result_claims={_TASKS_EXT: list(claims)})


def _adopt_modern(session: ClientSession) -> None:
    session.adopt(
        types.DiscoverResult(
            supported_versions=[LATEST_MODERN_VERSION],
            capabilities=ServerCapabilities(),
        )
    )


def _adopt_handshake(session: ClientSession) -> None:
    session.adopt(
        types.InitializeResult(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="stub", version="0"),
        )
    )


def test_duplicate_claim_tag_across_extensions_rejected() -> None:
    """SDK-defined: two claims on the same resultType cannot be routed apart, so construction fails."""
    with pytest.raises(ValueError) as exc_info:
        ClientSession(
            dispatcher=_RecordingDispatcher(),
            extensions={_TASKS_EXT: {}, _AD_ONLY_EXT: {}},
            result_claims={_TASKS_EXT: [_task_claim()], _AD_ONLY_EXT: [_task_claim()]},
        )

    assert str(exc_info.value) == snapshot("duplicate result claim for resultType 'task'")


def test_claims_keyed_to_unadvertised_extension_rejected() -> None:
    """SDK-defined: a `result_claims` key with no `extensions` entry advertises nothing, so construction fails."""
    messages: list[str] = []
    for extensions in (None, {_AD_ONLY_EXT: {"flag": True}}):
        with pytest.raises(ValueError) as exc_info:
            ClientSession(
                dispatcher=_RecordingDispatcher(),
                extensions=extensions,
                result_claims={_TASKS_EXT: [_task_claim()]},
            )
        messages.append(str(exc_info.value))

    assert messages == snapshot(
        [
            "result_claims key 'com.example/tasks' has no extensions entry; a claim is only "
            "advertised through its extension's capability ad",
            "result_claims key 'com.example/tasks' has no extensions entry; a claim is only "
            "advertised through its extension's capability ad",
        ]
    )


def test_empty_claim_sequence_rejected() -> None:
    """SDK-defined: an empty claim list is rejected at construction; a claim-less extension omits the key."""
    with pytest.raises(ValueError) as exc_info:
        ClientSession(dispatcher=_RecordingDispatcher(), extensions={_TASKS_EXT: {}}, result_claims={_TASKS_EXT: []})

    assert str(exc_info.value) == snapshot(
        "result_claims['com.example/tasks'] is empty and would drop the extension from "
        "the capability ad at every version. Omit the key instead"
    )


def test_empty_settings_count_as_an_advertised_extension() -> None:
    """SDK-defined: empty settings ({}) still count as an ad, so claims keyed to the extension construct."""
    session = _claims_session(_RecordingDispatcher(), _task_claim())

    assert isinstance(session, ClientSession)


def test_without_claims_the_call_tool_adapter_is_the_module_constant() -> None:
    """SDK-defined: with zero active claims the session holds the module-level adapter by identity."""
    session = ClientSession(dispatcher=_RecordingDispatcher())

    assert session._call_tool_adapter is _CallToolResultAdapter
    _adopt_modern(session)
    assert session._call_tool_adapter is _CallToolResultAdapter
    _adopt_handshake(session)
    assert session._call_tool_adapter is _CallToolResultAdapter


@pytest.mark.anyio
@pytest.mark.parametrize("protocol_versions", [None, frozenset({LATEST_MODERN_VERSION})])
async def test_modern_adopt_activates_claims_and_routes_claimed_results(
    protocol_versions: frozenset[str] | None,
) -> None:
    """SDK-defined: at a modern adopt, a claim active at the negotiated version routes
    the claimed raw to the claim model."""
    dispatcher = _RecordingDispatcher(tool_result=_CLAIMED_TASK_RESULT)
    session = _claims_session(dispatcher, _task_claim(protocol_versions=protocol_versions))
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            result = await session.call_tool("t", {}, allow_claimed=True)

    assert isinstance(result, _TaskResult)
    assert result.task_id == "t-1"


@pytest.mark.anyio
async def test_legacy_adopt_clears_active_claims() -> None:
    """SDK-defined: a legacy adopt clears active claims and restores the module-level adapter."""
    dispatcher = _RecordingDispatcher(tool_result=_CLAIMED_TASK_RESULT)
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            assert isinstance(await session.call_tool("t", {}, allow_claimed=True), _TaskResult)

            _adopt_handshake(session)
            assert session._call_tool_adapter is _CallToolResultAdapter
            with pytest.raises(ValidationError):
                await session.call_tool("t", {}, allow_claimed=True)
            # Rejected at response parsing; the request did reach the wire.
            assert dispatcher.calls[-1][0] == "tools/call"


@pytest.mark.anyio
async def test_modern_readopt_after_legacy_reactivates_claims() -> None:
    """SDK-defined: a modern re-adopt after legacy reactivates the claims."""
    dispatcher = _RecordingDispatcher(tool_result=_CLAIMED_TASK_RESULT)
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            _adopt_handshake(session)
            assert session._call_tool_adapter is _CallToolResultAdapter

            _adopt_modern(session)
            result = await session.call_tool("t", {}, allow_claimed=True)

    assert isinstance(result, _TaskResult)
    assert session._call_tool_adapter is not _CallToolResultAdapter


@pytest.mark.anyio
async def test_legacy_initialize_ad_drops_claim_bearing_identifiers() -> None:
    """SDK-defined: the legacy initialize ad drops claim-bearing identifiers; ad-only ones ride along."""
    dispatcher = _RecordingDispatcher()
    session = ClientSession(
        dispatcher=dispatcher,
        extensions={_TASKS_EXT: {}, _AD_ONLY_EXT: {"flag": True}},
        result_claims={_TASKS_EXT: [_task_claim()]},
    )
    with anyio.fail_after(5):
        async with session:
            await session.initialize()

    [(_, params, _)] = [call for call in dispatcher.calls if call[0] == "initialize"]
    assert params is not None
    assert params["capabilities"]["extensions"] == {_AD_ONLY_EXT: {"flag": True}}


@pytest.mark.anyio
async def test_legacy_ad_omits_extensions_entirely_when_every_identifier_drops() -> None:
    """SDK-defined: when every identifier drops, the ad omits the `extensions` key entirely."""
    dispatcher = _RecordingDispatcher()
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            await session.initialize()

    [(_, params, _)] = [call for call in dispatcher.calls if call[0] == "initialize"]
    assert params is not None
    assert "extensions" not in params["capabilities"]


@pytest.mark.anyio
async def test_modern_adopt_ad_includes_active_claim_identifiers() -> None:
    """SDK-defined: the modern per-request `_meta` ad includes identifiers whose claims are active."""
    dispatcher = _RecordingDispatcher()
    session = ClientSession(
        dispatcher=dispatcher,
        extensions={_TASKS_EXT: {}, _AD_ONLY_EXT: {"flag": True}},
        result_claims={_TASKS_EXT: [_task_claim()]},
    )
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            await session.send_ping()

    [(_, params, _)] = dispatcher.calls
    assert params is not None
    capabilities = params["_meta"][CLIENT_CAPABILITIES_META_KEY]
    assert capabilities["extensions"] == {_TASKS_EXT: {}, _AD_ONLY_EXT: {"flag": True}}


@pytest.mark.anyio
async def test_discover_probe_ad_includes_claim_identifiers_at_the_probe_version() -> None:
    """SDK-defined: `send_discover` builds its `_meta` ad at the probe version, where claims are active."""
    dispatcher = _RecordingDispatcher()
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            await session.send_discover(LATEST_MODERN_VERSION)

    [(_, params, _)] = dispatcher.calls
    assert params is not None
    capabilities = params["_meta"][CLIENT_CAPABILITIES_META_KEY]
    assert capabilities["extensions"] == {_TASKS_EXT: {}}


@pytest.mark.anyio
async def test_discover_probe_ad_drops_claim_identifiers_at_a_legacy_probe_version() -> None:
    """SDK-defined: at a legacy probe version no claim can be active, so the identifier drops."""
    dispatcher = _RecordingDispatcher()
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            await session.send_discover(LATEST_HANDSHAKE_VERSION)

    [(_, params, _)] = dispatcher.calls
    assert params is not None
    capabilities = params["_meta"][CLIENT_CAPABILITIES_META_KEY]
    assert "extensions" not in capabilities


class _CoreTaggedResult(Result):
    """A claim whose wire tag collides with the adapter's internal routing sentinel."""

    result_type: Literal["core"] = "core"
    payload: str = ""


async def _resolve_core_tagged(result: _CoreTaggedResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError


@pytest.mark.anyio
async def test_claim_tagged_core_cannot_hijack_core_parsing() -> None:
    """SDK-defined: a claim may use "core" as its wire tag without colliding with core parsing."""
    claim = ResultClaim(result_type="core", model=_CoreTaggedResult, resolve=_resolve_core_tagged)
    dispatcher = _RecordingDispatcher(tool_result={"resultType": "core", "payload": "p-1"})
    session = ClientSession(dispatcher=dispatcher, extensions={_TASKS_EXT: {}}, result_claims={_TASKS_EXT: [claim]})
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            ordinary = session._call_tool_adapter.validate_python(_COMPLETE_TOOL_RESULT)
            claimed = await session.call_tool("t", {}, allow_claimed=True)

    assert isinstance(ordinary, CallToolResult)
    assert isinstance(claimed, _CoreTaggedResult)


@pytest.mark.anyio
@pytest.mark.parametrize("with_claims", [True, False])
async def test_unknown_result_type_fails_validation_with_and_without_claims(with_claims: bool) -> None:
    """SDK-defined: a resultType outside the active claim set fails core validation, claims or not."""
    raw = {"resultType": "weird", "taskId": "t-1"}
    dispatcher = _RecordingDispatcher(tool_result=raw)
    session = _claims_session(dispatcher, _task_claim()) if with_claims else ClientSession(dispatcher=dispatcher)
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            with pytest.raises(ValidationError):
                await session.call_tool("t", {}, allow_claimed=True)
            # Rejected at response parsing; the request did reach the wire.
            assert dispatcher.calls[-1][0] == "tools/call"


@pytest.mark.anyio
async def test_non_string_result_type_fails_core_validation_not_discrimination() -> None:
    """SDK-defined: a non-string resultType stays on the core arm and fails as ValidationError, not TypeError."""
    raw: dict[str, Any] = {"resultType": {"nested": True}}
    dispatcher = _RecordingDispatcher(tool_result=raw)
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            with pytest.raises(ValidationError):
                await session.call_tool("t", {}, allow_claimed=True)
            # Rejected at response parsing; the request did reach the wire.
            assert dispatcher.calls[-1][0] == "tools/call"


def test_adopt_built_adapter_revalidates_model_instances() -> None:
    """SDK-defined: the adopt-built adapter routes already-built model instances as well as raw dicts."""
    session = _claims_session(_RecordingDispatcher(), _task_claim())
    _adopt_modern(session)
    adapter = session._call_tool_adapter

    claimed = adapter.validate_python(_TaskResult(task_id="t-2"))
    assert isinstance(claimed, _TaskResult)
    core = adapter.validate_python(CallToolResult(content=[]))
    assert isinstance(core, CallToolResult)


@pytest.mark.anyio
async def test_input_required_routes_to_core_arm_with_claims_active() -> None:
    """Spec-mandated: `input_required` is core vocabulary; active claims leave that arm untouched."""
    raw = {"resultType": "input_required", "requestState": "s-1"}
    session = _claims_session(_RecordingDispatcher(tool_result=raw), _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            result = await session.call_tool("t", {}, allow_input_required=True, allow_claimed=True)

    assert isinstance(result, InputRequiredResult)
    assert result.request_state == "s-1"


@pytest.mark.anyio
async def test_claimed_result_raises_unexpected_claimed_result_by_default() -> None:
    """SDK-defined: without `allow_claimed` a claimed shape raises, carrying the parsed
    result so the caller can clean up any server-side state it references."""
    dispatcher = _RecordingDispatcher(tool_result=_CLAIMED_TASK_RESULT)
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            with pytest.raises(UnexpectedClaimedResult) as exc_info:
                await session.call_tool("t", {})
            # The shape parsed and then raised; the request did reach the wire.
            assert dispatcher.calls[-1][0] == "tools/call"

    assert isinstance(exc_info.value.result, _TaskResult)
    assert exc_info.value.result.task_id == "t-1"
    assert str(exc_info.value) == snapshot(
        "Server returned a claimed result (_TaskResult); pass the owning extension to "
        "Client(extensions=[...]) for transparent resolution, or call with allow_claimed=True "
        "and handle the shape. The carried result may reference server-side state needing cleanup."
    )


@pytest.mark.anyio
async def test_call_tool_result_path_identical_under_both_allow_claimed_values() -> None:
    """SDK-defined: `allow_claimed` only affects claimed shapes; ordinary results come back identical."""
    dispatcher = _RecordingDispatcher()
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            r_default = await session.call_tool("t", {})
            r_opted = await session.call_tool("t", {}, allow_claimed=True)

    assert isinstance(r_opted, CallToolResult)
    assert r_opted == r_default


@pytest.mark.anyio
async def test_call_tool_overload_matrix_narrows_statically() -> None:
    """SDK-defined: each flag combination narrows `call_tool` to its documented return union under pyright."""
    dispatcher = _RecordingDispatcher()
    session = _claims_session(dispatcher, _task_claim())
    with anyio.fail_after(5):
        async with session:
            _adopt_modern(session)
            r1 = await session.call_tool("t", {})
            assert_type(r1, CallToolResult)
            r2 = await session.call_tool("t", {}, allow_input_required=True)
            assert_type(r2, CallToolResult | InputRequiredResult)
            r3 = await session.call_tool("t", {}, allow_claimed=True)
            assert_type(r3, CallToolResult | Result)
            r4 = await session.call_tool("t", {}, allow_input_required=True, allow_claimed=True)
            assert_type(r4, CallToolResult | InputRequiredResult | Result)

    assert [type(r) for r in (r1, r2, r3, r4)] == [CallToolResult] * 4


def test_claimed_raw_passes_v2026_tools_call_surface_validation() -> None:
    """Pins the claim path's dependency: an unknown resultType passes `validate_server_result`
    at 2026-07-28; this failing is the signal that mcp-types tightened the surface."""
    validate_server_result("tools/call", LATEST_MODERN_VERSION, {"resultType": "task", "taskId": "t-1"})
