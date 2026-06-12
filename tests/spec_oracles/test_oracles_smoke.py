"""Wire-fidelity smoke tests for the generated spec-oracle modules.

Each test pins one schema behavior the oracles must reproduce before they can
serve as the burn-down's comparison baseline: `_meta` reserved-key
round-trips, content-union discrimination, the per-version `resultType` split,
the 2026-07-28 initialize→discover swap, and extra-field retention.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.spec_oracles import v2024_11_05, v2026_07_28

CALL_TOOL_REQUEST_2026_07_28 = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "smoke-client", "version": "0.0.1"},
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        },
        "name": "echo",
        "arguments": {"text": "hi"},
    },
}


def test_2026_07_28_call_tool_request_meta_round_trip() -> None:
    request = v2026_07_28.CallToolRequest.model_validate(CALL_TOOL_REQUEST_2026_07_28)
    meta = request.params.meta
    assert meta.io_modelcontextprotocol_protocol_version == "2026-07-28"
    assert meta.io_modelcontextprotocol_client_info.name == "smoke-client"
    dumped = request.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert dumped == CALL_TOOL_REQUEST_2026_07_28


def test_2026_07_28_content_union_discriminates() -> None:
    adapter: TypeAdapter[v2026_07_28.ContentBlock] = TypeAdapter(v2026_07_28.ContentBlock)
    text = adapter.validate_python({"type": "text", "text": "hello"})
    assert isinstance(text, v2026_07_28.TextContent)
    link = adapter.validate_python({"type": "resource_link", "name": "r", "uri": "https://example.com/r"})
    assert isinstance(link, v2026_07_28.ResourceLink)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "nope"})


def test_call_tool_result_has_no_result_type_in_2024_11_05() -> None:
    result = v2024_11_05.CallToolResult.model_validate({"content": [{"type": "text", "text": "ok"}]})
    assert "result_type" not in v2024_11_05.CallToolResult.model_fields
    assert isinstance(result.content[0], v2024_11_05.TextContent)


def test_2026_07_28_result_requires_result_type() -> None:
    result = v2026_07_28.Result.model_validate({"resultType": "callTool"})
    assert result.result_type == "callTool"
    with pytest.raises(ValidationError):
        v2026_07_28.Result.model_validate({})


def test_2026_07_28_drops_initialize_and_adds_discover() -> None:
    assert not hasattr(v2026_07_28, "InitializeRequest")
    assert not hasattr(v2026_07_28, "InitializeResult")
    assert hasattr(v2026_07_28, "DiscoverRequest")
    assert hasattr(v2026_07_28, "DiscoverResult")
    assert hasattr(v2024_11_05, "InitializeRequest")


def test_extra_fields_survive_round_trip() -> None:
    payload = {"resultType": "callTool", "x-vendor-key": {"nested": 1}}
    result = v2026_07_28.Result.model_validate(payload)
    assert result.model_dump(by_alias=True, exclude_none=True, mode="json") == payload
