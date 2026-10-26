from __future__ import annotations

import pytest

from mcp.client.session import _default_inbound_complete_result
from mcp_types import methods


def test_modern_missing_discriminator_is_a_complete_result_for_the_client() -> None:
    original = {"content": [{"type": "text", "text": "ok"}]}
    normalized = _default_inbound_complete_result(original, "2026-07-28")
    assert original == {"content": [{"type": "text", "text": "ok"}]}
    assert normalized["resultType"] == "complete"
    methods.validate_server_result("tools/call", "2026-07-28", normalized)


@pytest.mark.parametrize("body", [
    {"resultType": "input_required", "inputRequests": {"confirm": {}}},
    {"resultType": "task", "content": []},
    {"inputRequests": {"confirm": {}}},
    {"requestState": "sealed"},
    {"resultType": None, "content": []},
])
def test_explicit_or_pending_result_types_are_never_downgraded(body: dict) -> None:
    assert _default_inbound_complete_result(body, "2026-07-28") == body


def test_legacy_wire_is_never_rewritten() -> None:
    body = {"content": []}
    assert _default_inbound_complete_result(body, "2025-11-25") is body
