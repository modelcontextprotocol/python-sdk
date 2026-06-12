"""Wire-fidelity smoke tests for the generated spec-oracle modules.

A hand-checked sample of concrete payloads pinning behaviors the generated
models must get right as wire models: `_meta` reserved-key round-trips,
content-union discrimination, the per-version `resultType` split, the
2026-07-28 initialize→discover swap, ext-tasks basics, and extra-field
retention. `test_burndown.py` compares the oracles against the SDK's types
structurally; these cases catch what a structural comparison cannot — a
regeneration that breaks field aliasing, union discrimination, or the
extra-field config still has to validate and re-dump these payloads.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.spec_oracles import ext_tasks, v2024_11_05, v2026_07_28

DRAFT_CALL_TOOL_REQUEST = {
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


def test_draft_call_tool_request_meta_round_trip() -> None:
    request = v2026_07_28.CallToolRequest.model_validate(DRAFT_CALL_TOOL_REQUEST)
    meta = request.params.meta
    assert meta.io_modelcontextprotocol_protocol_version == "2026-07-28"
    assert meta.io_modelcontextprotocol_client_info.name == "smoke-client"
    dumped = request.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert dumped == DRAFT_CALL_TOOL_REQUEST


def test_draft_content_union_discriminates() -> None:
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


def test_draft_result_requires_result_type() -> None:
    result = v2026_07_28.Result.model_validate({"resultType": "callTool"})
    assert result.result_type == "callTool"
    with pytest.raises(ValidationError):
        v2026_07_28.Result.model_validate({})


def test_draft_drops_initialize_and_adds_discover() -> None:
    assert not hasattr(v2026_07_28, "InitializeRequest")
    assert not hasattr(v2026_07_28, "InitializeResult")
    assert hasattr(v2026_07_28, "DiscoverRequest")
    assert hasattr(v2026_07_28, "DiscoverResult")
    assert hasattr(v2024_11_05, "InitializeRequest")


def test_ext_tasks_minimal_task_and_manifest() -> None:
    task = ext_tasks.Task.model_validate(
        {
            "taskId": "t-1",
            "status": "working",
            "createdAt": "2026-06-05T00:00:00Z",
            "lastUpdatedAt": "2026-06-05T00:00:00Z",
            "ttlMs": None,
        }
    )
    assert task.task_id == "t-1"
    assert len(ext_tasks.SPEC_DEFS) == 24
    for name in ext_tasks.SPEC_DEFS:
        assert getattr(ext_tasks, name, None) is not None


def test_extra_fields_survive_round_trip() -> None:
    payload = {"resultType": "callTool", "x-vendor-key": {"nested": 1}}
    result = v2026_07_28.Result.model_validate(payload)
    assert result.model_dump(by_alias=True, exclude_none=True, mode="json") == payload
