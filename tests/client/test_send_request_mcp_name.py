"""`ClientSession.send_request` mirrors `Request.name_param` into the `Mcp-Name` header.

The modern stamp emits `Mcp-Name` for the core `NAME_BEARING_METHODS` table; the
`name_param` delta covers every other send path (vendor request types, the
legacy handshake stamp), keyed on header presence so the stamp's table rows
always win by ordering. The vendor sends below also pin the widened
`send_request` typing: a `Request[...]` subclass passes without a cast.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import anyio
import anyio.abc
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    Implementation,
    ListToolsResult,
    Request,
    ServerCapabilities,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from mcp.client.session import ClientSession
from mcp.shared.dispatcher import CallOptions, OnNotify, OnRequest
from mcp.shared.inbound import MCP_NAME_HEADER, MCP_PROTOCOL_VERSION_HEADER, encode_header_value


class _RecordingDispatcher:
    """Records `send_raw_request` opts and answers with canned per-method results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, CallOptions]] = []

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        task_status.started()
        await anyio.sleep_forever()

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, opts or {}))
        if method == "tools/call":
            return CallToolResult(content=[TextContent(type="text", text="ok")]).model_dump(
                by_alias=True, mode="json", exclude_none=True
            )
        if method == "tools/list":
            return ListToolsResult(tools=[Tool(name="my-tool", input_schema={"type": "object"})]).model_dump(
                by_alias=True, mode="json", exclude_none=True
            )
        return {}

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        raise NotImplementedError


class _GetWidgetParams(types.RequestParams):
    widget_id: str


class _GetWidgetRequest(Request[_GetWidgetParams, Literal["vendor/widgets/get"]]):
    method: Literal["vendor/widgets/get"] = "vendor/widgets/get"
    name_param = "widgetId"


class _RawWidgetRequest(Request[dict[str, Any], Literal["vendor/widgets/get"]]):
    """Same wire shape with untyped params, so tests can omit or mistype the name value."""

    method: Literal["vendor/widgets/get"] = "vendor/widgets/get"
    name_param = "widgetId"


class _ShadowCallToolRequest(Request[dict[str, Any], Literal["tools/call"]]):
    """A vendor type declaring `name_param` for a method the core table already covers."""

    method: Literal["tools/call"] = "tools/call"
    name_param = "customKey"


class _PlainVendorRequest(Request[dict[str, Any], Literal["vendor/widgets/list"]]):
    method: Literal["vendor/widgets/list"] = "vendor/widgets/list"


class _OptionalParamsWidgetRequest(Request[dict[str, Any] | None, Literal["vendor/widgets/get"]]):
    """Optional params, so a send can carry no params key at all."""

    method: Literal["vendor/widgets/get"] = "vendor/widgets/get"
    params: dict[str, Any] | None = None
    name_param = "widgetId"


