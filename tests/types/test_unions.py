"""Resolution pins for the public result-union adapter.

``server_result_adapter`` is a plain smart union. Growing the union for
2026-07-28 (``DiscoverResult``, plus ``InputRequiredResult`` appended last)
must not silently change how result bodies producible under released protocol
versions resolve, so each case below pins the exact class a representative
body resolves to:

- One typed body per pre-2026-07-28 member resolves to its own class, and the
  empty and ``_meta``-only bodies still resolve to ``EmptyResult`` — the
  appended all-optional ``InputRequiredResult`` arm absorbs nothing.
- A body carrying ``supportedVersions``, ``capabilities``, and ``serverInfo``
  resolves to ``DiscoverResult``. This capture is deliberate: those three keys
  are the complete required key set of the ``server/discover`` result
  introduced in 2026-07-28, ``supportedVersions`` exists in no earlier schema
  revision, and the body stays accepted either way.
"""

from typing import Any

import pytest

from mcp.types import (
    CallToolResult,
    CompleteResult,
    DiscoverResult,
    EmptyResult,
    GetPromptResult,
    InitializeResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    ReadResourceResult,
    server_result_adapter,
)

SERVER_INFO = {"name": "example-server", "version": "1.0.0"}

RESOLUTION_PINS: list[tuple[str, dict[str, Any], type[Any]]] = [
    (
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": SERVER_INFO},
        InitializeResult,
    ),
    ("complete", {"completion": {"values": ["py"]}}, CompleteResult),
    (
        "get-prompt",
        {"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}]},
        GetPromptResult,
    ),
    ("list-prompts", {"prompts": []}, ListPromptsResult),
    ("list-resources", {"resources": []}, ListResourcesResult),
    ("list-resource-templates", {"resourceTemplates": []}, ListResourceTemplatesResult),
    ("read-resource", {"contents": []}, ReadResourceResult),
    ("call-tool", {"content": []}, CallToolResult),
    ("list-tools", {"tools": []}, ListToolsResult),
    ("empty-body", {}, EmptyResult),
    ("meta-only", {"_meta": {"example.com/trace": "abc"}}, EmptyResult),
    (
        "discover-key-set",
        {"supportedVersions": ["2026-07-28"], "capabilities": {}, "serverInfo": SERVER_INFO},
        DiscoverResult,
    ),
]


@pytest.mark.parametrize(
    ("body", "expected"),
    [(body, expected) for _, body, expected in RESOLUTION_PINS],
    ids=[case_id for case_id, _, _ in RESOLUTION_PINS],
)
def test_server_result_resolution_pin(body: dict[str, Any], expected: type[Any]) -> None:
    """Each pinned body resolves to exactly the pinned member class."""
    resolved = server_result_adapter.validate_python(body)
    assert type(resolved) is expected
