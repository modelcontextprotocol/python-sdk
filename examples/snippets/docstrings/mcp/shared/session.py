"""Companion examples for src/mcp/shared/session.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.shared.session import RequestResponder


async def RequestResponder_usage(request_responder: RequestResponder[Any, Any], result: Any) -> None:
    # region RequestResponder_usage
    with request_responder as resp:
        await resp.respond(result)
    # endregion RequestResponder_usage