def _adopt_modern(session: ClientSession) -> None:
    session.adopt(
        types.DiscoverResult(
            supported_versions=[LATEST_MODERN_VERSION],
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="stub", version="0"),
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


def _headers(opts: CallOptions) -> dict[str, str]:
    return opts.get("headers") or {}


@pytest.mark.anyio
async def test_vendor_name_param_emits_mcp_name_on_the_modern_path() -> None:
    """A vendor request type declaring `name_param` gets `Mcp-Name` on a modern
    wire even though its method is not in `NAME_BEARING_METHODS`."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_modern(session)
            await session.send_request(_GetWidgetRequest(params=_GetWidgetParams(widget_id="w-1")), types.EmptyResult)
    [(_, opts)] = dispatcher.calls
    assert _headers(opts)[MCP_NAME_HEADER] == "w-1"


@pytest.mark.anyio
async def test_vendor_name_param_emits_mcp_name_on_the_handshake_path() -> None:
    """The handshake stamp sets no `Mcp-Name` at all, so for a legacy wire the
    delta is the responsible emitter — emission is era-unconditional."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_handshake(session)
            await session.send_request(_GetWidgetRequest(params=_GetWidgetParams(widget_id="w-1")), types.EmptyResult)
    [(_, opts)] = dispatcher.calls
    assert _headers(opts)[MCP_NAME_HEADER] == "w-1"
    # The stamp's own headers survive the delta.
    assert _headers(opts)[MCP_PROTOCOL_VERSION_HEADER] == LATEST_HANDSHAKE_VERSION


@pytest.mark.anyio
async def test_name_value_passes_through_encode_header_value() -> None:
    """A name that cannot ride as a plain ASCII header value is base64-sentinel
    encoded (spec MUST for `Mcp-Name`)."""
    name = "wídget ✨"
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_handshake(session)
            await session.send_request(_GetWidgetRequest(params=_GetWidgetParams(widget_id=name)), types.EmptyResult)
    [(_, opts)] = dispatcher.calls
    assert _headers(opts)[MCP_NAME_HEADER] == encode_header_value(name)
    assert _headers(opts)[MCP_NAME_HEADER].startswith("=?base64?")


@pytest.mark.anyio
async def test_core_tools_call_header_comes_from_the_stamp_alone() -> None:
    """Core `tools/call` is unchanged: the modern stamp emits `Mcp-Name` from the
    table; `CallToolRequest` declares no `name_param`, and on a legacy wire core
    methods stay headerless exactly as today."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_modern(session)
            await session.call_tool("my-tool", {})
            _adopt_handshake(session)
            await session.call_tool("my-tool", {})
    (_, modern_opts), (_, legacy_opts) = (call for call in dispatcher.calls if call[0] == "tools/call")
    assert _headers(modern_opts)[MCP_NAME_HEADER] == "my-tool"
    assert MCP_NAME_HEADER not in _headers(legacy_opts)


@pytest.mark.anyio
async def test_stamp_table_rows_win_over_name_param_by_ordering() -> None:
    """Header-presence keying: when the modern stamp already emitted `Mcp-Name`
    from the core table, a `name_param` on the request type does not overwrite it."""
    dispatcher = _RecordingDispatcher()
    request = _ShadowCallToolRequest(params={"name": "real-tool", "customKey": "other-value"})
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_modern(session)
            await session.send_request(request, types.CallToolResult)
    [(_, opts)] = dispatcher.calls
    assert _headers(opts)[MCP_NAME_HEADER] == "real-tool"


@pytest.mark.anyio
async def test_vendor_name_param_emits_mcp_name_on_the_preconnect_path() -> None:
    """Emission is era-unconditional: a lowlevel caller that never adopts any
    version (the preconnect stamp) still gets `Mcp-Name` from `name_param`."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            await session.send_request(_GetWidgetRequest(params=_GetWidgetParams(widget_id="w-1")), types.EmptyResult)
    [(_, opts)] = dispatcher.calls
    assert _headers(opts) == {MCP_NAME_HEADER: "w-1"}  # and no era headers: nothing adopted


@pytest.mark.anyio
async def test_missing_name_value_fails_loud_naming_method_and_key() -> None:
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_handshake(session)
            with pytest.raises(ValueError) as exc_info:
                await session.send_request(_RawWidgetRequest(params={}), types.EmptyResult)
            assert dispatcher.calls == []  # raised before reaching the wire
    assert str(exc_info.value) == snapshot("vendor/widgets/get requires params['widgetId'] for Mcp-Name")


@pytest.mark.anyio
async def test_non_string_name_value_fails_loud() -> None:
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_handshake(session)
            with pytest.raises(ValueError) as exc_info:
                await session.send_request(_RawWidgetRequest(params={"widgetId": 7}), types.EmptyResult)
            assert dispatcher.calls == []
    assert str(exc_info.value) == snapshot("vendor/widgets/get requires params['widgetId'] for Mcp-Name")


@pytest.mark.anyio
async def test_absent_params_fails_loud_not_attribute_error() -> None:
    """`exclude_none` drops a None params entirely; the delta still answers with
    the documented ValueError, not an AttributeError on the missing key."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_handshake(session)
            with pytest.raises(ValueError) as exc_info:
                await session.send_request(_OptionalParamsWidgetRequest(), types.EmptyResult)
            assert dispatcher.calls == []
    assert str(exc_info.value) == snapshot("vendor/widgets/get requires params['widgetId'] for Mcp-Name")


@pytest.mark.anyio
async def test_request_without_name_param_sends_no_mcp_name() -> None:
    """No `name_param` and a method outside `NAME_BEARING_METHODS`: neither
    emitter produces an `Mcp-Name` header, on either era's stamp."""
    dispatcher = _RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            _adopt_modern(session)
            await session.send_request(_PlainVendorRequest(params={}), types.EmptyResult)
            _adopt_handshake(session)
            await session.send_ping()
    for _, opts in dispatcher.calls:
        assert MCP_NAME_HEADER not in _headers(opts)
