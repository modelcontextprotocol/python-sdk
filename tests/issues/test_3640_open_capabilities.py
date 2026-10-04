"""Open capability keys survive discovery. Regression for python-sdk #3640.

`ServerCapabilities` and `ClientCapabilities` are not closed sets. Unknown keys
such as a draft `events` object, and a different self-hosted key, round-trip
through the public models and the `server/discover` / `initialize` sieve.
Known fields stay validated. Nested known capability objects stay closed.
Names that belong only to another schema era still drop (`tasks` on
2026-07-28, `extensions` on earlier versions). This does not register Events
methods.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types as types
import pytest
from mcp_types import methods
from mcp_types.version import LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS
from pydantic import ValidationError

from mcp import Client, MCPError
from mcp.server import NotificationOptions, Server, ServerRequestContext
from mcp.server.connection import Connection
from mcp.server.runner import serve_one
from mcp.shared.dispatcher import CallOptions
from mcp.shared.message import MessageMetadata
from mcp.shared.transport_context import TransportContext
from tests.interaction._connect import base_headers, mounted_app

pytestmark = pytest.mark.anyio

_HOOKS = "com.example/hooks"
_HOOKS_VALUE: dict[str, Any] = {"version": 1, "nested": {"enabled": True, "label": None}, "ids": [1, None]}
_EVENTS_VALUE: dict[str, Any] = {"listChanged": False}


def _discover_body(**capabilities: Any) -> dict[str, Any]:
    return {
        "supportedVersions": ["2026-07-28"],
        "capabilities": dict(capabilities),
        "resultType": "complete",
        "ttlMs": 0,
        "cacheScope": "private",
    }


def _initialize_body(**capabilities: Any) -> dict[str, Any]:
    return {
        "protocolVersion": "2025-11-25",
        "capabilities": dict(capabilities),
        "serverInfo": {"name": "s", "version": "1"},
    }


class _AdvertisingServer(Server[Any]):
    """Low-level server whose capability ad carries two unknown keys."""

    def get_capabilities(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
        *,
        protocol_version: str | None = None,
    ) -> types.ServerCapabilities:
        base = super().get_capabilities(
            notification_options,
            experimental_capabilities,
            extensions,
            protocol_version=protocol_version,
        )
        payload = base.model_dump(by_alias=True, exclude_none=True)
        payload["events"] = dict(_EVENTS_VALUE)
        payload[_HOOKS] = json.loads(json.dumps(_HOOKS_VALUE))
        return types.ServerCapabilities.model_validate(payload)


def _advertising_server() -> _AdvertisingServer:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        del ctx, params
        return types.ListToolsResult(tools=[])

    server = _AdvertisingServer("cap-host", version="1.2.3", on_list_tools=list_tools)
    server.extensions = {"io.modelcontextprotocol/ui": {}}
    return server


def _modern_headers(method: str) -> dict[str, str]:
    return base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION, "mcp-method": method}


def _meta_envelope() -> dict[str, object]:
    return {
        types.PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
        types.CLIENT_INFO_META_KEY: {"name": "raw", "version": "0"},
        types.CLIENT_CAPABILITIES_META_KEY: {},
    }


@dataclass
class _StubDispatchContext:
    """Minimal dispatch context for one `serve_one` call. Discover never sends."""

    request_id: int | str | None = 1
    transport: TransportContext = field(default_factory=lambda: TransportContext(kind="direct", can_send_request=False))
    message_metadata: MessageMetadata = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)
    can_send_request: bool = False

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        del method, params, opts
        raise NotImplementedError

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        del method, params, opts
        raise NotImplementedError

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        del progress, total, message
        raise NotImplementedError


def test_reporter_model_dump_keeps_events_and_known_aliases() -> None:
    """The #3640 snippet: `ServerCapabilities(tools={}, events={})` keeps `events`.

    `listChanged` still serializes under its wire alias. A second unknown key is
    not special-cased as `events`.
    """
    kwargs: dict[str, Any] = {"tools": {}, "events": {}}
    caps = types.ServerCapabilities(**kwargs)
    assert caps.model_dump(by_alias=True, exclude_none=True) == {"tools": {}, "events": {}}
    aliased = types.ServerCapabilities(tools=types.ToolsCapability(list_changed=True))
    assert aliased.model_dump(by_alias=True, exclude_none=True) == {"tools": {"listChanged": True}}
    assert aliased.tools is not None and aliased.tools.list_changed is True


def test_null_unknown_keys_are_omitted_and_nested_nulls_stay() -> None:
    """Null and omitted unknown keys both leave the dump, matching known optionals.

    A null inside an unknown capability object is data, not a model field, so it
    stays. A null `listChanged` is omitted and the empty `tools` object remains.
    """
    parsed = types.ServerCapabilities.model_validate(
        {
            "tools": {"listChanged": None},
            "logging": None,
            "events": None,
            _HOOKS: _HOOKS_VALUE,
        }
    )
    assert parsed.model_dump(by_alias=True, exclude_none=True) == {"tools": {}, _HOOKS: _HOOKS_VALUE}
    absent = types.ServerCapabilities(tools=types.ToolsCapability())
    assert "events" not in absent.model_dump(by_alias=True, exclude_none=True)
    assert absent.logging is None


def test_discover_sieve_keeps_unknown_keys_and_drops_cross_era_tasks() -> None:
    """2026-07-28 `server/discover` keeps unknown capability keys and drops `tasks`.

    `tasks` is a 2025-11-25 field. `extensions` belongs on this era and stays.
    An unknown key inside `tools` is still sieved. The caller's dict is not mutated.
    """
    capabilities: dict[str, Any] = {
        "tools": {"listChanged": True, "extraFlag": 1},
        "events": dict(_EVENTS_VALUE),
        _HOOKS: json.loads(json.dumps(_HOOKS_VALUE)),
        "tasks": {"list": {}},
        "extensions": {"io.modelcontextprotocol/ui": {}},
        "logging": None,
    }
    original = json.loads(json.dumps({"capabilities": capabilities}))
    sieved = methods.serialize_server_result("server/discover", "2026-07-28", _discover_body(**capabilities))
    assert sieved["capabilities"] == {
        "tools": {"listChanged": True},
        "events": _EVENTS_VALUE,
        _HOOKS: _HOOKS_VALUE,
        "extensions": {"io.modelcontextprotocol/ui": {}},
    }
    assert original["capabilities"]["tasks"] == {"list": {}}
    wire = json.dumps(sieved, sort_keys=True).encode()
    assert b'"events"' in wire and b'"com.example/hooks"' in wire and b'"tasks"' not in wire
    assert b'"extraFlag"' not in wire


def test_initialize_sieve_keeps_unknown_keys_and_drops_extensions_before_2026() -> None:
    """Handshake-era `initialize` keeps unknown keys and still drops `extensions`.

    The same rule holds at the oldest surfaced version, 2024-11-05, which shares
    the 2025-11-25 capability schema. `tasks` is in that schema and stays.
    """
    capabilities: dict[str, Any] = {
        "tools": {"listChanged": False, "extraFlag": 1},
        "events": {},
        _HOOKS: {"version": 1},
        "extensions": {"io.modelcontextprotocol/ui": {}},
        "tasks": {"list": {}},
    }
    for version in ("2024-11-05", "2025-11-25"):
        body = _initialize_body(**capabilities)
        body["protocolVersion"] = version
        sieved = methods.serialize_server_result("initialize", version, body)
        assert sieved["capabilities"] == {
            "tools": {"listChanged": False},
            "events": {},
            _HOOKS: {"version": 1},
            "tasks": {"list": {}},
        }
        assert sieved["protocolVersion"] == version


def test_closed_results_and_version_gates_are_unchanged() -> None:
    """Unknown keys on a non-capability result still drop, and version gates hold.

    `tools/list` is not an open capability object. `server/discover` does not
    exist at 2025-11-25. An unknown protocol version is rejected. Events methods
    are not part of the spec method set.
    """
    listed = methods.serialize_server_result(
        "tools/list",
        "2026-07-28",
        {
            "tools": [{"name": "echo", "inputSchema": {"type": "object", "title": "X"}, "unknownField": 1}],
            "events": {},
            "resultType": "complete",
            "ttlMs": 0,
            "cacheScope": "private",
        },
    )
    assert listed["tools"] == [{"name": "echo", "inputSchema": {"type": "object", "title": "X"}}]
    assert "events" not in listed
    with pytest.raises(KeyError):
        methods.serialize_server_result("server/discover", "2025-11-25", {})
    with pytest.raises(ValueError):
        methods.serialize_server_result("ping", "2099-01-01", {})
    assert not any(name.startswith("events/") for name in methods.SPEC_CLIENT_METHODS)


def test_invalid_known_capability_values_are_rejected() -> None:
    """A bad known field fails validation even when an unknown key sits beside it.

    `listChanged: "nope"` is not a boolean. A non-object `capabilities` value is
    not a capability map. `experimental` and `extensions` must stay maps of
    objects, so a list or a string extension setting is rejected. The open set
    does not relax those checks, and the accompanying `events` object is not
    serialized on the failing path.
    """
    bad_flag = _discover_body(tools={"listChanged": "nope"}, events={"shouldNotAdvertise": True})
    with pytest.raises(ValidationError) as flagged:
        methods.serialize_server_result("server/discover", "2026-07-28", bad_flag)
    assert flagged.value.errors()[0]["loc"] == ("capabilities", "tools", "listChanged")

    bad_shape = _discover_body()
    bad_shape["capabilities"] = ["not-an-object"]
    with pytest.raises(ValidationError) as shaped:
        methods.serialize_server_result("server/discover", "2026-07-28", bad_shape)
    assert shaped.value.errors()[0]["loc"] == ("capabilities",)

    bad_experimental = _discover_body(experimental="nope", events={})
    with pytest.raises(ValidationError) as experimental:
        methods.serialize_server_result("server/discover", "2026-07-28", bad_experimental)
    assert experimental.value.errors()[0]["loc"] == ("capabilities", "experimental")

    bad_extensions = _discover_body(extensions=[], events={"shouldNotAdvertise": True})
    with pytest.raises(ValidationError) as extensions:
        methods.serialize_server_result("server/discover", "2026-07-28", bad_extensions)
    assert extensions.value.errors()[0]["loc"] == ("capabilities", "extensions")

    bad_extension_value = _discover_body(extensions={"io.example/hooks": "nope"}, events={})
    with pytest.raises(ValidationError) as extension_value:
        methods.serialize_server_result("server/discover", "2026-07-28", bad_extension_value)
    assert extension_value.value.errors()[0]["loc"][:3] == ("capabilities", "extensions", "io.example/hooks")


def test_client_capabilities_keep_unknown_keys_and_reject_bad_known_fields() -> None:
    """The same open-set rule applies to client capabilities on `initialize`."""
    params = {
        "protocolVersion": "2025-11-25",
        "capabilities": {"roots": {"listChanged": False}, "events": {"a": 1}, _HOOKS: {"n": None}},
        "clientInfo": {"name": "c", "version": "1"},
    }
    parsed = methods.parse_client_request("initialize", "2025-11-25", params)
    dumped = parsed.params.capabilities.model_dump(by_alias=True, exclude_none=True)
    assert dumped["roots"] == {"listChanged": False}
    assert dumped["events"] == {"a": 1}
    assert dumped[_HOOKS] == {"n": None}
    broken = {
        "protocolVersion": "2025-11-25",
        "capabilities": {"roots": {"listChanged": "nope"}, "events": {}},
        "clientInfo": {"name": "c", "version": "1"},
    }
    with pytest.raises(ValidationError):
        methods.validate_client_request("initialize", "2025-11-25", broken)


async def _discover_over_runner(server: Server[Any]) -> dict[str, Any]:
    connection = Connection.from_envelope(MODERN_PROTOCOL_VERSIONS[0], None, None)
    params: dict[str, Any] = {
        "_meta": {
            types.PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSIONS[0],
            types.CLIENT_CAPABILITIES_META_KEY: {},
        }
    }
    return await serve_one(
        server, _StubDispatchContext(), "server/discover", params, connection=connection, lifespan_state={}
    )


async def test_runner_discover_wire_keeps_open_keys() -> None:
    """`ServerRunner._serialize` emits unknown capability keys on `server/discover`."""
    result = await _discover_over_runner(_advertising_server())
    wire = json.dumps(result, sort_keys=True).encode()
    capabilities = result["capabilities"]
    assert capabilities["tools"] == {"listChanged": False}
    assert capabilities["extensions"] == {"io.modelcontextprotocol/ui": {}}
    assert capabilities["events"] == _EVENTS_VALUE
    assert capabilities[_HOOKS] == _HOOKS_VALUE
    assert "tasks" not in capabilities
    assert b'"events"' in wire and b'"label": null' in wire
    assert result["_meta"][types.SERVER_INFO_META_KEY] == {"name": "cap-host", "version": "1.2.3"}


async def test_runner_rejects_invalid_known_capability_beside_events() -> None:
    """A discover handler that returns `listChanged: "nope"` is an internal error.

    The accompanying `events` object is not advertised on a success result.
    """
    server = Server("bad-caps", version="1.0.0")

    async def bad_discover(ctx: ServerRequestContext[Any], params: types.RequestParams | None) -> dict[str, Any]:
        del ctx, params
        return _discover_body(tools={"listChanged": "nope"}, events={"shouldNotAdvertise": True})

    server.add_request_handler("server/discover", types.RequestParams, bad_discover)
    with pytest.raises(MCPError) as exc:
        await _discover_over_runner(server)
    assert exc.value.error.code == types.INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"


async def test_http_discover_wire_bytes_and_sdk_client_read_the_same_keys() -> None:
    """A streamable-HTTP discover body and an SDK client both retain the open keys.

    The HTTP response is the wire document. The in-process client is the SDK
    consumer of that advertisement, on the modern path and on the legacy
    handshake. Legacy still omits `extensions`, which is not in the 2025 schema.
    """
    server = _advertising_server()
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(server) as (http, _manager):
        response = await http.post("/mcp", json=body, headers=_modern_headers("server/discover"))
    assert response.status_code == 200
    raw = response.content
    assert b'"events"' in raw and b'"com.example/hooks"' in raw
    assert b'"tasks"' not in raw
    payload = response.json()
    result = payload["result"]
    assert result["capabilities"]["events"] == _EVENTS_VALUE
    assert result["capabilities"][_HOOKS] == _HOOKS_VALUE
    assert result["capabilities"]["extensions"] == {"io.modelcontextprotocol/ui": {}}
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["supportedVersions"] == [LATEST_MODERN_VERSION]

    async with Client(server, mode="auto") as client:
        dumped = client.server_capabilities.model_dump(by_alias=True, exclude_none=True)
    assert dumped["events"] == _EVENTS_VALUE
    assert dumped[_HOOKS] == _HOOKS_VALUE
    assert dumped["extensions"] == {"io.modelcontextprotocol/ui": {}}
    assert dumped["tools"] == {"listChanged": False}

    legacy_server = _advertising_server()
    async with Client(legacy_server, mode="legacy") as client:
        dumped = client.server_capabilities.model_dump(by_alias=True, exclude_none=True)
        assert client.server_capabilities.extensions is None
    assert dumped["events"] == _EVENTS_VALUE
    assert dumped[_HOOKS] == _HOOKS_VALUE
    assert "extensions" not in dumped
    assert dumped["tools"] == {"listChanged": False}
